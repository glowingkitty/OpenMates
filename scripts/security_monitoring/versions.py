"""Per-ecosystem version comparison and advisory range evaluation.

Comparators return None when a version cannot be parsed, so callers can treat
the result as "unknown" and stay conservative (an unknown version is never
reported as unaffected). Supported orderings: npm/crates/semver-like tags,
PEP 440 (via `packaging` when importable) and Debian/Ubuntu dpkg versions.
See specifications/architecture/security-monitoring/specification.yml
(security-monitoring.sources.hourly-deterministic).
"""

from __future__ import annotations

import re
from typing import Any, Callable, Literal, Sequence

try:  # PEP 440 ordering; absent packaging only makes PyPI comparisons unknown.
    from packaging.version import InvalidVersion, Version
except ImportError:  # pragma: no cover - exercised only on hosts without packaging
    Version = None  # type: ignore[assignment,misc]  # optional dependency marker
    InvalidVersion = ValueError  # type: ignore[assignment,misc]  # keeps except clauses valid

RangeResult = Literal["exact", "range", "not_affected", "unknown"]

_SEMVER_RE = re.compile(
    r"^[vV]?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-.]?([0-9A-Za-z][0-9A-Za-z.-]*))?(?:\+[0-9A-Za-z.-]+)?$"
)
_DIGITS = "0123456789"


def _semver_key(version: str) -> tuple[Any, ...] | None:
    match = _SEMVER_RE.match(version.strip())
    if not match:
        return None
    major, minor, patch, pre = match.groups()
    core = (int(major), int(minor or 0), int(patch or 0))
    if not pre:
        return (*core, 1, ())
    parts: list[tuple[int, Any]] = []
    for piece in pre.split("."):
        parts.append((0, int(piece)) if piece.isdigit() else (1, piece))
    return (*core, 0, tuple(parts))


def compare_semver(left: str, right: str) -> int | None:
    a, b = _semver_key(left), _semver_key(right)
    if a is None or b is None:
        return None
    return (a > b) - (a < b)


def compare_pep440(left: str, right: str) -> int | None:
    if Version is None:
        return None
    try:
        a, b = Version(left), Version(right)
    except InvalidVersion:
        return None
    return (a > b) - (a < b)


def _dpkg_order(char: str | None) -> int:
    if char is None or char in _DIGITS:
        return 0
    if char.isascii() and char.isalpha():
        return ord(char)
    if char == "~":
        return -1
    return ord(char) + 256


def _dpkg_verrevcmp(a: str, b: str) -> int:
    i = j = 0
    while i < len(a) or j < len(b):
        first_diff = 0
        while (i < len(a) and a[i] not in _DIGITS) or (j < len(b) and b[j] not in _DIGITS):
            ac = _dpkg_order(a[i] if i < len(a) else None)
            bc = _dpkg_order(b[j] if j < len(b) else None)
            if ac != bc:
                return ac - bc
            i += 1
            j += 1
        while i < len(a) and a[i] == "0":
            i += 1
        while j < len(b) and b[j] == "0":
            j += 1
        while i < len(a) and a[i] in _DIGITS and j < len(b) and b[j] in _DIGITS:
            if not first_diff:
                first_diff = ord(a[i]) - ord(b[j])
            i += 1
            j += 1
        if i < len(a) and a[i] in _DIGITS:
            return 1
        if j < len(b) and b[j] in _DIGITS:
            return -1
        if first_diff:
            return first_diff
    return 0


def _dpkg_parse(version: str) -> tuple[int, str, str] | None:
    text = version.strip()
    if not text or any(ch.isspace() for ch in text):
        return None
    epoch = 0
    if ":" in text:
        raw_epoch, text = text.split(":", 1)
        if not raw_epoch.isdigit():
            return None
        epoch = int(raw_epoch)
    upstream, revision = (text.rsplit("-", 1) if "-" in text else (text, ""))
    if not upstream or upstream[0] not in _DIGITS:
        return None
    return epoch, upstream, revision


def compare_dpkg(left: str, right: str) -> int | None:
    """Pure implementation of `dpkg --compare-versions` ordering."""
    a, b = _dpkg_parse(left), _dpkg_parse(right)
    if a is None or b is None:
        return None
    if a[0] != b[0]:
        return (a[0] > b[0]) - (a[0] < b[0])
    result = _dpkg_verrevcmp(a[1], b[1]) or _dpkg_verrevcmp(a[2], b[2])
    return (result > 0) - (result < 0)


def comparator_for(ecosystem: str) -> Callable[[str, str], int | None]:
    lowered = ecosystem.lower()
    if lowered in {"pypi", "pip"}:
        return compare_pep440
    if lowered.startswith(("ubuntu", "debian")):
        return compare_dpkg
    return compare_semver


def compare(ecosystem: str, left: str, right: str) -> int | None:
    if left == right:
        return 0
    return comparator_for(ecosystem)(left, right)


def _events_affected(ecosystem: str, version: str, events: Sequence[Any]) -> bool | None:
    """OSV event evaluation for one ordered SEMVER/ECOSYSTEM range."""
    affected = False
    for event in events:
        if not isinstance(event, dict):
            return None
        if "introduced" in event:
            introduced = str(event["introduced"])
            order = 1 if introduced == "0" else compare(ecosystem, version, introduced)
            if order is None:
                return None
            if order >= 0:
                affected = True
        elif "fixed" in event or "limit" in event:
            bound = str(event.get("fixed", event.get("limit")))
            order = compare(ecosystem, version, bound)
            if order is None:
                return None
            if order >= 0:
                affected = False
        elif "last_affected" in event:
            order = compare(ecosystem, version, str(event["last_affected"]))
            if order is None:
                return None
            if order > 0:
                affected = False
    return affected


_CONSTRAINT_RE = re.compile(r"(>=|<=|>|<|==|=|!=)?\s*v?([0-9][^\s,|]*)")


def _expression_affected(ecosystem: str, version: str, expression: str) -> bool | None:
    """GitHub-style `>= 1.0, < 1.2.3` (commas optional); `||` separates alternatives."""
    alternatives = [part.strip() for part in expression.split("||") if part.strip()]
    if not alternatives:
        return None
    unknown = False
    for alternative in alternatives:
        constraints = _CONSTRAINT_RE.findall(alternative)
        leftover = _CONSTRAINT_RE.sub("", alternative)
        if not constraints or re.sub(r"[\s,]|\[[^\]]*\]", "", leftover):
            return None
        holds = True
        for operator, bound in constraints:
            order = compare(ecosystem, version, bound)
            if order is None:
                unknown = True
                holds = False
                break
            checks = {">=": order >= 0, "<=": order <= 0, ">": order > 0, "<": order < 0,
                      "=": order == 0, "==": order == 0, "!=": order != 0}
            if not checks[operator or "="]:
                holds = False
                break
        if holds:
            return True
    return None if unknown else False


def _at_or_above_patched(ecosystem: str, version: str, patched: Sequence[str]) -> bool:
    """True only when every listed patched version compares and `version` is at or above the highest."""
    orders = [compare(ecosystem, version, str(bound)) for bound in patched if bound]
    return bool(orders) and all(order is not None and order >= 0 for order in orders)


def evaluate_affected(ecosystem: str, version: str | None, entry: dict[str, Any]) -> RangeResult:
    """Decide whether `version` falls inside one normalized affected entry.

    Entry keys: versions (explicit list), ranges (OSV ranges), range_expr
    (GitHub-style expression), fixed (list; implies `introduced 0`) and
    patched (versions at or above which the entry is not affected).
    """
    if not version:
        return "unknown"
    versions = entry.get("versions") or ()
    if version in versions:
        return "exact"
    result = _evaluate_ranges(ecosystem, version, entry, versions)
    if result == "range" and _at_or_above_patched(ecosystem, version, entry.get("patched") or ()):
        return "not_affected"  # upstream ranges are sometimes open-ended while a patched version is listed
    return result


def _evaluate_ranges(ecosystem: str, version: str, entry: dict[str, Any], versions: Sequence[Any]) -> RangeResult:
    saw_unknown = False
    evaluated = False
    for rng in entry.get("ranges") or ():
        if not isinstance(rng, dict) or str(rng.get("type", "")).upper() == "GIT":
            continue
        evaluated = True
        result = _events_affected(ecosystem, version, rng.get("events") or ())
        if result is None:
            saw_unknown = True
        elif result:
            return "range"
    expression = entry.get("range_expr")
    if isinstance(expression, str) and expression.strip():
        evaluated = True
        result = _expression_affected(ecosystem, version, expression)
        if result is None:
            saw_unknown = True
        elif result:
            return "range"
    fixed = [str(value) for value in entry.get("fixed") or () if value]
    if fixed and not evaluated:
        evaluated = True
        orders = [compare(ecosystem, version, bound) for bound in fixed]
        if any(order is None for order in orders):
            saw_unknown = True
        elif all(order < 0 for order in orders):  # type: ignore[operator]  # None excluded above
            return "range"
    if saw_unknown or (not evaluated and not versions):
        return "unknown"
    return "not_affected"
