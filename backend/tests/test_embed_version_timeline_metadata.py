"""Version timeline metadata: kind enum, sealed name, hashed contributors and session compaction.

Specification: live-collab.versions.named-snapshots. The route is called through
the helpers of the user-revision route tests; the compaction plan is a pure
function and its batch runner uses a fake Directus.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.core.api.app.routes import embed_user_revisions as routes
from backend.core.api.app.routes.embeds_api import _version_meta, derive_version_kind
from backend.core.api.app.services import embed_version_compaction_service as compaction
from backend.tests.test_embed_user_revisions_routes import (  # noqa: F401  (fixture is autouse)
    FakeCache, FakeDirectus, _body, _commit, _committed, _internal_token,
)

NOW = 1_800_000_000
OLD = NOW - 40 * 86_400
DAY = 86_400


# contract-test: direct surface=rest_api assertions=live-collab.versions.named-snapshots
def test_request_without_timeline_fields_stays_valid_and_forwards_none():
    body = _body()
    assert body.version_kind is None and body.encrypted_version_name is None and body.contributors is None
    dumped = body.model_dump(exclude_unset=True)
    assert not {"version_kind", "encrypted_version_name", "contributors"} & dumped.keys()


@pytest.mark.parametrize("kind", ["session", "assistant", "restore", "named", "commit"])
# contract-test: direct surface=rest_api assertions=live-collab.versions.named-snapshots
def test_every_version_kind_is_accepted(kind):
    assert _body(version_kind=kind).version_kind == kind


@pytest.mark.parametrize("extra", [
    {"version_kind": "weekly"},
    {"version_kind": "session", "encrypted_version_name": "sealed"},
    {"encrypted_version_name": "sealed"},
    {"version_kind": "named", "encrypted_version_name": ""},
    {"version_kind": "named", "encrypted_version_name": "x" * (routes.MAX_VERSION_NAME_LENGTH + 1)},
    {"contributors": []},
    {"contributors": [{"user_hash": "plain-user-id"}]},
    {"contributors": [{"user_hash": "a" * 64, "mate_name": "Sophia"}]},
    {"contributors": [{}]},
    {"contributors": [{"mate_name": "Sophia"}] * (routes.MAX_CONTRIBUTORS + 1)},
])
# contract-test: direct surface=rest_api assertions=live-collab.versions.named-snapshots
def test_invalid_timeline_metadata_is_refused(extra):
    with pytest.raises(ValidationError):
        _body(**extra)


# contract-test: direct surface=rest_api assertions=live-collab.versions.named-snapshots
@pytest.mark.asyncio
async def test_timeline_metadata_is_forwarded_to_the_allowlisting_transaction():
    directus = FakeDirectus(payload=_committed())
    contributors = [{"user_hash": "a" * 64}, {"mate_name": "Sophia"}]
    await _commit(directus, _body(version_kind="named", encrypted_version_name="sealed-name", contributors=contributors))
    sent = directus.sent[0]
    assert sent["version_kind"] == "named" and sent["encrypted_version_name"] == "sealed-name"
    assert sent["contributors"] == contributors


# contract-test: direct surface=rest_api assertions=live-collab.versions.named-snapshots
def test_legacy_rows_derive_their_kind_and_expose_metadata():
    assert derive_version_kind({"revision_origin": None}) == "assistant"
    assert derive_version_kind({"revision_origin": "user", "revision_action": "edit"}) == "session"
    assert derive_version_kind({"revision_origin": "user", "revision_action": "restore"}) == "restore"
    assert derive_version_kind({"revision_origin": "user", "version_kind": "named"}) == "named"
    meta = _version_meta({"version_number": 2, "created_at": 5, "revision_origin": "user", "compacted_at": 9,
                          "contributors": '[{"mate_name": "Sophia"}]'})
    assert meta["contributors"] == [{"mate_name": "Sophia"}] and meta["compacted"] is True


def _row(version, created_at, embed="e1", **extra):
    return {"id": f"{embed}-{version}", "embed_id": embed, "version_number": version, "created_at": created_at,
            "revision_origin": "user", "revision_action": "edit", **extra}


# contract-test: direct surface=rest_api assertions=live-collab.versions.named-snapshots
def test_compaction_keeps_the_last_session_row_per_embed_and_day():
    day = (OLD // DAY) * DAY
    rows = [
        _row(2, day + 10), _row(3, day + 500), _row(4, day + 900),
        _row(5, day + DAY + 5),
        _row(2, day + 10, embed="e2"),
    ]
    planned = compaction.plan_session_compaction(rows, now=NOW)
    assert [(row["embed_id"], row["version_number"]) for row in planned] == [("e1", 2), ("e1", 3)]


# contract-test: direct surface=rest_api assertions=live-collab.versions.named-snapshots
def test_compaction_never_selects_named_recent_assistant_restore_or_compacted_rows():
    day = (OLD // DAY) * DAY
    rows = [
        _row(2, day + 1),
        _row(3, day + 2, version_kind="named", encrypted_version_name="sealed"),
        _row(4, day + 3, revision_action="restore"),
        _row(5, day + 4, revision_origin=None, revision_action=None),
        _row(6, day + 5, compacted_at=NOW - 100),
        _row(7, NOW - 5 * DAY),
        _row(8, day + 6, version_kind="commit"),
        _row(9, day + 7),
    ]
    assert compaction.plan_session_compaction(rows, now=NOW) == [rows[0]]


# contract-test: direct surface=rest_api assertions=live-collab.versions.named-snapshots
@pytest.mark.asyncio
async def test_compaction_runner_marks_only_planned_rows_and_never_touches_ciphertext():
    day = (OLD // DAY) * DAY

    class Directus:
        updates = []

        async def get_items(self, collection, params=None, **kwargs):
            assert collection == "embed_diffs" and "encrypted" not in params["fields"].replace("encrypted_version_name", "")
            return [_row(2, day + 1), _row(3, day + 2)]

        async def update_item(self, collection, item_id, data, **kwargs):
            self.updates.append((item_id, data))
            return True

    directus = Directus()
    result = await compaction.compact_session_versions(directus, now=NOW)
    assert result == {"scanned": 2, "planned": 1, "marked": 1}
    assert directus.updates == [("e1-2", {"compacted_at": NOW})]
