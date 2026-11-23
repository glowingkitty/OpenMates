"""The checkout is ready for Codex chats only with fresh AGENTS.md and the fixed adapter hooks (TASK-4476)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import codex_setup  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


# contract-test: tooling
def test_committed_codex_hooks_run_only_the_adapter():
    assert codex_setup.hooks_problems(REPO) == []
    assert codex_setup.problems(REPO, REPO, cli=False) == []


# contract-test: tooling
def test_extra_or_changed_hooks_are_refused(tmp_path):
    (tmp_path / ".codex").mkdir()
    hooks = json.loads((REPO / ".codex" / "hooks.json").read_text())
    hooks["hooks"]["PreToolUse"][0]["hooks"].append({"type": "command", "command": "true"})
    hooks["hooks"]["Notify"] = []
    (tmp_path / ".codex" / "hooks.json").write_text(json.dumps(hooks))
    found = codex_setup.hooks_problems(tmp_path)
    assert any("PreToolUse" in f for f in found) and any("unexpected" in f for f in found)


# contract-test: tooling
def test_host_config_must_switch_hooks_on_and_trust_the_checkout(tmp_path):
    assert codex_setup.config_problems(REPO, tmp_path)  # missing
    root = Path(codex_setup.subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                           cwd=REPO, capture_output=True, text=True).stdout.strip()).parent
    (tmp_path / "config.toml").write_text(f'[features]\nhooks = true\n\n[projects."{root}"]\ntrust_level = "trusted"\n')
    assert codex_setup.config_problems(REPO, tmp_path) == []
