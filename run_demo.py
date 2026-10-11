"""Start the existing phone relay and connected local model dashboard together."""
from __future__ import annotations
import argparse
import importlib.util
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import json
from urllib.request import urlopen
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent


def node_path():
    configured = os.getenv('DROWSY_NODE')
    candidates = [configured, shutil.which('node'), str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')]
    return next((p for p in candidates if p and Path(p).is_file()),None)


def existing_local_llm():
    """Inspect only an existing local Ollama; never pull or contact a cloud API."""
    base=os.getenv('LLM_BASE_URL','http://localhost:11434/v1')
    url=urlsplit(base)
    if url.hostname not in {'localhost','127.0.0.1'} or url.port != 11434:return None
    try:
        with urlopen(f'{url.scheme}://{url.netloc}/api/tags',timeout=2) as response:
            models=json.load(response).get('models',[])
        local=[m for m in models if m.get('name') and not m['name'].endswith(':cloud') and not m.get('remote_host')]
        if not local:return None
        preferred=next((m['name'] for m in local if m['name']=='llama3.2:3b'),None)
        return preferred or min(local,key=lambda m:m.get('size',float('inf')))['name']
    except Exception:return None


def free_port(port):
    with socket.socket() as sock:
        return sock.connect_ex(('127.0.0.1',port)) != 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8777)
    parser.add_argument('--relay-port',type=int,default=8765)
    parser.add_argument('--reuse-relay',action='store_true',help='Use a running relay with DROWSY_RELAY_TOKEN')
    parser.add_argument('--check',action='store_true',help='Validate setup without starting servers or sensors')
    args = parser.parse_args()
    for port in (args.port,args.relay_port):
        if not 1 <= port <= 65535: parser.error('Ports must be 1–65535')
    missing = [name for name in ['flask','pydantic','torch','numpy','pandas','sklearn','joblib','requests']
               if importlib.util.find_spec(name) is None]
    if missing: parser.error('Install web/requirements.txt with Python 3.12. Missing: '+', '.join(missing))
    artifacts = ['baseline_model.pkl','small_tcn.pt','tcn_scaler.joblib','facial_model.pkl']
    if any(not (ROOT/'data/processed'/name).is_file() for name in artifacts):
        parser.error('The shipped model artifacts must be present in data/processed')
    node = node_path()
    if node is None and not args.reuse_relay: parser.error('Install Node.js or set DROWSY_NODE')
    if args.check:
        from src.models.predict import load_model
        from src.models.facial_baseline import FacialModels
        load_model(ROOT/'data/processed/baseline_model.pkl')
        FacialModels.load(ROOT/'data/processed')
        print('Ready: watch gradient boosting, video TCN/logistic, original fusion, advisor and phone relay.')
        print('Physical watch, phone pairing and live sensor availability remain device checks.')
        return
    if not free_port(args.port): parser.error(f'Dashboard port {args.port} is in use; choose --port 8778')
    env = dict(os.environ)
    env.setdefault('LOKY_MAX_CPU_COUNT','4')
    if not env.get('LLM_MODEL') and env.get('DROZY_LLM_DISABLED','0') != '1':
        local_model=existing_local_llm()
        if local_model:
            env['LLM_MODEL']=local_model
            print('Local advisor model: '+local_model,flush=True)
    token = env.get('DROWSY_RELAY_TOKEN')
    if args.reuse_relay and not token: parser.error('Set DROWSY_RELAY_TOKEN to the running relay pairing token')
    if not args.reuse_relay and not free_port(args.relay_port):
        parser.error('Relay port is already in use. Use --reuse-relay with its token, or another --relay-port')
    token = token or secrets.token_hex(24)
    env.update(DROWSY_RELAY_TOKEN=token,DROWSY_RELAY_URL=f'http://127.0.0.1:{args.relay_port}')
    # The token stays in child-process memory. The local page shows it only
    # after a user requests pairing details; it is never written to a file.
    children = []
    try:
        if not args.reuse_relay:
            relay_env = {**env,'PORT':str(args.relay_port),'HOST':env.get('DROWSY_RELAY_BIND','0.0.0.0')}
            relay = subprocess.Popen([node,str(ROOT/'phone-companion/local-relay/server.cjs')],
                                     cwd=ROOT,env=relay_env,stdout=subprocess.DEVNULL)
            children.append(relay)
            for _ in range(50):
                if relay.poll() is not None: raise RuntimeError('Phone relay failed to start')
                if not free_port(args.relay_port): break
                time.sleep(.1)
        web = subprocess.Popen([sys.executable,'-B',str(ROOT/'web/app.py'),'--port',str(args.port)],cwd=ROOT,env=env)
        children.append(web)
        print(f'Connected dashboard: http://127.0.0.1:{args.port}/',flush=True)
        print('Use “Show phone pairing details” on the page, then connect DrowsyRelay on iPhone.',flush=True)
        print('Keep DrowsyAlert and the iPhone companion foreground. Press Ctrl+C here to stop both servers.',flush=True)
        while all(child.poll() is None for child in children): time.sleep(.5)
    except KeyboardInterrupt: pass
    finally:
        for child in reversed(children):
            if child.poll() is None: child.terminate()
        for child in children:
            try: child.wait(timeout=8)
            except subprocess.TimeoutExpired: child.kill(); child.wait()


if __name__=='__main__': main()
