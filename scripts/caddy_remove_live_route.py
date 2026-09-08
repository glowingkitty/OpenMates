#!/usr/bin/env python3
"""Remove one reviewed, exclusive host route through Caddy's live config API.

The apply-caddy-config.sh narrow mode delegates here before broad setup logic.
A full-config ETag prevents overwriting concurrent changes. Caddy validates and
hot-reloads the replacement atomically; failures never trigger service restarts.
No Caddyfile, credential, package, environment or systemd file is modified.
Reference: https://caddyserver.com/docs/api#concurrent-config-changes
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

ADMIN_CONFIG_URL = "http://localhost:2019/config/"
TIMEOUT_SECONDS = 15


class RouteRemovalError(RuntimeError):
    """A safe, reportable route-removal failure without configuration contents."""


def config_bytes(config: dict) -> bytes:
    return json.dumps(config, sort_keys=True, separators=(",", ":")).encode()


def config_hash(config: dict) -> str:
    return hashlib.sha256(config_bytes(config)).hexdigest()


def remove_exclusive_host(config: dict, host: str) -> dict:
    """Delete exactly one route; reject shared matchers and ambiguous targets."""
    if not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)+", host):
        raise RouteRemovalError("An exact lowercase hostname is required")
    candidate = copy.deepcopy(config)
    matches = []

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "routes" and isinstance(child, list):
                    for index, route in enumerate(child):
                        if not isinstance(route, dict):
                            continue
                        matchers = route.get("match", [])
                        if any(isinstance(m, dict) and host in m.get("host", []) for m in matchers):
                            if matchers != [{"host": [host]}]:
                                raise RouteRemovalError("Target route has shared or additional matchers")
                            matches.append((child, index))
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(candidate)
    if len(matches) != 1:
        raise RouteRemovalError(f"Expected exactly one exclusive host route; found {len(matches)}")
    routes, index = matches[0]
    del routes[index]
    return candidate


def request_config(method="GET", *, data=None, etag=None):
    headers = {"Content-Type": "application/json"}
    if etag:
        headers["If-Match"] = etag
    request = urllib.request.Request(ADMIN_CONFIG_URL, data=data, headers=headers, method=method)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read()
            return (json.loads(body) if body else None), response.headers.get("Etag")
    except urllib.error.HTTPError as error:
        # Caddy errors may contain config values; never echo their response body.
        raise RouteRemovalError(f"Caddy config {method} rejected with HTTP {error.code}; no restart attempted") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise RouteRemovalError(f"Caddy config {method} failed; inspect live state before retrying") from None


def execute(host: str, *, apply: bool, expected_hash: str | None, backup: Path | None, transport=request_config):
    current, etag = transport()
    if not isinstance(current, dict) or not etag:
        raise RouteRemovalError("Caddy must return a config object and concurrency ETag")
    before_hash = config_hash(current)
    candidate = remove_exclusive_host(current, host)
    summary = {"host": host, "before_sha256": before_hash, "after_sha256": config_hash(candidate),
               "mode": "review", "persistence": "live config/autosave only; startup Caddyfile unchanged"}
    if not apply:
        return summary
    if expected_hash != before_hash:
        raise RouteRemovalError("Live config differs from the exact reviewed hash")
    if backup is None:
        raise RouteRemovalError("An exclusive private backup path is required")
    # Never overwrite earlier recovery evidence or follow a symlink.
    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(config_bytes(current))
        output.flush()
        os.fsync(output.fileno())
    # Caddy provisions/validates then atomically hot-reloads this config. If-Match
    # binds the entire current config, not merely the removed route's array index.
    transport("POST", data=config_bytes(candidate), etag=etag)
    actual, _ = transport()
    if actual != candidate:
        raise RouteRemovalError("Post-apply live config differs; stop and inspect, never restart or blindly roll back")
    return {**summary, "mode": "applied", "unrelated_config_unchanged": True, "backup": str(backup)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-config-sha256")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    try:
        result = execute(args.host, apply=args.apply, expected_hash=args.expected_config_sha256, backup=args.backup)
    except (RouteRemovalError, OSError) as error:
        parser.exit(1, f"Route removal stopped: {error}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
