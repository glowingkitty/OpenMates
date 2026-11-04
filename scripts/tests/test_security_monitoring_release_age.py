"""Offline contracts for release-age policy: routine 7-day wait and security-fix selection.

All registry access is replaced by an in-memory fake; no network is used.
"""

# contract-test-file: infrastructure
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "security_monitoring"))
import release_age as age  # noqa: E402 - path insert must precede import
import release_age_artifacts as artifacts  # noqa: E402
import release_age_routine as routine  # noqa: E402

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


class FakeLookup:
    """In-memory registry facts keyed by (name, version)."""

    def __init__(self, published, *, malicious=False, meta=None, flags=(), previous="4.6.5"):
        self.published = published
        self.malicious = malicious
        self.meta = meta or {}
        self.flags = None if flags is None else list(flags)
        self.previous = previous

    def published_at(self, ecosystem, name, version):
        return self.published.get((name, version))

    def is_malicious(self, ecosystem, name, version):
        return self.malicious

    def previous_version(self, ecosystem, name, version):
        return self.previous

    def package_meta(self, ecosystem, name, version):
        return self.meta.get(version)

    def content_flags(self, ecosystem, name, previous, version):
        return self.flags


def clean_meta(**overrides):
    base = {"publisher": "maintainer", "trusted_publisher": True, "install_scripts": [], "dependencies": ["a"]}
    return {**base, **overrides}


def ago(**kwargs):
    return NOW - timedelta(**kwargs)


# Spec coverage: security-monitoring.release-age.routine
# contract-test: infrastructure
def test_routine_three_day_old_version_is_blocked() -> None:
    lookup = FakeLookup({("lib", "2.1.0"): ago(days=3)})
    violations, _ = routine.evaluate([("req.txt", ("PyPI", "lib", "2.1.0"))], now=NOW, lookup=lookup)
    # The 3-day-old version is below the 7-day routine rule and is reported.
    assert len(violations) == 1 and "below the 7-day routine rule" in violations[0]


# Spec coverage: security-monitoring.release-age.routine
# contract-test: infrastructure
def test_routine_new_transitive_crate_one_day_old_is_blocked_and_old_one_passes() -> None:
    old_lock = '[[package]]\nname = "serde"\nversion = "1.0.0"\nsource = "registry+https://github.com/rust-lang/crates.io-index"\n'
    new_lock = old_lock + '[[package]]\nname = "tiny-new"\nversion = "0.1.0"\nsource = "registry+https://github.com/rust-lang/crates.io-index"\n'
    entries = [("Cargo.lock", e) for e in routine.changed_entries("cargo", old_lock, new_lock)]
    lookup = FakeLookup({("tiny-new", "0.1.0"): ago(days=1)})
    violations, _ = routine.evaluate(entries, now=NOW, lookup=lookup)
    # Only the newly added transitive entry is checked, and it is blocked at 1 day old.
    assert [e[1][1] for e in entries] == ["tiny-new"] and len(violations) == 1
    lookup.published[("tiny-new", "0.1.0")] = ago(days=8)
    # Once older than 7 days the same entry passes.
    assert routine.evaluate(entries, now=NOW, lookup=lookup)[0] == []


# Spec coverage: security-monitoring.release-age.routine
# contract-test: infrastructure
def test_routine_image_change_detected_and_unobtainable_registry_fails_closed() -> None:
    old = "FROM python:3.12-slim AS base\nFROM base AS final\n"
    new = "FROM python:3.13-slim AS base\nFROM base AS final\nFROM ghcr.io/org/tool:1.0\n"
    entries = routine.changed_entries("docker", old, new)
    # Stage aliases are ignored; the changed tag and the new image are the only entries.
    assert [e[1] for e in entries] == ["ghcr.io/org/tool", "python"]
    result = routine.evaluate(
        [("Dockerfile", e) for e in entries], now=NOW, lookup=FakeLookup({}),
        docker_lookup=lambda image, tag, digest: None if "ghcr" in image else ago(days=2),
    )
    # The unobtainable registry fails closed and the 2-day-old tag is blocked.
    assert len(result[0]) == 2 and "failing closed" in result[0][0]
    exempt = routine.evaluate(
        [("Dockerfile", ("docker", "ghcr.io/org/tool", "1.0"))], now=NOW, lookup=FakeLookup({}),
        docker_lookup=lambda *_: None, security_fix="GHSA-xxxx",
    )
    # An explicit Security-Fix marker turns the unobtainable registry into a warning.
    assert exempt[0] == [] and len(exempt[1]) == 1


# Spec coverage: security-monitoring.release-age.routine
# contract-test: infrastructure
def test_security_fix_trailer_uses_the_72_hour_rule() -> None:
    lookup = FakeLookup({("lib", "2.1.0"): ago(days=4), ("lib", "2.1.1"): ago(hours=10)})
    entries = [("req.txt", ("PyPI", "lib", "2.1.0")), ("req.txt", ("PyPI", "lib", "2.1.1"))]
    violations, _ = routine.evaluate(entries, now=NOW, lookup=lookup, security_fix="GHSA-xxxx")
    # A 4-day-old fix passes the 72h rule while the 10-hour-old one is still blocked.
    assert len(violations) == 1 and "2.1.1" in violations[0]


# Spec coverage: security-monitoring.release-age.routine
# contract-test: infrastructure
def test_requirements_parser_reads_only_pinned_changes() -> None:
    old = "fastapi==0.1.0\nlib[extra]==1.0 ; python_version>'3'\n"
    new = "fastapi==0.1.0\nlib[extra]==1.1 ; python_version>'3'\nloose>=2\n# c\n"
    # Only the changed pin is reported; unpinned and unchanged lines are ignored.
    assert routine.changed_entries("pypi", old, new) == [("PyPI", "lib", "1.1")]


# Spec coverage: security-monitoring.release-age.security-priority
# contract-test: infrastructure
def test_oldest_fixing_version_old_enough_applies_immediately() -> None:
    lookup = FakeLookup({("zod", "4.6.6"): ago(days=5), ("zod", "4.7.1"): ago(days=1)})
    decision = age.select_fix_version("npm", "zod", "4.6.2", ["4.7.1", "4.6.6"], urgent_reachable_exposed=False, now=NOW, lookup=lookup)
    # 4.6.6 is the oldest fixing version on the current major line and is over 72 hours old.
    assert (decision.version, decision.mode) == ("4.6.6", "immediate")


# Spec coverage: security-monitoring.release-age.security-priority
# contract-test: infrastructure
def test_young_fix_with_new_postinstall_becomes_mitigation() -> None:
    lookup = FakeLookup(
        {("zod", "4.6.6"): ago(hours=10)},
        meta={"4.6.6": clean_meta(install_scripts=["postinstall"]), "4.6.5": clean_meta()},
    )
    decision = age.select_fix_version("npm", "zod", "4.6.2", ["4.6.6"], urgent_reachable_exposed=True, now=NOW, lookup=lookup)
    # The new postinstall script fails the integrity checks, so no bump is applied.
    assert decision.mode == "mitigate" and any("postinstall" in r for r in decision.reasons)


# Spec coverage: security-monitoring.release-age.security-priority
# contract-test: infrastructure
def test_young_fix_with_clean_integrity_and_urgent_exposure_is_emergency() -> None:
    lookup = FakeLookup({("zod", "4.6.6"): ago(hours=10)}, meta={"4.6.6": clean_meta(), "4.6.5": clean_meta()})
    decision = age.select_fix_version("npm", "zod", "4.6.2", ["4.6.6"], urgent_reachable_exposed=True, now=NOW, lookup=lookup)
    # All integrity checks pass for an urgent exposed issue, so the emergency bump is allowed.
    assert (decision.version, decision.mode) == ("4.6.6", "emergency")
    calm = age.select_fix_version("npm", "zod", "4.6.2", ["4.6.6"], urgent_reachable_exposed=False, now=NOW, lookup=lookup)
    # Without urgent reachable exposure the same young version is only mitigated.
    assert calm.mode == "mitigate"


# Spec coverage: security-monitoring.release-age.security-priority
# contract-test: infrastructure
def test_unverifiable_integrity_fails_closed_to_mitigate() -> None:
    lookup = FakeLookup({("lib", "2.0.1"): ago(hours=5)}, meta={"2.0.1": {"publisher": None, "install_scripts": None, "dependencies": ["a"]}, "2.0.0": {"publisher": None, "install_scripts": None, "dependencies": ["a"]}}, flags=None, previous="2.0.0")
    decision = age.select_fix_version("PyPI", "lib", "2.0.0", ["2.0.1"], urgent_reachable_exposed=True, now=NOW, lookup=lookup)
    # Unknown publisher, install scripts and content diff all count as failures.
    assert decision.mode == "mitigate" and sum("unverifiable" in r for r in decision.reasons) == 3


# Spec coverage: security-monitoring.release-age.security-priority
# contract-test: infrastructure
def test_malicious_record_and_changed_publisher_block_emergency() -> None:
    lookup = FakeLookup(
        {("zod", "4.6.6"): ago(hours=2)}, malicious=True,
        meta={"4.6.6": clean_meta(publisher="attacker"), "4.6.5": clean_meta()},
    )
    decision = age.select_fix_version("npm", "zod", "4.6.2", ["4.6.6"], urgent_reachable_exposed=True, now=NOW, lookup=lookup)
    # A MAL- record and a publisher change are both reported and prevent the bump.
    assert decision.mode == "mitigate" and any("MAL-" in r for r in decision.reasons) and any("publisher changed" in r for r in decision.reasons)


# Spec coverage: security-monitoring.release-age.security-priority
# contract-test: infrastructure
def test_version_choice_prefers_current_major_line_and_handles_no_fix() -> None:
    # The lowest fix on the current major wins over a lower-numbered other-major fix being absent.
    assert age.choose_oldest_fix("4.6.2", ["5.0.1", "4.7.1", "4.6.6"]) == "4.6.6"
    assert age.choose_oldest_fix("4.6.2", ["5.0.1"]) == "5.0.1"
    decision = age.select_fix_version("npm", "zod", "4.6.2", ["4.6.1"], urgent_reachable_exposed=True, now=NOW, lookup=FakeLookup({}))
    # A fix that is not above the current version leaves only mitigation.
    assert decision.version is None and decision.mode == "mitigate"


# Spec coverage: security-monitoring.release-age.security-priority
# contract-test: infrastructure
def test_tarball_diff_flags_new_binary_and_minified_without_extracting(tmp_path: Path) -> None:
    import io
    import tarfile

    def build(path: Path, files: dict[str, bytes]) -> None:
        with tarfile.open(path, "w:gz") as archive:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

    build(tmp_path / "old.tgz", {"package/index.js": b"a\n"})
    build(tmp_path / "new.tgz", {"package/index.js": b"a\n", "package/x.node": b"\x7fELF", "package/big.js": b"x" * 300_000})
    flags = artifacts.flag_new_content(artifacts.summarize_tarball(tmp_path / "old.tgz"), artifacts.summarize_tarball(tmp_path / "new.tgz"))
    # The new native addon and the 300KB single-line script are flagged; nothing is extracted.
    assert len(flags) == 2 and not list(tmp_path.glob("package*"))
