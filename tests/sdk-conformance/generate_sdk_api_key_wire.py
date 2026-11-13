"""Regenerate the synthetic API-key billing + memories wire fixture deterministically.

Gate capabilities sdk.billing (every billing route incl. raw invoice/credit-note/
usage-export downloads, no payment executed) and sdk.memories (legacy typed entry
list decryption with JSON/TOON/text plaintexts, published guidance, delete).
All keys, ids and plaintexts are synthetic; ciphertexts use fixed IVs so the
fixture bytes (and the conformance fixture hash) are reproducible:

    python3 tests/sdk-conformance/generate_sdk_api_key_wire.py
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "tests/sdk-conformance/fixtures/sdk-api-key-wire.json"
OPERATIONS = ROOT / "tests/sdk-conformance/fixtures/sdk-api-key-operations.json"
API_KEY = "sk-api-wireOwner.localSetupSuffix"
DEVICE = "synthetic-wire-device"
MASTER = bytes([0x61] * 32)
FOREIGN = bytes([0x62] * 32)
SALT = bytes([0x63] * 16)
WRAP_IV = bytes([0x64] * 12)
_counter = [0]


def _iv() -> bytes:
    _counter[0] += 1
    return _counter[0].to_bytes(12, "big")


def fingerprint(key: bytes) -> bytes:
    value = 0x811C9DC5
    for byte in key:
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return value.to_bytes(4, "big")


def seal(plaintext: str, key: bytes) -> str:
    iv = _iv()
    sealed = AESGCM(key).encrypt(iv, plaintext.encode(), None)
    return base64.b64encode(b"OM" + fingerprint(key) + iv + sealed).decode()


def key_wrapper() -> dict:
    secret = API_KEY.split(".", 1)[1].encode()
    wrapping = hashlib.pbkdf2_hmac("sha256", secret, SALT, 100_000, 32)
    return {
        "salt": base64.b64encode(SALT).decode(),
        "key_iv": base64.b64encode(WRAP_IV).decode(),
        "encrypted_key": base64.b64encode(AESGCM(wrapping).encrypt(WRAP_IV, MASTER, None)).decode(),
    }


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def route(method, path, *, body=None, auth="bearer", status=200, json_response=None, raw=None):
    response = {"json": json_response} if raw is None else raw
    return {"method": method, "path": path, "auth": auth, "body": body, "status": status, "response": response}


def raw_response(data: bytes, headers: dict) -> dict:
    return {"raw_b64": b64(data), "headers": headers}


def vector(identity, operation, routes, *, args=(), kwargs=None, query=None, confirmed=None,
           session=False, expected=None, expected_error=None):
    item = {"id": identity, "operation": operation, "args": list(args), "kwargs": kwargs or {},
            "session": session, "routes": routes, "expected": expected, "expected_error": expected_error}
    if query is not None:
        item["query"] = query
    if confirmed is not None:
        item["confirmed"] = confirmed
    return item


def billing_vectors() -> list[dict]:
    vectors = []
    # Every JSON billing route already vectored for sdk.api-key-operations.v1,
    # replayed here with a distinct reply so the decoded result is compared too.
    operations = json.loads(OPERATIONS.read_text())["capabilities"]["sdk.api-key-operations.v1"]["vectors"]
    for source in operations:
        if not source["operation"].startswith("billing."):
            continue
        reply = {"synthetic": source["id"], "ok": True}
        expect = source["expect"]
        vectors.append(vector(
            source["id"], source["operation"],
            [route(expect["method"], expect["path"], body=expect["body"], json_response=reply)],
            args=source["args"], kwargs=source["kwargs"], confirmed=source.get("confirmed"), expected=reply,
        ))

    def json_case(identity, operation, method, path, *, body=None, **options):
        reply = {"synthetic": identity, "ok": True}
        vectors.append(vector(identity, operation, [route(method, path, body=body, json_response=reply)],
                              expected=reply, **options))

    json_case("billing-usage-query", "billing.usage", "GET",
              "/v1/sdk/billing/usage?month=2026-10&scope=a+b%2Fc", query=[["month", "2026-10"], ["scope", "a b/c"]])
    json_case("billing-usage-no-query", "billing.usage", "GET", "/v1/sdk/billing/usage", query=[])
    json_case("billing-usage-overview-query", "billing.usage_overview", "GET",
              "/v1/sdk/billing/usage/overview?granularity=monthly&months=2",
              query=[["granularity", "monthly"], ["months", "2"]])
    json_case("billing-usage-overview-no-query", "billing.usage_overview", "GET", "/v1/sdk/billing/usage/overview", query=[])
    address = {"city": "Berlin", "country": "DE"}
    json_case("billing-gift-card-bank-transfer-order", "billing.create_gift_card_bank_transfer_order", "POST",
              "/v1/sdk/billing/gift-cards/bank-transfer-orders",
              body={"credits_amount": 120000, "currency": "eur", "email_encryption_key": "synthetic-email-key", "buyer_address": address},
              args=[120000], kwargs={"email_encryption_key": "synthetic-email-key", "buyer_address": address})
    json_case("billing-gift-card-bank-transfer-order-minimal", "billing.create_gift_card_bank_transfer_order", "POST",
              "/v1/sdk/billing/gift-cards/bank-transfer-orders",
              body={"credits_amount": 5000, "currency": "eur", "email_encryption_key": None}, args=[5000])
    vectors.append(vector("billing-refund-requires-confirmation", "billing.request_refund", [], args=["inv-1"],
                          confirmed=False, expected_error="invalid"))

    pdf = b"%PDF-1.7 synthetic\x00\xff\x10"

    def raw_case(identity, operation, path, data, headers, *, filename, content_type, **options):
        vectors.append(vector(identity, operation, [route("GET", path, raw=raw_response(data, headers))],
                              expected={"content_type": content_type, "filename": filename, "data_b64": b64(data)},
                              **options))

    raw_case("billing-download-invoice-keeps-last-path-component", "billing.download_invoice",
             "/v1/sdk/billing/invoices/inv%2F2%20a/download", pdf,
             {"Content-Type": "application/pdf", "Content-Disposition": 'attachment; filename="../../invoice-2.pdf"'},
             filename="invoice-2.pdf", content_type="application/pdf", args=["inv/2 a"])
    raw_case("billing-download-credit-note-prefers-utf8-name", "billing.download_credit_note",
             "/v1/sdk/billing/invoices/inv-1/credit-note/download", pdf,
             {"Content-Type": "application/pdf",
              "Content-Disposition": "attachment; filename=\"fallback.pdf\"; filename*=UTF-8''Gutschrift%20%E2%82%AC.pdf"},
             filename="Gutschrift \u20ac.pdf", content_type="application/pdf", args=["inv-1"])
    raw_case("billing-download-invoice-windows-path-name", "billing.download_invoice",
             "/v1/sdk/billing/invoices/inv-3/download", pdf,
             {"Content-Type": "application/pdf", "Content-Disposition": 'attachment; filename="C:\\exports\\inv-3.pdf"'},
             filename="inv-3.pdf", content_type="application/pdf", args=["inv-3"])
    raw_case("billing-download-invoice-refuses-dot-name", "billing.download_invoice",
             "/v1/sdk/billing/invoices/inv-4/download", pdf,
             {"Content-Type": "application/pdf", "Content-Disposition": 'attachment; filename=".."'},
             filename=None, content_type="application/pdf", args=["inv-4"])
    raw_case("billing-download-invoice-malformed-utf8-name", "billing.download_invoice",
             "/v1/sdk/billing/invoices/inv-5/download", pdf,
             {"Content-Type": "application/pdf", "Content-Disposition": "attachment; filename*=UTF-8''bad%zz.pdf; filename=\"ok.pdf\""},
             filename=None, content_type="application/pdf", args=["inv-5"])
    raw_case("billing-usage-export-months", "billing.usage_export", "/v1/sdk/billing/usage/export?months=3",
             b"month,credits\n2026-10,1200\n", {"Content-Type": "text/csv"},
             filename=None, content_type="text/csv", kwargs={"months": 3})
    raw_case("billing-usage-export-default-content-type", "billing.usage_export", "/v1/sdk/billing/usage/export",
             b"\x00\x01binary", {}, filename=None, content_type="application/octet-stream")
    vectors.append(vector("billing-download-invoice-forbidden", "billing.download_invoice",
                          [route("GET", "/v1/sdk/billing/invoices/inv-6/download", status=403,
                                 json_response={"detail": "synthetic forbidden"})],
                          args=["inv-6"], expected_error="forbidden"))
    vectors.append(vector("billing-download-credit-note-missing-non-json", "billing.download_credit_note",
                          [route("GET", "/v1/sdk/billing/invoices/inv-7/credit-note/download", status=404,
                                 raw=raw_response(b"not found", {"Content-Type": "text/plain"}))],
                          args=["inv-7"], expected_error="invalid"))
    return vectors


def memory_row(identity, plaintext=None, *, key=MASTER, encrypted=True):
    row = {"id": identity, "app_id": "books", "item_type": "favorite_books", "item_key": "synthetic-hash",
           "item_version": 2, "created_at": 1700000000, "updated_at": 1700000100}
    if encrypted:
        row["encrypted_item_json"] = seal(plaintext, key)
    return row


def memories_vectors() -> list[dict]:
    decoded = [
        (memory_row("m-json", json.dumps({"title": "Dune \u754c", "settings_group": "books"}, ensure_ascii=False)),
         {"title": "Dune \u754c", "settings_group": "books"}),
        (memory_row("m-toon", "title: Dune \u754c\nsettings_group: books\ntags[2]: sci-fi,classic\nrating: 4.5"),
         {"title": "Dune \u754c", "settings_group": "books", "tags": ["sci-fi", "classic"], "rating": 4.5}),
        (memory_row("m-toon-table", "items[2]{id,label}:\n  1,first\n  2,second"),
         {"items": [{"id": 1, "label": "first"}, {"id": 2, "label": "second"}]}),
        (memory_row("m-text", "not json at all"), "not json at all"),
    ]
    empty = [
        (memory_row("m-empty", ""), None),
        (memory_row("m-foreign-key", '{"secret":"other account"}', key=FOREIGN), None),
    ]

    def rows_with_data(pairs):
        return [{**row, "data": data} for row, data in pairs]

    plain = memory_row("m-plain", encrypted=False)
    return [
        vector("memories-list-decodes-json-toon-and-text", "memories.list",
               [route("GET", "/v1/sdk/memories?app_id=books&item_type=favorite_books",
                      json_response={"memories": [row for row, _ in decoded]})],
               query=[["app_id", "books"], ["item_type", "favorite_books"]], session=True,
               expected={"memories": rows_with_data(decoded)}),
        vector("memories-list-null-for-empty-and-foreign-plaintext", "memories.list",
               [route("GET", "/v1/sdk/memories", json_response={"memories": [row for row, _ in empty] + [plain]})],
               query=[], session=True, expected={"memories": rows_with_data(empty) + [plain]}),
        vector("memories-list-without-ciphertext-needs-no-key", "memories.list",
               [route("GET", "/v1/sdk/memories?app_id=books", json_response={"memories": [plain]})],
               query=[["app_id", "books"]], expected={"memories": [plain]}),
        vector("memories-published-all-apps", "memories.published",
               [route("GET", "/v1/apps/metadata?include_unavailable=true", auth="public",
                      json_response={"apps": {"books": {"memories": [{"id": "guide-b"}]}, "web": {"memories": [{"id": "guide-w"}]}, "zeta": {}}})],
               expected={"memories": [{"id": "guide-b"}, {"id": "guide-w"}]}),
        vector("memories-published-one-app", "memories.published",
               [route("GET", "/v1/apps/web%20app/metadata?include_unavailable=true", auth="public",
                      json_response={"id": "web app", "memories": [{"id": "guide-w"}]})],
               kwargs={"app_id": "web app"}, expected={"memories": [{"id": "guide-w"}]}),
        vector("memories-published-app-without-guidance", "memories.published",
               [route("GET", "/v1/apps/books/metadata?include_unavailable=true", auth="public", json_response={"id": "books"})],
               kwargs={"app_id": "books"}, expected={"memories": []}),
        vector("memories-delete-confirmed", "memories.delete",
               [route("DELETE", "/v1/sdk/memories/mem%201%2Fa", json_response={"success": True, "id": "mem 1/a"})],
               args=["mem 1/a"], confirmed=True, expected={"success": True, "id": "mem 1/a"}),
        vector("memories-delete-requires-confirmation", "memories.delete", [], args=["mem-1"], confirmed=False,
               expected_error="invalid"),
    ]


def build() -> dict:
    shared = {"api_key": API_KEY, "device_id": DEVICE,
              "session": {"key_wrapper": key_wrapper(), "user": {"id": "synthetic-wire-owner"}}}
    return {
        "schema_version": 1,
        "description": "Synthetic API-key billing and memories wire vectors: exact routes, bodies, credential boundary and decoded results through the public Rust, npm and Python clients against an independent loopback peer. No real backend, purchase, refund or deletion is involved.",
        "capabilities": {
            "sdk.billing": {**shared, "vectors": billing_vectors()},
            "sdk.memories": {**shared, "vectors": memories_vectors()},
        },
    }


def main() -> None:
    OUTPUT.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
