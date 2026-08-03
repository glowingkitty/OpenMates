"""Test the read-only historical zero-key exposure audit.

The fixtures authenticate synthetic AES-GCM and NaCl records under a zero key.
They also prove strict parsing, repeatable snapshots, sanitized findings, and
nonzero CLI exits for matches or inconclusive scans. No real Directus service
or durable user data is used by this test module.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
import ctypes
import ctypes.util
from io import StringIO
import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pytest

from scripts import audit_zero_key_exposure as audit


ZERO_KEY = bytes(32)
NONZERO_KEY = bytes(range(32))
AUDITED_AT = "2026-08-03T15:00:00+00:00"


class FakeRepository:
    def __init__(
        self,
        records: Mapping[str, list[dict[str, Any]]],
        *,
        count_overrides: Mapping[str, list[int]] | None = None,
        read_failures: set[str] | None = None,
        page_overrides: Mapping[str, list[list[dict[str, Any]]]] | None = None,
    ) -> None:
        self.records = {collection: list(rows) for collection, rows in records.items()}
        self.count_overrides = {collection: list(counts) for collection, counts in (count_overrides or {}).items()}
        self.read_failures = read_failures or set()
        self.page_overrides = {collection: list(pages) for collection, pages in (page_overrides or {}).items()}
        self.read_calls: list[tuple[str, int, int]] = []
        self.write_calls = 0

    def count(self, collection: str, filters: Mapping[str, str]) -> int:
        overrides = self.count_overrides.get(collection)
        if overrides:
            return overrides.pop(0)
        return len(self._filtered(collection, filters))

    def page(
        self,
        collection: str,
        fields: tuple[str, ...],
        filters: Mapping[str, str],
        offset: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        del fields
        self.read_calls.append((collection, offset, limit))
        if collection in self.read_failures:
            raise RuntimeError("synthetic read failure containing ciphertext-marker")
        overrides = self.page_overrides.get(collection)
        if overrides:
            return overrides.pop(0)
        rows = sorted(self._filtered(collection, filters), key=lambda row: str(row.get("id", "")))
        return rows[offset : offset + limit]

    def _filtered(self, collection: str, filters: Mapping[str, str]) -> list[dict[str, Any]]:
        rows = self.records.get(collection, [])
        if any(key.startswith("_or[") for key in filters):
            return [
                row
                for row in rows
                if row.get("login_method") == "passkey"
                or str(row.get("login_method", "")).startswith("passkey_")
            ]
        for expression, expected in filters.items():
            field, operator = expression.split("[", 1)
            if operator == "_eq]":
                rows = [row for row in rows if row.get(field) == expected]
            elif operator == "_starts_with]":
                rows = [row for row in rows if str(row.get(field, "")).startswith(expected)]
            elif operator == "_nnull]":
                rows = [row for row in rows if row.get(field) is not None]
        return rows

    def update(self, *_args: Any, **_kwargs: Any) -> None:
        self.write_calls += 1
        raise AssertionError("audit attempted a write")

    def delete(self, *_args: Any, **_kwargs: Any) -> None:
        self.write_calls += 1
        raise AssertionError("audit attempted a write")


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


class FakeHttpResponse:
    def __init__(self, payload: Any) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _aes_separate(record_id: str, login_method: str, key: bytes) -> dict[str, str]:
    iv = bytes(range(12))
    return {
        "id": record_id,
        "login_method": login_method,
        "encrypted_key": _b64(AESGCM(key).encrypt(iv, bytes([41]) * 32, None)),
        "key_iv": _b64(iv),
    }


def _aes_prefixed(record_id: str, field: str, key: bytes, **extra: str) -> dict[str, str]:
    nonce = bytes(range(12, 24))
    return {
        "id": record_id,
        field: _b64(nonce + AESGCM(key).encrypt(nonce, bytes([73]) * 32, None)),
        **extra,
    }


def _secretbox(record_id: str, key: bytes) -> dict[str, str]:
    nonce = bytes(range(24))
    plaintext = b"private@example.invalid"
    library_name = ctypes.util.find_library("sodium")
    assert library_name is not None
    sodium = ctypes.cdll.LoadLibrary(library_name)
    assert sodium.sodium_init() >= 0
    ciphertext = ctypes.create_string_buffer(len(plaintext) + 16)
    assert sodium.crypto_secretbox_easy(ciphertext, plaintext, len(plaintext), nonce, key) == 0
    return {"id": record_id, "encrypted_email_address": _b64(nonce + ciphertext.raw)}


def _all_collections() -> dict[str, list[dict[str, Any]]]:
    return {
        "encryption_keys": [
            _aes_separate("password-row", "password", ZERO_KEY),
            _aes_separate("recovery-row", "recovery_key", ZERO_KEY),
            _aes_separate("api-row", "api_key_hash", ZERO_KEY),
            _aes_separate("passkey-row", "passkey_credential", ZERO_KEY),
            _aes_separate("safe-password-row", "password", NONZERO_KEY),
            _aes_separate("ineligible-row", "oauth_google", ZERO_KEY),
        ],
        "users": [_secretbox("email-row", ZERO_KEY), _secretbox("safe-email-row", NONZERO_KEY)],
        "chats": [
            _aes_prefixed("chat-row", "encrypted_chat_key", ZERO_KEY),
            _aes_prefixed("safe-chat-row", "encrypted_chat_key", NONZERO_KEY),
        ],
        "chat_key_wrappers": [
            _aes_prefixed("wrapper-row", "encrypted_chat_key", ZERO_KEY, key_type="master"),
            _aes_prefixed("safe-wrapper-row", "encrypted_chat_key", NONZERO_KEY, key_type="master"),
            _aes_prefixed("ineligible-wrapper-row", "encrypted_chat_key", ZERO_KEY, key_type="chat"),
        ],
    }


def test_detects_every_eligible_zero_key_format_without_flagging_nonzero_records() -> None:
    repository = FakeRepository(_all_collections())

    report = audit.audit_repository(repository, page_size=1, audited_at=AUDITED_AT)

    assert report["status"] == "blocked"
    assert report["complete"] is True
    assert report["matched"] == 7
    assert {finding["category"] for finding in report["findings"]} == {
        "encryption_keys.password",
        "encryption_keys.recovery_key",
        "encryption_keys.api_key",
        "encryption_keys.passkey",
        "users.encrypted_email_address",
        "chats.encrypted_chat_key",
        "chat_key_wrappers.master",
    }
    assert all(set(finding) == {"category", "finding_id", "timestamp", "match"} for finding in report["findings"])
    assert all(finding["match"] is True and finding["timestamp"] == AUDITED_AT for finding in report["findings"])
    assert len({finding["finding_id"] for finding in report["findings"]}) == 7
    assert all(len(finding["finding_id"]) == 64 for finding in report["findings"])
    assert repository.write_calls == 0
    assert any(offset > 0 for _, offset, _ in repository.read_calls)
    assert [offset for collection, offset, _ in repository.read_calls if collection == "users"] == [0, 1, 0, 1]


@pytest.mark.parametrize("change", ["record", "ciphertext"])
def test_compensating_same_count_snapshot_changes_make_the_scan_incomplete(change: str) -> None:
    first = _secretbox("a-email-row", NONZERO_KEY)
    unchanged = _secretbox("b-email-row", NONZERO_KEY)
    if change == "record":
        changed = _secretbox("c-email-row", NONZERO_KEY)
        second_snapshot = [unchanged, changed]
    else:
        changed = _secretbox("a-email-row", ZERO_KEY)
        second_snapshot = [changed, unchanged]
    records = _all_collections()
    records["users"] = [first, unchanged]
    repository = FakeRepository(
        records,
        page_overrides={"users": [[first, unchanged], second_snapshot]},
    )

    report = audit.audit_repository(repository, audited_at=AUDITED_AT)

    assert report["status"] == "incomplete"
    assert report["complete"] is False
    assert "users.encrypted_email_address:snapshot_mismatch" in report["errors"]
    assert not any(finding["category"] == "users.encrypted_email_address" for finding in report["findings"])
    assert [offset for collection, offset, _ in repository.read_calls if collection == "users"] == [0, 0]
    assert repository.write_calls == 0


def test_finding_ids_are_domain_separated_and_report_never_exposes_sensitive_values() -> None:
    shared_id = "same-private-record-id"
    records = _all_collections()
    records["chats"] = [_aes_prefixed(shared_id, "encrypted_chat_key", ZERO_KEY)]
    records["chat_key_wrappers"] = [
        _aes_prefixed(shared_id, "encrypted_chat_key", ZERO_KEY, key_type="master")
    ]
    records["encryption_keys"][0]["salt"] = "salt-marker"
    repository = FakeRepository(records)

    report = audit.audit_repository(repository, audited_at=AUDITED_AT)
    serialized = json.dumps(report, sort_keys=True)

    matching_ids = [
        finding["finding_id"]
        for finding in report["findings"]
        if finding["category"] in {"chats.encrypted_chat_key", "chat_key_wrappers.master"}
    ]
    assert len(set(matching_ids)) == 2
    for forbidden in (shared_id, "salt-marker", "private@example.invalid"):
        assert forbidden not in serialized
    assert repository.write_calls == 0


def test_malformed_base64_and_count_changes_make_the_scan_incomplete() -> None:
    records = _all_collections()
    records["users"] = [{"id": "malformed-email", "encrypted_email_address": "not base64!!"}]
    repository = FakeRepository(records, count_overrides={"chats": [2, 3]})

    report = audit.audit_repository(repository, page_size=1, audited_at=AUDITED_AT)

    assert report["status"] == "incomplete"
    assert report["complete"] is False
    assert set(report["incomplete_categories"]) == {
        "users.encrypted_email_address",
        "chats.encrypted_chat_key",
    }
    assert all("malformed-email" not in error for error in report["errors"])
    assert all("not base64" not in error for error in report["errors"])
    assert repository.write_calls == 0


def test_read_failure_is_sanitized_and_never_reported_as_clean() -> None:
    repository = FakeRepository(_all_collections(), read_failures={"chat_key_wrappers"})

    report = audit.audit_repository(repository, audited_at=AUDITED_AT)
    serialized = json.dumps(report)

    assert report["status"] == "incomplete"
    assert report["complete"] is False
    assert "chat_key_wrappers.master" in report["incomplete_categories"]
    assert "ciphertext-marker" not in serialized
    assert repository.write_calls == 0


def test_duplicate_ids_in_offset_pages_make_the_scan_incomplete() -> None:
    duplicate = _secretbox("duplicate-email-row", NONZERO_KEY)
    records = _all_collections()
    records["users"] = [duplicate, dict(duplicate)]
    repository = FakeRepository(records, page_overrides={"users": [[duplicate, dict(duplicate)]]})

    report = audit.audit_repository(repository, page_size=2, audited_at=AUDITED_AT)

    assert report["status"] == "incomplete"
    assert "users.encrypted_email_address:duplicate_record" in report["errors"]
    assert report["categories"]["users.encrypted_email_address"]["scanned"] == 2
    assert repository.write_calls == 0


def test_unsorted_ids_in_offset_page_make_the_scan_incomplete() -> None:
    first = _secretbox("b-email-row", NONZERO_KEY)
    second = _secretbox("a-email-row", NONZERO_KEY)
    records = _all_collections()
    records["users"] = [first, second]
    repository = FakeRepository(records, page_overrides={"users": [[first, second]]})

    report = audit.audit_repository(repository, page_size=2, audited_at=AUDITED_AT)

    assert report["status"] == "incomplete"
    assert "users.encrypted_email_address:sort_order_malformed" in report["errors"]
    assert repository.write_calls == 0


def test_strict_base64_rejects_whitespace_and_noncanonical_encoding() -> None:
    records = _all_collections()
    records["chats"] = [
        {"id": "whitespace", "encrypted_chat_key": records["chats"][0]["encrypted_chat_key"] + "\n"},
        {"id": "extra-padding", "encrypted_chat_key": records["chats"][0]["encrypted_chat_key"] + "="},
    ]
    repository = FakeRepository(records)

    report = audit.audit_repository(repository, audited_at=AUDITED_AT)

    assert report["status"] == "incomplete"
    assert "chats.encrypted_chat_key" in report["incomplete_categories"]
    assert not any(finding["category"] == "chats.encrypted_chat_key" for finding in report["findings"])


def test_cli_requires_explicit_environment_and_read_only_acknowledgement() -> None:
    stderr = StringIO()
    assert audit.main([], repository=FakeRepository(_all_collections()), stderr=stderr) != 0
    assert audit.main(["--env", "dev"], repository=FakeRepository(_all_collections()), stderr=StringIO()) != 0


def test_repository_uses_api_container_cms_url(monkeypatch: Any) -> None:
    monkeypatch.delenv("DIRECTUS_DEV_URL", raising=False)
    monkeypatch.delenv("DIRECTUS_URL", raising=False)
    monkeypatch.setenv("CMS_URL", "http://cms:8055")
    monkeypatch.setenv("DIRECTUS_TOKEN", "synthetic-token")
    monkeypatch.setenv("DATABASE_ADMIN_EMAIL", "admin@example.invalid")
    monkeypatch.setenv("DATABASE_ADMIN_PASSWORD", "synthetic-password")

    repository = audit._repository_from_environment("dev")

    assert repository._base_url == "http://cms:8055"
    assert repository._admin_email == "admin@example.invalid"
    assert repository._admin_password == "synthetic-password"


def test_directus_filters_use_nested_read_only_query_parameters() -> None:
    repository = audit.DirectusReadOnlyRepository("https://directus.invalid", "test-token")

    assert repository._params(
        {
            "login_method[_eq]": "password",
            "_or[0][login_method][_starts_with]": "passkey_",
        }
    ) == {
        "filter[login_method][_eq]": "password",
        "filter[_or][0][login_method][_starts_with]": "passkey_",
    }


def test_directus_users_count_uses_filter_count_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = []

    def fake_urlopen(request: Any, *, timeout: int) -> FakeHttpResponse:
        requests.append((request, timeout))
        return FakeHttpResponse({"data": [], "meta": {"filter_count": "3"}})

    monkeypatch.setattr(audit, "urlopen", fake_urlopen)
    repository = audit.DirectusReadOnlyRepository("https://directus.invalid", "test-token")

    assert repository.count("users", {"encrypted_email_address[_nnull]": "true"}) == 3
    request, timeout = requests[0]
    parsed = urlparse(request.full_url)
    query = parse_qs(parsed.query)
    assert request.get_method() == "GET"
    assert timeout == audit.DEFAULT_TIMEOUT_SECONDS
    assert parsed.path == "/users"
    assert query["meta"] == ["filter_count"]
    assert query["limit"] == ["0"]
    assert "aggregate[count]" not in query


def test_directus_item_count_uses_aggregate_response(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = []

    def fake_urlopen(request: Any, *, timeout: int) -> FakeHttpResponse:
        requests.append((request, timeout))
        return FakeHttpResponse({"data": [{"count": {"*": "4"}}]})

    monkeypatch.setattr(audit, "urlopen", fake_urlopen)
    repository = audit.DirectusReadOnlyRepository("https://directus.invalid", "test-token")

    assert repository.count("chats", {"encrypted_chat_key[_nnull]": "true"}) == 4
    request, _ = requests[0]
    parsed = urlparse(request.full_url)
    query = parse_qs(parsed.query)
    assert request.get_method() == "GET"
    assert parsed.path == "/items/chats"
    assert query["aggregate[count]"] == ["*"]
    assert "meta" not in query


def test_directus_401_logs_in_and_retries_the_same_get_once(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = []

    def fake_urlopen(request: Any, *, timeout: int) -> FakeHttpResponse:
        del timeout
        requests.append(request)
        if len(requests) == 1:
            raise HTTPError(request.full_url, 401, "unauthorized", {}, None)
        if request.get_method() == "POST":
            return FakeHttpResponse({"data": {"access_token": "refreshed-token"}})
        return FakeHttpResponse({"data": [{"count": {"*": "4"}}]})

    monkeypatch.setattr(audit, "urlopen", fake_urlopen)
    repository = audit.DirectusReadOnlyRepository(
        "https://directus.invalid",
        "expired-token",
        admin_email="admin@example.invalid",
        admin_password="synthetic-password",
    )

    assert repository.count("chats", {"encrypted_chat_key[_nnull]": "true"}) == 4
    assert [(request.get_method(), urlparse(request.full_url).path) for request in requests] == [
        ("GET", "/items/chats"),
        ("POST", "/auth/login"),
        ("GET", "/items/chats"),
    ]
    assert requests[0].full_url == requests[2].full_url
    assert requests[2].get_header("Authorization") == "Bearer refreshed-token"


@pytest.mark.parametrize(
    "auth_result",
    [
        FakeHttpResponse({"data": {}}),
        HTTPError("https://directus.invalid/auth/login", 403, "forbidden", {}, None),
    ],
)
def test_directus_auth_failure_makes_audit_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    auth_result: FakeHttpResponse | HTTPError,
) -> None:
    requests = []

    def fake_urlopen(request: Any, *, timeout: int) -> FakeHttpResponse:
        del timeout
        requests.append(request)
        if request.get_method() == "POST":
            if isinstance(auth_result, HTTPError):
                raise auth_result
            return auth_result
        raise HTTPError(request.full_url, 401, "unauthorized", {}, None)

    monkeypatch.setattr(audit, "urlopen", fake_urlopen)
    repository = audit.DirectusReadOnlyRepository(
        "https://directus.invalid",
        "expired-token",
        admin_email="admin@example.invalid",
        admin_password="synthetic-password",
    )

    report = audit.audit_repository(repository, audited_at=AUDITED_AT)

    assert report["status"] == "incomplete"
    assert report["complete"] is False
    assert report["incomplete_categories"] == sorted(scan.category for scan in audit.SCANS)
    assert {(request.get_method(), urlparse(request.full_url).path) for request in requests} <= {
        ("GET", "/users"),
        ("GET", "/items/encryption_keys"),
        ("GET", "/items/chats"),
        ("GET", "/items/chat_key_wrappers"),
        ("POST", "/auth/login"),
    }
    assert all(
        request.get_method() == "GET" or urlparse(request.full_url).path == "/auth/login"
        for request in requests
    )


@pytest.mark.parametrize(
    ("collection", "payload"),
    [
        ("users", {"data": [], "meta": {}}),
        ("users", {"data": [], "meta": {"filter_count": -1}}),
        ("chats", {"data": []}),
        ("chats", {"data": [{"count": True}]}),
    ],
)
def test_directus_rejects_malformed_counts(
    monkeypatch: pytest.MonkeyPatch,
    collection: str,
    payload: dict[str, Any],
) -> None:
    monkeypatch.setattr(audit, "urlopen", lambda *_args, **_kwargs: FakeHttpResponse(payload))
    repository = audit.DirectusReadOnlyRepository("https://directus.invalid", "test-token")

    with pytest.raises(RuntimeError, match="count_response_malformed"):
        repository.count(collection, {})


@pytest.mark.parametrize(
    ("collection", "expected_path"),
    [("users", "/users"), ("chats", "/items/chats")],
)
def test_directus_pages_use_get_only_offset_queries(
    monkeypatch: pytest.MonkeyPatch,
    collection: str,
    expected_path: str,
) -> None:
    requests = []
    rows = [{"id": "b"}, {"id": "c"}]

    def fake_urlopen(request: Any, *, timeout: int) -> FakeHttpResponse:
        requests.append((request, timeout))
        return FakeHttpResponse({"data": rows})

    monkeypatch.setattr(audit, "urlopen", fake_urlopen)
    repository = audit.DirectusReadOnlyRepository("https://directus.invalid", "test-token")

    assert repository.page(collection, ("id",), {}, 3, 2) == rows
    request, _ = requests[0]
    parsed = urlparse(request.full_url)
    query = parse_qs(parsed.query)
    assert request.get_method() == "GET"
    assert parsed.path == expected_path
    assert query["sort"] == ["id"]
    assert query["limit"] == ["2"]
    assert query["offset"] == ["3"]
    assert "filter[id][_gt]" not in query


def test_directus_rejects_malformed_page_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        audit,
        "urlopen",
        lambda *_args, **_kwargs: FakeHttpResponse({"data": {"id": "not-a-list"}}),
    )
    repository = audit.DirectusReadOnlyRepository("https://directus.invalid", "test-token")

    with pytest.raises(RuntimeError, match="page_response_malformed"):
        repository.page("chats", ("id",), {}, 0, 10)


def test_cli_exit_codes_block_matches_and_incomplete_scans_but_allow_clean_scan() -> None:
    matched_stdout = StringIO()
    matched = audit.main(
        ["--env", "dev", "--read-only"],
        repository=FakeRepository(_all_collections()),
        stdout=matched_stdout,
        stderr=StringIO(),
        audited_at=AUDITED_AT,
    )
    incomplete = audit.main(
        ["--env", "dev", "--read-only"],
        repository=FakeRepository(_all_collections(), read_failures={"users"}),
        stdout=StringIO(),
        stderr=StringIO(),
        audited_at=AUDITED_AT,
    )
    clean_records = _all_collections()
    clean_records["encryption_keys"] = [_aes_separate("safe", "password", NONZERO_KEY)]
    clean_records["users"] = [_secretbox("safe", NONZERO_KEY)]
    clean_records["chats"] = [_aes_prefixed("safe", "encrypted_chat_key", NONZERO_KEY)]
    clean_records["chat_key_wrappers"] = [
        _aes_prefixed("safe", "encrypted_chat_key", NONZERO_KEY, key_type="master")
    ]
    clean = audit.main(
        ["--env", "dev", "--read-only"],
        repository=FakeRepository(clean_records),
        stdout=StringIO(),
        stderr=StringIO(),
        audited_at=AUDITED_AT,
    )

    assert matched != 0
    assert incomplete != 0
    assert clean == 0
    assert "private@example.invalid" not in matched_stdout.getvalue()
