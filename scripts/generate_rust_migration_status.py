#!/usr/bin/env python3
"""Generate docs/architecture/platforms/rust-migration-status.md.

Deterministic and offline: the report is derived only from committed files
(config/sdk-capabilities.json, config/cli-command-catalog.json, the shared Rust
core Worker unit registry and its sources). `--check` fails when the committed
document differs from the generator output, like sync_rust_cli_assets.py.

Architecture: docs/architecture/platforms/rust-migration-status.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path("docs/architecture/platforms/rust-migration-status.md")
MIGRATION_DIR = Path("docs/migration/rust")
SDK_CAPABILITIES = Path("config/sdk-capabilities.json")
CLI_CATALOG = Path("config/cli-command-catalog.json")
UNIT_REGISTRY = Path("frontend/apps/web_app/src/lib/rustCore/shared/sharedWorkerUnits.ts")
UNIT_PROTOCOL = Path("frontend/packages/ui/src/services/rustCore/host/sharedWorkerProtocol.ts")
WEB_SHARED_DIR = UNIT_REGISTRY.parent
UI_ALIAS = "@openmates/ui/src/"
UI_SRC = Path("frontend/packages/ui/src")
WEB_SPECS = Path("frontend/apps/web_app/tests")
DIFFERENTIAL_PREFIX = "Differential-verified against the npm CLI"
# Bumped by hand when this generator's layout or definitions change; the report
# content itself only depends on the committed inputs.
LAST_VERIFIED = "2026-11-07"
FRONTMATTER = f"""---
status: active
doc_type: reference
audience:
- contributors
- technical-users
last_verified: {LAST_VERIFIED}
key_files:
- scripts/generate_rust_migration_status.py
- scripts/rust_migration_yaml.py
- docs/migration/rust/overview.yml
- docs/migration/rust/performance-history.yml
- config/sdk-capabilities.json
- config/cli-command-catalog.json
- {UNIT_REGISTRY}
claims:
- id: arch-platforms-rust-migration-status-fresh
  type: unit
  claim: The committed Rust migration status equals the output of its generator for the current inputs.
  source:
  - scripts/generate_rust_migration_status.py
  test:
    file: scripts/tests/test_rust_migration_status.py
    command: python3 -m pytest scripts/tests/test_rust_migration_status.py
    assertion: arch-platforms-rust-migration-status-fresh
  verified: '{LAST_VERIFIED}'
---
"""


def load_json(relative: Path) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def cell(text: str, limit: int = 0) -> str:
    """Make text safe for one Markdown table cell, optionally truncated."""
    flat = re.sub(r"\s+", " ", str(text)).strip().replace("|", "\\|")
    if limit and len(flat) > limit:
        flat = flat[: limit - 3].rstrip() + "..."
    return flat


def table(headers: list[str], rows: list[list[object]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return lines


def pct(part: int, whole: int) -> str:
    return f"{part} / {whole} ({100 * part / whole:.0f}%)" if whole else f"{part} / 0"


# --- SDK ---------------------------------------------------------------------

STATUS_CODE = {"implemented": "I", "partial": "P", "missing": "M"}


def sdk_metrics(data: dict) -> list[dict]:
    rows = []
    capabilities = data["capabilities"]
    for language in data["languages"]:
        entries = [cap["languages"][language] for cap in capabilities]
        rows.append(
            {
                "language": language,
                "total": len(entries),
                "api": sum(1 for e in entries if e["api"]),
                "conformance": sum(1 for e in entries if e["conformance"]),
                "implemented": sum(1 for e in entries if e["status"] == "implemented"),
                "partial": sum(1 for e in entries if e["status"] == "partial"),
                "partial_one_gap": sum(1 for e in entries if e["status"] == "partial" and len(e["gaps"]) == 1),
                "missing": sum(1 for e in entries if e["status"] == "missing"),
            }
        )
    return rows


def matrix_cell(entry: dict) -> str:
    vectors = "vec" if entry["conformance"] else "-"
    return f"{STATUS_CODE.get(entry['status'], entry['status'])} · {vectors} · {len(entry['gaps'])}"


def sdk_section(data: dict) -> list[str]:
    metrics = sdk_metrics(data)
    total = metrics[0]["total"]
    with_fixture = sum(1 for cap in data["capabilities"] if "fixture" in cap)
    lines = ["## SDK capabilities", "", f"Source: `{SDK_CAPABILITIES}` ({total} capabilities, schema {data['schemaVersion']}).", ""]
    lines += table(
        ["Language", "(a) Public API", "(b) Shared conformance", "(c) Implemented", "(d) Partial, one gap left", "Partial total", "Missing"],
        [
            [
                f"**{m['language']}**",
                pct(m["api"], m["total"]),
                pct(m["conformance"], m["total"]),
                pct(m["implemented"], m["total"]),
                pct(m["partial_one_gap"], m["total"]),
                m["partial"],
                m["missing"],
            ]
            for m in metrics
        ],
    )
    lines += [
        "",
        f"{with_fixture} of {total} capabilities carry a shared conformance fixture file; "
        "the conformance column counts capabilities whose conformance flag is set for that language.",
        "",
        "### Per-capability matrix",
        "",
        "Each cell is `status · vectors · gaps` (see the legend). Capabilities are sorted by domain, then id.",
        "",
    ]
    rows = []
    for cap in sorted(data["capabilities"], key=lambda c: (c["domain"], c["id"])):
        rows.append([f"`{cap['id']}`", cap["domain"]] + [matrix_cell(cap["languages"][lang]) for lang in ("rust", "npm", "python")])
    lines += table(["Capability", "Domain", "Rust", "npm", "Python"], rows)
    lines += ["", "### Remaining Rust gaps", "", "First recorded gap per capability whose Rust entry is not implemented (full text in the source file).", ""]
    gap_rows = []
    for cap in sorted(data["capabilities"], key=lambda c: (c["domain"], c["id"])):
        entry = cap["languages"]["rust"]
        if entry["gaps"]:
            gap_rows.append([f"`{cap['id']}`", len(entry["gaps"]), cell(entry["gaps"][0], 200)])
    lines += table(["Capability", "Gaps", "First gap"], gap_rows)
    return lines


# --- CLI ---------------------------------------------------------------------


def cli_section(catalog: dict) -> list[str]:
    commands = catalog["commands"]
    statuses = Counter(c["implementation"]["status"] for c in commands)
    handler = sum(1 for c in commands if c["implementation"].get("handler"))
    differential = [c for c in commands if any(g.startswith(DIFFERENTIAL_PREFIX) for g in c["gaps"])]
    e2e_evidence = sum(1 for c in commands if c.get("evidence"))
    platform = {os_name: Counter(c["platforms"][os_name] for c in commands) for os_name in ("linux", "macos", "windows")}
    total = len(commands)
    lines = ["## CLI commands", "", f"Source: `{CLI_CATALOG}` (TypeScript CLI {catalog['source_version']}, {total} command records, {len(catalog['flags'])} flags).", ""]
    lines += table(
        ["Metric", "Count"],
        [
            ["Commands in the catalog", total],
            ["Status `implemented`", statuses.get("implemented", 0)],
            ["Status `partial` (native handler exists, parity not complete)", statuses.get("partial", 0)],
            ["Status `unsupported` (no native handler)", statuses.get("unsupported", 0)],
            ["With a named native handler", pct(handler, total)],
            ["Differential-verified against the npm CLI", pct(len(differential), total)],
            ["With recorded real-CI E2E evidence", pct(e2e_evidence, total)],
            ["Linux verified", pct(platform["linux"].get("verified", 0), total)],
            ["macOS verified", pct(platform["macos"].get("verified", 0), total)],
            ["Windows verified (testing waived)", pct(platform["windows"].get("verified", 0), total)],
        ],
    )
    lines += ["", "### By command group", "", "Largest groups first. `Top gap` is the most common first gap text in the group.", ""]
    groups: dict[str, list[dict]] = defaultdict(list)
    for command in commands:
        groups[command["path"][0]].append(command)
    rows = []
    for name, members in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        counts = Counter(m["implementation"]["status"] for m in members)
        diff = sum(1 for m in members if any(g.startswith(DIFFERENTIAL_PREFIX) for g in m["gaps"]))
        linux = sum(1 for m in members if m["platforms"]["linux"] == "verified")
        first_gaps = Counter(m["gaps"][0] for m in members if m["gaps"])
        top_gap = cell(sorted(first_gaps.items(), key=lambda kv: (-kv[1], kv[0]))[0][0], 110) if first_gaps else "-"
        rows.append([f"`{name}`", len(members), counts.get("implemented", 0), counts.get("partial", 0), counts.get("unsupported", 0), diff, linux, top_gap])
    lines += table(["Group", "Commands", "Implemented", "Partial", "Unsupported", "Differential", "Linux verified", "Top gap"], rows)
    return lines


# --- Web shared Worker units ---------------------------------------------------


def resolve_import(path: str) -> Path | None:
    base = UI_SRC / path[len(UI_ALIAS):] if path.startswith(UI_ALIAS) else WEB_SHARED_DIR / path
    candidate = base.with_suffix(".ts")
    return candidate if (ROOT / candidate).is_file() else None


def parse_installers(source: str) -> dict[str, Path | None]:
    """Map each registered namespace to the file that holds its installer."""
    named = {m.group(1): m.group(2) for m in re.finditer(r"import \{ (\w+) \} from '([^']+)'", source)}
    body = source.split("Object.freeze({", 1)[1]
    installers: dict[str, Path | None] = {}
    for match in re.finditer(r"^\s*(\w+):\s*(.+?),?\s*$", body, re.MULTILINE):
        namespace, expression = match.groups()
        lazy = re.search(r"import\('([^']+)'\)", expression)
        reference = named.get(expression.strip().rstrip(","))
        target = lazy.group(1) if lazy else reference
        installers[namespace] = resolve_import(target) if target else None
    return installers


def header_summary(path: Path) -> str:
    """Leading comment of the file as sentences, minus the boilerplate opener."""
    words: list[str] = []
    for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("/**") or stripped.startswith("/*"):
            stripped = stripped.lstrip("/*").strip()
        elif stripped.startswith("*/") or stripped.startswith("import "):
            break
        elif not stripped.startswith(("*", "//")):
            if words:
                break
            continue
        words.append(re.sub(r"^(\*|//)\s?", "", stripped).strip())
    sentences = re.split(r"(?<=\.)\s+", " ".join(w for w in words if w))
    described = [x for x in sentences if "of the shared Rust core Worker" not in x] or sentences
    return cell(" ".join(described[:2]), 330)


def unit_tests(namespace_dir: Path, installer: Path) -> list[str]:
    """Unit tests under the unit's folder, or shared tests that import it."""
    found = set()
    tests_dir = UI_SRC / "services/rustCore/__tests__"
    stem = installer.stem
    imports = re.compile(rf"from\s+['\"][^'\"]*(?:/{re.escape(namespace_dir.name)}/|/{re.escape(stem)}['\"])")
    for folder in (tests_dir, namespace_dir / "__tests__"):
        if not (ROOT / folder).is_dir():
            continue
        for test in sorted((ROOT / folder).glob("*.test.*")):
            own = folder != tests_dir
            text = test.read_text(encoding="utf-8", errors="replace")
            if own or imports.search(text):
                found.add(test.relative_to(ROOT).as_posix())
    return sorted(found)


def fallback_state(namespace_dir: Path) -> str:
    pattern = re.compile(r"no\s+(?:typescript\s+|ts\s+)?fallback", re.IGNORECASE)
    files = 0
    for source in sorted((ROOT / namespace_dir).glob("*.ts")):
        text = re.sub(r"\n\s*(?:\*|//)\s?", " ", source.read_text(encoding="utf-8"))
        if pattern.search(text):
            files += 1
    return f"none declared ({files} file{'s' if files != 1 else ''})" if files else "not declared in unit sources"


def web_section() -> list[str]:
    installers = parse_installers((ROOT / UNIT_REGISTRY).read_text(encoding="utf-8"))
    protocol = (ROOT / UNIT_PROTOCOL).read_text(encoding="utf-8")
    namespaces = re.findall(r"'(\w+)'", re.search(r"SHARED_NAMESPACES = \[(.*?)\]", protocol, re.S).group(1))
    pre_bind = set(re.findall(r"'(\w+)'", re.search(r"PRE_BIND_NAMESPACES.*?\[(.*?)\]", protocol, re.S).group(1)))
    installed = [ns for ns in namespaces if installers.get(ns)]
    planned = [ns for ns in namespaces if ns not in installed]
    specs = sorted(p.name for p in (ROOT / WEB_SPECS).glob("web-rust-core-*.spec.ts"))
    lines = [
        "## Web shared Rust core Worker units",
        "",
        f"Sources: `{UNIT_REGISTRY}` (installed units) and `{UNIT_PROTOCOL}` (namespace allowlist).",
        "",
    ]
    lines += table(
        ["Metric", "Count"],
        [
            ["Namespaces in the allowlist", len(namespaces)],
            ["Units installed (installer registered)", pct(len(installed), len(namespaces))],
            ["Units planned (namespace reserved, no installer)", pct(len(planned), len(namespaces))],
        ],
    )
    lines += ["", f"Planned: {', '.join(f'`{ns}`' for ns in planned) or 'none'}. A namespace without an installer is refused as `unit_unavailable`.", ""]
    rows = []
    for namespace in installed:
        installer = installers[namespace]
        namespace_dir = installer.parent
        tests = unit_tests(namespace_dir, installer)
        rows.append(
            [
                f"`{namespace}`",
                "yes" if namespace in pre_bind else "no",
                header_summary(installer),
                fallback_state(namespace_dir),
                f"`{installer.as_posix()}`",
                ", ".join(f"`{Path(t).name}`" for t in tests) or "-",
            ]
        )
    for namespace in planned:
        rows.append([f"`{namespace}`", "yes" if namespace in pre_bind else "no", "Planned; no installer yet.", "-", "-", "-"])
    lines += table(["Unit", "Pre-bind", "What moves to Rust (from the unit header)", "TypeScript fallback", "Installer", "Unit tests"], rows)
    lines += [
        "",
        "All units run only in builds with `VITE_OPENMATES_RUST_CORE=1`; with the flag off the original TypeScript path is unchanged.",
        f"Web Rust core E2E specs in `{WEB_SPECS}`: {', '.join(f'`{s}`' for s in specs)}.",
    ]
    return lines


# --- Performance -----------------------------------------------------------------


def overview_section() -> list[str]:
    """Area table read from the structured YAML (the single source for the numbers)."""
    overview = yaml.safe_load((ROOT / MIGRATION_DIR / "overview.yml").read_text(encoding="utf-8"))
    rows = [[a["priority_rank"], f"`{a['id']}`", a["title"], f"{a['done']} / {a['total']} ({a['percent']}%)", a["partial"], a["missing"], f"`{a['file']}`"] for a in overview["areas"]]
    return [
        "## Area overview",
        "",
        f"Read from `{MIGRATION_DIR}/overview.yml` (machine-readable; sub-files hold the detail). Priority 1 is the web app and shared client code, 2 the CLI, 3 the SDKs. {overview['formula']}",
        "",
        *table(["Priority", "Area", "Scope", "Done", "Partial", "Missing", "Detail file"], rows),
    ]


def perf_section() -> list[str]:
    history = yaml.safe_load((ROOT / MIGRATION_DIR / "performance-history.yml").read_text(encoding="utf-8"))
    latest: dict[str, dict] = {}
    for entry in history["measurements"]:
        if entry["verdict"] not in ("invalid_measurement", "unverified"):
            latest[entry["flow"]] = entry
    rows = []
    for flow, entry in sorted(latest.items()):
        ci = f"[{entry['ci95'][0]}, {entry['ci95'][1]}]" if entry["ci95"] else "-"
        rows.append([f"`{flow}`", entry["date"], f"{entry['value_kind']} {entry['value'] if entry['value'] is not None else '-'}", ci, entry["n_pairs"] or "-", entry["verdict"], entry["confidence"]])
    return [
        "## Performance verdicts",
        "",
        f"The measurement log is `{MIGRATION_DIR}/performance-history.yml` (append-only; add entries with `scripts/record_perf_measurement.py`). Latest gate-relevant entry per flow:",
        "",
        *table(["Flow", "Date", "Value", "95% CI", "Pairs", "Verdict", "Confidence"], rows),
        "",
        "- Budget and method: `.claude/rules/cli-sdk.md` (web Rust performance gate; paired, interleaved, at least 12 pairs).",
        "- `uncertain` entries come from lane summaries without a traceable CI run; see the log for notes.",
    ]


# --- Document ----------------------------------------------------------------


def legend_section() -> list[str]:
    return [
        "## Legend",
        "",
        "- **implemented**: public API exists and cross-language conformance and validation are established.",
        "- **partial**: mostly means the API exists but cross-language conformance or validation is not yet established; the gap list says what is missing. It does not mean half-written code.",
        "- **missing**: no public API in that language.",
        "- **(a) Public API**: the capability lists at least one public API symbol for the language.",
        "- **(b) Shared conformance**: the capability's conformance flag is set, meaning shared vectors run for that language.",
        "- **(c) Implemented**: status `implemented`. Never read this number alone: compare it with (a) and (b).",
        "- **(d) Partial, one gap left**: status `partial` with exactly one recorded gap, so closest to implemented.",
        "- **Matrix cell** `status · vectors · gaps`: status is `I` implemented, `P` partial or `M` missing; vectors is `vec` when conformance is set, else `-`; gaps is the number of recorded gaps.",
        "- **CLI differential-verified**: the command's gap list records a run that matched the npm CLI on the isolated CI backend (exit code, normalized JSON stdout and stderr class). Platform columns count only independently verified platforms.",
        "- **Web unit tests**: test files that import the unit's folder or installer; vector tests that only read fixtures may be missing from the list.",
        "- **Web installed / planned**: installed units have a registered installer; planned namespaces are reserved in the allowlist.",
    ]


def render() -> str:
    sdk = load_json(SDK_CAPABILITIES)
    catalog = load_json(CLI_CATALOG)
    sections = [
        ["# Rust migration status", "", "> Generated by `scripts/generate_rust_migration_status.py` from committed sources. Do not edit by hand; run `python3 scripts/generate_rust_migration_status.py` to refresh and `--check` to verify.", ""],
        ["The Rust migration target is described in [Platform Architecture](README.md). The structured, deterministic source of the numbers is [docs/migration/rust/](../../migration/rust/overview.yml). This report shows how far each surface has actually come, with several side-by-side numbers so that a single \"implemented\" count is never the whole story."],
        overview_section(),
        legend_section(),
        sdk_section(sdk),
        cli_section(catalog),
        web_section(),
        perf_section(),
    ]
    return FRONTMATTER + "\n" + "\n\n".join("\n".join(section) for section in sections) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when the committed document is stale")
    args = parser.parse_args()
    expected = render()
    target = ROOT / OUTPUT
    if args.check:
        if not target.is_file() or target.read_text(encoding="utf-8") != expected:
            print(f"{OUTPUT} is stale; run python3 scripts/generate_rust_migration_status.py", file=sys.stderr)
            return 1
        return 0
    target.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
