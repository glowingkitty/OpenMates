"""Bounded hot cursors through the actual internal JS query and SQLite truth.

SQLite executes the emitted SQL with only PostgreSQL cast/collation spellings
adapted. No Directus, network, application filtering or product runtime is used.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
from types import SimpleNamespace
from uuid import UUID

import pytest

from backend.core.api.app.services.directus.chat_methods import (
    ChatMethods,
    MESSAGE_ALL_FIELDS,
)

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = r"""
import { archiveOperation } from './backend/core/directus/extensions/chat-archive-transaction/src/operations.js';
const input = JSON.parse(await new Promise(resolve => {
  let text = ''; process.stdin.on('data', chunk => text += chunk);
  process.stdin.on('end', () => resolve(text));
}));
let query;
const trx = table => {
  if (table !== 'chats') throw new Error('Unexpected table');
  let chatId;
  const chain = { where: (field, value) => {
    if (field !== 'id') throw new Error('Unscoped chat'); chatId = value; return chain;
  }, forUpdate: () => chain, first: async () => input.chats.find(chat => chat.id === chatId) };
  return chain;
};
trx.raw = async (sql, bindings) => { query = {sql, bindings}; return {rows: []}; };
try {
  await archiveOperation({transaction: async action => action(trx)}, input.body);
  process.stdout.write(JSON.stringify({query}));
} catch (error) { process.stdout.write(JSON.stringify({error: error.code || error.message, status: error.status})); }
"""


def compiled(body, chats=None):
    output = subprocess.run(
        ["node", "--input-type=module", "-e", BRIDGE],
        cwd=ROOT,
        input=json.dumps(
            {
                "body": body,
                "chats": chats or [{"id": "chat", "hashed_user_id": "owner"}],
            }
        ),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(output.stdout)


def row(number, *, timestamp=10, client=True, chat="chat"):
    return {
        "id": str(UUID(int=number)),
        "client_message_id": f"m-{number:04d}" if client else None,
        "chat_id": chat,
        "created_at": timestamp,
        "role": "user",
        "encrypted_content": f"cipher-{number}",
    }


class SqlDirectus:
    base_url = "http://cms:8055"

    def __init__(self, rows, *, team=False):
        self.rows = rows
        self.chats = (
            [{"id": "chat", "hashed_team_id": "team"}]
            if team
            else [{"id": "chat", "hashed_user_id": "owner"}]
        )
        self.requests = []

    async def _make_api_request(self, method, url, *, headers, json):
        assert method == "POST" and url == self.base_url + "/chat-archive-transaction"
        assert headers == {"X-Internal-Service-Token": "disposable-internal-test"}
        self.requests.append(json)
        result = compiled(json, self.chats)
        if "error" in result:
            return SimpleNamespace(
                status_code=result["status"], json=lambda: {"error": result}
            )
        query = result["query"]
        # The actual query must perform all filtering/sorting/limiting in SQL.
        assert "chat_id = ?" in query["sql"] and "LIMIT ?" in query["sql"]
        assert "encrypted_content" in query["sql"] and "SELECT *" not in query["sql"]
        sql = (
            query["sql"]
            .replace("id::text", "CAST(id AS TEXT)")
            .replace("?::text", "CAST(? AS TEXT)")
            .replace('COLLATE "C"', "COLLATE BINARY")
        )
        with sqlite3.connect(":memory:") as db:
            db.row_factory = sqlite3.Row
            fields = MESSAGE_ALL_FIELDS.split(",")
            db.execute(
                "CREATE TABLE messages ("
                + ", ".join(
                    field + (" INTEGER" if field == "created_at" else " TEXT")
                    for field in fields
                )
                + ")"
            )
            db.executemany(
                "INSERT INTO messages VALUES (" + ",".join("?" for _ in fields) + ")",
                [[record.get(field) for field in fields] for record in self.rows],
            )
            records = [dict(record) for record in db.execute(sql, query["bindings"])]
        return SimpleNamespace(
            status_code=200, json=lambda: {"data": {"messages": records}}
        )

    async def get_items(self, collection, *, params, **kwargs):
        assert collection == "messages" and params["limit"] == 1
        # Anchor lookup uses equality only; Directus rejects relational string filters.
        filters = params["filter"]
        assert filters["chat_id"] == {"_eq": "chat"}
        field = next(field for field in ("client_message_id", "id") if field in filters)
        return [
            record.copy()
            for record in self.rows
            if record["chat_id"] == "chat" and record[field] == filters[field]["_eq"]
        ][:1]


@pytest.fixture(autouse=True)
def internal_token(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "disposable-internal-test")


def records(window):
    return [json.loads(value) for value in window["messages"]]


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded,storage.export.persisted-bounded-complete
@pytest.mark.asyncio
@pytest.mark.parametrize("team", [False, True])
async def test_equal_timestamp_cursor_paging_has_no_gaps_duplicates_or_foreign_chat_rows(
    team,
):
    rows = [row(number, client=number % 7 != 0) for number in range(1, 124)]
    rows[6]["client_message_id"] = ""
    rows += [row(2000, chat="foreign")]
    expected = sorted(
        rows[:-1],
        key=lambda record: (
            record["created_at"],
            record["client_message_id"] or record["id"],
        ),
    )
    service = SqlDirectus(rows, team=team)
    methods = ChatMethods(service)
    seen = []
    cursor = {"created_at": -2147483648, "message_id": ""}
    while True:
        page = await methods.get_message_window_for_chat(
            "chat",
            direction="after",
            limit=20,
            after_timestamp=cursor["created_at"],
            after_message_id=cursor["message_id"],
        )
        seen.extend(records(page))
        assert len(page["messages"]) <= 20
        if not page["has_more_after"]:
            break
        assert (page["end_cursor"]["created_at"], page["end_cursor"]["message_id"]) > (
            cursor["created_at"],
            cursor["message_id"],
        )
        cursor = page["end_cursor"]
    assert [record["id"] for record in seen] == [record["id"] for record in expected]
    assert len({record["id"] for record in seen}) == 123
    latest = await methods.get_message_window_for_chat("chat", limit=20)
    backwards = records(latest)
    while latest["has_more_before"]:
        cursor = latest["start_cursor"]
        latest = await methods.get_message_window_for_chat(
            "chat",
            direction="before",
            limit=20,
            before_timestamp=cursor["created_at"],
            before_message_id=cursor["message_id"],
        )
        backwards = records(latest) + backwards
    assert [record["id"] for record in backwards] == [
        record["id"] for record in expected
    ]
    assert all(request["data"]["limit"] == 21 for request in service.requests)


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.asyncio
async def test_timestamp_only_and_compression_lower_bound_are_preserved():
    methods = ChatMethods(
        SqlDirectus([row(1, timestamp=9), row(2, timestamp=10), row(3, timestamp=11)])
    )
    before = await methods.get_message_window_for_chat(
        "chat", direction="before", before_timestamp=10, lower_bound_timestamp=9
    )
    assert [record["id"] for record in records(before)] == [str(UUID(int=2))]
    after = await methods.get_message_window_for_chat(
        "chat", direction="after", after_timestamp=10
    )
    assert [record["id"] for record in records(after)] == [str(UUID(int=3))]
    latest = await methods.get_message_window_for_chat("chat", lower_bound_timestamp=10)
    assert [record["id"] for record in records(latest)] == [str(UUID(int=3))]


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.asyncio
async def test_around_window_preserves_anchor_and_sentinel_flags():
    service = SqlDirectus([row(number) for number in range(1, 10)])
    window = await ChatMethods(service).get_message_window_for_chat(
        "chat", direction="around", anchor_message_id="m-0005", limit=5
    )
    assert [record["message_id"] for record in records(window)] == [
        f"m-{number:04d}" for number in range(3, 8)
    ]
    assert (
        window["anchor_found"]
        and window["has_more_before"]
        and window["has_more_after"]
    )
    assert [request["data"]["limit"] for request in service.requests] == [3, 3]


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.parametrize(
    "change",
    [
        {"limit": 0},
        {"limit": 102},
        {"limit": 1.5},
        {"direction": "injected"},
        {"cursor_timestamp": "10"},
        {"cursor_message_id": "x" * 257},
        {"fields": "*"},
        {"lower_bound_timestamp": False},
    ],
)
# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
def test_internal_query_rejects_unbounded_or_arbitrary_requests(change):
    result = compiled(
        {
            "operation": "hot_message_window",
            "data": {
                "chat_id": "chat",
                "direction": "after",
                "limit": 21,
                "cursor_timestamp": 10,
                **change,
            },
        }
    )
    assert result == {"error": "invalid_hot_message_window", "status": 400}


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.parametrize(
    "chat",
    [
        {"id": "chat"},
        {"id": "chat", "hashed_user_id": "owner", "storage_state": "deleting"},
    ],
)
def test_internal_read_retains_chat_owner_and_deletion_guard(chat):
    result = compiled(
        {
            "operation": "hot_message_window",
            "data": {"chat_id": "chat", "direction": "latest", "limit": 21},
        },
        [chat],
    )
    assert result["error"] in {"archive_owner_missing", "chat_unavailable"}


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        {"messages": "bad"},
        {"messages": [row(1, chat="foreign")]},
        {"messages": [row(1)] * 22},
    ],
)
# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
async def test_failed_or_invalid_query_never_becomes_empty_history(result):
    async def request(*args, **kwargs):
        return SimpleNamespace(status_code=200, json=lambda: {"data": result})

    methods = ChatMethods(
        SimpleNamespace(base_url="http://cms:8055", _make_api_request=request)
    )
    with pytest.raises(RuntimeError, match="Canonical message window unavailable"):
        await methods.get_message_window_for_chat("chat", limit=20)


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.asyncio
async def test_public_window_limit_keeps_exact_bounded_probe_count():
    service = SqlDirectus([row(number) for number in range(1, 125)])
    window = await ChatMethods(service).get_message_window_for_chat("chat", limit=10000)
    assert len(window["messages"]) == 100 and window["has_more_before"] is True
    assert service.requests[0]["data"]["limit"] == 101


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.asyncio
async def test_missing_internal_token_fails_before_read(monkeypatch):
    monkeypatch.delenv("INTERNAL_API_SHARED_TOKEN")
    service = SqlDirectus([])
    with pytest.raises(RuntimeError, match="INTERNAL_API_SHARED_TOKEN_REQUIRED"):
        await ChatMethods(service).get_message_window_for_chat("chat")
    assert service.requests == []


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
def test_sql_cursor_values_are_bound_not_interpolated():
    cursor = "x'); SELECT pg_sleep(30); --"
    result = compiled(
        {
            "operation": "hot_message_window",
            "data": {
                "chat_id": "chat",
                "direction": "before",
                "limit": 21,
                "cursor_timestamp": 10,
                "cursor_message_id": cursor,
            },
        }
    )
    assert cursor not in result["query"]["sql"]
    assert cursor in result["query"]["bindings"]


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
def test_fixed_ciphertext_projection_matches_existing_window_fields():
    result = compiled(
        {
            "operation": "hot_message_window",
            "data": {"chat_id": "chat", "direction": "latest", "limit": 21},
        }
    )
    projection = (
        result["query"]["sql"].split(" FROM messages", 1)[0].removeprefix("SELECT ")
    )
    assert projection.split(", ") == MESSAGE_ALL_FIELDS.split(",")
