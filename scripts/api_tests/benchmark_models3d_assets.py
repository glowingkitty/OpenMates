#!/usr/bin/env python3
"""Benchmark licensed representative 3D assets against preview/storage budgets.

This deterministic harness intentionally fails when fixtures or production
optimizers are unavailable. It never downloads arbitrary models at runtime and
records transfer size, validation, duration, peak memory, and stream integrity.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "backend" / "tests" / "fixtures" / "models3d"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", default="30mb,60mb,100mb")
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def run_benchmark(args: argparse.Namespace) -> dict[str, object]:
    names = [name.strip() for name in args.fixtures.split(",") if name.strip()]
    missing = [name for name in names if not (FIXTURE_ROOT / f"{name}.glb").is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing licensed models3d benchmark fixtures: " + ", ".join(missing)
        )
    raise RuntimeError("models3d preview optimizer is not implemented")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = run_benchmark(args)
    except (FileNotFoundError, RuntimeError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}))
        return 1
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
