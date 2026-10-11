"""Real localhost HTTP test using isolated offline fixtures and temporary CSVs."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from urllib.error import URLError
from urllib.request import Request, urlopen
from .test_receiver import AUTH, TOKEN, fixture


class LiveHTTPTest(unittest.TestCase):
    def test_server_socket_and_csv(self):
        with TemporaryDirectory() as folder:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env = {**os.environ, "GARMIN_API_TOKEN": TOKEN, "GARMIN_DATA_DIR": folder}
            # Windows venv python.exe is a redirector; launch the base interpreter
            # with the venv import paths so terminating it also releases SQLite.
            command = [sys.executable, "-m", "uvicorn", "server.main:create_app", "--factory", "--host", "127.0.0.1", "--port", str(port)]
            if os.name == "nt":
                script = f"import sys; sys.path[:] = {sys.path!r}; import uvicorn; uvicorn.run('server.main:create_app', factory=True, host='127.0.0.1', port={port})"
                command = [sys._base_executable, "-c", script]
            process = subprocess.Popen(
                command,
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                base = f"http://127.0.0.1:{port}"
                deadline = time.monotonic()+15
                while True:
                    try:
                        with urlopen(base+"/health", timeout=1) as response:
                            self.assertEqual(json.load(response)["status"], "ok")
                        break
                    except URLError:
                        if process.poll() is not None or time.monotonic()>deadline:
                            self.fail("Receiver did not start")
                        time.sleep(.1)
                for expected in ("accepted", "duplicate"):
                    request = Request(base+"/garmin/data", data=json.dumps(fixture()).encode(),
                                      headers={**AUTH, "Content-Type": "application/json"}, method="POST")
                    with urlopen(request, timeout=5) as response:
                        self.assertEqual(json.load(response)["status"], expected)
                self.assertTrue((Path(folder)/"garmin_heart_rate.csv").exists())
                with (Path(folder)/"garmin_accelerometer.csv").open() as f:
                    self.assertEqual(len(f.readlines()), 3)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
