"""Install a small forwarder in managed worktrees without replacing their files.

Old test dispatchers must not run preflights against shared dev before reaching
GitHub. The forwarder runs before imports and resolves the canonical coordinator.
Only executable dispatch is forwarded; imports used by unit tests are unchanged.
See docs/plans/isolated-github-tests/plan.yml.
"""

from __future__ import annotations

from pathlib import Path
import hashlib

START = "# BEGIN OPENMATES CANONICAL CI DISPATCH\n"
END = "# END OPENMATES CANONICAL CI DISPATCH\n"


def forwarder(entry: str) -> str:
    condition = (
        'len(_ci_sys.argv) > 1 and _ci_sys.argv[1] == "run"'
        if entry == "tests.py"
        else "True"
    )
    arguments = "_ci_sys.argv[2:]" if entry == "tests.py" else "_ci_sys.argv[1:]"
    return (
        START
        + f"""if __name__ == "__main__":
    import os as _ci_os
    import sys as _ci_sys
    import subprocess as _ci_subprocess
    from pathlib import Path as _CiPath
    if {condition}:
        _ci_checkout = _CiPath(__file__).resolve().parent.parent
        _ci_common = _ci_subprocess.check_output(["git", "rev-parse", "--git-common-dir"], cwd=_ci_checkout, text=True).strip()
        _ci_root = (_ci_checkout / _ci_common).resolve().parent
        _ci_dispatch = _ci_root / "scripts/ci_dispatch.py"
        if not _ci_dispatch.is_file():
            raise SystemExit("Canonical isolated CI dispatcher is unavailable; shared-dev fallback is forbidden")
        _ci_os.execv(_ci_sys.executable, [_ci_sys.executable, str(_ci_dispatch), "--worktree", str(_ci_checkout), *{arguments}])
"""
        + END
    )


def install(root: Path) -> list[dict]:
    result = []
    for entry in ("tests.py", "run_tests.py"):
        path = root / "scripts" / entry
        source = path.read_text()
        before = hashlib.sha256(source.encode()).hexdigest()
        if START in source:
            first, rest = source.split(START, 1)
            _, last = rest.split(END, 1)
            source = first.removesuffix("\n") + last
        marker = "from __future__ import annotations\n"
        if source.count(marker) != 1:
            raise RuntimeError(f"Cannot safely install CI forwarder into {path}")
        updated = source.replace(marker, marker + "\n" + forwarder(entry), 1)
        if updated != path.read_text():
            path.write_text(updated)
        result.append(
            {
                "path": str(path),
                "before": before,
                "after": hashlib.sha256(updated.encode()).hexdigest(),
            }
        )
    return result
