# contract-test-file: tooling
"""The nightly production backup scripts and systemd units stay consistent.

Covers deployment/prod_server/backup (TASK-5693): every script parses, every
unit points at a script that exists, failures alert through ExecStopPost, the
upload is encrypted before it leaves the host, and old copies are pruned only
after a verified upload.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

BACKUP = Path(__file__).resolve().parents[2] / "deployment/prod_server/backup"
SCRIPTS = sorted(BACKUP.glob("*.sh"))


def test_scripts_parse_and_are_executable() -> None:
    assert {p.name for p in SCRIPTS} >= {
        "openmates-prod-backup.sh",
        "openmates-prod-backup-lib.sh",
        "openmates-prod-backup-watchdog.sh",
        "openmates-prod-backup-restore-drill.sh",
    }
    for script in SCRIPTS:
        subprocess.run(["bash", "-n", str(script)], check=True)
        assert script.stat().st_mode & 0o111, f"{script.name} is not executable"


def test_units_reference_shipped_scripts_and_alert_on_failure() -> None:
    names = {p.name for p in SCRIPTS}
    for unit in (BACKUP / "systemd").glob("*.service"):
        text = unit.read_text(encoding="utf-8")
        for target in re.findall(r"openmates-backup/(\S+\.sh)", text):
            assert target in names, f"{unit.name} runs missing {target}"
    backup_unit = (BACKUP / "systemd/openmates-prod-backup.service").read_text(encoding="utf-8")
    assert "ExecStopPost=/home/superdev/openmates-backup/openmates-prod-backup.sh after-run" in backup_unit
    watchdog = (BACKUP / "openmates-prod-backup-watchdog.sh").read_text(encoding="utf-8")
    assert 'MAX_AGE_HOURS="${OPENMATES_BACKUP_MAX_AGE_HOURS:-26}"' in watchdog


def test_backup_encrypts_before_upload_and_prunes_after_verification() -> None:
    text = (BACKUP / "openmates-prod-backup.sh").read_text(encoding="utf-8")
    order = [text.index(marker) for marker in (
        'step "encrypt"', 'step "upload"', 'step "verify upload"', 'step "prune old copies"')]
    assert order == sorted(order)
    upload = text[text.index('step "upload"'):text.index('step "verify upload"')]
    assert ".tar.gpg" in text and "core.tar.gz\" \"s3://" not in upload
    assert "trap 'unpause_vault" in text


def test_no_secret_values_in_shipped_files() -> None:
    for path in BACKUP.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "BEGIN PGP PRIVATE KEY" not in text
            assert "discord.com/api/webhooks/" not in text
