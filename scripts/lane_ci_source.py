"""Per-lane friction removal for ``sessions.py ci-source`` and ``sessions.py deploy``.

Lanes cannot commit and must not hand-run generators or ``track`` commands:

* ``fresh_generated_artifacts`` rebuilds the Specification artifacts and the
  generated Rust migration YAML inside the lane worktree for the duration of
  one ci-source publication, then restores the original bytes, so the
  candidate is never judged on stale generated files and the lane's own
  state is left exactly as it was.
* ``plan_only_tracking`` makes files named in ``deploy --only`` count as
  tracked by the deploying session while still reporting files that other
  sessions also track.

The generated-artifact sets live here so sessions.py and ci_source.py share
one definition. See .claude/rules/session-lifecycle.md.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

try:
    from scripts import rust_migration_inputs, worktree_fast_forward
except ModuleNotFoundError:
    import rust_migration_inputs
    import worktree_fast_forward

SPECIFICATION_GENERATED_ARTIFACTS = {
    "specifications/generated/assertion-index.yml",
    "specifications/generated/coverage.yml",
    "specifications/generated/registry.yml",
}
# Outputs of scripts/rust_migration_yaml.py (its GENERATED tuple).
RUST_MIGRATION_GENERATED_ARTIFACTS = {
    "docs/migration/rust/overview.yml",
    "docs/migration/rust/web-app.yml",
    "docs/migration/rust/shared-client.yml",
    "docs/migration/rust/cli.yml",
    "docs/migration/rust/sdk.yml",
}
REGENERABLE_GENERATED_ARTIFACTS = SPECIFICATION_GENERATED_ARTIFACTS | RUST_MIGRATION_GENERATED_ARTIFACTS


@contextmanager
def fresh_generated_artifacts(root: Path, paths: list[str], *, specification_governed: bool):
    """Regenerate stale generated files for one publication; restore them after.

    Yields the generator warnings (empty when everything rebuilt). Does nothing
    unless the candidate touches Specification-governed or Rust migration inputs.
    """
    root = Path(root)
    rebuild_specifications = specification_governed or any(p in SPECIFICATION_GENERATED_ARTIFACTS for p in paths)
    rebuild_rust = rebuild_specifications or any(
        rust_migration_inputs.is_rust_migration_input(p) or p in RUST_MIGRATION_GENERATED_ARTIFACTS for p in paths
    )
    if not rebuild_rust:
        yield []
        return
    snapshot: dict[str, bytes | None] = {}
    for relative in sorted(REGENERABLE_GENERATED_ARTIFACTS):
        target = root / relative
        snapshot[relative] = target.read_bytes() if target.is_file() else None
    reset = sorted(SPECIFICATION_GENERATED_ARTIFACTS) if rebuild_specifications else sorted(RUST_MIGRATION_GENERATED_ARTIFACTS)
    try:
        yield worktree_fast_forward.regenerate(
            root,
            reset,
            specification=set(SPECIFICATION_GENERATED_ARTIFACTS),
            rust_migration=set(RUST_MIGRATION_GENERATED_ARTIFACTS),
        )
    finally:
        for relative, data in snapshot.items():
            target = root / relative
            if data is None:
                target.unlink(missing_ok=True)
            elif not target.is_file() or target.read_bytes() != data:
                target.write_bytes(data)


def plan_only_tracking(
    selector: str,
    to_commit: list[str],
    modified: list[str],
    file_tracking: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Return (files to record as tracked, advisory lines) for ``--only``.

    Files explicitly named in ``--only`` are the deploying session's work, so
    they no longer need ``track`` plus ``--allow-untracked``. A file another
    session also tracks still yields an advisory (never a block).
    """
    if selector != "only":
        return [], []
    newly = sorted(path for path in to_commit if path not in set(modified))
    advisories = [
        f"  ~ {path} [also tracked by: {file_tracking[path]}; advisory]"
        for path in sorted(to_commit)
        if path in file_tracking
    ]
    return newly, advisories
