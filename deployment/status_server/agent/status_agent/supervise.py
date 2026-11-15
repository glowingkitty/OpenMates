"""Container entry point: Gatus, Caddy and the status agent in one container.

The status server is a single image. This process starts Gatus (HTTP checks)
and Caddy (TLS and the public page) as child processes, waits until Gatus
answers, then runs the agent loop. When any part stops, every part is stopped
and the process exits non-zero, so Docker's restart policy restarts the whole
set instead of leaving a half-working server.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request

from . import main as agent_main

LOG = logging.getLogger("status_agent.supervise")
CHILDREN = {
    "gatus": ["/usr/local/bin/gatus"],
    "caddy": ["/usr/local/bin/caddy", "run", "--config", "/app/Caddyfile", "--adapter", "caddyfile"],
}
GATUS_READY_TIMEOUT_S = 60


def stop_all(processes: dict[str, subprocess.Popen], code: int) -> None:
    for process in processes.values():
        if process.poll() is None:
            process.terminate()
    deadline = time.time() + 10
    for process in processes.values():
        try:
            process.wait(timeout=max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            process.kill()
    os._exit(code)


def watch_children(processes: dict[str, subprocess.Popen]) -> None:
    while True:
        for name, process in processes.items():
            if process.poll() is not None:
                LOG.error("%s exited with code %s; stopping the status server", name, process.returncode)
                stop_all(processes, 1)
        time.sleep(2)


def wait_for_gatus(url: str) -> None:
    deadline = time.time() + GATUS_READY_TIMEOUT_S
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=3):
                return
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    LOG.warning("Gatus not ready after %ss; the agent reports it as the status checker check", GATUS_READY_TIMEOUT_S)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    processes = {name: subprocess.Popen(command) for name, command in CHILDREN.items()}
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop_all(processes, 0))
    threading.Thread(target=watch_children, args=(processes,), daemon=True).start()
    wait_for_gatus(os.environ.get("GATUS_URL", "http://127.0.0.1:8080"))
    try:
        agent_main.main()
    finally:
        stop_all(processes, 1)


if __name__ == "__main__":
    main()
