"""Contracts for the security monitoring inventory, hourly sources and matcher.

Everything is offline: the dev-host probe and every source fetch are faked, so
no test reads the real host, calls the network or runs gh. Fixture data uses
placeholder names and versions only.
"""

# contract-test-file: infrastructure
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from security_monitoring import inventory, matcher, sources  # noqa: E402 - scripts dir added above
from security_monitoring.models import AdvisoryItem, HostReport  # noqa: E402 - scripts dir added above
from security_monitoring.sources.fetch import FetchError  # noqa: E402 - scripts dir added above
from security_monitoring.versions import compare_dpkg, compare_semver, evaluate_affected  # noqa: E402 - scripts dir added above

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
CVE = "CVE-2026-90001"
GHSA = "GHSA-aaaa-bbbb-cccc"


class FakeProbe:
    """Dev host with cursor-agent and claude installed, no Cursor IDE."""

    tools = {"cursor-agent": "2025.10.02-abc1234", "claude": "2.1.300"}

    def which(self, name):
        return Path(f"/opt/placeholder/bin/{name}") if name in self.tools else None

    def tool_version(self, name, path):
        return self.tools[name]

    def npm_global_packages(self):
        return {"@google/gemini-cli": "0.38.2"}

    def dpkg_packages(self):
        return {"openssh-server": "1:9.6p1-3ubuntu13.5", "libc6": "2.39-0ubuntu8.4"}

    def kernel(self):
        return "6.8.0-100-generic"

    def os_release(self):
        return 'ID=ubuntu\nVERSION_ID="24.04"\n'


@pytest.fixture(autouse=True)
def fake_dev_host(monkeypatch):
    monkeypatch.setattr(inventory, "dev_host_probe", FakeProbe)


PNPM_LOCK = """lockfileVersion: '9.0'

importers:

  .: {}

packages:

  zod@4.6.2:
    resolution: {integrity: sha512-placeholder}

  next@15.0.0:
    resolution: {integrity: sha512-placeholder}

  vite@7.3.7:
    resolution: {integrity: sha512-placeholder}

snapshots:

  zod@4.6.2: {}
"""

PBXPROJ = """
\t\tA1 /* XCRemoteSwiftPackageReference "swift-sodium" */ = {
\t\t\tisa = XCRemoteSwiftPackageReference;
\t\t\trepositoryURL = "https://github.com/example/swift-sodium.git";
\t\t\trequirement = {
\t\t\t\tkind = exactVersion;
\t\t\t\tversion = 0.9.1;
\t\t\t};
\t\t};
"""


def write_repo(root: Path) -> Path:
    files = {
        "pnpm-lock.yaml": PNPM_LOCK,
        "backend/status/frontend/package-lock.json": json.dumps(
            {"lockfileVersion": 3, "packages": {"": {"name": "status"}, "node_modules/svelte": {"version": "5.55.7"}}}),
        "backend/core/api/requirements.txt": "fastapi==0.135.1\nhttpx>=0.27.0  # floor only\n",
        "packages/openmates-python/pyproject.toml": '[project]\nname = "openmates"\ndependencies = ["requests>=2.31"]\n',
        "Cargo.lock": 'version = 3\n\n[[package]]\nname = "h2"\nversion = "0.4.1"\nsource = "registry+https://github.com/rust-lang/crates.io-index"\n',
        "apple/PairOpaqueBridge/Cargo.lock": 'version = 3\n\n[[package]]\nname = "opaque-ke"\nversion = "3.0.0"\nsource = "registry+https://github.com/rust-lang/crates.io-index"\n',
        "frontend/packages/openmates-tui-prototype/Cargo.lock": 'version = 3\n\n[[package]]\nname = "local-crate"\nversion = "0.1.0"\n',
        "apple/OpenMates.xcodeproj/project.pbxproj": PBXPROJ,
        "backend/core/api/Dockerfile": "ARG BASE=python:3.13-slim\nFROM ${BASE} AS base\nRUN cat <<EOF > /tmp/x\nFROM not_an_image\nEOF\nFROM base\n",
        "backend/core/docker-compose.yml": "services:\n  cache:\n    image: docker.io/library/postgres:16-alpine\n  api:\n    image: openmates-api:dev\n",
        ".github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@" + "a" * 40 + "\n      - uses: ./local\n",
        "backend/providers/example.yml": 'provider_id: "example"\nname: "Example Provider"\n',
    }
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def fresh_report(role: str, age: timedelta = timedelta(hours=2)) -> HostReport:
    return HostReport(host_role=role, host_id=f"placeholder-{role}", generated_at=(NOW - age).isoformat(),
                      contents={"os_release": {"ID": "ubuntu", "VERSION_ID": "24.04"}, "running_kernel": "6.8.0-90-generic",
                                "package_versions": {"libc6": "2.39-0ubuntu8.3", "openssh-server": "1:9.6p1-3ubuntu13.5"}})


def all_reports() -> dict[str, HostReport]:
    return {role: fresh_report(role) for role in ("core", "upload", "preview")}


def find(inv, name, kind=None):
    return [asset for asset in inv.assets if asset.name == name and (kind is None or asset.kind == kind)]


def osv_item(*, fixed="4.6.6", modified="2026-11-04T10:00:00Z") -> AdvisoryItem:
    return AdvisoryItem(source="osv", advisory_id=GHSA, aliases=(CVE,), title="zod parsing flaw", severity="high",
                        published_at="2026-11-04T09:00:00Z", modified_at=modified,
                        affected=({"ecosystem": "npm", "name": "zod",
                                   "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": fixed}]}]},))


def dependabot_item() -> AdvisoryItem:
    return AdvisoryItem(source="dependabot", advisory_id=GHSA, aliases=(CVE, GHSA), title="zod parsing flaw",
                        severity="high", published_at="2026-11-04T09:00:00Z", modified_at="2026-11-04T10:00:00Z",
                        affected=({"ecosystem": "npm", "name": "zod", "range_expr": "< 4.6.6", "fixed": ["4.6.6"]},))


def news_item(title: str, *, severity="unknown", known_exploited=False, keywords=()) -> AdvisoryItem:
    return AdvisoryItem(source="news:placeholder", advisory_id=f"NEWS-{abs(hash(title))}", aliases=(), title=title,
                        severity=severity, published_at=None, modified_at=None, keywords=keywords,
                        known_exploited=known_exploited)


# -- inventory ----------------------------------------------------------------------

# Monitoring coverage: security-monitoring.inventory.explicit
# contract-test: infrastructure
def test_installed_cursor_agent_is_used_and_only_cursor_ide_stays_not_used(tmp_path):
    inv = inventory.build_inventory(write_repo(tmp_path), all_reports(), NOW)
    assert inv.incomplete_sources == ()
    agent = find(inv, "cursor-agent", "dev_tool")
    assert len(agent) == 1 and agent[0].usage == "used" and agent[0].environments == ("dev_tools",)
    ide = find(inv, "Cursor IDE editor extension")
    assert len(ide) == 1 and ide[0].usage == "not_used"
    assert ide[0].not_used_reason == "no Cursor IDE installed on any host"
    # A not-used entry naming an installed tool is overridden, never classified not_used.
    entries = [inventory.NotUsedEntry("cursor-agent", (), "stale entry"), inventory.NotUsedEntry("Drupal", (), "unused")]
    kept, overridden = inventory.resolve_not_used(entries, inv.assets)
    assert [entry.name for entry in overridden] == ["cursor-agent"]
    assert [entry.name for entry in kept] == ["Drupal"]
    assert all(entry.reason.strip() for entry in inventory.load_not_used())


# Monitoring coverage: security-monitoring.inventory.explicit
# contract-test: infrastructure
def test_inventory_records_sources_environments_and_exposure(tmp_path):
    inv = inventory.build_inventory(write_repo(tmp_path), all_reports(), NOW)
    assert find(inv, "zod")[0].environments == ("dev", "vercel")
    assert find(inv, "fastapi")[0].version == "0.135.1" and find(inv, "fastapi")[0].exposure == "internet_facing"
    assert find(inv, "httpx")[0].version is None  # floor-only requirement stays version-unknown
    assert find(inv, "h2")[0].ecosystem == "crates.io"
    assert find(inv, "opaque-ke")[0].environments == ("apple_client",)
    assert find(inv, "github.com/example/swift-sodium")[0].version == "0.9.1"
    images = {(asset.name, asset.version) for asset in inv.assets if asset.kind == "container_image"}
    assert images == {("python", "3.13-slim"), ("postgres", "16-alpine")}  # heredoc body and local builds ignored
    action = find(inv, "actions/checkout")[0]
    assert action.environments == ("ci",) and action.exposure == "build_only" and inventory.is_sha_pinned(action)
    assert find(inv, "Example Provider")[0].kind == "skill_provider"
    assert {asset.name for asset in inv.assets if asset.kind == "vendor" and asset.usage == "used"} == {"Hetzner", "Vercel", "GitHub"}
    libc = {asset.version: asset.environments for asset in find(inv, "libc6")}
    assert libc == {"2.39-0ubuntu8.4": ("dev",), "2.39-0ubuntu8.3": ("preview", "prod", "upload")}
    assert {asset.version for asset in find(inv, "linux-kernel", "kernel")} == {"6.8.0-100-generic", "6.8.0-90-generic"}
    assert find(inv, "@google/gemini-cli")[0].environments == ("dev_tools",)
    assert find(inv, "gemini", "dev_tool")[0].version == "0.38.2"
    assert inv.complete


# Monitoring coverage: security-monitoring.inventory.explicit
# contract-test: infrastructure
def test_unreadable_source_and_stale_host_mark_inventory_incomplete(tmp_path):
    root = write_repo(tmp_path)
    (root / "pnpm-lock.yaml").write_text("not a lockfile\n", encoding="utf-8")
    (root / "Cargo.lock").write_text("[[package]\nbroken", encoding="utf-8")
    reports = {"core": fresh_report("core"), "upload": fresh_report("upload", timedelta(days=3)), "preview": None}
    inv = inventory.build_inventory(root, reports, NOW)
    assert not inv.complete
    assert set(inv.stale_hosts) == {"upload", "preview"}
    labels = " ".join(inv.incomplete_sources)
    assert "pnpm-lock.yaml" in labels and "Cargo.lock" in labels
    libc_envs = {env for asset in find(inv, "libc6") for env in asset.environments}
    assert "prod" in libc_envs and "upload" not in libc_envs  # a stale report contributes nothing


# -- matching -----------------------------------------------------------------------

@pytest.fixture
def inv(tmp_path):
    return inventory.build_inventory(write_repo(tmp_path), all_reports(), NOW)


# Monitoring coverage: security-monitoring.sources.hourly-deterministic
# contract-test: infrastructure
def test_critical_exploited_drupal_news_is_suppressed_as_not_used(inv):
    item = news_item("Critical Drupal Commerce flaw actively exploited, PoC on GitHub", severity="critical",
                     known_exploited=True)
    observations = matcher.match([item], inv, {})
    assert len(observations) == 1
    observation = observations[0]
    assert observation.disposition == "suppressed_not_used"
    assert observation.suppression_reason == "not used: no Drupal or PHP in any environment"
    assert not [obs for obs in observations if obs.disposition == "triage"]


# Monitoring coverage: security-monitoring.sources.hourly-deterministic
# contract-test: infrastructure
def test_zod_range_match_triages_and_dependabot_copy_stays_the_same_observation(inv):
    first = matcher.match([osv_item()], inv, {})
    assert len(first) == 1
    assert first[0].match_strength == "version_range" and first[0].disposition == "triage"
    assert [asset.name for asset in first[0].assets] == ["zod"]
    later = matcher.match([osv_item(), dependabot_item()], inv, {})
    assert len(later) == 1
    assert later[0].identity == first[0].identity
    assert later[0].identity.startswith(CVE)  # canonical id prefers the CVE alias
    alone = matcher.match([dependabot_item()], inv, {})
    assert alone[0].identity == first[0].identity
    assert matcher.match([osv_item(fixed="4.6.1")], inv, {}) == []  # outside the range: no observation


# Monitoring coverage: security-monitoring.sources.hourly-deterministic
# contract-test: infrastructure
def test_recorded_verdict_suppresses_until_material_change(inv):
    observation = matcher.match([osv_item()], inv, {})[0]
    recorded = {observation.identity: observation.material_fingerprint}
    again = matcher.match([osv_item()], inv, recorded)[0]
    assert again.disposition == "suppressed_recorded_verdict" and again.suppression_reason
    escalated = matcher.match([replace(osv_item(), known_exploited=True)], inv, recorded)[0]
    assert escalated.identity == observation.identity and escalated.disposition == "triage"
    bumped_assets = tuple(replace(asset, version="4.6.3") if asset.name == "zod" else asset for asset in inv.assets)
    bumped = matcher.match([osv_item()], replace(inv, assets=bumped_assets), recorded)[0]
    assert bumped.identity == observation.identity and bumped.disposition == "triage"


# Monitoring coverage: security-monitoring.sources.hourly-deterministic
# contract-test: infrastructure
def test_name_only_news_goes_to_digest_unless_critical_or_exploited(inv):
    plain = matcher.match([news_item("New Claude Code release notes mention sandbox hardening")], inv, {})
    assert [(obs.match_strength, obs.disposition) for obs in plain] == [("name_only", "digest_only")]
    critical = matcher.match([news_item("Critical flaw in Claude Code sandbox", severity="critical")], inv, {})
    assert critical[0].disposition == "triage"
    vendor = matcher.match([news_item("Hetzner phishing wave", keywords=("Hetzner",))], inv, {})
    assert [(obs.match_strength, obs.disposition) for obs in vendor] == [("vendor_only", "digest_only")]
    exploited_kernel = matcher.match([news_item("Linux kernel bug exploited", known_exploited=True)], inv, {})
    assert exploited_kernel[0].disposition == "triage"
    assert {asset.kind for asset in exploited_kernel[0].assets} == {"kernel"}


# Monitoring coverage: security-monitoring.sources.hourly-deterministic
# contract-test: infrastructure
def test_keyword_matching_uses_word_boundaries_and_no_generic_names(inv):
    for title in ("Next steps for go developers", "Vitest plugin flaw", "keyvault exposure", "Python packaging news"):
        assert matcher.match([news_item(title, severity="critical")], inv, {}) == [], title
    assert matcher.match([news_item("Vite dev server flaw")], inv, {})[0].assets[0].name == "vite"


# Monitoring coverage: security-monitoring.sources.hourly-deterministic
# contract-test: infrastructure
def test_ubuntu_notice_matches_only_hosts_with_older_packages(inv):
    usn = AdvisoryItem(source="ubuntu_usn", advisory_id="USN-9000-1", aliases=("CVE-2026-90002",), title="glibc",
                       severity="unknown", published_at=None, modified_at=None,
                       affected=({"ecosystem": "ubuntu", "release": "24.04", "name": "libc6", "fixed": ["2.39-0ubuntu8.4"]},))
    observation = matcher.match([usn], inv, {})[0]
    assert observation.disposition == "triage" and observation.match_strength == "version_range"
    assert {env for asset in observation.assets for env in asset.environments} == {"prod", "upload", "preview"}
    other_release = replace(usn, affected=({**usn.affected[0], "release": "22.04"},))
    assert matcher.match([other_release], inv, {}) == []


# Monitoring coverage: security-monitoring.sources.hourly-deterministic
# contract-test: infrastructure
def test_version_ordering_per_ecosystem():
    assert compare_dpkg("1:9.6p1-3ubuntu13.5", "1:9.6p1-3ubuntu13.10") == -1
    assert compare_dpkg("1.0~rc1", "1.0") == -1 and compare_dpkg("2:0.1", "1:9.9") == 1
    assert compare_dpkg("1.0", "1.0-0") == 0
    assert compare_semver("1.0.0-beta.2", "1.0.0") == -1 and compare_semver("4.6.10", "4.6.6") == 1
    assert evaluate_affected("npm", "2.1.300", {"range_expr": "> 0.2.116 < 1.0.24"}) == "not_affected"
    assert evaluate_affected("npm", "11.5.0", {"range_expr": ">=10.10.0", "patched": ["10.11.0"]}) == "not_affected"
    assert evaluate_affected("PyPI", "not a version", {"range_expr": "< 2.0"}) == "unknown"
    assert evaluate_affected("npm", None, {"range_expr": "< 2.0"}) == "unknown"


# -- sources ------------------------------------------------------------------------

USN_PAYLOAD = {"notices": [
    {"id": "USN-9001-1", "title": "glibc vulnerability", "published": "2026-11-04T08:00:00", "cves_ids": ["CVE-2026-90003"],
     "releases": [{"codename": "noble", "version": "24.04"}, {"codename": "jammy", "version": "22.04"}],
     "release_packages": {"noble": [{"name": "libc6", "version": "2.39-0ubuntu8.5", "is_source": False}],
                          "jammy": [{"name": "libc6", "version": "2.35-0ubuntu3.9", "is_source": False}]}},
    {"id": "USN-8000-1", "title": "old", "published": "2026-10-01T08:00:00", "cves_ids": [], "releases": [],
     "release_packages": {}},
]}
RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Critical Drupal flaw exploited (CVE-2026-90009)</title><link>https://news.example/a</link>
<description>Attackers exploit Drupal.</description><pubDate>Wed, 04 Nov 2026 09:00:00 +0000</pubDate></item>
<item><title>Old Hetzner story</title><link>https://news.example/b</link>
<description>x</description><pubDate>Mon, 02 Nov 2026 09:00:00 +0000</pubDate></item>
</channel></rss>"""


class FakeFetch:
    def __init__(self, failures=None):
        self.failures = failures or {}
        self.urls: list[str] = []

    def __call__(self, url, options=None):
        self.urls.append(url)
        for fragment, error in self.failures.items():
            if fragment in url:
                raise error
        if url.endswith("/querybatch"):
            queries = options["json"]["queries"]
            return {"results": [{"vulns": [{"id": "MAL-2026-1", "modified": "2026-11-04T09:00:00Z"}]}
                                if query["package"]["name"] == "zod" else {} for query in queries]}
        if "/v1/vulns/MAL-2026-1" in url:
            return {"id": "MAL-2026-1", "aliases": [], "summary": "Malicious code in zod",
                    "affected": [{"package": {"ecosystem": "npm", "name": "zod"}, "versions": ["4.6.2"]}]}
        if "dependabot/alerts" in url:
            return [{"security_advisory": {"ghsa_id": GHSA, "cve_id": CVE, "summary": "zod flaw", "severity": "high"},
                     "security_vulnerability": {"package": {"ecosystem": "npm", "name": "zod"}, "severity": "high",
                                                "vulnerable_version_range": "< 4.6.6",
                                                "first_patched_version": {"identifier": "4.6.6"}}}]
        if "security-advisories" in url:
            return []
        if "notices.json" in url:
            return USN_PAYLOAD if "offset=0" in url else {"notices": []}
        if "known_exploited" in url:
            return {"vulnerabilities": [{"cveID": CVE, "dateAdded": "2026-11-04", "vendorProject": "Example",
                                         "product": "zod", "vulnerabilityName": "zod flaw"}]}
        if "epss" in url:
            return {"data": [{"cve": CVE, "epss": "0.42"}]}
        if options and options.get("format") == "text":
            return RSS
        raise FetchError("http_404")


# Monitoring coverage: security-monitoring.sources.hourly-deterministic
# contract-test: infrastructure
def test_collect_normalizes_offline_sources_and_marks_exploitation(inv):
    fetch = FakeFetch()
    items, statuses = sources.collect(since=NOW - timedelta(hours=24), now=NOW, inventory=inv, fetch=fetch)
    by_name = {status.name: status for status in statuses}
    assert by_name["osv"].ok and by_name["osv"].item_count == 1
    assert by_name["dependabot"].item_count == 1 and by_name["ubuntu_usn"].item_count == 1
    assert not by_name["vendor:vercel"].ok and not by_name["vendor:vercel"].supported
    malicious = [item for item in items if item.advisory_id == "MAL-2026-1"][0]
    assert malicious.severity == "critical"
    dependabot = [item for item in items if item.source == "dependabot"][0]
    assert dependabot.known_exploited and dependabot.exploit_probability == pytest.approx(0.42)
    usn = [item for item in items if item.source == "ubuntu_usn"][0]
    assert [entry["release"] for entry in usn.affected] == ["24.04"]  # releases not in use are dropped
    news = [item for item in items if item.source.startswith("news:")]
    assert news and all("Old Hetzner story" != item.title for item in news)  # outside the since window
    assert all("Drupal" in item.keywords for item in news)
    dispositions = {obs.advisory.source: obs.disposition for obs in matcher.match(items, inv, {})}
    assert dispositions["news:bleepingcomputer"] == "suppressed_not_used"


# Monitoring coverage: security-monitoring.sources.hourly-deterministic
# contract-test: infrastructure
def test_source_timeout_is_recorded_as_incomplete_never_raised(inv):
    fetch = FakeFetch({"querybatch": FetchError("timeout"), "TheHackersNews": TimeoutError("slow"),
                       "notices.json": FetchError("http_503"), "cisa.gov": FetchError("http_403")})
    items, statuses = sources.collect(since=NOW - timedelta(hours=1), now=NOW, inventory=inv, fetch=fetch)
    by_name = {status.name: status for status in statuses}
    assert (by_name["osv"].ok, by_name["osv"].error_code, by_name["osv"].item_count) == (False, "timeout", 0)
    assert (by_name["news:thehackernews"].ok, by_name["news:thehackernews"].error_code) == (False, "timeout")
    assert by_name["ubuntu_usn"].error_code == "http_503"
    assert by_name["cisa_kev"].ok  # the official mirror answered after the primary URL refused
    assert by_name["dependabot"].ok and any(item.source == "dependabot" for item in items)
