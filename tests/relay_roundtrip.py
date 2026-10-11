"""Isolated real-HTTP relay round trip with virtual sensor time and actual models.

Run from the repository root: python -B tests/relay_roundtrip.py.
Never uses a physical phone/watch or an existing relay. Simulated telemetry is
marked live only inside this separately spawned fixture so the real transport
eligibility checks are exercised. Test logs are temporary and removed.
"""
from pathlib import Path
import json,os,secrets,subprocess,sys,tempfile
from unittest.mock import patch
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from run_demo import node_path
from test_connected import packet
from src.models.predict import load_model
from src.models.facial_baseline import FacialModels
from web.model_service import ModelService
from web.relay_worker import RelayWorker
import torch

def main():
    torch.set_num_threads(1)
    node=node_path()
    if not node:raise RuntimeError('Node.js is needed for the isolated HTTP test')
    token=secrets.token_hex(24)
    process=subprocess.Popen([node,str(ROOT/'tests/relay_fixture.cjs')],cwd=ROOT,
        env={**os.environ,'DROWSY_TEST_TOKEN':token},stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    service=None
    try:
        port=json.loads(process.stdout.readline())['port']
        base=f'http://127.0.0.1:{port}'
        now=[1790000000000]
        def exchange(telemetry,events=()):
            body={'protocol':1,'clientId':'isolated-test','relaySession':'fixture-only',
                  'watchSession':'watch-1','running':True,'telemetry':telemetry,'events':list(events)}
            request=Request(base+'/api/phone/exchange',data=json.dumps(body).encode(),
                headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
            with urlopen(request,timeout=5) as response:return json.load(response)
        with tempfile.TemporaryDirectory(prefix='drozy-http-test-') as logs,patch.dict(os.environ,{'DROZY_LOG_DIRECTORY':logs}):
            service=ModelService(load_model(ROOT/'data/processed/baseline_model.pkl'),
                FacialModels.load(ROOT/'data/processed'),ROOT,now=lambda:now[0],llm=False)
            worker=RelayWorker(service,ROOT,token=token,url=base,client_id='isolated-test',monotonic=lambda:now[0]/1000)
            for second in range(76):
                p=packet(second,temperature=31.5 if second==0 else None).model_dump(by_alias=True)
                now[0]=round(p['sentAt']*1000)
                process.stdin.write(json.dumps({'now':p['sentAt']})+'\n');process.stdin.flush()
                assert json.loads(process.stdout.readline())['now']==p['sentAt']
                exchange(p);worker.ingest(worker.relay.state())
                # Let both actual components be present for the final return.
                if second<75:worker.send_latest()
            # This is the real browser feature module with synthetic geometry.
            script="""import {LiveModelFeatures} from './web/static/model-features.mjs';
            const a=new LiveModelFeatures();for(let t=1790000000000;t<=1790000075000;t+=50)a.push(t,[.3,.3,.1]);
            console.log(JSON.stringify(a.window(1790000075000)));"""
            video=json.loads(subprocess.check_output([node,'--input-type=module','-e',script],cwd=ROOT,text=True))
            state=service.update('video',{'device_id':'isolated-test','session_id':'watch-1','data_origin':'live',
                'schema_id':'facial.rgb.geometry.v1','model':'small_tcn','channels':video['channels'],
                'sequence':video['sequence'],'features':video['features'],
                'baseline_reference':video['baselineReference'],
                'window':{'start_ms':video['startRelativeMs'],'end_ms':video['endRelativeMs']}})
            assert state['mode']=='watch_video',state
            assert state['facial_score']==0,state
            assert abs(state['score']-(state['watch_score']+state['facial_score'])/2)<1e-8
            assert worker.preprocessor.temperature==31.5
            assert worker.preprocessor.quality['temperature_age_ms']==75000
            worker.send_latest();worker.send_camera_latest()
            commands=exchange(p)['commands']
            results=[c for c in commands if c['type']=='model_result']
            assert len(results)==1,commands
            result=results[0]
            assert result['status']=='ready' and abs(result['riskScore']-state['score'])<1e-8
            assert result['capturedAt']==state['window_end_ms']/1000
            assert result['inputTelemetrySequence']==p['sequence']
            exchange(p,[{'type':'command_result','commandId':result['commandId'],'status':'accepted'}])
            # The last queued command may be the camera channel, so validate the
            # received event independently instead of claiming physical receipt.
            assert any(e.get('commandId')==result['commandId'] and e.get('status')=='accepted'
                       for e in worker.relay.state()['events'])
            print('PASS: synthetic raw sensors → original four-feature extractor → saved watch model;')
            print('browser geometry → original 15×60 schema → saved TCN → 50/50 average → real HTTP relay → simulated phone receipt.')
            print('PASS: null temperature carried 75 seconds; genuine IBI used; original capture time and sequence preserved. No physical device involved.')
    finally:
        if service:service.close()
        if process.stdin:process.stdin.close()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)

if __name__=='__main__':main()
