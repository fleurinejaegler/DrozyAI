"""Poll the existing phone relay; no new HTTP server, models, or camera startup."""
import argparse
import asyncio
import importlib.util
import logging
import os
from pathlib import Path
from urllib.error import HTTPError, URLError

from .repository import RepositoryFunctions
from .service import Runtime
from .telemetry import ingest_relay_snapshot, pending_watch_result


def load_gateway(repo_root):
    path = repo_root / 'phone-companion/local-relay/gateway_client.py'
    spec = importlib.util.spec_from_file_location('drozy_existing_gateway', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RelayClient


async def run(relay, runtime, send_status=False):
    await runtime.start()
    sent = None
    try:
        while True:
            try:
                snapshot = await asyncio.to_thread(relay.state)
                session = ingest_relay_snapshot(runtime, snapshot, relay.client_id)
                if session is not None:
                    runtime.latest(session)
                    packet = snapshot['telemetry']
                    key = packet['session'], packet['sequence']
                    if send_status and key != sent:
                        score, version, status = pending_watch_result(runtime, session, snapshot)
                        await asyncio.to_thread(relay.send_model_result, snapshot, score, version, status)
                        sent = key
            except (HTTPError, URLError, ValueError, KeyError) as exc:
                logging.getLogger(__name__).warning('Relay unavailable/invalid: %s', type(exc).__name__)
            await asyncio.sleep(max(runtime.settings.relay_poll_interval_s,
                                    runtime.settings.inference_interval_s if send_status else 0))
    finally:
        await runtime.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--relay-url', default='http://127.0.0.1:8765')
    parser.add_argument('--client-id', default='demo')
    parser.add_argument('--send-status', action='store_true', help='Send null/model_not_connected via the existing relay')
    args = parser.parse_args()
    token = os.getenv('DROWSY_RELAY_TOKEN')
    if not token:
        parser.error('Set DROWSY_RELAY_TOKEN to the existing relay pairing token')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    gateway = load_gateway(args.repo_root)(args.relay_url, token, args.client_id)
    functions = RepositoryFunctions(args.repo_root)
    try:
        asyncio.run(run(gateway, Runtime(score_fuser=functions.fuse_scores), args.send_status))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
