#!/usr/bin/env python3
# scripts/cleanup_dev_signup_accounts.py
#
# Dry-run-first maintenance tool for dev signup-limit cleanup. The dev server can
# accumulate failed E2E signup accounts that completed enough of the flow to count
# against SIGNUP_LIMIT, even when they have no chats, messages, or embeds.
#
# The script never prints plaintext test-account emails. It preserves configured
# OPENMATES_TEST_ACCOUNT_*_EMAIL users by hashing those secrets inside the api
# container, reports candidate counts, and only applies deletion with an explicit
# confirmation flag.

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from typing import Iterable, Sequence


API_CONTAINER = "api"
DATABASE_CONTAINER = "cms-database"
DATABASE_NAME = "directus"
DATABASE_USER = "directus"
DEFAULT_LIMIT = 600
DEFAULT_AUTO_SAFE_AGE_DAYS = 7
AUTO_SAFE_USERNAME_REGEX = (
    "^(testacct([1-9]|1[0-9]|2[0-7])[a-z0-9]{6}|"
    "cliprov(1[4-9]|20)[a-z0-9]{6}|"
    "ref_[a-z0-9_]{12}|"
    "(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    "(0[1-9]|[12][0-9]|3[01])([01][0-9]|2[0-3])"
    "[0-5][0-9][0-5][0-9][a-z0-9]{3})$"
)
REQUIRED_TEST_ACCOUNT_SLOTS = set(range(1, 28))
PROTECTED_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


@dataclass(frozen=True)
class KnownAccountHash:
    label: str
    hashed_email: str


def _run(command: Sequence[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def configured_account_hashes_from_payload(accounts: Sequence[dict]) -> list[KnownAccountHash]:
    """Hash supplied account emails without retaining plaintext identifiers."""
    hashes: list[KnownAccountHash] = []
    seen: set[str] = set()
    for account in accounts:
        email = str(account.get("email") or "").strip().lower()
        if not email or "@" not in email:
            continue
        hashed_email = base64.b64encode(hashlib.sha256(email.encode()).digest()).decode()
        if hashed_email in seen:
            continue
        seen.add(hashed_email)
        hashes.append(KnownAccountHash(label=str(account.get("slot") or "unknown"), hashed_email=hashed_email))
    return hashes


def _merge_known_hashes(*groups: Sequence[KnownAccountHash]) -> list[KnownAccountHash]:
    merged: dict[str, KnownAccountHash] = {}
    for group in groups:
        for account in group:
            merged.setdefault(account.hashed_email, account)
    return list(merged.values())


def validate_automated_protected_accounts(accounts: Sequence[dict]) -> None:
    if len(accounts) != len(REQUIRED_TEST_ACCOUNT_SLOTS):
        raise SystemExit("automatic cleanup requires exactly slots 1-27 with distinct emails")
    slots: set[int] = set()
    emails: set[str] = set()
    for account in accounts:
        try:
            slot = int(account.get("slot"))
        except (TypeError, ValueError):
            continue
        email = str(account.get("email") or "").strip().lower()
        if not PROTECTED_EMAIL_PATTERN.fullmatch(email):
            continue
        slots.add(slot)
        emails.add(email)
    if slots != REQUIRED_TEST_ACCOUNT_SLOTS or len(emails) != len(REQUIRED_TEST_ACCOUNT_SLOTS):
        raise SystemExit("automatic cleanup requires exactly slots 1-27 with distinct emails")


def is_auto_safe_username(username: str) -> bool:
    return re.fullmatch(AUTO_SAFE_USERNAME_REGEX, username) is not None


def get_configured_test_account_hashes() -> list[KnownAccountHash]:
    code = r'''
import base64
import hashlib
import json
import os

rows = []
seen = set()
for key, value in sorted(os.environ.items()):
    if not key.startswith("OPENMATES_TEST_ACCOUNT") or not key.endswith("EMAIL"):
        continue
    if not value or "@" not in value:
        continue
    label = key.removeprefix("OPENMATES_TEST_ACCOUNT_").removesuffix("_EMAIL") or "default"
    digest = hashlib.sha256(value.lower().strip().encode()).digest()
    hashed_email = base64.b64encode(digest).decode()
    if hashed_email in seen:
        continue
    seen.add(hashed_email)
    rows.append({"label": label, "hashed_email": hashed_email})

expanded = json.loads(os.environ.get("OPENMATES_TEST_ACCOUNTS_EXPANDED_JSON") or "{}")
for slot, account in sorted(expanded.items()):
    value = account.get("email", "") if isinstance(account, dict) else ""
    if not value or "@" not in value:
        continue
    digest = hashlib.sha256(value.lower().strip().encode()).digest()
    hashed_email = base64.b64encode(digest).decode()
    if hashed_email in seen:
        continue
    seen.add(hashed_email)
    rows.append({"label": str(slot), "hashed_email": hashed_email})

print(json.dumps(rows))
'''
    result = _run(["docker", "exec", API_CONTAINER, "python", "-c", code])
    if result.returncode != 0:
        raise RuntimeError(
            "Failed to read configured test-account hashes from api container:\n"
            f"{result.stderr.strip()}"
        )

    return [KnownAccountHash(**row) for row in json.loads(result.stdout)]


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def known_values_sql(known_hashes: Sequence[KnownAccountHash]) -> str:
    if not known_hashes:
        return "select null::text as label, null::text as hashed_email where false"

    values = ", ".join(
        f"({sql_literal(item.label)}, {sql_literal(item.hashed_email)})" for item in known_hashes
    )
    return f"values {values}"


def candidate_cte(
    known_hashes: Sequence[KnownAccountHash],
    *,
    auto_safe: bool = False,
    older_than_days: int = DEFAULT_AUTO_SAFE_AGE_DAYS,
) -> str:
    auto_safe_sql = ""
    if auto_safe:
        auto_safe_sql = f"""
      and coalesce(u.signup_completed, false) = false
      and u.last_access is not null
      and u.last_access < now() - interval '{int(older_than_days)} days'
"""
    return f"""
with known(label, hashed_email) as ({known_values_sql(known_hashes)}),
user_base as (
    select
        u.id,
        u.email,
        u.hashed_email,
        u.is_admin,
        u.signup_completed,
        u.signup_started_at,
        u.last_access,
        u.last_opened,
        encode(sha256(u.id::text::bytea), 'hex') as user_id_hash
    from directus_users u
),
content_counts as (
    select
        u.id,
        coalesce(chats.chat_count, 0) as chat_count,
        coalesce(messages.message_count, 0) as message_count,
        coalesce(embeds.embed_count, 0) as embed_count
    from user_base u
    left join (
        select hashed_user_id, count(*) as chat_count from chats group by hashed_user_id
    ) chats on chats.hashed_user_id = u.user_id_hash
    left join (
        select hashed_user_id, count(*) as message_count from messages group by hashed_user_id
    ) messages on messages.hashed_user_id = u.user_id_hash
    left join (
        select hashed_user_id, count(*) as embed_count from embeds group by hashed_user_id
    ) embeds on embeds.hashed_user_id = u.user_id_hash
),
candidates as (
    select
        u.id,
        u.signup_completed,
        u.signup_started_at,
        u.last_access,
        u.last_opened,
        c.chat_count,
        c.message_count,
        c.embed_count
    from user_base u
    join content_counts c on c.id = u.id
    left join known k on k.hashed_email = u.hashed_email
    where coalesce(u.is_admin, false) = false
      and k.hashed_email is null
      and c.chat_count = 0
      and c.message_count = 0
      and c.embed_count = 0
      {auto_safe_sql}
      and (
          u.signup_started_at is not null
          or u.signup_completed is true
          or u.last_opened like '/chat/%'
          or u.last_opened ~* '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$'
      )
)
""".strip()


def summary_sql(
    known_hashes: Sequence[KnownAccountHash],
    *,
    auto_safe: bool = False,
    older_than_days: int = DEFAULT_AUTO_SAFE_AGE_DAYS,
) -> str:
    return candidate_cte(known_hashes, auto_safe=auto_safe, older_than_days=older_than_days) + """
select
    count(*) as candidate_users,
    count(*) filter (
        where last_opened like '/chat/%'
           or last_opened ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    ) as signup_limit_counted_candidates,
    count(*) filter (where signup_started_at is not null) as signup_started_candidates,
    count(*) filter (where signup_completed is true) as signup_completed_flag_candidates,
    min(last_access) as oldest_last_access,
    max(last_access) as newest_last_access
from candidates;
"""


def candidate_ids_sql(
    known_hashes: Sequence[KnownAccountHash],
    limit: int,
    *,
    auto_safe: bool = False,
    older_than_days: int = DEFAULT_AUTO_SAFE_AGE_DAYS,
) -> str:
    return candidate_cte(known_hashes, auto_safe=auto_safe, older_than_days=older_than_days) + f"""
select id
from candidates
order by last_access nulls first, id
limit {int(limit)};
"""


def sample_sql(
    known_hashes: Sequence[KnownAccountHash],
    limit: int = 20,
    *,
    auto_safe: bool = False,
    older_than_days: int = DEFAULT_AUTO_SAFE_AGE_DAYS,
) -> str:
    return candidate_cte(known_hashes, auto_safe=auto_safe, older_than_days=older_than_days) + f"""
select
    left(id::text, 8) as user_prefix,
    signup_completed,
    signup_started_at,
    last_access,
    last_opened
from candidates
order by last_access nulls first, id
limit {int(limit)};
"""


def run_psql(sql: str) -> str:
    result = _run(
        [
            "docker",
            "exec",
            "-i",
            DATABASE_CONTAINER,
            "psql",
            "-U",
            DATABASE_USER,
            "-d",
            DATABASE_NAME,
            "-P",
            "pager=off",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input_text=sql,
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def get_candidate_ids(
    known_hashes: Sequence[KnownAccountHash],
    limit: int,
    *,
    auto_safe: bool = False,
    older_than_days: int = DEFAULT_AUTO_SAFE_AGE_DAYS,
) -> list[str]:
    output = run_psql(
        "\\t on\n" + candidate_ids_sql(
            known_hashes,
            limit,
            auto_safe=auto_safe,
            older_than_days=older_than_days,
        )
    )
    return [line.strip() for line in output.splitlines() if line.strip() and line.strip() != "id"]


def get_server_environment() -> str:
    result = _run([
        "docker",
        "exec",
        API_CONTAINER,
        "python",
        "-c",
        "import os; print(os.getenv('SERVER_ENVIRONMENT', ''))",
    ])
    if result.returncode != 0:
        raise RuntimeError(f"Failed to read SERVER_ENVIRONMENT: {result.stderr.strip()}")
    return result.stdout.strip().lower()


def delete_with_product_path(
    user_ids: Sequence[str],
    *,
    known_hashes: Sequence[KnownAccountHash],
    auto_safe: bool,
    older_than_days: int,
) -> None:
    code = r'''
import asyncio
import datetime
import hashlib
import json
import logging
import re
import sys
import uuid

logging.disable(logging.CRITICAL)

from backend.core.api.app.tasks.user_cache_tasks import _async_delete_user_account
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService


async def auto_safe_eligible(directus, encryption, user_id, protected_hashes, username_regex, older_than_days):
    user = await directus.get_user_fields_direct(user_id, [
        "id", "is_admin", "signup_completed", "last_access", "hashed_email",
        "encrypted_username", "vault_key_id",
    ])
    if not user or user.get("is_admin") or user.get("signup_completed"):
        return False
    if user.get("hashed_email") in protected_hashes:
        return False

    last_access_raw = user.get("last_access")
    try:
        last_access = datetime.datetime.fromisoformat(str(last_access_raw).replace("Z", "+00:00"))
        if last_access.tzinfo is None:
            last_access = last_access.replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return False
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=older_than_days)
    if last_access >= cutoff:
        return False

    encrypted_username = user.get("encrypted_username")
    vault_key_id = user.get("vault_key_id")
    if not encrypted_username or not vault_key_id:
        return False
    try:
        username = await encryption.decrypt_with_user_key(encrypted_username, vault_key_id)
    except Exception:
        return False
    if not username or re.fullmatch(username_regex, username) is None:
        return False

    user_hash = hashlib.sha256(user_id.encode()).hexdigest()
    for collection in ("chats", "messages", "embeds"):
        rows = await directus.get_items(
            collection,
            params={
                "fields": "id",
                "filter": {"hashed_user_id": {"_eq": user_hash}},
                "limit": 1,
            },
            admin_required=True,
        )
        if rows:
            return False
    return True


async def main() -> int:
    payload = json.load(sys.stdin)
    user_ids = payload["user_ids"]
    auto_safe = bool(payload["auto_safe"])
    failures = 0
    skipped = 0
    cache = CacheService()
    encryption = EncryptionService()
    directus = DirectusService(cache_service=cache, encryption_service=encryption)
    try:
        for user_id in user_ids:
            if auto_safe and not await auto_safe_eligible(
                directus,
                encryption,
                user_id,
                set(payload["protected_hashes"]),
                payload["username_regex"],
                int(payload["older_than_days"]),
            ):
                skipped += 1
                print(json.dumps({"user_prefix": user_id[:8], "success": False, "skipped": True}), flush=True)
                continue
            task_id = f"dev-signup-cleanup-{uuid.uuid4()}"
            ok = await _async_delete_user_account(
                user_id=user_id,
                deletion_type="dev_stale_signup_cleanup",
                reason="Remove zero-content stale dev signup account from SIGNUP_LIMIT count",
                ip_address=None,
                device_fingerprint=None,
                refund_invoices=False,
                task_id=task_id,
            )
            print(json.dumps({"user_prefix": user_id[:8], "success": bool(ok), "skipped": False}), flush=True)
            if not ok:
                failures += 1
    finally:
        await directus.close()
        await cache.close()
    print(json.dumps({"deleted_or_attempted": len(user_ids) - skipped, "skipped": skipped}), flush=True)
    return 1 if failures else 0


raise SystemExit(asyncio.run(main()))
'''
    result = _run(
        ["docker", "exec", "-i", API_CONTAINER, "python", "-c", code],
        input_text=json.dumps({
            "user_ids": list(user_ids),
            "protected_hashes": [account.hashed_email for account in known_hashes],
            "auto_safe": auto_safe,
            "older_than_days": older_than_days,
            "username_regex": AUTO_SAFE_USERNAME_REGEX,
        }),
    )
    progress_lines = [
        line for line in result.stdout.splitlines()
        if line.strip().startswith("{") and '"user_prefix"' in line
    ]
    for line in progress_lines:
        print(line)
    if result.returncode != 0:
        raise RuntimeError(
            "Product deletion path reported at least one failed deletion. "
            f"Progress rows: {len(progress_lines)}. Stderr: {result.stderr.strip()}"
        )


def clear_signup_requirement_cache() -> None:
    code = r'''
import asyncio

from backend.core.api.app.services.cache import CacheService


async def main() -> None:
    cache = CacheService()
    try:
        await cache.delete("require_invite_code")
    finally:
        await cache.close()


asyncio.run(main())
'''
    result = _run(["docker", "exec", API_CONTAINER, "python", "-c", code])
    if result.returncode != 0:
        raise RuntimeError(f"Failed to clear require_invite_code cache:\n{result.stderr.strip()}")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run or delete zero-content stale dev signup accounts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Default dry-run:
              python3 scripts/cleanup_dev_signup_accounts.py

            Apply conservative zero-content cleanup:
              python3 scripts/cleanup_dev_signup_accounts.py --apply --confirm-delete-zero-content-users
            """
        ),
    )
    parser.add_argument("--apply", action="store_true", help="Delete candidate users with the product account-deletion path.")
    parser.add_argument(
        "--auto-safe",
        action="store_true",
        help="Restrict apply mode to old incomplete zero-content accounts.",
    )
    parser.add_argument(
        "--automated-daily-cleanup",
        action="store_true",
        help="Authorize the daily runner's narrowly scoped automatic cleanup mode.",
    )
    parser.add_argument(
        "--confirm-delete-zero-content-users",
        action="store_true",
        help="Required with --apply to acknowledge deletion of zero-content stale dev users.",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Maximum candidates to delete in one apply run.")
    parser.add_argument("--older-than-days", type=int, default=DEFAULT_AUTO_SAFE_AGE_DAYS)
    parser.add_argument(
        "--protected-accounts-json",
        help="JSON list of configured slot/email objects, or '-' to read it from stdin.",
    )
    parser.add_argument("--require-protected-count", type=int, default=0)
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    if args.auto_safe and not args.apply:
        raise SystemExit("--auto-safe requires --apply")
    if args.auto_safe and not args.automated_daily_cleanup:
        raise SystemExit("--auto-safe requires --automated-daily-cleanup")
    if args.apply and not args.confirm_delete_zero_content_users and not args.auto_safe:
        raise SystemExit("--apply requires --confirm-delete-zero-content-users")
    if args.limit <= 0:
        raise SystemExit("--limit must be positive")

    if args.older_than_days <= 0:
        raise SystemExit("--older-than-days must be positive")
    if args.auto_safe and get_server_environment() != "development":
        raise SystemExit("refusing automatic cleanup outside SERVER_ENVIRONMENT=development")

    supplied_accounts: list[dict] = []
    if args.protected_accounts_json:
        raw_accounts = sys.stdin.read() if args.protected_accounts_json == "-" else args.protected_accounts_json
        supplied_accounts = json.loads(raw_accounts)
        if not isinstance(supplied_accounts, list):
            raise SystemExit("--protected-accounts-json must contain a JSON list")

    supplied_hashes = configured_account_hashes_from_payload(supplied_accounts)
    if args.auto_safe:
        validate_automated_protected_accounts(supplied_accounts)
    if len(supplied_hashes) < args.require_protected_count:
        raise SystemExit(
            f"refusing cleanup: protected account count {len(supplied_hashes)} "
            f"is below required {args.require_protected_count}"
        )

    known_hashes = _merge_known_hashes(get_configured_test_account_hashes(), supplied_hashes)
    print(f"Configured test-account hashes preserved: {len(known_hashes)}")
    print("\nCandidate summary:")
    print(run_psql(summary_sql(known_hashes, auto_safe=args.auto_safe, older_than_days=args.older_than_days)))
    print("\nCandidate sample:")
    print(run_psql(sample_sql(known_hashes, auto_safe=args.auto_safe, older_than_days=args.older_than_days)))

    if not args.apply:
        print("\nDry-run only. No users were deleted.")
        return 0

    candidate_ids = get_candidate_ids(
        known_hashes,
        args.limit,
        auto_safe=args.auto_safe,
        older_than_days=args.older_than_days,
    )
    if not candidate_ids:
        print("No candidate users to delete.")
        clear_signup_requirement_cache()
        return 0

    print(f"\nDeleting {len(candidate_ids)} zero-content stale dev signup account(s)...")
    delete_with_product_path(
        candidate_ids,
        known_hashes=known_hashes,
        auto_safe=args.auto_safe,
        older_than_days=args.older_than_days,
    )
    clear_signup_requirement_cache()
    print("Cleared require_invite_code cache.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
