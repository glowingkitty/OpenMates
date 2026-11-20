"""Accounts, gift cards and gates for AI test users (private state under ~/.openmates/ai-test-users).

Every run creates a fresh account identity (never reused). `accounts.jsonl` is the append-only
registry (the briefing's growth exclusion reads its `email` field, so lines are never deleted).
Passwords live only in a 0600 per-account secret file, removed after the account is deleted.
Dev gift cards and invites are created inside the dev api container; prod gift cards come from
a private code file the owner fills, one code per run.
"""

from __future__ import annotations

import fcntl
import json
import os
import secrets
import string
import subprocess
from datetime import UTC, datetime
from pathlib import Path

HOME = Path.home() / ".openmates" / "ai-test-users"
EMAIL_PREFIX = "omtestuser-"
EMAIL_DOMAIN = "inboxkitten.com"
GIFT_CREDITS = 1000
PROD_CODES_FILE = "prod-gift-cards.txt"
PROD_ENABLED_FILE = "prod-enabled"
LOW_CODES_THRESHOLD = 6
LOW_MARKER = "prod-gift-cards-low-notified"
RETENTION_DAYS = 90
PUSH_SOURCE = "ai-test-users"


def home(base: Path | None = None) -> Path:
    path = base or HOME
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _private_write(path: Path, text: str, append: bool = False) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_TRUNC), 0o600)
    with os.fdopen(fd, "a" if append else "w") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


def _api_env(name: str) -> str:
    run = subprocess.run(["docker", "exec", "api", "printenv", name], capture_output=True, text=True,
                         timeout=60, check=False)
    return run.stdout if run.returncode == 0 else ""


def _domains(raw: str) -> list[str]:
    return [d.strip().lstrip("@").lower() for d in raw.split(",") if d.strip()]


def signup_mailbox(target: str, printenv=None) -> tuple[str, str]:
    """(email domain, inbox kind) for a target.

    Inbox Kitten wherever the server admits it. Dev limits signup to its approved test domains
    (SIGNUP_TEST_EMAIL_DOMAINS); unless inboxkitten.com is one of them, dev runs use the first
    approved domain and the worker reads the codes from the dev cache (as dev_test_account.py).
    """
    if target != "dev":
        return EMAIL_DOMAIN, "inboxkitten"
    printenv = printenv or _api_env
    restricted = _domains(printenv("SIGNUP_DOMAIN_RESTRICTION"))
    approved = _domains(printenv("SIGNUP_TEST_EMAIL_DOMAINS"))
    if (not restricted and not approved) or EMAIL_DOMAIN in restricted + approved:
        return EMAIL_DOMAIN, "inboxkitten"
    if not approved:
        raise RuntimeError("dev signup is domain-restricted and has no approved test domain")
    return approved[0], "dev_cache"


def new_identity(base: Path | None = None, domain: str = EMAIL_DOMAIN) -> dict[str, str]:
    """Fresh email, username and password; the email never appeared in the registry before."""
    known = {entry.get("email") for entry in registry_entries(base)}
    while True:
        email = f"{EMAIL_PREFIX}{secrets.token_hex(8)}@{domain}"
        if email not in known:
            break
    username = "ait" + secrets.token_hex(5)
    password = secrets.token_urlsafe(24) + "aZ9!" + secrets.choice(string.ascii_uppercase) + "#7"
    return {"email": email, "username": username, "password": password}


def registry_path(base: Path | None = None) -> Path:
    return home(base) / "accounts.jsonl"


def registry_entries(base: Path | None = None) -> list[dict]:
    path = (base or HOME) / "accounts.jsonl"
    if not path.exists():
        return []
    entries = []
    for line in path.read_text().splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def register_account(email: str, target: str, run_id: str, persona: str, status: str = "created",
                     base: Path | None = None) -> None:
    entry = {"email": email, "target": target, "run_id": run_id, "persona": persona,
             "created_at": datetime.now(UTC).isoformat(), "status": status}
    _private_write(registry_path(base), json.dumps(entry) + "\n", append=True)


def update_status(email: str, status: str, base: Path | None = None) -> None:
    """Append a status line (history is kept; the latest line per email wins)."""
    last = next((e for e in reversed(registry_entries(base)) if e.get("email") == email), None)
    if last:
        register_account(email, last["target"], last["run_id"], last["persona"], status, base)


def latest_by_email(base: Path | None = None) -> dict[str, dict]:
    return {e["email"]: e for e in registry_entries(base)}


def secret_path(email: str, base: Path | None = None) -> Path:
    directory = home(base) / "secrets"
    directory.mkdir(exist_ok=True)
    os.chmod(directory, 0o700)
    return directory / (email.replace("@", "_at_") + ".json")


def save_secret(email: str, signup: dict, base: Path | None = None) -> None:
    _private_write(secret_path(email, base), json.dumps(signup))


def load_secret(email: str, base: Path | None = None) -> dict | None:
    path = secret_path(email, base)
    return json.loads(path.read_text()) if path.exists() else None


def remove_secret(email: str, base: Path | None = None) -> None:
    secret_path(email, base).unlink(missing_ok=True)


STALE_ACCOUNT_SECONDS = 2 * 3600  # accounts live under an hour; older leftovers belong to no running run


def pending_deletions(base: Path | None = None, run_id: str | None = None, now: datetime | None = None) -> list[dict]:
    """Registry accounts whose deletion did not finish and whose secret file still exists.

    With `run_id`, only that run's accounts and stale leftovers of earlier runs: another run that is
    still going (a manual run next to the daily one) keeps its accounts until it deletes them itself.
    """
    now = now or datetime.now(UTC)

    def ours(entry: dict) -> bool:
        if run_id is None or entry.get("run_id") == run_id:
            return True
        created = datetime.fromisoformat(entry["created_at"])
        return (now - created).total_seconds() > STALE_ACCOUNT_SECONDS

    return [e for e in latest_by_email(base).values()
            if e["status"] in ("delete_failed", "created", "signed_up") and load_secret(e["email"], base)
            and ours(e)]


# --- production gate and gift cards -----------------------------------------------


def prod_enabled(base: Path | None = None) -> bool:
    return (home(base) / PROD_ENABLED_FILE).exists()


def pop_prod_code(base: Path | None = None) -> tuple[str | None, int]:
    """Take one prod gift card code (consumed codes move to a .used file); returns (code, remaining)."""
    directory = home(base)
    path = directory / PROD_CODES_FILE
    if not path.exists():
        return None, 0
    with path.open("r+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        codes = [line.strip() for line in handle.read().splitlines() if line.strip() and not line.startswith("#")]
        if not codes:
            return None, 0
        code, rest = codes[0], codes[1:]
        handle.seek(0)
        handle.truncate()
        handle.write("".join(c + "\n" for c in rest))
    _private_write(directory / (PROD_CODES_FILE + ".used"), f"{code} {datetime.now(UTC).isoformat()}\n", append=True)
    os.chmod(path, 0o600)
    return code, len(rest)


def low_codes_message() -> str:
    return ("❓ Prod gift cards for the AI test users are running low. Please reconnect prod SSH and run "
            "`create_test_gift_card_batch.py` to refill prod-gift-cards.txt.")


def notify_low_codes(remaining: int, post_push=None, base: Path | None = None) -> bool:
    """Send ONE push per batch when <= LOW_CODES_THRESHOLD codes remain; the marker clears on refill."""
    marker = home(base) / LOW_MARKER
    if remaining > LOW_CODES_THRESHOLD:
        marker.unlink(missing_ok=True)
        return False
    if marker.exists():
        return False
    (post_push or _push)(low_codes_message(), "AI test users gift cards")
    _private_write(marker, datetime.now(UTC).isoformat())
    return True


def _push(message: str, title: str) -> None:
    import time

    import agent_question
    import discord_webhook
    from pending_work_gate import canonical_root

    root = canonical_root()
    agent_question.deliver(agent_question.webhook(root), message, discord_webhook.post_message)
    agent_question.record_push(root, message, time.time(), title=title, source=PUSH_SOURCE)


# --- dev gift card and invite (created inside the dev api container) ------------------

_CARD_PROGRAM = """
import json, os, sys, urllib.request, urllib.error
base = os.getenv('CMS_URL', 'http://cms:8055').rstrip('/')
email = os.getenv('DIRECTUS_ADMIN_EMAIL') or os.getenv('DATABASE_ADMIN_EMAIL')
password = os.getenv('DIRECTUS_ADMIN_PASSWORD') or os.getenv('DATABASE_ADMIN_PASSWORD')
assert email and password
def call(path, body, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers=headers, method='POST')
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
token = call('/auth/login', {'email': email, 'password': password})['data']['access_token']
code, invite, credits = sys.argv[1], sys.argv[2], int(sys.argv[3])
call('/items/invite_codes', {'code': invite, 'remaining_uses': 1, 'is_admin': False, 'gifted_credits': 0}, token)
card = {'code': code, 'credits_value': credits, 'notes': 'AI test user (single use)'}
try:
    call('/items/gift_cards', {**card, 'marks_test_account': True}, token)
except urllib.error.HTTPError as exc:
    if exc.code not in (400, 403):
        raise
    print('WARNING: marks_test_account missing on gift_cards, created without it', file=sys.stderr)
    call('/items/gift_cards', card, token)
"""


GIFT_CARD_CHARSET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # the web deep link rejects I, O, 0 and 1


def _random_code() -> str:
    alphabet = GIFT_CARD_CHARSET
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


def create_dev_card(run_docker=None) -> dict[str, str]:
    """One single-use 1,000-credit dev gift card plus a 0-credit single-use invite; returns both codes."""
    code, invite = _random_code(), secrets.token_hex(9)
    run = run_docker or (lambda *a: subprocess.run(["docker", *a], capture_output=True, text=True,
                                                   timeout=90, check=False))
    result = run("exec", "api", "python3", "-c", _CARD_PROGRAM, code, invite, str(GIFT_CREDITS))
    if result.returncode:
        raise RuntimeError(f"dev gift card creation failed: {result.stderr[-300:]}")
    if "WARNING" in result.stderr:
        print(result.stderr.strip(), flush=True)
    return {"gift_card_code": code, "invite_code": invite}
