#!/usr/bin/env python3
"""Verify chat-group title generation with real dev inference and synthetic titles.

Reserves a test-account lane, uses disposable CLI state and closes its session.
No real chats/projects, transcripts, private account state or keys are emitted.
Usage: python3 scripts/verify_chat_sidebar_title_live.py --session 40f4
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
from run_test_account_cli import _acquire_account
import sessions

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.dev.openmates.org"


def test_account_environment() -> dict[str, str]:
    """Read only test-account credentials from the bound control plane."""
    env = dict(os.environ)
    for path in (ROOT / ".env", sessions.ENV_FILE):
        if not path.is_file():
            continue
        for raw_line in path.read_text().splitlines():
            key, separator, value = raw_line.strip().partition("=")
            key = key.strip()
            if not separator or not re.fullmatch(r"OPENMATES_TEST_ACCOUNT(?:_\d+)?_(?:EMAIL|PASSWORD|OTP_KEY)", key):
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            env.setdefault(key, value)
    return env


def safe_failure(stderr: str) -> str:
    """Keep diagnostics useful without exposing server messages or credentials."""
    http = re.search(r"(?:Lookup|Login|Password login\w*)[^\n]*?HTTP (\d{3})", stderr, re.IGNORECASE)
    if http:
        return f"authentication HTTP {http.group(1)}"
    diagnostic = re.search(r"SIDEBAR_CHECK_FAILURE:(login|inference|cleanup):([a-zA-Z0-9_. -]+)", stderr)
    if diagnostic:
        return f"{diagnostic.group(1)}: {diagnostic.group(2)}"
    for marker in ("fetch failed", "Missing OPENMATES_TEST_ACCOUNT", "password-encrypted master key", "decrypt", "Cannot find", "ERR_MODULE_NOT_FOUND"):
        if marker.lower() in stderr.lower():
            return marker
    return "helper failed (private output withheld)"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--slot", type=int, choices=range(1, 14))
    args = parser.parse_args()
    owner = f"repository-session-{args.session}"
    lease, slot, resources = _acquire_account(owner, args.slot)
    stop = threading.Event()

    def renew() -> None:
        while not stop.wait(sessions.DOCKER_TEST_LEASE_RENEW_INTERVAL_SECONDS):
            sessions.renew_test_resource_lease(lease, owner, resources, mode="exclusive")

    heartbeat = threading.Thread(target=renew, daemon=True)
    heartbeat.start()
    try:
        with tempfile.TemporaryDirectory(prefix="openmates-sidebar-title-") as state_dir:
            env = {**test_account_environment(), "HOME": state_dir, "USERPROFILE": state_dir,
                   "OPENMATES_STATE_DIR": str(Path(state_dir) / ".openmates"), "OPENMATES_API_URL": API,
                   "OPENMATES_API_KEY": "", "OPENMATES_TEST_ACCOUNT_SOURCE_SLOT": str(slot)}
            program = r'''
import { OpenMatesClient } from './frontend/packages/openmates-cli/src/client.ts';
import { createHmac } from 'node:crypto';
const slot = process.env.OPENMATES_TEST_ACCOUNT_SOURCE_SLOT;
const credential = name => process.env[`OPENMATES_TEST_ACCOUNT_${slot}_${name}`] || process.env[`OPENMATES_TEST_ACCOUNT_${name}`];
function otp(secret, offset = 0) {
  if (!secret) return undefined;
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const char of secret.toUpperCase().replace(/[\s=]/g, '')) {
    const digit = alphabet.indexOf(char);
    if (digit < 0) throw new Error('Invalid test-account OTP configuration');
    bits += digit.toString(2).padStart(5, '0');
  }
  const key = Buffer.from((bits.match(/.{8}/g) || []).map(byte => parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now()/30000) + offset));
  const digest = createHmac('sha1', key).update(counter).digest();
  const truncationOffset = digest[digest.length-1] & 15;
  return ((digest.readUInt32BE(truncationOffset) & 0x7fffffff) % 1000000).toString().padStart(6, '0');
}
const client = new OpenMatesClient({apiUrl: process.env.OPENMATES_API_URL});
let inferenceFailure = '';
const post = client.http.post.bind(client.http);
client.http.post = async (...args) => {
  const response = await post(...args);
  if (args[0] === '/v1/projects/ask/plan' && !response.ok) {
    const detail = String(response.data?.detail || '').toLowerCase();
    inferenceFailure = ['api key','not configured','rate limit','no tool arguments','invalid project','ambiguity','no valid','authentication','timeout','connection','no available','blocked','clarification'].find(marker => detail.includes(marker)) || '';
  }
  return response;
};
let authenticated = false;
let stage = 'login';
try {
  let login;
  for (const offset of [0,-1,1]) {
    login = await client.loginWithPassword({email: credential('EMAIL'), password: credential('PASSWORD'), tfaCode: otp(credential('OTP_KEY'), offset)});
    if (login.status === 'authenticated' || !credential('OTP_KEY')) break;
  }
  if (login.status !== 'authenticated') throw new Error('Leased test-account authentication did not complete');
  authenticated = true;
  stage = 'inference';
  const response = await client.planProjectAsk({instruction: 'Name a new project from chat titles.', chatTitles: ['Launch copy', 'Market research']});
  if (response.processing?.purpose !== 'chat_project_title') throw new Error('Title generation route is not deployed');
  const name = response.proposed_project?.name?.trim();
  if (!name || name.length > 200) throw new Error('Invalid generated project title');
  process.stdout.write(JSON.stringify({passed:true,title_length:name.length,real_inference:true,transcripts_sent:false,projects_created:0}));
} catch (error) {
  const message = String(error?.message || '');
  const http = message.match(/HTTP (\d{3})/);
  const known = message.match(/^login\.[a-z_]+$/);
  const diagnostic = http ? `HTTP ${http[1]} ${inferenceFailure}` : known ? known[0] : ['Invalid generated project title','Leased test-account authentication did not complete'].includes(message) ? message : (error?.name || 'Error');
  process.stderr.write(`SIDEBAR_CHECK_FAILURE:${stage}:${diagnostic}\n`);
  process.exitCode = 1;
} finally {
  if (authenticated) {
    try { await client.logout(); }
    catch { process.stderr.write('SIDEBAR_CHECK_FAILURE:cleanup:session logout failed\n'); process.exitCode = 1; }
  }
}
'''
            result = subprocess.run(["node", "--experimental-strip-types", "--loader", "./frontend/packages/openmates-cli/tests/loader.mjs",
                                     "--input-type=module", "-e", program], cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise RuntimeError(f"Real dev project-title inference or session cleanup failed: {safe_failure(result.stderr)}")
            receipt = {**json.loads(result.stdout), "target": API, "session": args.session, "account_lane": slot}
            output = ROOT / "test-results/sidebar-live-title.json"
            output.parent.mkdir(exist_ok=True)
            output.write_text(json.dumps(receipt, indent=2) + "\n")
            print("PASS: real dev inference produced a bounded project title; synthetic titles only; session closed")
    finally:
        stop.set()
        heartbeat.join(timeout=1)
        sessions.release_test_resource_lease(lease)


if __name__ == "__main__":
    main()
