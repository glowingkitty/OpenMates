#!/usr/bin/env python3
"""Report, per web Worker unit, how many Rust files carry a specification header.

A conforming header is a module comment line in the first 40 lines:
  //! spec: specifications/<category>/<name>#<assertion-id>
The Rust files of each unit are the `rust_paths` globs in
docs/migration/rust/web-app-curated.yml (test files `*_tests.rs` are skipped).
Report only: the exit code is always 0 unless --strict is passed (not used by CI yet).

  python3 scripts/report_rust_spec_headers.py [--yaml] [--strict]

Architecture: docs/migration/rust/overview.yml
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CURATED = Path("docs/migration/rust/web-app-curated.yml")
HEADER = re.compile(r"^//! spec: specifications/(?:architecture|features|surfaces)/[\w./-]+#[\w.-]+\s*$")
HEADER_LINES = 40


def has_header(path: Path) -> bool:
    with path.open(encoding="utf-8", errors="replace") as handle:
        for _, line in zip(range(HEADER_LINES), handle):
            if HEADER.match(line):
                return True
    return False


def unit_files(globs: list[str]) -> list[Path]:
    found: set[Path] = set()
    for pattern in globs:
        found.update(p for p in ROOT.glob(pattern) if p.is_file() and not p.name.endswith("_tests.rs"))
    return sorted(found)


def report() -> list[dict]:
    units = yaml.safe_load((ROOT / CURATED).read_text(encoding="utf-8"))["units"]
    rows = []
    for namespace, unit in units.items():
        files = unit_files(unit.get("rust_paths", []))
        missing = [p.relative_to(ROOT).as_posix() for p in files if not has_header(p)]
        rows.append({"unit": namespace, "files": len(files), "with_header": len(files) - len(missing), "without_header": len(missing), "missing": missing})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yaml", action="store_true", help="print the full report (including file lists) as YAML")
    parser.add_argument("--strict", action="store_true", help="exit 1 when any file lacks a header")
    args = parser.parse_args()
    rows = report()
    if args.yaml:
        yaml.safe_dump(rows, sys.stdout, sort_keys=False)
    else:
        print(f"{'unit':<12}{'files':>6}{'with':>6}{'without':>9}")
        for row in rows:
            print(f"{row['unit']:<12}{row['files']:>6}{row['with_header']:>6}{row['without_header']:>9}")
        total = [sum(r[k] for r in rows) for k in ("files", "with_header", "without_header")]
        print(f"{'total':<12}{total[0]:>6}{total[1]:>6}{total[2]:>9}")
    return 1 if args.strict and any(r["without_header"] for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
