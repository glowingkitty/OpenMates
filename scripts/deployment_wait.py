"""Bounded exact-commit Vercel status wait using GitHub commit statuses."""
import json
import re
import subprocess
import time


def wait_deploy(root, commit, *, timeout=600, poll=15, read=None, clock=time.monotonic, sleep=time.sleep):
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise ValueError("Use the full 40-character deployed commit SHA")
    if timeout <= 0 or poll <= 0:
        raise ValueError("Timeout and poll must be positive")
    def github_status():
        output = subprocess.check_output(
            ["gh", "api", f"repos/{{owner}}/{{repo}}/commits/{commit}/status"],
            cwd=root, text=True, timeout=min(30, max(1, deadline - clock())))
        return json.loads(output)
    read = read or github_status
    deadline = clock() + timeout
    state, url = "pending", ""
    while True:
        payload = read()
        # API lists newest status first; retain the newest status for each Vercel context.
        latest = {}
        for status in payload.get("statuses", []):
            context = str(status.get("context", ""))
            if "vercel" in context.lower():
                latest.setdefault(context, status)
        if latest:
            states = {item.get("state") for item in latest.values()}
            url = next((item.get("target_url", "") for item in latest.values() if item.get("target_url")), "")
            state = "failure" if states & {"failure", "error"} else "success" if states == {"success"} else "pending"
            if state != "pending":
                return {"commit": commit, "state": state, "url": url}
        remaining = deadline - clock()
        if remaining <= 0:
            return {"commit": commit, "state": "timeout", "url": url}
        sleep(min(poll, remaining))
