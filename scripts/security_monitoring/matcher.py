"""Deterministic matching of advisory items to inventory assets.

Items are grouped by normalized aliases (CVE, GHSA, source id), matched to
assets with an explicit match strength and given exactly one disposition per
security-monitoring.sources.hourly-deterministic:

- exact or range match on a used asset, or any match on a known-exploited
  item -> triage;
- name-only or vendor-only matches -> triage only when critical or known
  exploited, otherwise digest_only;
- matches only on not_used assets -> suppressed_not_used (with reason);
- an identity whose stored not_affected fingerprint equals the current
  material fingerprint -> suppressed_recorded_verdict.

Unmatched items produce no observation. News keyword matching uses word
boundaries and an explicit alias table; short or generic names never match
on their own. See specifications/architecture/security-monitoring/.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Iterable, Mapping, Sequence

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from security_monitoring.inventory import NOT_USED_PATH, SourceUnreadable, load_not_used  # noqa: E402 - package import after path setup
from security_monitoring.models import AdvisoryItem, Asset, Inventory, Observation  # noqa: E402 - package import after path setup
from security_monitoring.versions import evaluate_affected  # noqa: E402 - package import after path setup

SEVERITY_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
STRENGTH_RANK = {"none": 0, "vendor_only": 1, "name_only": 2, "version_range": 3, "exact_version": 4}
MIN_AUTO_TERM_LENGTH = 4
# Generic words that never match on their own, even when an asset is named so.
GENERIC_TERMS = {
    "node", "next", "core", "api", "app", "web", "server", "client", "agent", "debug", "test", "vault",
    "python", "alpine", "linux", "stable", "cache", "proxy", "http", "https", "docker", "image", "cloud",
    "worker", "store", "react", "graph", "query", "build", "lint", "types", "utils", "config", "common",
    # Vendor names too broad for news (product news would flood the digest); own name.
    "google", "inception", "openmates", "youtube",
}
# Explicit news aliases (asset name, lower-case) -> phrases that name it in prose.
KEYWORD_ALIASES: dict[str, tuple[str, ...]] = {
    "claude": ("Claude Code",),
    "codex": ("Codex CLI", "OpenAI Codex"),
    "cursor-agent": ("cursor-agent", "Cursor CLI"),
    "gemini": ("Gemini CLI",),
    "opencode": ("OpenCode",),
    "aider": ("Aider",),
    "vercel": ("Vercel CLI",),
    "cloudflared": ("cloudflared", "Cloudflare Tunnel"),
    "vscode-server": ("VS Code Server", "code-server", "Visual Studio Code Server"),
    "tailscale": ("Tailscale",),
    "linux-kernel": ("Linux kernel",),
    "ubuntu": ("Ubuntu",),
    "node": ("Node.js",),
    "python": ("CPython",),
    "postgres": ("PostgreSQL", "Postgres"),
    "hashicorp/vault": ("HashiCorp Vault",),
    "directus/directus": ("Directus",),
    "docker.dragonflydb.io/dragonflydb/dragonfly": ("DragonflyDB", "Dragonfly DB"),
    "caddy": ("Caddy",),
    "clamav/clamav-debian": ("ClamAV",),
    "prom/prometheus": ("Prometheus",),
    "grafana/promtail": ("Promtail", "Grafana Loki"),
    "public.ecr.aws/zinclabs/openobserve": ("OpenObserve",),
    "gcr.io/cadvisor/cadvisor": ("cAdvisor",),
    "openssh-server": ("OpenSSH",),
    "libc6": ("glibc", "GNU C Library"),
    "openssl": ("OpenSSL",),
    "sudo": ("sudo",),
    "xz-utils": ("xz-utils", "XZ Utils", "liblzma"),
    "systemd": ("systemd",),
    "docker-ce": ("Docker Engine",),
    "containerd.io": ("containerd",),
    "runc": ("runc",),
    "@sveltejs/kit": ("SvelteKit",),
    "svelte": ("Svelte",),
    "vite": ("Vite",),
    "fastapi": ("FastAPI",),
    "celery": ("Celery",),
    "pydantic": ("Pydantic",),
    "uvicorn": ("Uvicorn",),
    "aiohttp": ("aiohttp",),
    "pillow": ("Pillow",),
    "jinja2": ("Jinja2",),
    "tweetnacl": ("TweetNaCl",),
    "dompurify": ("DOMPurify",),
    "axios": ("axios",),
    "zod": ("zod",),
    "hetzner": ("Hetzner",),
    "vercel-vendor": ("Vercel",),
    "github": ("GitHub",),
}
# Ecosystems on which news-derived names may land (packages need an explicit alias).
_AUTO_TERM_KINDS = {"vendor", "skill_provider", "container_image", "ci_action"}
_DOCKER_SUFFIX = re.compile(r"-(alpine|slim|bookworm|bullseye|buster|jammy|noble|focal|debian|ubuntu)[\w.-]*$")
_CANONICAL_ORDER = (("CVE-", 0), ("GHSA-", 1), ("MAL-", 2))


def _ecosystem_key(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in {"pypi", "pip"}:
        return "pypi"
    if lowered in {"crates.io", "rust", "cargo"}:
        return "crates.io"
    if lowered in {"swifturl", "swift"}:
        return "swifturl"
    if lowered in {"github actions", "github-actions", "actions"}:
        return "github-actions"
    if lowered.startswith("ubuntu"):
        return "ubuntu"
    if lowered.startswith("debian"):
        return "debian"
    return lowered


def _name_key(ecosystem: str, name: str) -> str:
    lowered = name.strip().lower()
    if ecosystem == "pypi":
        return re.sub(r"[-_.]+", "-", lowered)
    return lowered


def comparable_version(asset: Asset) -> str | None:
    if not asset.version:
        return None
    if asset.ecosystem == "docker":
        tag = asset.version.split("@", 1)[0]
        return _DOCKER_SUFFIX.sub("", tag) or None
    return asset.version


def _keyword_alias_key(asset: Asset) -> str:
    if asset.kind == "vendor" and asset.ecosystem == "vendor" and asset.name.lower() == "vercel":
        return "vercel-vendor"
    return asset.name.lower()


def _compile_term(term: str) -> re.Pattern[str]:
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_])", re.IGNORECASE)


def _not_used_aliases() -> dict[str, tuple[str, ...]]:
    try:
        return {entry.name.lower(): entry.aliases for entry in load_not_used(NOT_USED_PATH)}
    except (OSError, SourceUnreadable):
        return {}


@dataclass(frozen=True)
class KeywordTable:
    """Compiled news terms -> assets they name."""

    entries: tuple[tuple[str, re.Pattern[str], tuple[Asset, ...]], ...]

    def find(self, text: str) -> list[tuple[str, tuple[Asset, ...]]]:
        return [(term, assets) for term, pattern, assets in self.entries if pattern.search(text)]

    def names_in(self, text: str) -> tuple[str, ...]:
        """Canonical asset names mentioned in `text` (used to fill AdvisoryItem.keywords)."""
        return tuple(sorted({asset.name for _term, assets in self.find(text) for asset in assets}))


def _auto_terms(asset: Asset) -> list[str]:
    if asset.usage == "not_used":
        return [asset.name]
    if asset.kind not in _AUTO_TERM_KINDS:
        return []
    candidates = {asset.name}
    if asset.kind == "container_image":
        candidates.add(asset.name.rsplit("/", 1)[-1])
    return [term for term in candidates
            if (len(term) >= MIN_AUTO_TERM_LENGTH or "/" in term) and term.lower() not in GENERIC_TERMS]


def build_keyword_table(inventory: Inventory) -> KeywordTable:
    not_used_aliases = _not_used_aliases()
    by_term: dict[str, list[Asset]] = {}
    for asset in inventory.assets:
        terms = list(_auto_terms(asset))
        terms.extend(KEYWORD_ALIASES.get(_keyword_alias_key(asset), ()))
        if asset.usage == "not_used":
            terms.extend(not_used_aliases.get(asset.name.lower(), ()))
        for term in terms:
            by_term.setdefault(term.lower(), []).append(asset)
    entries = tuple((term, _compile_term(term), tuple(assets)) for term, assets in sorted(by_term.items()))
    return KeywordTable(entries)


# -- structured matching ------------------------------------------------------------

def _structured_index(inventory: Inventory) -> dict[tuple[str, str], list[Asset]]:
    index: dict[tuple[str, str], list[Asset]] = {}
    for asset in inventory.assets:
        if asset.usage != "used":
            continue
        ecosystem = _ecosystem_key(asset.ecosystem)
        index.setdefault((ecosystem, _name_key(ecosystem, asset.name)), []).append(asset)
    return index


def _release_by_environment(inventory: Inventory) -> dict[str, str]:
    return {environment: str(asset.version) for asset in inventory.assets
            if asset.kind == "runtime" and asset.ecosystem == "os" for environment in asset.environments}


def _match_structured(item: AdvisoryItem, index: Mapping[tuple[str, str], list[Asset]],
                      releases: Mapping[str, str]) -> dict[Asset, str]:
    matches: dict[Asset, str] = {}
    for entry in item.affected:
        if not isinstance(entry, dict) or not entry.get("name") or not entry.get("ecosystem"):
            continue
        ecosystem = _ecosystem_key(str(entry["ecosystem"]))
        release = entry.get("release")
        for asset in index.get((ecosystem, _name_key(ecosystem, str(entry["name"]))), ()):
            if release and not any(releases.get(environment) == str(release) for environment in asset.environments):
                continue
            result = evaluate_affected(ecosystem, comparable_version(asset), entry)
            if result == "not_affected":
                continue
            strength = "exact_version" if result == "exact" else "version_range"
            if STRENGTH_RANK[strength] > STRENGTH_RANK.get(matches.get(asset, "none"), 0):
                matches[asset] = strength
    return matches


def _match_keywords(item: AdvisoryItem, table: KeywordTable) -> dict[Asset, str]:
    text = " ".join([item.title, *item.keywords])
    matches: dict[Asset, str] = {}
    for _term, assets in table.find(text):
        for asset in assets:
            strength = "vendor_only" if asset.kind in {"vendor", "skill_provider"} else "name_only"
            if STRENGTH_RANK[strength] > STRENGTH_RANK.get(matches.get(asset, "none"), 0):
                matches[asset] = strength
    return matches


# -- grouping, identity and fingerprints ------------------------------------------------

def item_aliases(item: AdvisoryItem) -> set[str]:
    """Normalized aliases, mirroring security_reporting._normalized_aliases."""
    return {str(alias).strip().upper() for alias in (item.advisory_id, *item.aliases) if str(alias or "").strip()}


def canonical_id(aliases: Iterable[str]) -> str:
    ordered = sorted(aliases)
    for prefix, _rank in _CANONICAL_ORDER:
        for alias in ordered:
            if alias.startswith(prefix):
                return alias
    return ordered[0] if ordered else "UNIDENTIFIED"


def _group(items: Sequence[AdvisoryItem]) -> list[list[AdvisoryItem]]:
    parent = list(range(len(items)))

    def find(position: int) -> int:
        while parent[position] != position:
            parent[position] = parent[parent[position]]
            position = parent[position]
        return position

    owner: dict[str, int] = {}
    for position, item in enumerate(items):
        for alias in item_aliases(item):
            if alias in owner:
                parent[find(position)] = find(owner[alias])
            else:
                owner[alias] = position
    groups: dict[int, list[AdvisoryItem]] = {}
    for position, item in enumerate(items):
        groups.setdefault(find(position), []).append(item)
    return list(groups.values())


def _merge_items(group: Sequence[AdvisoryItem]) -> AdvisoryItem:
    """One representative item: structured sources first, strongest signals merged."""
    ordered = sorted(group, key=lambda item: (not item.affected, item.source, item.advisory_id))
    aliases = set().union(*(item_aliases(item) for item in group))
    identifier = canonical_id(aliases)
    head = ordered[0]
    probabilities = [item.exploit_probability for item in group if item.exploit_probability is not None]
    modified = [item.modified_at for item in group if item.modified_at]
    return replace(
        head,
        advisory_id=identifier,
        aliases=tuple(sorted(aliases - {identifier})),
        severity=max((item.severity for item in group), key=lambda value: SEVERITY_RANK.get(value, 0)),
        affected=tuple(entry for item in ordered for entry in item.affected),
        keywords=tuple(sorted({keyword for item in group for keyword in item.keywords})),
        known_exploited=any(item.known_exploited for item in group),
        exploit_probability=max(probabilities) if probabilities else None,
        public_exploit=any(item.public_exploit for item in group),
        withdrawn=any(item.withdrawn for item in group),
        modified_at=max(modified) if modified else None,
    )


def observation_identity(advisory_id: str, assets: Iterable[Asset]) -> str:
    names = sorted({f"{asset.ecosystem}:{asset.name.lower()}" for asset in assets})
    return f"{advisory_id}|{','.join(names)}"


def material_fingerprint(item: AdvisoryItem, assets: Iterable[Asset]) -> str:
    facts = {
        "assets": sorted([asset.identity, list(asset.environments)] for asset in assets),
        "severity": item.severity,
        "known_exploited": item.known_exploited,
        "public_exploit": item.public_exploit,
        "withdrawn": item.withdrawn,
        "modified_at": item.modified_at,
    }
    return hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _disposition(item: AdvisoryItem, strength: str) -> str:
    if strength in {"exact_version", "version_range"} or item.known_exploited:
        return "triage"
    if item.severity == "critical":
        return "triage"
    return "digest_only"


def match(items: Sequence[AdvisoryItem], inventory: Inventory, recorded_verdicts: Mapping[str, str]) -> list[Observation]:
    """Match normalized items to inventory assets and assign one disposition each."""
    index = _structured_index(inventory)
    releases = _release_by_environment(inventory)
    table = build_keyword_table(inventory)
    observations: list[Observation] = []
    for group in _group(items):
        item = _merge_items(group)
        matches: dict[Asset, str] = {}
        for member in group:
            # Structured items match on coordinates only; prose keywords apply to unstructured items.
            found = _match_structured(member, index, releases) if member.affected else _match_keywords(member, table)
            for asset, strength in found.items():
                if STRENGTH_RANK[strength] > STRENGTH_RANK.get(matches.get(asset, "none"), 0):
                    matches[asset] = strength
        if not matches:
            continue
        used = {asset: strength for asset, strength in matches.items() if asset.usage == "used"}
        not_used_hit = any(asset.usage == "not_used" for asset in matches)
        keyword_level_only = all(STRENGTH_RANK[strength] <= STRENGTH_RANK["name_only"] for strength in used.values())
        if not_used_hit and keyword_level_only:
            # A not-used product named next to an incidental used name (e.g. "on GitHub") stays suppressed.
            matches = {asset: strength for asset, strength in matches.items() if asset.usage == "not_used"}
            used = {}
        if not used:
            suppressed = tuple(sorted(matches, key=lambda asset: asset.name))
            reason = "; ".join(sorted({asset.not_used_reason or f"not used: {asset.name}" for asset in suppressed}))
            observations.append(Observation(
                identity=observation_identity(item.advisory_id, suppressed), advisory=item, assets=suppressed,
                match_strength=max(matches.values(), key=lambda value: STRENGTH_RANK[value]),  # type: ignore[arg-type]  # enum values
                disposition="suppressed_not_used", suppression_reason=reason,
                material_fingerprint=material_fingerprint(item, suppressed)))
            continue
        assets = tuple(sorted(used, key=lambda asset: (asset.identity, asset.environments)))
        strength = max(used.values(), key=lambda value: STRENGTH_RANK[value])
        identity = observation_identity(item.advisory_id, assets)
        fingerprint = material_fingerprint(item, assets)
        disposition = _disposition(item, strength)
        reason = None
        if recorded_verdicts.get(identity) == fingerprint:
            disposition, reason = "suppressed_recorded_verdict", "recorded not_affected verdict still valid"
        observations.append(Observation(
            identity=identity, advisory=item, assets=assets, match_strength=strength,  # type: ignore[arg-type]  # enum values
            disposition=disposition, suppression_reason=reason, material_fingerprint=fingerprint))  # type: ignore[arg-type]  # enum values
    return sorted(observations, key=lambda observation: observation.identity)
