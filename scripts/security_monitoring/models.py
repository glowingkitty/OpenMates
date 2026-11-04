"""Shared data contracts for automated security monitoring.

Every lane (inventory, sources, matcher, host reports, dispatch, notifications)
exchanges these dataclasses only. Values are plain JSON-serializable types so
records can be persisted in the SQLite state store and handed to the triage
chat as validated structured input. See
docs/architecture/infrastructure/security-monitoring.md.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

AssetKind = Literal[
    "package",
    "container_image",
    "os_package",
    "kernel",
    "runtime",
    "vendor",
    "skill_provider",
    "dev_tool",
    "ci_action",
]
Environment = Literal["prod", "dev", "upload", "preview", "vercel", "ci", "dev_tools", "apple_client"]
Exposure = Literal["internet_facing", "internal", "build_only", "client_only"]
MatchStrength = Literal["exact_version", "version_range", "name_only", "vendor_only", "none"]
Disposition = Literal["triage", "digest_only", "suppressed_not_used", "suppressed_recorded_verdict"]
VerdictOutcome = Literal["not_affected", "affected_low", "affected_fix_soon", "urgent"]
NotAffectedReason = Literal[
    "component_not_present",
    "version_not_affected",
    "vulnerable_code_not_present",
    "not_reachable",
    "mitigated",
]
FixClass = Literal["dependency_bump", "image_digest_bump", "malicious_package_removal", "config_mitigation"]
Severity = Literal["critical", "high", "medium", "low", "unknown"]

VERDICT_OUTCOMES: tuple[str, ...] = ("not_affected", "affected_low", "affected_fix_soon", "urgent")
NOT_AFFECTED_REASONS: tuple[str, ...] = (
    "component_not_present",
    "version_not_affected",
    "vulnerable_code_not_present",
    "not_reachable",
    "mitigated",
)
FIX_CLASSES: tuple[str, ...] = (
    "dependency_bump",
    "image_digest_bump",
    "malicious_package_removal",
    "config_mitigation",
)
HOST_ROLES: tuple[str, ...] = ("core", "upload", "preview")
HOST_REPORT_FIELDS: tuple[str, ...] = (
    "os_release",
    "running_kernel",
    "installed_kernels",
    "reboot_required",
    "package_versions",
    "pending_security_updates",
    "deployed_image_digests",
    "listening_ports",
    "sshd_effective_settings",
    "authorized_key_fingerprints",
    "ssh_config_checksums",
    "successful_ssh_logins",
    "local_accounts_and_sudoers",
    "package_file_integrity",
)


@dataclass(frozen=True)
class Asset:
    """One thing OpenMates runs or builds with, scoped by ecosystem and environment."""

    kind: AssetKind
    ecosystem: str  # npm, PyPI, crates.io, SwiftURL, docker, ubuntu, debian, alpine, vendor, tool, github-actions
    name: str
    version: str | None
    environments: tuple[str, ...]
    exposure: Exposure
    usage: Literal["used", "not_used"] = "used"
    not_used_reason: str | None = None
    source_file: str | None = None  # where the inventory found it (repo-relative or host-report role)

    @property
    def identity(self) -> str:
        return f"{self.ecosystem}:{self.name.lower()}@{self.version or '*'}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Inventory:
    generated_at: str
    assets: tuple[Asset, ...]
    incomplete_sources: tuple[str, ...] = ()  # required sources that could not be read
    stale_hosts: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.incomplete_sources and not self.stale_hosts


@dataclass(frozen=True)
class AdvisoryItem:
    """A normalized item from one source before matching."""

    source: str  # osv, ghsa, dependabot, ubuntu_usn, debian, alpine, cisa_kev, vendor:<name>, news:<feed>
    advisory_id: str
    aliases: tuple[str, ...]
    title: str
    severity: Severity
    published_at: str | None
    modified_at: str | None
    # Affected package coordinates when the source is structured; empty for news/vendor bulletins.
    affected: tuple[dict[str, Any], ...] = ()  # {ecosystem, name, ranges|versions, fixed: [..]}
    keywords: tuple[str, ...] = ()  # names mentioned in unstructured text (news/vendor)
    known_exploited: bool = False
    exploit_probability: float | None = None  # EPSS 0..1
    public_exploit: bool = False
    withdrawn: bool = False
    url: str | None = None  # only rendered after origin allowlisting


@dataclass(frozen=True)
class Observation:
    """An advisory matched (or deliberately not matched) to inventory assets."""

    identity: str  # stable: canonical advisory id + sorted asset identities
    advisory: AdvisoryItem
    assets: tuple[Asset, ...]
    match_strength: MatchStrength
    disposition: Disposition
    suppression_reason: str | None = None
    # Hash over the material facts (asset versions, environments, severity, KEV, exploit, withdrawn).
    material_fingerprint: str = ""


@dataclass(frozen=True)
class ProposedFix:
    fix_class: FixClass
    target_files: tuple[str, ...]
    package: str | None
    from_version: str | None
    target_version: str | None
    mitigation: str | None = None


@dataclass(frozen=True)
class TriageVerdict:
    observation_identity: str
    outcome: VerdictOutcome
    not_affected_reason: NotAffectedReason | None
    environments_assessed: tuple[str, ...]
    reachability: str
    exploitability: str
    blast_radius: str
    evidence_summary: str
    proposed_fix: ProposedFix | None
    manual_actions: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class HostReport:
    host_role: str  # core | upload | preview
    host_id: str  # stable reporter key id, never an address
    generated_at: str
    contents: dict[str, Any]
