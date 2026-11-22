"""Verify the packaged Electron window renders the local Octop Dashboard."""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def main(root: Path, state: Path) -> None:
    state.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(root / "resources/sidecar/runtime/Lib/site-packages"))
    from websockets.sync.client import connect

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    home = state / "octop-data"
    env = dict(os.environ, OCTOP_HOME=str(home), OCTOP_DATABASE_DRIVER="sqlite")
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    log = state / "electron.log"
    with log.open("wb") as output:
        process = subprocess.Popen(
            [
                str(root / "Octop.exe"),
                f"--user-data-dir={state / 'chromium'}",
                f"--remote-debugging-port={port}",
                "--remote-debugging-address=127.0.0.1",
                "--enable-logging=stderr",
            ],
            cwd=root,
            env=env,
            stdout=output,
            stderr=output,
        )
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError(f"Electron exited on startup ({process.returncode})")
                try:
                    with http.open(f"http://127.0.0.1:{port}/json/list", timeout=2) as response:
                        targets = json.load(response)
                    for target in targets:
                        if not target.get("url", "").startswith("octop://app/"):
                            continue
                        with connect(target["webSocketDebuggerUrl"], open_timeout=3) as devtools:
                            devtools.send(
                                json.dumps(
                                    {
                                        "id": 1,
                                        "method": "Runtime.evaluate",
                                        "params": {
                                            "expression": "document.readyState === 'complete' && !!document.querySelector('#root')?.firstElementChild",
                                            "returnByValue": True,
                                        },
                                    }
                                )
                            )
                            result = json.loads(devtools.recv(timeout=3))
                        if result.get("result", {}).get("result", {}).get("value") is True:
                            print(json.dumps({"dashboardRendered": True}))
                            return
                except (OSError, TimeoutError):
                    pass
                time.sleep(0.5)
            raise TimeoutError("Electron did not render the Octop Dashboard")
        except Exception:
            print(log.read_text("utf-8", errors="replace")[-12000:], file=sys.stderr)
            for desktop_log in home.glob("logs/desktop/*.log"):
                print(desktop_log.read_text("utf-8", errors="replace")[-12000:], file=sys.stderr)
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


if __name__ == "__main__":
    main(*(Path(value).resolve() for value in sys.argv[1:]))
