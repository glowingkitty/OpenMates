"""Derive feature-overview cells from Specification assertions, tests and CI results.

A cell is one feature (or sub-feature) on one surface. Its status comes from the
evidence chain, never from a hand-written value:

    Specification assertion  ->  tests that declare it on that surface  ->  latest CI result

- An assertion "counts" on a surface when the registry requires it there
  (``required_applies_to``) or a test on that surface declares it.
- Assertion state per surface: ``failing`` (a test failed in its latest run),
  ``passing`` (a test passed, none failed), ``not_run`` (tests exist, no CI
  result in the snapshot) or ``missing`` (required, no test on that surface).
- Cell status: ``failing`` if any counted assertion fails; ``tested`` when all
  pass (``live`` when the feature is also on in production config);
  ``partial`` when some pass; ``not_run`` when tests exist but none ran.
  Without any test on the surface the cell shows the human intent from
  ``specifications/features.yml`` (implemented, in_progress, planned,
  unverified, not_planned).

Sub-features are named groups of assertion ids (exact ids or ``fnmatch`` globs).
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

INTENTS = ("implemented", "in_progress", "planned", "unverified", "not_planned")
DERIVED = ("live", "tested", "partial", "failing", "not_run")
STATUSES = ("live", "tested", "partial", "failing", "not_run", *INTENTS)
DONE = ("live", "tested")
# Assertion-index surface tags -> overview surfaces (path rules in classify_test refine these).
TAG_SURFACES = {
    "gui.web": "web", "gui.apple": "apple", "cli": "cli", "rest_api": "rest_api",
    "sdks.npm": "sdk_npm", "sdks.pip": "sdk_pypi",
}
# Order used by `gaps`: lower ranks first.
GAP_RANK = {"failing": 0, "partial": 1, "not_run": 2, "implemented": 3, "in_progress": 4, "planned": 5, "unverified": 6}


def classify_test(path: str, tag: str | None) -> tuple[str, str] | None:
    """Map one test file to (surface, "e2e" | "unit"), or None when it proves no product surface."""
    name = path.rsplit("/", 1)[-1]
    if path.startswith("apple/"):
        top = path.split("/")[1] if "/" in path else ""
        surface = "watchos" if "Watch" in top or name.startswith("Watch") else "apple"
        return surface, ("e2e" if "UITests" in top else "unit")
    if path.startswith("frontend/apps/web_app/tests/") and name.endswith(".spec.ts"):
        if name.startswith("cli-tui-") or "-tui-" in name or name.startswith("tui-"):
            return "tui", "e2e"
        if name.startswith("cli-"):
            return "cli", "e2e"
        surface = TAG_SURFACES.get(tag or "")
        return (surface, "e2e") if surface else None
    if "openmates-tui" in path or "/tui/" in path:
        return "tui", "unit"
    if path.startswith("frontend/packages/openmates-cli/"):
        return ("sdk_npm" if tag == "sdks.npm" else "cli"), "unit"
    if path.startswith("packages/openmates-python/"):
        return "sdk_pypi", "unit"
    surface = TAG_SURFACES.get(tag or "")
    return (surface, "unit") if surface else None


@dataclass
class Evidence:
    """Registry, assertion index and CI result snapshot, indexed for cell derivation."""

    required: dict[str, set[str]]  # assertion id -> surfaces it is required on
    tests: dict[str, dict[str, set[tuple[str, str]]]]  # assertion id -> surface -> (test path, test name)
    results: dict[str, dict[str, Any]]  # test path -> {result, date, commit, job}
    by_spec: dict[str, list[str]] = field(default_factory=dict)  # spec id -> assertion ids

    @classmethod
    def build(cls, registry: dict[str, Any], index: dict[str, Any], results: dict[str, Any]) -> "Evidence":
        required: dict[str, set[str]] = {}
        by_spec: dict[str, list[str]] = {}
        for assertion_id, data in (registry.get("assertions") or {}).items():
            required[assertion_id] = {TAG_SURFACES[t] for t in data.get("required_applies_to") or [] if t in TAG_SURFACES}
            spec_id = str(data.get("specification_id") or str(data.get("specification") or "").split("@", 1)[0])
            by_spec.setdefault(spec_id, []).append(assertion_id)
        tests: dict[str, dict[str, set[tuple[str, str]]]] = {}
        for assertion_id, data in (index.get("assertions") or {}).items():
            per_surface: dict[str, set[tuple[str, str]]] = {}
            for test in [*(data.get("direct_tests") or []), *(data.get("supporting_tests") or [])]:
                path = str(test.get("path") or "")
                mapped = classify_test(path, test.get("surface"))
                if mapped:
                    per_surface.setdefault(mapped[0], set()).add((path, str(test.get("name") or "")))
            tests[assertion_id] = per_surface
            required.setdefault(assertion_id, set())
        return cls(required=required, tests=tests, results=results or {}, by_spec=by_spec)

    def assertions_of(self, spec_ids: Iterable[str]) -> list[str]:
        return sorted({a for spec_id in spec_ids for a in self.by_spec.get(spec_id, [])})

    def match(self, patterns: Iterable[str]) -> list[str]:
        ids = sorted(self.required)
        return sorted({a for pattern in patterns for a in ids if fnmatch.fnmatchcase(a, pattern)})

    def case_result(self, path: str, name: str) -> str | None:
        """Latest result of one declared test; a failed file fails only its listed cases when known."""
        data = self.results.get(path)
        if not data:
            return None
        if data.get("result") == "failed" and data.get("failed") and name:
            return "failed" if any(_name_matches(name, failed) for failed in data["failed"]) else "passed"
        return data.get("result")

    def test_state(self, tests: Iterable[tuple[str, str]]) -> tuple[str, list[str]]:
        outcomes = {(path, name): self.case_result(path, name) for path, name in tests}
        failed = sorted(f"{path} › {name}" if name else path for (path, name), r in outcomes.items() if r == "failed")
        if failed:
            return "failing", failed
        if any(r in ("passed", "flaky") for r in outcomes.values()):
            return "passing", []
        return "not_run", []


def _name_matches(declared: str, reported: str) -> bool:
    """Declared test names may be templates (`${appId} renders`); reported names are concrete."""
    if declared == reported:
        return True
    if "${" not in declared:
        return False
    pattern = re.escape(declared)
    pattern = re.sub(r"\\\$\\\{[^}]*\\\}", ".+", pattern)
    return re.fullmatch(pattern, reported) is not None


def derive_cell(
    evidence: Evidence, assertion_ids: list[str], surface: str, intent: str | None,
    key_tests: list[str], on_prod: bool,
) -> dict[str, Any]:
    """Status and counts of one cell; see the module docstring for the rules."""
    states: dict[str, str] = {}
    failing_tests: set[str] = set()
    for assertion_id in assertion_ids:
        paths = evidence.tests.get(assertion_id, {}).get(surface, set())
        if paths:
            state, failed = evidence.test_state(paths)
            states[assertion_id] = state
            failing_tests.update(failed)
        elif surface in evidence.required.get(assertion_id, set()):
            states[assertion_id] = "missing"
    for path in key_tests:
        state, failed = evidence.test_state([(path, "")])
        states[f"key:{path}"] = state
        failing_tests.update(failed)
    counts = {name: sum(1 for s in states.values() if s == name) for name in ("passing", "failing", "not_run", "missing")}
    counts["counted"] = len(states)
    tested = counts["counted"] - counts["missing"]
    if counts["failing"]:
        status = "failing"
    elif tested and counts["passing"] == counts["counted"]:
        status = "live" if on_prod else "tested"
    elif counts["passing"]:
        status = "partial"
    elif tested:
        status = "not_run"
    else:
        status = intent or "unverified"
    cell: dict[str, Any] = {
        "status": status,
        "source": "tests" if status in DERIVED else "intent",
        "intent": intent,
        "assertions": counts,
    }
    if failing_tests:
        cell["failing_tests"] = sorted(failing_tests)
    if intent == "not_planned" and status in DERIVED:
        cell["conflict"] = f"marked not_planned, but tests on {surface} exist"
    elif intent == "not_planned" and counts["missing"]:
        cell["conflict"] = f"marked not_planned, but {counts['missing']} required assertion(s) apply to {surface}"
    return cell


def short_status(cell: dict[str, Any], labels: dict[str, str]) -> str:
    counts = cell.get("assertions") or {}
    label = labels[cell["status"]]
    if cell["status"] in DERIVED and counts.get("counted"):
        return f"{label} {counts['passing']}/{counts['counted']}"
    return label


def gaps(view: dict[str, Any], surface: str, kinds: tuple[str, ...]) -> list[dict[str, Any]]:
    """Every feature and sub-feature not done on `surface`, most urgent first."""
    kind_order = {kind: i for i, kind in enumerate(kinds)}
    rows: list[dict[str, Any]] = []

    def add(feature: dict[str, Any], sub: dict[str, Any] | None) -> None:
        owner = sub or feature
        cell = owner["surfaces"].get(surface)
        if not cell or cell["status"] in DONE or cell["status"] == "not_planned":
            return
        web = (owner["surfaces"].get("web") or {}).get("status", "")
        rows.append({
            "feature": feature["id"], "subfeature": sub["id"] if sub else None,
            "name": f"{feature['name']} › {sub['name']}" if sub else feature["name"],
            "status": cell["status"], "assertions": cell.get("assertions") or {},
            "failing_tests": cell.get("failing_tests") or [], "web": web,
            "sort": (GAP_RANK.get(cell["status"], 9), 0 if web in DONE else 1 if web == "partial" else 2,
                     kind_order.get(feature["kind"], 9), -(cell.get("assertions") or {}).get("missing", 0),
                     feature["id"], sub["id"] if sub else ""),
        })

    for feature in view["features"]:
        add(feature, None)
        for sub in feature.get("subfeatures") or []:
            add(feature, sub)
    rows.sort(key=lambda row: row["sort"])
    for row in rows:
        del row["sort"]
    return rows


def render_gaps(rows: list[dict[str, Any]], surface: str, as_of: str | None) -> str:
    lines = [f"Gaps on {surface} (results as of {as_of or 'never'}): {len(rows)} feature/sub-feature rows", ""]
    for position, row in enumerate(rows, 1):
        counts = row["assertions"]
        coverage = f"{counts.get('passing', 0)}/{counts.get('counted', 0)} passing" if counts.get("counted") else "no assertions"
        extra = f" · missing tests {counts['missing']}" if counts.get("missing") else ""
        failing = f" · failing: {', '.join(p.rsplit('/', 1)[-1] for p in row['failing_tests'][:3])}" if row["failing_tests"] else ""
        lines.append(f"{position:>3}. [{row['status']}] {row['name']} — {coverage}{extra} · web {row['web'] or '-'}{failing}")
    return "\n".join(lines) + "\n"


def subfeature_errors(label: str, subs: Any, evidence: Evidence, surfaces: tuple[str, ...]) -> list[str]:
    """Validate sub-feature definitions of one entry."""
    if subs is None:
        return []
    if not isinstance(subs, list):
        return [f"{label}: subfeatures must be a list"]
    errors: list[str] = []
    seen: set[str] = set()
    for position, sub in enumerate(subs):
        if not isinstance(sub, dict):
            errors.append(f"{label}: subfeatures[{position}] must be a mapping")
            continue
        sub_label = f"{label} sub-feature '{sub.get('id') or position}'"
        unknown = set(sub) - {"id", "name", "description", "assertions", "surfaces", "notes"}
        if unknown:
            errors.append(f"{sub_label}: unknown keys {sorted(unknown)}")
        if not sub.get("id") or sub["id"] in seen:
            errors.append(f"{sub_label}: id is required and must be unique")
        seen.add(str(sub.get("id")))
        if not str(sub.get("name") or "").strip():
            errors.append(f"{sub_label}: name is required")
        for pattern in sub.get("assertions") or []:
            if not evidence.match([pattern]):
                errors.append(f"{sub_label}: assertion pattern '{pattern}' matches no assertion")
        for surface, intent in (sub.get("surfaces") or {}).items():
            if surface not in surfaces or intent not in INTENTS:
                errors.append(f"{sub_label}: surface intent {surface}={intent} must use a known surface and one of {list(INTENTS)}")
    return errors

