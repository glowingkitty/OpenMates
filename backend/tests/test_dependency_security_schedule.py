"""Test deterministic dev dependency-security scheduling.

The installer owns only its bounded crontab block, preserves unrelated jobs,
removes legacy scanner entries, and never imports the repository secret file.
"""

from pathlib import Path

from scripts.dependency_security_schedule import default_project_root, render_crontab


# contract-test: infrastructure
def test_render_crontab_replaces_legacy_entries_and_is_idempotent() -> None:
    root = Path("/srv/openmates")
    existing = "\n".join(
        [
            "15 1 * * * /srv/cleanup.sh",
            "#DISABLED 30 * * * * bash -c '. /srv/openmates/.env && /srv/openmates/scripts/check-dependabot-daily.sh'",
            "35 * * * * bash -c '. /srv/openmates/.env && /srv/openmates/scripts/check-eu-vulns-daily.sh'",
            "",
        ]
    )

    rendered = render_crontab(existing, root)

    assert "15 1 * * * /srv/cleanup.sh" in rendered
    assert rendered.count("check-dependabot-daily.sh") == 1
    assert rendered.count("check-eu-vulns-daily.sh") == 1
    assert ".env" not in rendered
    assert render_crontab(rendered, root) == rendered


# contract-test: infrastructure
def test_default_project_root_escapes_managed_worktree(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.dependency_security_schedule.__file__",
        "/srv/OpenMates/.openmates-agent-worktrees/agent-test/scripts/dependency_security_schedule.py",
    )

    assert default_project_root() == Path("/srv/OpenMates")
