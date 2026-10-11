'use strict';
const test=require('node:test'), assert=require('node:assert/strict');
const {createRelayServer}=require('../local-relay/server.cjs');
test('laptop model → local relay → phone exchange → watch receipt contract',async()=>{
  let now=1000;
  const token='test-only-pairing-token'; const server=createRelayServer({token,now:()=>now});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base=`http://127.0.0.1:${server.address().port}`;
  async function request(path,body,authenticated=true){
    const response=await fetch(base+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json',...(authenticated?{Authorization:`Bearer ${token}`}:{})},body:body?JSON.stringify(body):undefined});
    return {status:response.status,body:await response.json()};
  }
  try {
    assert.equal((await request('/api/state',null,false)).status,401);
    const packet={protocol:1,type:'telemetry',schema:1,source:'watch_sensors',session:'watch-1',sequence:1,sentAt:1000,heartRateBpm:72,spo2Percent:null};
    const exchange={protocol:1,clientId:'demo',relaySession:'phone-1',watchSession:'watch-1',running:true,telemetry:packet,events:[]};
    assert.equal((await request('/api/phone/exchange',exchange)).status,200);
    const state=(await request('/api/state')).body; assert.deepEqual(state.telemetry,packet);
    const command={protocol:1,commandId:'model-1',type:'model_result',watchSession:state.watchSession,capturedAt:1000,riskScore:0.91,status:'ready',modelVersion:'team-v1',inputTelemetrySequence:1};
    assert.equal((await request('/api/command',{clientId:'demo',command})).status,202);
    assert.equal((await request('/api/command',{clientId:'demo',command})).status,409);
    assert.deepEqual((await request('/api/phone/exchange',exchange)).body.commands,[command]);
    assert.deepEqual((await request('/api/phone/exchange',exchange)).body.commands,[]);
    const event={protocol:1,type:'command_result',commandId:'model-1',status:'accepted',watchSequence:9};
    exchange.events=[event]; await request('/api/phone/exchange',exchange);
    assert.deepEqual((await request('/api/state')).body.events,[event]);
    command.commandId='invalid-score';command.riskScore=91;
    assert.equal((await request('/api/command',{command})).body.error,'invalid_score');
    command.commandId='unknown-input';command.riskScore=0.91;command.inputTelemetrySequence=99;
    assert.equal((await request('/api/command',{command})).body.error,'unknown_or_stale_input');
    const camera={protocol:1,commandId:'camera-1',type:'camera_alert',watchSession:'watch-1',capturedAt:1000,severity:'high'};
    assert.equal((await request('/api/command',{command:camera})).status,202);
    exchange.watchSession='watch-2';exchange.telemetry=null;
    assert.deepEqual((await request('/api/phone/exchange',exchange)).body.commands,[]);
    assert.equal((await request('/api/command',{command:camera})).body.error,'wrong_session');
    now=1011; assert.equal((await request('/api/state')).body.telemetry,null);
    camera.watchSession='watch-2';camera.capturedAt=1011;camera.commandId='offline';
    assert.equal((await request('/api/command',{command:camera})).body.error,'phone_unavailable');
  } finally { server.closeAllConnections(); await new Promise(resolve=>server.close(resolve)); }
});
