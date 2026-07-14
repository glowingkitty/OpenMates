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
import json
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


def candidate_cte(known_hashes: Sequence[KnownAccountHash]) -> str:
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
)
""".strip()


def summary_sql(known_hashes: Sequence[KnownAccountHash]) -> str:
    return candidate_cte(known_hashes) + """
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


def candidate_ids_sql(known_hashes: Sequence[KnownAccountHash], limit: int) -> str:
    return candidate_cte(known_hashes) + f"""
select id
from candidates
order by last_access nulls first, id
limit {int(limit)};
"""


def sample_sql(known_hashes: Sequence[KnownAccountHash], limit: int = 20) -> str:
    return candidate_cte(known_hashes) + f"""
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


def get_candidate_ids(known_hashes: Sequence[KnownAccountHash], limit: int) -> list[str]:
    output = run_psql("\\t on\n" + candidate_ids_sql(known_hashes, limit))
    return [line.strip() for line in output.splitlines() if line.strip() and line.strip() != "id"]


def delete_with_product_path(user_ids: Sequence[str]) -> None:
    code = r'''
import asyncio
import json
import logging
import sys
import uuid

logging.disable(logging.CRITICAL)

from backend.core.api.app.tasks.user_cache_tasks import _async_delete_user_account


async def main() -> int:
    user_ids = json.load(sys.stdin)
    failures = 0
    for user_id in user_ids:
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
        print(json.dumps({"user_prefix": user_id[:8], "success": bool(ok)}), flush=True)
        if not ok:
            failures += 1
    return 1 if failures else 0


raise SystemExit(asyncio.run(main()))
'''
    result = _run(
        ["docker", "exec", "-i", API_CONTAINER, "python", "-c", code],
        input_text=json.dumps(list(user_ids)),
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
        "--confirm-delete-zero-content-users",
        action="store_true",
        help="Required with --apply to acknowledge deletion of zero-content stale dev users.",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Maximum candidates to delete in one apply run.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    if args.apply and not args.confirm_delete_zero_content_users:
        raise SystemExit("--apply requires --confirm-delete-zero-content-users")
    if args.limit <= 0:
        raise SystemExit("--limit must be positive")

    known_hashes = get_configured_test_account_hashes()
    print(f"Configured test-account hashes preserved: {len(known_hashes)}")
    print("\nCandidate summary:")
    print(run_psql(summary_sql(known_hashes)))
    print("\nCandidate sample:")
    print(run_psql(sample_sql(known_hashes)))

    if not args.apply:
        print("\nDry-run only. No users were deleted.")
        return 0

    candidate_ids = get_candidate_ids(known_hashes, args.limit)
    if not candidate_ids:
        print("No candidate users to delete.")
        clear_signup_requirement_cache()
        return 0

    print(f"\nDeleting {len(candidate_ids)} zero-content stale dev signup account(s)...")
    delete_with_product_path(candidate_ids)
    clear_signup_requirement_cache()
    print("Cleared require_invite_code cache.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
