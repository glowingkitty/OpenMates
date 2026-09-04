#!/usr/bin/env python3
"""Move known OpenCode MCP credentials into its mode-0600 environment file."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import tempfile


KEYS = (
    "BRAVE_API_KEY",
    "CONTEXT7_API_KEY",
    "FIRECRAWL_API_KEY",
    "GITHUB_PERSONAL_ACCESS_TOKEN",
    "PENPOT_ACCESS_TOKEN",
)


def _atomic_write(path: Path, data: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def migrate(configs: list[Path], secrets_path: Path) -> dict[str, object]:
    existing: dict[str, str] = {}
    if secrets_path.exists():
        for line in secrets_path.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            existing[key] = value

    migrated: set[str] = set()
    changed: list[str] = []
    for config in configs:
        source = config.read_text(encoding="utf-8")
        updated = source
        for key in KEYS:
            pattern = re.compile(rf'("{re.escape(key)}"\s*:\s*)("(?:\\.|[^"\\])*")')

            def replace(match: re.Match[str]) -> str:
                value = json.loads(match.group(2))
                if value == f"{{env:{key}}}":
                    return match.group(0)
                existing[key] = value
                migrated.add(key)
                return f'{match.group(1)}"{{env:{key}}}"'

            updated = pattern.sub(replace, updated)
        if updated == source:
            continue
        _atomic_write(config, updated)
        changed.append(str(config))

    lines = [f"{key}={existing[key]}" for key in sorted(existing)]
    _atomic_write(secrets_path, "\n".join(lines) + ("\n" if lines else ""))
    return {"changed_configs": changed, "migrated_keys": sorted(migrated), "secrets_mode": "0600"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", action="append", required=True, type=Path)
    parser.add_argument("--secrets", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(migrate(args.config, args.secrets), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
