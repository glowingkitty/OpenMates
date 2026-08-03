#!/usr/bin/env python3
"""Audit historical client ciphertext for authenticated zero-key exposure.

The detector reads two count-verified, offset-paginated snapshots per category.
It emits only category counts and domain-separated identifier hashes, never
ciphertext, crypto metadata, identifiers, plaintext, or decrypted bytes.
Any match, snapshot difference, malformed record, or read failure exits nonzero.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from collections.abc import Mapping, Sequence
import ctypes
import ctypes.util
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import sys
from typing import Any, Protocol, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


ZERO_KEY = bytes(32)
AES_GCM_NONCE_BYTES = 12
AES_GCM_TAG_BYTES = 16
WRAPPED_KEY_BYTES = 32
AES_WRAPPED_KEY_CIPHERTEXT_BYTES = WRAPPED_KEY_BYTES + AES_GCM_TAG_BYTES
SECRETBOX_NONCE_BYTES = 24
SECRETBOX_TAG_BYTES = 16
DEFAULT_PAGE_SIZE = 250
DEFAULT_TIMEOUT_SECONDS = 30
FINDING_ID_DOMAIN = b"openmates.zero-key-audit.v1"
INTERNAL_ID_DOMAIN = b"openmates.zero-key-audit.internal-id.v1"
RECORD_FINGERPRINT_DOMAIN = b"openmates.zero-key-audit.record.v1"
SNAPSHOT_FINGERPRINT_DOMAIN = b"openmates.zero-key-audit.snapshot.v1"
EXIT_BLOCKED = 1
EXIT_USAGE = 2


class ReadOnlyRepository(Protocol):
    """Minimal repository surface intentionally incapable of writes."""

    def count(self, collection: str, filters: Mapping[str, str]) -> int: ...

    def page(
        self,
        collection: str,
        fields: tuple[str, ...],
        filters: Mapping[str, str],
        offset: int,
        limit: int,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class ScanDefinition:
    category: str
    collection: str
    fields: tuple[str, ...]
    filters: Mapping[str, str]
    ciphertext_field: str
    format: str
    expected_login_method: str | None = None
    login_method_prefix: str | None = None
    expected_key_type: str | None = None


ENCRYPTION_KEY_FIELDS = ("id", "login_method", "encrypted_key", "key_iv")
PREFIXED_FIELDS = ("id", "encrypted_chat_key")
SCANS = (
    ScanDefinition(
        "encryption_keys.password",
        "encryption_keys",
        ENCRYPTION_KEY_FIELDS,
        {"login_method[_eq]": "password"},
        "encrypted_key",
        "aes-separate-iv",
        expected_login_method="password",
    ),
    ScanDefinition(
        "encryption_keys.recovery_key",
        "encryption_keys",
        ENCRYPTION_KEY_FIELDS,
        {"login_method[_eq]": "recovery_key"},
        "encrypted_key",
        "aes-separate-iv",
        expected_login_method="recovery_key",
    ),
    ScanDefinition(
        "encryption_keys.api_key",
        "encryption_keys",
        ENCRYPTION_KEY_FIELDS,
        {"login_method[_starts_with]": "api_key_"},
        "encrypted_key",
        "aes-separate-iv",
        login_method_prefix="api_key_",
    ),
    ScanDefinition(
        "encryption_keys.passkey",
        "encryption_keys",
        ENCRYPTION_KEY_FIELDS,
        {
            "_or[0][login_method][_eq]": "passkey",
            "_or[1][login_method][_starts_with]": "passkey_",
        },
        "encrypted_key",
        "aes-separate-iv",
        login_method_prefix="passkey",
    ),
    # encrypted_email_with_master_key is intentionally out of scope: this audit
    # targets the deriveEmailEncryptionKey zero fallback used by NaCl
    # encrypted_email_address, while that field uses independently generated
    # master keys. Do not broaden this detector to unrelated master-key ciphertext.
    ScanDefinition(
        "users.encrypted_email_address",
        "users",
        ("id", "encrypted_email_address"),
        {"encrypted_email_address[_nnull]": "true"},
        "encrypted_email_address",
        "secretbox-prefixed-nonce",
    ),
    ScanDefinition(
        "chats.encrypted_chat_key",
        "chats",
        PREFIXED_FIELDS,
        {"encrypted_chat_key[_nnull]": "true"},
        "encrypted_chat_key",
        "aes-prefixed-nonce",
    ),
    ScanDefinition(
        "chat_key_wrappers.master",
        "chat_key_wrappers",
        ("id", "key_type", "encrypted_chat_key"),
        {"key_type[_eq]": "master", "encrypted_chat_key[_nnull]": "true"},
        "encrypted_chat_key",
        "aes-prefixed-nonce",
        expected_key_type="master",
    ),
)


class DirectusReadOnlyRepository:
    """Directus HTTP adapter with a narrowly scoped admin-auth fallback."""

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        *,
        admin_email: str | None = None,
        admin_password: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._admin_email = admin_email
        self._admin_password = admin_password

    def count(self, collection: str, filters: Mapping[str, str]) -> int:
        params = self._params(filters)
        if collection == "users":
            params.update({"limit": "0", "meta": "filter_count"})
            payload = self._request(collection, params)
            meta = payload.get("meta")
            raw_count = meta.get("filter_count") if isinstance(meta, dict) else None
        else:
            params["aggregate[count]"] = "*"
            payload = self._request(collection, params)
            data = payload.get("data")
            if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
                raise RuntimeError("count_response_malformed")
            raw_count = data[0].get("count")
            if isinstance(raw_count, dict):
                raw_count = raw_count.get("*")
        if isinstance(raw_count, bool):
            raise RuntimeError("count_response_malformed")
        try:
            count = int(raw_count)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("count_response_malformed") from exc
        if count < 0:
            raise RuntimeError("count_response_malformed")
        return count

    def page(
        self,
        collection: str,
        fields: tuple[str, ...],
        filters: Mapping[str, str],
        offset: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        params = self._params(filters)
        params.update(
            {
                "fields": ",".join(fields),
                "limit": str(limit),
                "offset": str(offset),
                "sort": "id",
            }
        )
        data = self._request(collection, params).get("data")
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise RuntimeError("page_response_malformed")
        return data

    @staticmethod
    def _params(filters: Mapping[str, str]) -> dict[str, str]:
        return {f"filter[{key.replace('[', '][', 1)}": value for key, value in filters.items()}

    def _request(self, collection: str, params: Mapping[str, str]) -> dict[str, Any]:
        collection_path = "users" if collection == "users" else f"items/{collection}"
        url = f"{self._base_url}/{collection_path}?{urlencode(params)}"
        try:
            payload = self._get(url)
        except HTTPError as exc:
            if exc.code != 401 or not self._admin_email or not self._admin_password:
                raise RuntimeError("directus_read_failed") from exc
            self._token = self._login()
            try:
                payload = self._get(url)
            except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as retry_exc:
                raise RuntimeError("directus_read_failed") from retry_exc
        except (URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("directus_read_failed") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("directus_response_malformed")
        return payload

    def _get(self, url: str) -> Any:
        request = Request(
            url,
            headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
            method="GET",
        )
        with urlopen(request, timeout=self._timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _login(self) -> str:
        request = Request(
            f"{self._base_url}/auth/login",
            data=json.dumps({"email": self._admin_email, "password": self._admin_password}).encode("utf-8"),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("directus_auth_failed") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        access_token = data.get("access_token") if isinstance(data, dict) else None
        if not isinstance(access_token, str) or not access_token:
            raise RuntimeError("directus_auth_failed")
        return access_token


def _strict_base64(value: Any) -> bytes:
    if not isinstance(value, str) or not value or len(value) % 4 != 0:
        raise ValueError("base64_malformed")
    try:
        encoded = value.encode("ascii")
        decoded = base64.b64decode(encoded, validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise ValueError("base64_malformed") from exc
    if base64.b64encode(decoded) != encoded:
        raise ValueError("base64_noncanonical")
    return decoded


def _authenticates_zero_aes_separate_iv(record: Mapping[str, Any]) -> bool:
    nonce = _strict_base64(record.get("key_iv"))
    ciphertext = _strict_base64(record.get("encrypted_key"))
    if len(nonce) != AES_GCM_NONCE_BYTES or len(ciphertext) != AES_WRAPPED_KEY_CIPHERTEXT_BYTES:
        raise ValueError("aes_format_malformed")
    try:
        AESGCM(ZERO_KEY).decrypt(nonce, ciphertext, None)
        return True
    except InvalidTag:
        return False


def _authenticates_zero_aes_prefixed(value: Any) -> bool:
    combined = _strict_base64(value)
    if len(combined) != AES_GCM_NONCE_BYTES + AES_WRAPPED_KEY_CIPHERTEXT_BYTES:
        raise ValueError("aes_format_malformed")
    nonce = combined[:AES_GCM_NONCE_BYTES]
    try:
        AESGCM(ZERO_KEY).decrypt(nonce, combined[AES_GCM_NONCE_BYTES:], None)
        return True
    except InvalidTag:
        return False


def _authenticates_zero_secretbox(value: Any) -> bool:
    combined = _strict_base64(value)
    if len(combined) <= SECRETBOX_NONCE_BYTES + SECRETBOX_TAG_BYTES:
        raise ValueError("secretbox_format_malformed")
    try:
        import nacl.exceptions
        import nacl.secret

        try:
            nacl.secret.SecretBox(ZERO_KEY).decrypt(combined)
            return True
        except nacl.exceptions.CryptoError:
            return False
    except ImportError:
        return _authenticates_zero_secretbox_libsodium(combined)


def _authenticates_zero_secretbox_libsodium(combined: bytes) -> bool:
    library_name = ctypes.util.find_library("sodium")
    if library_name is None:
        raise RuntimeError("secretbox_verifier_unavailable")
    try:
        sodium = ctypes.cdll.LoadLibrary(library_name)
        if sodium.sodium_init() < 0:
            raise RuntimeError("secretbox_verifier_unavailable")
        nonce = (ctypes.c_ubyte * SECRETBOX_NONCE_BYTES).from_buffer_copy(combined[:SECRETBOX_NONCE_BYTES])
        ciphertext_bytes = combined[SECRETBOX_NONCE_BYTES:]
        ciphertext = (ctypes.c_ubyte * len(ciphertext_bytes)).from_buffer_copy(ciphertext_bytes)
        plaintext = (ctypes.c_ubyte * (len(ciphertext_bytes) - SECRETBOX_TAG_BYTES))()
        key = (ctypes.c_ubyte * len(ZERO_KEY)).from_buffer_copy(ZERO_KEY)
        result = sodium.crypto_secretbox_open_easy(plaintext, ciphertext, len(ciphertext_bytes), nonce, key)
        sodium.sodium_memzero(plaintext, len(plaintext))
        return result == 0
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        raise RuntimeError("secretbox_verifier_unavailable") from exc


def _record_is_eligible(scan: ScanDefinition, record: Mapping[str, Any]) -> bool:
    login_method = record.get("login_method")
    if scan.expected_login_method is not None and login_method != scan.expected_login_method:
        return False
    if scan.login_method_prefix is not None and (
        not isinstance(login_method, str) or not login_method.startswith(scan.login_method_prefix)
    ):
        return False
    if scan.expected_key_type is not None and record.get("key_type") != scan.expected_key_type:
        return False
    return True


def _record_matches(scan: ScanDefinition, record: Mapping[str, Any]) -> bool:
    if scan.format == "aes-separate-iv":
        return _authenticates_zero_aes_separate_iv(record)
    if scan.format == "aes-prefixed-nonce":
        return _authenticates_zero_aes_prefixed(record.get(scan.ciphertext_field))
    if scan.format == "secretbox-prefixed-nonce":
        return _authenticates_zero_secretbox(record.get(scan.ciphertext_field))
    raise RuntimeError("unsupported_scan_format")


def _finding_id(category: str, record_id: str) -> str:
    digest = hashlib.sha256()
    digest.update(FINDING_ID_DOMAIN)
    digest.update(b"\0")
    digest.update(category.encode("utf-8"))
    digest.update(b"\0")
    digest.update(record_id.encode("utf-8"))
    return digest.hexdigest()


def _internal_id(category: str, record_id: str) -> bytes:
    digest = hashlib.sha256()
    digest.update(INTERNAL_ID_DOMAIN)
    digest.update(b"\0")
    digest.update(category.encode("utf-8"))
    digest.update(b"\0")
    digest.update(record_id.encode("utf-8"))
    return digest.digest()


def _record_fingerprint(scan: ScanDefinition, record_id: str, record: Mapping[str, Any]) -> bytes:
    digest = hashlib.sha256()
    digest.update(RECORD_FINGERPRINT_DOMAIN)
    digest.update(b"\0")
    digest.update(scan.category.encode("utf-8"))
    for value in (record_id, record.get(scan.ciphertext_field)):
        if not isinstance(value, str):
            raise ValueError("fingerprint_field_malformed")
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    if scan.format == "aes-separate-iv":
        key_iv = record.get("key_iv")
        if not isinstance(key_iv, str):
            raise ValueError("fingerprint_field_malformed")
        encoded_iv = key_iv.encode("utf-8")
        digest.update(len(encoded_iv).to_bytes(8, "big"))
        digest.update(encoded_iv)
    return digest.digest()


def _id_advances(previous: str | int, current: str | int) -> bool:
    if type(previous) is type(current):
        return current > previous
    return str(current) > str(previous)


def _mark_incomplete(
    category: str,
    code: str,
    incomplete_categories: set[str],
    errors: list[str],
) -> None:
    incomplete_categories.add(category)
    sanitized = f"{category}:{code}"
    if sanitized not in errors:
        errors.append(sanitized)


@dataclass(frozen=True)
class Snapshot:
    count: int
    scanned: int
    fingerprint: bytes
    matches: frozenset[str]
    complete: bool


def _read_snapshot(
    repository: ReadOnlyRepository,
    scan: ScanDefinition,
    page_size: int,
    incomplete_categories: set[str],
    errors: list[str],
) -> Snapshot:
    try:
        expected_count = repository.count(scan.collection, scan.filters)
        if isinstance(expected_count, bool) or not isinstance(expected_count, int) or expected_count < 0:
            raise ValueError("count_malformed")
    except Exception:
        _mark_incomplete(scan.category, "count_read_failed", incomplete_categories, errors)
        return Snapshot(0, 0, b"", frozenset(), False)

    snapshot_digest = hashlib.sha256()
    snapshot_digest.update(SNAPSHOT_FINGERPRINT_DOMAIN)
    snapshot_digest.update(b"\0")
    snapshot_digest.update(scan.category.encode("utf-8"))
    seen_id_hashes: set[bytes] = set()
    match_hashes: set[str] = set()
    previous_id: str | int | None = None
    scanned = 0
    offset = 0
    complete = True

    while offset < expected_count:
        try:
            page = repository.page(scan.collection, scan.fields, scan.filters, offset, page_size)
        except Exception:
            _mark_incomplete(scan.category, "page_read_failed", incomplete_categories, errors)
            complete = False
            break
        if not isinstance(page, list) or len(page) > page_size:
            _mark_incomplete(scan.category, "page_malformed", incomplete_categories, errors)
            complete = False
            break
        if not page:
            _mark_incomplete(scan.category, "page_short", incomplete_categories, errors)
            complete = False
            break

        for record in page:
            scanned += 1
            if not isinstance(record, dict):
                _mark_incomplete(scan.category, "record_malformed", incomplete_categories, errors)
                complete = False
                continue
            record_id = record.get("id")
            if not isinstance(record_id, (str, int)) or isinstance(record_id, bool) or not str(record_id):
                _mark_incomplete(scan.category, "record_malformed", incomplete_categories, errors)
                complete = False
                continue
            if previous_id is not None and not _id_advances(previous_id, record_id):
                _mark_incomplete(scan.category, "sort_order_malformed", incomplete_categories, errors)
                complete = False
            previous_id = record_id
            normalized_id = str(record_id)
            id_hash = _internal_id(scan.category, normalized_id)
            if id_hash in seen_id_hashes:
                _mark_incomplete(scan.category, "duplicate_record", incomplete_categories, errors)
                complete = False
                continue
            seen_id_hashes.add(id_hash)
            if not _record_is_eligible(scan, record):
                _mark_incomplete(scan.category, "eligibility_mismatch", incomplete_categories, errors)
                complete = False
                continue
            try:
                matched = _record_matches(scan, record)
                record_fingerprint = _record_fingerprint(scan, normalized_id, record)
            except ValueError:
                _mark_incomplete(scan.category, "crypto_record_malformed", incomplete_categories, errors)
                complete = False
                continue
            except Exception:
                _mark_incomplete(scan.category, "crypto_check_failed", incomplete_categories, errors)
                complete = False
                continue
            snapshot_digest.update(record_fingerprint)
            if matched:
                match_hashes.add(_finding_id(scan.category, normalized_id))
        offset += len(page)

    try:
        final_count = repository.count(scan.collection, scan.filters)
    except Exception:
        _mark_incomplete(scan.category, "final_count_read_failed", incomplete_categories, errors)
        complete = False
    else:
        if final_count != expected_count or scanned != expected_count:
            _mark_incomplete(scan.category, "count_mismatch", incomplete_categories, errors)
            complete = False

    return Snapshot(expected_count, scanned, snapshot_digest.digest(), frozenset(match_hashes), complete)


def audit_repository(
    repository: ReadOnlyRepository,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    audited_at: str | None = None,
) -> dict[str, Any]:
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    timestamp = audited_at or datetime.now(timezone.utc).isoformat()
    findings: list[dict[str, Any]] = []
    category_counts: dict[str, dict[str, int]] = {}
    incomplete_categories: set[str] = set()
    errors: list[str] = []

    for scan in SCANS:
        counts = {"eligible": 0, "scanned": 0, "matched": 0}
        category_counts[scan.category] = counts
        first = _read_snapshot(repository, scan, page_size, incomplete_categories, errors)
        second = _read_snapshot(repository, scan, page_size, incomplete_categories, errors)
        counts["eligible"] = first.count
        counts["scanned"] = first.scanned

        if first.complete and second.complete and (
            first.count != second.count
            or first.fingerprint != second.fingerprint
            or first.matches != second.matches
        ):
            _mark_incomplete(scan.category, "snapshot_mismatch", incomplete_categories, errors)

        if first.complete and second.complete and scan.category not in incomplete_categories:
            counts["matched"] = len(first.matches)
            findings.extend(
                {
                    "category": scan.category,
                    "finding_id": finding_id,
                    "timestamp": timestamp,
                    "match": True,
                }
                for finding_id in sorted(first.matches)
            )

    complete = not incomplete_categories
    matched_total = len(findings)
    status = "incomplete" if not complete else "blocked" if matched_total else "clean"
    return {
        "status": status,
        "complete": complete,
        "timestamp": timestamp,
        "matched": matched_total,
        "categories": category_counts,
        "incomplete_categories": sorted(incomplete_categories),
        "errors": errors,
        "findings": findings,
    }


def _repository_from_environment(environment: str) -> DirectusReadOnlyRepository:
    prefix = f"DIRECTUS_{environment.upper()}"
    base_url = os.getenv(f"{prefix}_URL") or os.getenv("DIRECTUS_URL") or os.getenv("CMS_URL")
    token = os.getenv(f"{prefix}_TOKEN") or os.getenv("DIRECTUS_TOKEN")
    if not base_url or not token:
        raise RuntimeError("directus_configuration_missing")
    return DirectusReadOnlyRepository(
        base_url,
        token,
        admin_email=os.getenv("DATABASE_ADMIN_EMAIL"),
        admin_password=os.getenv("DATABASE_ADMIN_PASSWORD"),
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only authenticated zero-key exposure audit", add_help=True)
    parser.add_argument("--env", choices=("dev", "prod"))
    parser.add_argument("--read-only", action="store_true")
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    repository: ReadOnlyRepository | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    audited_at: str | None = None,
) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or EXIT_USAGE)
    if args.env is None or not args.read_only:
        print("Both --env dev|prod and --read-only are required.", file=stderr)
        return EXIT_USAGE
    try:
        active_repository = repository or _repository_from_environment(args.env)
        report = audit_repository(active_repository, audited_at=audited_at)
    except Exception:
        report = {
            "status": "incomplete",
            "complete": False,
            "matched": 0,
            "categories": {},
            "incomplete_categories": ["repository"],
            "errors": ["repository:initialization_failed"],
            "findings": [],
        }
    report["environment"] = args.env
    print(json.dumps(report, sort_keys=True), file=stdout)
    return 0 if report["status"] == "clean" else EXIT_BLOCKED


if __name__ == "__main__":
    sys.exit(main())
