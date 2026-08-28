from pathlib import Path

from scripts.opencode_credential_migration import migrate


def test_migration_moves_values_without_returning_them(tmp_path: Path) -> None:
    project = tmp_path / "project.jsonc"
    global_config = tmp_path / "global.json"
    secrets = tmp_path / "secrets.env"
    project.write_text(
        '{\n  // retained\n  "environment": {"BRAVE_API_KEY": "secret-brave", "PENPOT_ACCESS_TOKEN": "secret-penpot"}\n}\n',
        encoding="utf-8",
    )
    global_config.write_text('{"headers":{"CONTEXT7_API_KEY":"secret-context"}}\n', encoding="utf-8")
    secrets.write_text("LINEAR_API_KEY=retained\n", encoding="utf-8")

    result = migrate([project, global_config], secrets)

    assert "secret-" not in str(result)
    assert "// retained" in project.read_text(encoding="utf-8")
    assert '"{env:BRAVE_API_KEY}"' in project.read_text(encoding="utf-8")
    assert '"{env:CONTEXT7_API_KEY}"' in global_config.read_text(encoding="utf-8")
    secret_text = secrets.read_text(encoding="utf-8")
    assert "LINEAR_API_KEY=retained" in secret_text
    assert "BRAVE_API_KEY=secret-brave" in secret_text
    assert (secrets.stat().st_mode & 0o777) == 0o600


def test_migration_is_idempotent(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    secrets = tmp_path / "secrets.env"
    config.write_text('{"GITHUB_PERSONAL_ACCESS_TOKEN":"token"}\n', encoding="utf-8")

    migrate([config], secrets)
    first = (config.read_bytes(), secrets.read_bytes())
    result = migrate([config], secrets)

    assert result["changed_configs"] == []
    assert (config.read_bytes(), secrets.read_bytes()) == first
