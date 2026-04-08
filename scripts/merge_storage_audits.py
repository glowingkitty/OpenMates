#!/usr/bin/env python3
"""
scripts/merge_storage_audits.py

Aggregate per-test storage snapshots produced by the cookie-audit Playwright
fixture (frontend/apps/web_app/tests/helpers/cookie-audit.ts) into TWO
separate canonical files under docs/architecture/compliance/:

  1. cookies.yml          — COOKIES ONLY, with full attributes. This is the
                            banner-decision file read by the legal compliance
                            cronjob. Cookies are the only storage type that
                            directly drives the ePrivacy / TTDSG cookie
                            banner requirement.

  2. browser-storage.yml  — localStorage, sessionStorage, and IndexedDB KEYS
                            (names) only — no values are ever stored. This
                            is an inventory of what the app places on the
                            user's device for engineering/privacy awareness,
                            separate from the legal banner question.

How it works:
  1. Read every JSON file under test-results/storage-audits/.
  2. Read existing cookies.yml + browser-storage.yml (if present) to
     preserve human-maintained fields: `purpose`, `consent_exempt`,
     `exemption_basis`, `notes`.
  3. Deduplicate observations:
     - Cookies are keyed by (name, domain, path).
     - localStorage / sessionStorage are keyed by key name.
     - IndexedDB databases are keyed by name.
  4. Track first_observed / last_observed dates and up to 5 example specs.
  5. Rewrite both files with the merged result, preserving the file headers.
  6. Print a stderr summary of additions / removals.

Run from repo root after a Playwright full-suite run:
    python3 scripts/merge_storage_audits.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("merge_storage_audits.py requires PyYAML — install via `pip install pyyaml`", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "test-results" / "storage-audits"
COOKIES_YAML = ROOT / "docs" / "architecture" / "compliance" / "cookies.yml"
BROWSER_STORAGE_YAML = ROOT / "docs" / "architecture" / "compliance" / "browser-storage.yml"

HUMAN_FIELDS = ("purpose", "consent_exempt", "exemption_basis", "notes")
# Non-cookie entries are informational only — they don't need a consent_exempt
# flag because they're not the banner-decision input. Just purpose + notes.
HUMAN_FIELDS_NON_COOKIE = ("purpose", "notes")
MAX_EXAMPLE_SPECS = 5

COOKIES_HEADER = """# Cookie Inventory (runtime evidence, banner-decision source of truth)
#
# Empirical record of every cookie the OpenMates web app sets during the
# full E2E test suite. This is the ONLY file that gates the ePrivacy
# Art. 5(3) / TTDSG §25 cookie-banner decision — because cookies are the
# only storage type legally tied to the banner requirement in the specific
# way we rely on ("strictly necessary" exemption).
#
# For a broader inventory of localStorage / sessionStorage / IndexedDB keys
# (informational only, not part of the banner decision), see
# browser-storage.yml in the same directory.
#
# Sources of truth:
#   - All fields except the human-maintained ones below are AUTO-GENERATED
#     by scripts/merge_storage_audits.py after a full Playwright run. Do
#     not hand-edit them — they will be overwritten on the next run.
#   - HUMAN-MAINTAINED fields (preserved across regenerations): `purpose`,
#     `consent_exempt`, `exemption_basis`, `notes`. Fill these in once per
#     entry.
#
# Anonymization (see frontend/apps/web_app/tests/helpers/cookie-audit.ts):
#   - Sensitive-named cookies (token / refresh / secret / key / auth /
#     session / csrf / jwt / otp / password / stripe) -> example_value:
#     "<redacted>" (length only).
#   - All other cookies -> first 4 chars + ellipsis + length.
#
# Compliance gate:
#   Every entry MUST have `consent_exempt: true` with an `exemption_basis`
#   that maps to "strictly necessary for the service explicitly requested
#   by the user" under ePrivacy Art. 5(3) and TTDSG §25 (German DDG).
#   Anything that does not meet this bar means a cookie banner is legally
#   required.
#
# Read by: scripts/_legal_compliance_helper.py (Mon + Thu cron)
# Updated by: scripts/run_tests.py after `--suite playwright` runs
# Related: docs/architecture/compliance/acknowledgments.yml (cookies entry)
#          docs/architecture/compliance/browser-storage.yml (non-cookie inventory)

"""

BROWSER_STORAGE_HEADER = """# Browser Storage Inventory (informational — NOT a banner-decision file)
#
# Runtime inventory of every localStorage key, sessionStorage key, and
# IndexedDB database name the OpenMates web app uses during the full E2E
# test suite. Key NAMES only — values are intentionally never captured or
# stored anywhere in this repository.
#
# Why this file exists:
#   For engineering + privacy awareness. It answers "what does the app
#   actually put on the user's device?" It is NOT used to decide whether
#   a cookie banner is required — that decision lives entirely in
#   cookies.yml in the same directory.
#
# Sources of truth:
#   - `seen_in_specs`, `first_observed`, `last_observed` are AUTO-GENERATED.
#   - `purpose` and `notes` are HUMAN-MAINTAINED and preserved across runs.
#
# Read by: scripts/_legal_compliance_helper.py (Mon + Thu cron, informational only)
# Updated by: scripts/run_tests.py after `--suite playwright` runs
# Related: docs/architecture/compliance/cookies.yml (banner-decision file)

"""


def _today() -> str:
    return date.today().isoformat()


def _load_existing(path: Path, sections: tuple[str, ...]) -> dict[str, list[dict]]:
    empty: dict[str, list[dict]] = {s: [] for s in sections}
    if not path.is_file():
        return empty
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        print(f"warning: existing {path.name} is invalid YAML ({e}); regenerating", file=sys.stderr)
        return empty
    for key in empty:
        if not isinstance(data.get(key), list):
            data[key] = []
    # Drop sections not in our schema
    return {k: data.get(k, []) for k in sections}


def _index_existing(items: list[dict], key_fn) -> dict[Any, dict]:
    out: dict[Any, dict] = {}
    for item in items:
        try:
            out[key_fn(item)] = item
        except (KeyError, TypeError):
            continue
    return out


def _preserve_human_fields(existing: dict | None, fresh: dict, fields: tuple[str, ...]) -> dict:
    if not existing:
        for f in fields:
            fresh.setdefault(f, None)
        return fresh
    for f in fields:
        if f in existing and existing[f] is not None:
            fresh[f] = existing[f]
        else:
            fresh.setdefault(f, None)
    return fresh


def _merge_observation(fresh: dict, existing_idx: dict, key: Any, spec: str, today: str) -> None:
    prior = existing_idx.get(key)
    fresh["first_observed"] = (prior or {}).get("first_observed", today) if prior else today
    fresh["last_observed"] = today
    seen = list((prior or {}).get("seen_in_specs", []))
    if spec and spec not in seen:
        seen.append(spec)
    fresh["seen_in_specs"] = seen[:MAX_EXAMPLE_SPECS]


def _collect_snapshots() -> list[dict]:
    if not SNAPSHOT_DIR.is_dir():
        return []
    out = []
    for fp in sorted(SNAPSHOT_DIR.glob("*.json")):
        try:
            out.append(json.loads(fp.read_text()))
        except json.JSONDecodeError as e:
            print(f"warning: skipping invalid snapshot {fp.name}: {e}", file=sys.stderr)
    return out


def merge() -> tuple[dict[str, Any], dict[str, Any]]:
    snapshots = _collect_snapshots()
    existing_cookies = _load_existing(COOKIES_YAML, ("cookies",))
    existing_storage = _load_existing(
        BROWSER_STORAGE_YAML,
        ("local_storage", "session_storage", "indexed_db"),
    )
    today = _today()

    cookie_idx = _index_existing(
        existing_cookies["cookies"],
        lambda c: (c["name"], c.get("domain", ""), c.get("path", "/")),
    )
    ls_idx = _index_existing(existing_storage["local_storage"], lambda c: c["key"])
    ss_idx = _index_existing(existing_storage["session_storage"], lambda c: c["key"])
    idb_idx = _index_existing(existing_storage["indexed_db"], lambda c: c["name"])

    cookies: dict[Any, dict] = {}
    locals_: dict[str, dict] = {}
    sessions_: dict[str, dict] = {}
    idbs: dict[str, dict] = {}

    for snap in snapshots:
        spec = snap.get("spec") or "unknown"
        for c in snap.get("cookies") or []:
            key = (c["name"], c.get("domain", ""), c.get("path", "/"))
            entry = cookies.get(key) or {
                "name": c["name"],
                "domain": c.get("domain", ""),
                "path": c.get("path", "/"),
                "http_only": c.get("http_only", False),
                "secure": c.get("secure", False),
                "same_site": c.get("same_site", "Lax"),
                "example_value": c.get("example_value", ""),
                "value_length": c.get("value_length", 0),
            }
            _merge_observation(entry, cookie_idx, key, spec, today)
            _preserve_human_fields(cookie_idx.get(key), entry, HUMAN_FIELDS)
            cookies[key] = entry

        for key_name in snap.get("local_storage_keys") or []:
            entry = locals_.get(key_name) or {"key": key_name}
            _merge_observation(entry, ls_idx, key_name, spec, today)
            _preserve_human_fields(ls_idx.get(key_name), entry, HUMAN_FIELDS_NON_COOKIE)
            locals_[key_name] = entry

        for key_name in snap.get("session_storage_keys") or []:
            entry = sessions_.get(key_name) or {"key": key_name}
            _merge_observation(entry, ss_idx, key_name, spec, today)
            _preserve_human_fields(ss_idx.get(key_name), entry, HUMAN_FIELDS_NON_COOKIE)
            sessions_[key_name] = entry

        for db in snap.get("indexed_db") or []:
            entry = idbs.get(db) or {"name": db}
            _merge_observation(entry, idb_idx, db, spec, today)
            _preserve_human_fields(idb_idx.get(db), entry, HUMAN_FIELDS_NON_COOKIE)
            idbs[db] = entry

    cookies_yaml = {
        "cookies": sorted(cookies.values(), key=lambda c: (c["name"], c["domain"])),
    }
    storage_yaml = {
        "local_storage": sorted(locals_.values(), key=lambda c: c["key"]),
        "session_storage": sorted(sessions_.values(), key=lambda c: c["key"]),
        "indexed_db": sorted(idbs.values(), key=lambda c: c["name"]),
    }

    # Drift summary
    prior_keys = {
        "cookies": set(cookie_idx.keys()),
        "local_storage": set(ls_idx.keys()),
        "session_storage": set(ss_idx.keys()),
        "indexed_db": set(idb_idx.keys()),
    }
    new_keys = {
        "cookies": set(cookies.keys()),
        "local_storage": set(locals_.keys()),
        "session_storage": set(sessions_.keys()),
        "indexed_db": set(idbs.keys()),
    }
    print(f"merge_storage_audits: read {len(snapshots)} snapshot(s)", file=sys.stderr)
    for section in ("cookies", "local_storage", "session_storage", "indexed_db"):
        added = new_keys[section] - prior_keys[section]
        removed = prior_keys[section] - new_keys[section]
        total = len(new_keys[section])
        if added or removed:
            print(
                f"  {section}: {total} total (+{len(added)} new, -{len(removed)} gone)",
                file=sys.stderr,
            )
            for k in sorted(map(str, added)):
                print(f"    + {k}", file=sys.stderr)
            for k in sorted(map(str, removed)):
                print(f"    - {k}", file=sys.stderr)
        else:
            print(f"  {section}: {total} total (no change)", file=sys.stderr)

    return cookies_yaml, storage_yaml


def write(cookies_data: dict[str, Any], storage_data: dict[str, Any]) -> None:
    COOKIES_YAML.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(cookies_data, sort_keys=False, allow_unicode=True, width=100)
    COOKIES_YAML.write_text(COOKIES_HEADER + body)
    print(f"merge_storage_audits: wrote {COOKIES_YAML.relative_to(ROOT)}", file=sys.stderr)

    body = yaml.safe_dump(storage_data, sort_keys=False, allow_unicode=True, width=100)
    BROWSER_STORAGE_YAML.write_text(BROWSER_STORAGE_HEADER + body)
    print(f"merge_storage_audits: wrote {BROWSER_STORAGE_YAML.relative_to(ROOT)}", file=sys.stderr)


def main() -> int:
    cookies_data, storage_data = merge()
    if not cookies_data["cookies"] and not any(storage_data.values()):
        print("merge_storage_audits: no observations found — leaving files untouched", file=sys.stderr)
        return 0
    write(cookies_data, storage_data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
