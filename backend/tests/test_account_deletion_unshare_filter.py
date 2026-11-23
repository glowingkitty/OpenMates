"""Regression: account deletion step 8 (unshare shared chats) filtered chats on
user_created, a field chats does not have, so Directus answered 403 and shared
links were never revoked before content deletion. Chats are owned by
hashed_user_id (backend/core/directus/schemas/chats.yml)."""
# contract-test-file: infrastructure
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_chats_schema_has_owner_hash_and_no_user_created():
    fields = yaml.safe_load((ROOT / "backend/core/directus/schemas/chats.yml").read_text())["chats"]["fields"]
    assert "hashed_user_id" in fields and "user_created" not in fields


def test_account_deletion_unshare_queries_chats_by_owner_hash():
    src = (ROOT / "backend/core/api/app/tasks/user_cache_tasks.py").read_text()
    block = src[src.index("# 8. Unshare all shared chats"):src.index("# 9. Sessions & Tokens")]
    assert re.search(r'"hashed_user_id":\s*\{"_eq":\s*user_id_hash\}', block)
    assert '"user_created"' not in block
