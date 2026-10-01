#!/usr/bin/env python3
# contract-test-file: tooling
"""Bounded, read-only Gandi shop research; no product/provider implementation.

Run inside the dev api container to compare its actual direct egress with the
existing Webshare residential proxy. Public synthetic queries only. JSON on
stdout retains response fixtures; progress on stderr never prints credentials.

docker exec -i api python - --mode both < scripts/api_tests/test_gandi_search_probe.py
"""
from __future__ import annotations

import argparse
import asyncio
import collections
from datetime import datetime, timezone
import json
import logging
import os
import sys
import time
from typing import Any
from urllib.parse import quote

import httpx

BASE_URL = "https://shop.gandi.net/api/v5/suggest"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Referer": "https://shop.gandi.net/en/domain/suggest",
}
DEFAULTS = {"currency": "EUR", "country": "DE", "grid": "A"}
CASES: list[tuple[str, str, dict[str, Any]]] = [
    ("registered", "lookup", {"search": "example.com"}),
    ("available-1", "lookup", {"search": "openmates-probe-20261001-a7f2c9.com"}),
    ("available-2", "lookup", {"search": "openmates-probe-20261001-a7f2c9.com"}),
    ("available-3", "lookup", {"search": "openmates-probe-20261001-a7f2c9.com"}),
    ("usd-us", "lookup", {"search": "openmates-probe-20261001-a7f2c9.net", "currency": "USD", "country": "US"}),
    ("idn", "lookup", {"search": "b\u00fccher-probe-20261001.com", "lang": "de"}),
    ("ai-tld", "lookup", {"search": "openmates-probe-20261001-a7f2c9.ai"}),
    ("unsupported-tld", "lookup", {"search": "openmates-probe.invalid"}),
    ("invalid-domain", "lookup", {"search": "bad domain.com"}),
    ("keyword-1", "suggest", {"search": "cedarcomet"}),
    ("keyword-2", "suggest", {"search": "cedarcomet"}),
    ("multiword", "suggest", {"search": "cedar comet"}),
    ("exact-fqdn", "suggest", {"search": "example.com", "lock_sentence": "true"}),
    ("tld-filter", "suggest", {"search": "cedarcomet", "tlds": ["com", "net"]}),
    ("tld-net", "suggest", {"search": "cedarcomet", "tlds": "net"}),
    ("tld-comma", "suggest", {"search": "cedarcomet", "tlds": "com,net"}),
    ("multiword-exact", "suggest", {"search": "cedar comet", "lock_sentence": "true"}),
    ("premium", "lookup", {"search": "cedar.online"}),
]


async def proxy_url() -> str:
    """Use existing secrets without exposing their values or proxy URL."""
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    sm = SecretsManager()
    try:
        await sm.initialize()
        username = await sm.get_secret("kv/data/providers/webshare", "proxy_username")
        password = await sm.get_secret("kv/data/providers/webshare", "proxy_password")
        username = username or os.environ.get("SECRET__WEBSHARE__PROXY_USERNAME")
        password = password or os.environ.get("SECRET__WEBSHARE__PROXY_PASSWORD")
        if not username or not password or "IMPORTED_TO_VAULT" in (username, password):
            raise RuntimeError("Proxy credentials unavailable")
        return f"http://{quote(username, safe='')}-rotate:{quote(password, safe='')}@p.webshare.io:80/"
    finally:
        await sm.aclose()


def summary(record: dict[str, Any]) -> dict[str, Any]:
    """Separate transport/schema success from individual registry errors."""
    body = record.get("body")
    if record["endpoint"] == "lookup" and isinstance(body, dict):
        return {
            "fqdn": body.get("fqdn"), "availability": body.get("availability"),
            "premium": body.get("premium"),
            "currency": body.get("prices", {}).get("currency"),
            "products": len(body.get("prices", {}).get("products", [])),
            "schema_valid": isinstance(body.get("fqdn"), str) and isinstance(body.get("availability"), str),
        }
    events = record.get("events", [])
    counts = dict(collections.Counter(event["event"] for event in events))
    domains = [item for event in events if event["event"] == "suggestions" for item in event["data"]]
    statuses = [event["data"] for event in events if event["event"] in ("das", "das_failed")]
    return {
        "events": counts, "domains": [item.get("fqdn") for item in domains],
        "availability": statuses,
        "done": "done" in counts,
        "schema_valid": "suggestions" in counts and "done" in counts,
    }


async def probe(mode: str, name: str, endpoint: str, overrides: dict[str, Any], proxy: str | None) -> dict[str, Any]:
    params: dict[str, Any] = dict(DEFAULTS)
    headers = dict(HEADERS)
    if endpoint == "suggest":
        params.update({"lang": "en", "page": 1, "per_page": 5, "source": "shop", "lock_sentence": "false", "phases": "golive"})
        headers["Accept"] = "text/event-stream"
    else:
        headers["Accept"] = "application/json"
    params.update(overrides)
    record: dict[str, Any] = {"mode": mode, "case": name, "endpoint": endpoint, "params": params}
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(proxy=proxy, trust_env=False, follow_redirects=False, timeout=httpx.Timeout(15, connect=10)) as client:
            async with asyncio.timeout(25):
                async with client.stream("GET", f"{BASE_URL}/{endpoint}", params=params, headers=headers) as response:
                    record.update({
                        "http_status": response.status_code,
                        "content_type": response.headers.get("content-type"),
                        "response_headers": {key: value for key, value in response.headers.items() if key.lower() in {"retry-after", "cache-control", "access-control-allow-origin"} or key.lower().startswith("x-ratelimit")},
                        "sent_cookie": "cookie" in response.request.headers,
                        "sent_authorization": "authorization" in response.request.headers,
                    })
                    if endpoint == "lookup" or response.status_code != 200:
                        raw = (await response.aread()).decode("utf-8", errors="replace")
                        try:
                            record["body"] = json.loads(raw)
                        except json.JSONDecodeError:
                            record["body"] = raw[:2000]
                    else:
                        events: list[dict[str, Any]] = []
                        record["events"] = events
                        event_type = "message"
                        data: list[str] = []
                        async for line in response.aiter_lines():
                            if line.startswith("event:"):
                                event_type = line[6:].strip()
                            elif line.startswith("data:"):
                                data.append(line[5:].strip())
                            elif not line:
                                if data or event_type != "message":
                                    value = json.loads("\n".join(data)) if data else None
                                    events.append({"event": event_type, "data": value})
                                    if event_type == "done":
                                        break
                                event_type, data = "message", []
    except Exception as exc:
        # Exception messages can contain proxy URLs. Preserve only safe types.
        record["error_type"] = type(exc).__name__
    record["duration_seconds"] = round(time.monotonic() - start, 3)
    record["summary"] = summary(record)
    record["status"] = "pass" if record.get("http_status") == 200 and record["summary"].get("schema_valid") and not record.get("error_type") else "fail"
    print(f"{mode:6} {name:16} HTTP {record.get('http_status', '-')} {record['duration_seconds']:.3f}s {record['status']} {record.get('error_type', '')}", file=sys.stderr, flush=True)
    return record


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("direct", "proxy", "both"), default="both")
    parser.add_argument("--case", action="append", help="Named case; repeat to select several")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list:
        for name, endpoint, _ in CASES:
            print(f"{name}: {endpoint}")
        return
    cases = [case for case in CASES if not args.case or case[0] in args.case]
    if not cases:
        parser.error("Unknown case")
    # Suppress dependency logs, including Vault internal metadata.
    logging.disable(logging.CRITICAL)
    modes = ["direct", "proxy"] if args.mode == "both" else [args.mode]
    proxy = None
    report: dict[str, Any] = {"tested_at": datetime.now(timezone.utc).isoformat(), "runtime": "dev api container", "cases": []}
    if "proxy" in modes:
        try:
            proxy = await proxy_url()
        except Exception as exc:
            report["proxy_configuration_error"] = type(exc).__name__
            print("Proxy unavailable; direct cases will still run", file=sys.stderr, flush=True)
            modes = [mode for mode in modes if mode != "proxy"]
    for name, endpoint, params in cases:
        for mode in modes:
            report["cases"].append(await probe(mode, name, endpoint, params, proxy if mode == "proxy" else None))
            await asyncio.sleep(1)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
