"""Exercise the extracted Octop backend and Dashboard over loopback."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class ModelHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/v1/chat/completions" or request.get("model") != "win7-smoke":
            self.send_error(400)
            return
        body = json.dumps(
            {
                "id": "smoke",
                "object": "chat.completion",
                "created": 0,
                "model": "win7-smoke",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "pong"},
                        "finish_reason": "stop",
                    }
                ],
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main(root: Path, state: Path) -> None:
    state.mkdir(parents=True, exist_ok=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = dict(os.environ)
    env.update(
        OCTOP_HOME=str(state / "octop-data"),
        OCTOP_DATABASE_DRIVER="sqlite",
        OCTOP_DESKTOP_SHELL="1",
        OCTOP_REQUIRE_SETUP_PASSWORD="0",
        PYTHONDONTWRITEBYTECODE="1",
    )
    launcher = root / "start.bat"
    command = ["cmd.exe", "/d", "/c", str(launcher), "--host", "127.0.0.1", "--port", str(port)]
    log = state / "octop-smoke.log"
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(path: str) -> bytes:
        with http.open(f"http://127.0.0.1:{port}{path}", timeout=3) as response:
            return response.read()

    def post(path: str, payload: dict, token: str | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", json.dumps(payload).encode(), headers
        )
        with http.open(request, timeout=40) as response:
            return json.load(response)

    with log.open("wb") as output:
        process = subprocess.Popen(command, cwd=root, env=env, stdout=output, stderr=output)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError(f"Octop exited on startup ({process.returncode})")
                try:
                    health = json.loads(get("/api/health"))
                    if health["ok"] and health["db"]:
                        break
                except OSError:
                    pass
                time.sleep(0.5)
            else:
                raise TimeoutError("Octop SQLite backend did not become ready")
            setup = json.loads(get("/api/setup/status"))
            assert setup["database_driver"] == "sqlite", setup
            assert setup["wizard_password_required"] is False, setup
            assert b'<div id="root">' in get("/"), "Dashboard entry not served"
            token = post("/api/setup/begin", {})["wizard_token"]
            with ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler) as model:
                worker = threading.Thread(target=model.serve_forever, daemon=True)
                worker.start()
                try:
                    probe = post(
                        "/api/setup/test-provider",
                        {
                            "name": "Win7 loopback smoke",
                            "type": "openai",
                            "api_key": "fixture",
                            "base_url": f"http://127.0.0.1:{model.server_port}/v1",
                            "model_id": "win7-smoke",
                        },
                        token,
                    )
                    assert probe["ok"], probe
                finally:
                    model.shutdown()
                    worker.join()
        except Exception:
            print(log.read_text("utf-8", errors="replace")[-24000:], file=sys.stderr)
            raise
        finally:
            if process.poll() is None:
                subprocess.run(
                    ["taskkill.exe", "/pid", str(process.pid), "/t", "/f"],
                    capture_output=True,
                    timeout=20,
                    check=True,
                )
            process.wait(timeout=15)
    print(
        json.dumps(
            {
                "sqlite": True,
                "dashboard": True,
                "setupPasswordRequired": False,
                "loopbackProvider": True,
            }
        )
    )


if __name__ == "__main__":
    main(*(Path(value).resolve() for value in sys.argv[1:]))
