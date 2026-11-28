"""Tests for scripts/agents_md.py using a temporary repo fixture."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agents_md  # noqa: E402


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "CLAUDE.md").write_text("# Rules\nbe good\n")
    rules = tmp_path / ".claude" / "rules"
    rules.mkdir(parents=True)
    (rules / "b.md").write_text('---\npaths:\n  - "**/*.rs"\n---\nbody-secret\n')
    (rules / "a.md").write_text("no frontmatter\n")
    skill = tmp_path / ".claude" / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo\ndescription: Does a demo\n---\nbody\n")
    return tmp_path


# contract-test: tooling
def test_deterministic_and_content(repo):
    a, b = agents_md.build(repo), agents_md.build(repo)
    assert a == b
    assert "be good" in a and "body-secret" not in a
    assert a.index(".claude/rules/a.md") < a.index(".claude/rules/b.md")
    assert "`**/*.rs`" in a and "`/demo` — Does a demo" in a


# contract-test: tooling
def test_check_passes_then_fails_on_edit(repo):
    assert agents_md.main(["generate", "--repo", str(repo)]) == 0
    assert agents_md.main(["check", "--repo", str(repo)]) == 0
    p = repo / "AGENTS.md"
    p.write_text(p.read_text() + "edit\n")
    assert agents_md.main(["check", "--repo", str(repo)]) == 1


# contract-test: tooling
def test_size_limit(repo, capsys):
    (repo / "CLAUDE.md").write_text("x" * (agents_md.MAX_BYTES + 10))
    agents_md.main(["generate", "--repo", str(repo)])
    assert agents_md.main(["check", "--repo", str(repo)]) == 1
    assert "exceeds" in capsys.readouterr().out
