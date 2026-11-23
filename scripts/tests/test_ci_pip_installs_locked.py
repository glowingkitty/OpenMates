# contract-test-file: tooling
"""Every pip install in a workflow that can reach a protected environment is locked.

Such a workflow can hold provider keys (the `real-inference` environment), so it
never installs whatever PyPI serves today: it installs a hash-locked requirements
file (resolved from releases older than 7 days) or an exact `==` pin. Ranges such
as `cryptography>=41` are refused. Workflows without an environment follow
TASK-3864.
"""

import re
import shlex
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
PIP_INSTALL = re.compile(r"\bpip3?\s+install\b(?P<rest>[^\n|;&]*)")


def unlocked_installs(text: str) -> list[str]:
    """Return the pip install commands in `text` that are neither hash-locked nor exactly pinned."""
    refused = []
    for match in PIP_INSTALL.finditer(text):
        words = shlex.split(match.group("rest").replace("\\", " "), comments=True)
        if "--require-hashes" in words and "-r" in words:
            continue
        packages = [word for word in words if not word.startswith("-")]
        if packages and all(re.fullmatch(r"[A-Za-z0-9_.\[\]-]+==[A-Za-z0-9_.+!-]+", word) for word in packages):
            continue
        refused.append(match.group(0).strip())
    return refused


def keyed_workflows() -> list[Path]:
    """Return the workflows whose jobs use a protected GitHub environment."""
    return [path for path in sorted(WORKFLOWS.glob("*.yml")) if re.search(r"^\s+environment:", path.read_text(), re.M)]


def test_no_keyed_workflow_installs_an_unlocked_python_package() -> None:
    workflows = keyed_workflows()
    assert "isolated-tests.yml" in {path.name for path in workflows}
    refused = {path.name: found for path in workflows if (found := unlocked_installs(path.read_text()))}
    assert refused == {}


def test_the_check_refuses_ranges_and_accepts_locks() -> None:
    assert unlocked_installs('run: python3 -m pip install "cryptography>=41"')
    assert unlocked_installs("run: pip install requests")
    assert unlocked_installs("run: pip install -r requirements.txt")
    assert not unlocked_installs("run: python3 -m pip install pyyaml==6.0.2")
    assert not unlocked_installs("run: python3 -m pip install --require-hashes -r ../tooling/locked.txt")
