"""Usage: docker cp this file into the app-code-worker container, then
`docker exec -w /app app-code-worker python /tmp/e2b_measure.py`.

Time E2B sandbox start, outbound throughput to Hetzner, RTT to dev API, file writes and AES speed. Synthetic only."""
import asyncio
import json
import os
import time
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async, CODE_RUN_TEMPLATE_ENV
from e2b import Sandbox

async def key():
    sm = SecretsManager()
    await sm.initialize()
    return await get_e2b_api_key_async(sm)

api_key = asyncio.run(key())
out = {}
for label, tmpl in (("default", None), ("code_run_template", os.getenv(CODE_RUN_TEMPLATE_ENV))):
    if label != "default" and not tmpl:
        continue
    t = time.monotonic()
    opts = {"template": tmpl} if tmpl else {}
    sb = Sandbox.create(**opts, api_key=api_key, secure=True, allow_internet_access=True,
                        network={"allow_public_traffic": False}, timeout=600)
    out[f"{label}_create_s"] = round(time.monotonic() - t, 2)
    try:
        if label == "default":
            cmds = {
                "cpu_mem": "nproc; free -m | awk 'NR==2{print $2\" MB\"}'; df -h / | tail -1",
                "rtt_dev_api": "for i in 1 2 3; do curl -s --http1.1 -o /dev/null -w '%{time_connect} %{time_starttransfer}\\n' https://api.dev.openmates.org/; done",
                "dl_nbg1_100MB": "curl -s --http1.1 -o /dev/null -w '%{speed_download} %{time_total}' https://nbg1-speed.hetzner.com/100MB.bin",
                "dl_fsn1_100MB": "curl -s --http1.1 -o /dev/null -w '%{speed_download} %{time_total}' https://fsn1-speed.hetzner.com/100MB.bin",
                "write_18k_files": "python3 -c \"import os,time;t=time.time();d='/tmp/w';os.makedirs(d,exist_ok=True)\nfor i in range(18000):\n  p=f'{d}/{i%300}';os.makedirs(p,exist_ok=True);open(f'{p}/{i}.txt','w').write('x'*6500)\nprint(round(time.time()-t,2))\"",
                "aes_gcm": "openssl speed -elapsed -seconds 2 -evp aes-256-gcm 2>/dev/null | tail -1",
                "geo": "curl -s --http1.1 https://ipinfo.io/json | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get(\"region\"),d.get(\"country\"),d.get(\"org\"))'",
            }
            for name, c in cmds.items():
                t = time.monotonic()
                try:
                    r = sb.commands.run(c + " 2>&1; true", timeout=180)
                    out[name] = (r.stdout.strip()[-300:], round(time.monotonic() - t, 2))
                except Exception as exc:  # measurement script: record and go on
                    out[name] = ("error " + type(exc).__name__, round(time.monotonic() - t, 2))
    finally:
        sb.kill()
print(json.dumps(out, indent=1))
