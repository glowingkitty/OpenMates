"""
Contract tests for shared-chat embed hash lookups.

Public shared-chat payloads resolve key-addressable embeds through
embed_keys.hashed_embed_id, so embed rows must persist the same deterministic
hash. These tests keep the Directus schema and Python read/write contract in
sync before Playwright catches missing preview cards.
"""

import hashlib
from pathlib import Path

import yaml

from backend.core.api.app.services.directus import embed_methods


BACKEND_ROOT = Path(__file__).resolve().parents[1]
EMBEDS_SCHEMA_PATH = BACKEND_ROOT / "core/directus/schemas/embeds.yml"


def _field_names(fields: str) -> set[str]:
    return {field.strip() for field in fields.split(",") if field.strip()}


def test_embeds_schema_declares_hashed_embed_id() -> None:
    schema = yaml.safe_load(EMBEDS_SCHEMA_PATH.read_text())

    assert "hashed_embed_id" in schema["embeds"]["fields"]
    assert "hashed_embed_id" in _field_names(embed_methods.EMBED_ALL_FIELDS)


def test_embed_payloads_derive_hashed_embed_id() -> None:
    payload = {"embed_id": "embed-1", "status": "finished", "hashed_embed_id": "stale"}

    updated_payload = embed_methods._with_hashed_embed_id(payload, "embed-1")

    assert updated_payload["hashed_embed_id"] == hashlib.sha256(b"embed-1").hexdigest()
    assert payload["hashed_embed_id"] == "stale"
