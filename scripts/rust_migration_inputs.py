"""Source paths that scripts/rust_migration_yaml.py reads to build docs/migration/rust/*.yml.

Dependency-free so sessions.py can decide when a deploy must regenerate the
generated Rust migration YAML without importing the generator. A drift test in
scripts/tests/test_sessions_lane_deploy_pipeline.py proves every path constant
the generator reads is covered here, so a new input cannot be forgotten.
"""

from __future__ import annotations

# Exact files the generator parses.
INPUT_FILES = (
    "config/sdk-capabilities.json",
    "config/cli-command-catalog.json",
    "specifications/generated/assertion-index.yml",
    "frontend/packages/ui/src/services/rustCore/host/sharedWorkerProtocol.ts",
)

# Directories (or filename prefixes) whose contents the generator scans.
INPUT_PREFIXES = (
    "docs/migration/rust/",  # curated lanes, web-app-curated, spec-links, performance-history
    "packages/openmates-rust/",  # shared vector files
    "frontend/packages/ui/src/services/",  # web-port-ledger.yml scope (includes rustCore/)
    "frontend/packages/ui/src/utils/",
    "frontend/packages/ui/src/stores/",
    "frontend/apps/web_app/src/lib/rustCore/",  # sharedWorkerUnits.ts and unit installers
    "frontend/apps/web_app/tests/web-rust-core-",  # web-rust-core-*.spec.ts
)


def is_rust_migration_input(relative_path: str) -> bool:
    """Return True when a changed path can alter the generated Rust migration YAML."""
    return relative_path in INPUT_FILES or relative_path.startswith(INPUT_PREFIXES)
