#!/usr/bin/env python3
"""Copy canonical CLI package inputs; --check rejects drift without changing files."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRATE = Path("frontend/packages/openmates-tui-native")
TEMPLATES = Path("frontend/packages/openmates-cli/templates")
FILES = {
    "assets/cli-command-catalog.json": "config/cli-command-catalog.json",
    "assets/selfhost/core/docker-compose.no-webapp.yml": "backend/core/docker-compose.no-webapp.yml",
    "assets/licenses/legacy-cli-MIT.txt": "frontend/packages/openmates-cli/LICENSE",
    "LICENSE": "LICENSE",
    "tests/crypto_fixtures/chat_completion_recovery_vectors.json": "backend/tests/fixtures/chat_completion_recovery_vectors.json",
    "tests/crypto_fixtures/session-saved-chat-read.json": "tests/sdk-conformance/fixtures/session-saved-chat-read.json",
}
for name in (
    "core/docker-compose.selfhost.yml",
    "upload/docker-compose.yml",
    "preview/docker-compose.preview.yml",
    "core/monitoring/prometheus/prometheus.yml",
    "core/monitoring/prometheus/alert_rules.yml",
    "core/monitoring/alertmanager/alertmanager.yml",
    "caddy/core/Caddyfile",
    "caddy/upload/Caddyfile",
    "caddy/preview/Caddyfile",
):
    FILES["assets/selfhost/" + name] = str(TEMPLATES / name)


def synchronize(root: Path = ROOT, *, check: bool = False) -> dict:
    entries = []
    expected = {}
    for target, source in sorted(FILES.items()):
        raw = (root / source).read_bytes()
        expected[target] = raw
        entries.append(
            {
                "path": target,
                "source": source,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    manifest = {"schemaVersion": 1, "files": entries}
    expected["assets/manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    stale = []
    for name, raw in expected.items():
        target = root / CRATE / name
        if check:
            if (
                target.is_symlink()
                or not target.is_file()
                or target.read_bytes() != raw
            ):
                stale.append(name)
        else:
            if target.is_symlink():
                raise ValueError("Refusing symlink package input: " + name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    actual_assets = {
        str(path.relative_to(root / CRATE))
        for path in (root / CRATE / "assets").rglob("*")
        if path.is_file() or path.is_symlink()
    }
    extra = actual_assets - set(expected)
    if stale or extra:
        raise ValueError(
            f"CLI asset drift: stale={sorted(stale)}, unexpected={sorted(extra)}"
        )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        result = synchronize(check=args.check)
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(f"Rust CLI canonical inputs: {len(result['files'])} checked")


if __name__ == "__main__":
    main()
