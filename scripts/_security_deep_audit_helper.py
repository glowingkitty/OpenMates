#!/usr/bin/env python3
"""
scripts/_security_deep_audit_helper.py

Agent-based deep security audit orchestrator.

For each folder defined in security-deep-audit-folders.yml:
1. Creates a git worktree (isolated repo copy)
2. Spawns a Claude session that runs haiku subagents (5 at a time)
3. Each agent starts from one file, traces security issues across the codebase
4. Each agent writes its own YAML findings file
5. After all folders complete, merges and deduplicates findings
6. Copies results to main repo's security-audit/ (gitignored)
7. Cleans up the worktree

Not intended to be called directly; use security-deep-audit.sh.
"""

import os
import shutil
import subprocess
import sys
import time
import yaml as pyyaml
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _claude_utils import run_claude_session
from _nightly_report import write_nightly_report


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# How many subagents to run in parallel per batch
AGENTS_PER_BATCH = 5

# Max files per folder session (alphabetical, capped)
MAX_FILES_PER_FOLDER = 15

# Default file extensions to audit
DEFAULT_EXTENSIONS = {".ts", ".py", ".svelte"}

# Skip patterns (substrings in path)
SKIP_PATTERNS = [
    "__tests__",
    ".test.",
    ".spec.",
    "node_modules",
    ".generated.",
    ".preview.",
    ".d.ts",
    "i18n/locales",
    "i18n/sources",
]

# Output directory name (relative to project root)
OUTPUT_DIR = "security-audit"

# Timeout per folder session (seconds) — 30 min
SESSION_TIMEOUT = 1800

# Priority levels and their numeric values (for filtering)
PRIORITY_LEVELS = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# Worktree base path
WORKTREE_BASE = "/tmp/openmates-deep-audit"


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_folder_config(script_dir: str) -> list[dict]:
    """Load folder configuration from YAML file."""
    config_path = Path(script_dir) / "security-deep-audit-folders.yml"
    if not config_path.is_file():
        print(f"[deep-audit] ERROR: Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        config = pyyaml.safe_load(f)

    return config.get("folders", [])


def _filter_folders(
    folders: list[dict], priority_filter: str, single_folder: str
) -> list[dict]:
    """Filter folders by priority or single folder override."""
    if single_folder:
        return [f for f in folders if f["path"] == single_folder]

    if priority_filter:
        max_level = PRIORITY_LEVELS.get(priority_filter, 2)
        return [
            f for f in folders
            if PRIORITY_LEVELS.get(f.get("priority", "medium"), 2) <= max_level
        ]

    return folders


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _find_files(project_root: str, folder_config: dict) -> list[str]:
    """Find auditable source files in a folder (non-recursive)."""
    folder = folder_config["path"]
    full_path = Path(project_root) / folder
    if not full_path.is_dir():
        return []

    # Use custom extensions if specified, otherwise defaults
    extensions = set(folder_config.get("extensions", [])) or DEFAULT_EXTENSIONS
    file_patterns = folder_config.get("file_patterns", [])

    files = []
    for f in sorted(full_path.iterdir()):
        if not f.is_file():
            continue

        rel = str(f.relative_to(project_root))

        # Check skip patterns
        if any(skip in rel for skip in SKIP_PATTERNS):
            continue

        # Check file patterns (if specified, only match those)
        if file_patterns:
            if any(pattern in f.name for pattern in file_patterns):
                files.append(rel)
            continue

        # Check extensions
        if f.suffix in extensions:
            files.append(rel)

    return files[:MAX_FILES_PER_FOLDER]


# ---------------------------------------------------------------------------
# Worktree management
# ---------------------------------------------------------------------------

def _create_worktree(project_root: str) -> str:
    """Create a temporary git worktree for the audit."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    worktree_path = f"{WORKTREE_BASE}-{today}"

    # Clean up any existing worktree at this path
    if Path(worktree_path).exists():
        print(f"[deep-audit] Cleaning up existing worktree at {worktree_path}")
        subprocess.run(
            ["git", "-C", project_root, "worktree", "remove", "--force", worktree_path],
            capture_output=True, timeout=30,
        )
        if Path(worktree_path).exists():
            shutil.rmtree(worktree_path, ignore_errors=True)

    # Create new worktree from current HEAD
    result = subprocess.run(
        ["git", "-C", project_root, "worktree", "add", "--detach", worktree_path, "HEAD"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        print(f"[deep-audit] ERROR: Failed to create worktree: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    print(f"[deep-audit] Worktree created at {worktree_path}")
    return worktree_path


def _cleanup_worktree(project_root: str, worktree_path: str) -> None:
    """Remove the temporary worktree."""
    try:
        subprocess.run(
            ["git", "-C", project_root, "worktree", "remove", "--force", worktree_path],
            capture_output=True, timeout=30,
        )
        print(f"[deep-audit] Worktree removed: {worktree_path}")
    except Exception as e:
        print(f"[deep-audit] WARNING: Failed to remove worktree: {e}", file=sys.stderr)
        # Try direct removal as fallback
        shutil.rmtree(worktree_path, ignore_errors=True)


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def _build_folder_prompt(folder: str, files: list[str], output_base: str) -> str:
    """Build the prompt for a folder session that spawns per-file agents."""
    file_entries = []
    for f in files:
        safe_name = Path(f).stem
        output_path = f"{output_base}/{safe_name}.yml"
        file_entries.append(f"  - file: {f}\n    output: {output_path}")

    file_list = "\n".join(file_entries)

    return f"""You are orchestrating a deep security audit of: {folder}

## Your task

Spawn subagents to audit each file below. Each agent investigates security
issues starting from its entry file, but traces imports and data flows across
the ENTIRE codebase.

## Files to audit

{file_list}

## Execution rules

1. Spawn agents in batches of {AGENTS_PER_BATCH} using the Agent tool with model: "haiku"
2. Wait for each batch to complete before starting the next
3. Each agent MUST write its findings to the specified output path using the Write tool

## Agent prompt template

For each file, use this prompt (replace FILE_PATH and OUTPUT_PATH):

---
You are a security researcher auditing a production codebase.
Your ENTRY POINT is FILE_PATH — start here but follow the code wherever it leads.

Instructions:
1. Read the entry file thoroughly
2. Follow imports, trace data flows, check callers and callees
3. Look for: cryptographic weaknesses, key management issues, race conditions,
   information leakage, timing attacks, error handling that leaks secrets,
   insecure defaults, missing validation, injection vulnerabilities (SQL, XSS,
   SSRF, command injection), authentication/authorization bypasses, path traversal,
   improper access control, sensitive data exposure
4. For each finding, trace the full attack path across files
5. Be realistic about severity — not everything is critical

IMPORTANT: You are READ-ONLY. Do not modify any source files.

After your research, write your findings to OUTPUT_PATH using the Write tool.
The file MUST be valid YAML in exactly this format:

```yaml
entry_file: FILE_PATH
findings:
  - severity: critical | high | medium | low | info
    category: crypto | auth | injection | info-leak | race-condition | validation | config | ssrf | access-control
    title: "Short descriptive title"
    attack_path:
      - file: path/to/file.ts
        line: 42
        role: "What happens here in the attack chain"
    impact: "What an attacker could achieve"
    exploitability: "trivial | moderate | difficult | theoretical"
    recommendation: "How to fix it"
    files_examined:
      - list of all files you read
```

If you find no issues, write: `entry_file: FILE_PATH\\nfindings: []`
Only report REAL findings with evidence in the code. No speculation.
---

4. After all agents complete, output a summary line:
   "Audit complete: X files audited, Y findings total"
"""


# ---------------------------------------------------------------------------
# Session runner
# ---------------------------------------------------------------------------

def _run_folder_session(
    worktree_path: str, folder: str, files: list[str]
) -> tuple[int, str | None]:
    """Run a single folder audit session in the worktree."""
    folder_slug = folder.replace("/", "_")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"deep-audit-{folder_slug}-{today}"

    # Output directory for this folder's findings
    output_base = f"{OUTPUT_DIR}/findings/{folder_slug}"

    # Create output dir in worktree
    output_dir = Path(worktree_path) / output_base
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt = _build_folder_prompt(folder, files, output_base)

    print(f"[deep-audit] Starting: {folder} ({len(files)} files)")

    returncode, session_id = run_claude_session(
        prompt=prompt,
        session_title=title,
        project_root=worktree_path,
        log_prefix=f"[deep-audit:{folder_slug}]",
        agent=None,  # needs Write tool for YAML output
        timeout=SESSION_TIMEOUT,
        job_type=None,  # no individual email per folder
        linear_task=False,
        use_zellij=False,
        model="haiku",
    )

    return returncode, session_id


# ---------------------------------------------------------------------------
# Results handling
# ---------------------------------------------------------------------------

def _copy_results(worktree_path: str, project_root: str) -> int:
    """Copy findings from worktree to main repo. Returns file count."""
    src = Path(worktree_path) / OUTPUT_DIR / "findings"
    dst = Path(project_root) / OUTPUT_DIR / "findings"

    if not src.exists():
        print("[deep-audit] WARNING: No findings directory in worktree")
        return 0

    # Clear previous findings
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)

    # Copy all yml files
    count = 0
    for yml_file in src.rglob("*.yml"):
        rel = yml_file.relative_to(src)
        dest_file = dst / rel
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(yml_file, dest_file)
        count += 1

    print(f"[deep-audit] Copied {count} finding files to {dst}")
    return count


def _merge_findings(project_root: str) -> dict:
    """Merge all per-file YAML findings into a single report."""
    findings_dir = Path(project_root) / OUTPUT_DIR / "findings"
    merged = {
        "audit_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "folders_audited": [],
        "files_audited": 0,
        "total_findings": 0,
        "findings_by_severity": {
            "critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0
        },
        "all_findings": [],
    }

    for folder_dir in sorted(findings_dir.iterdir()):
        if not folder_dir.is_dir():
            continue

        folder_name = folder_dir.name.replace("_", "/")
        merged["folders_audited"].append(folder_name)

        for yml_file in sorted(folder_dir.glob("*.yml")):
            merged["files_audited"] += 1
            try:
                with open(yml_file) as f:
                    data = pyyaml.safe_load(f)
                if not data or not isinstance(data, dict):
                    continue

                entry_file = data.get("entry_file", yml_file.stem)
                for finding in data.get("findings", []):
                    if not isinstance(finding, dict):
                        continue
                    finding["entry_file"] = entry_file
                    severity = finding.get("severity", "info").lower()
                    if severity in merged["findings_by_severity"]:
                        merged["findings_by_severity"][severity] += 1
                    merged["total_findings"] += 1
                    merged["all_findings"].append(finding)

            except Exception as e:
                print(
                    f"[deep-audit] WARNING: could not parse {yml_file}: {e}",
                    file=sys.stderr,
                )

    # Write merged report
    report_path = Path(project_root) / OUTPUT_DIR / "merged-report.yml"
    with open(report_path, "w") as f:
        pyyaml.dump(merged, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"[deep-audit] Merged report: {report_path}")
    print(f"[deep-audit]   Files audited: {merged['files_audited']}")
    print(f"[deep-audit]   Total findings: {merged['total_findings']}")
    print(f"[deep-audit]   By severity: {merged['findings_by_severity']}")

    return merged


def _deduplicate_findings(project_root: str) -> dict:
    """Deduplicate merged findings by title similarity + file overlap."""
    report_path = Path(project_root) / OUTPUT_DIR / "merged-report.yml"
    if not report_path.is_file():
        return {}

    with open(report_path) as f:
        data = pyyaml.safe_load(f)

    if not data or not data.get("all_findings"):
        return data or {}

    seen: list[tuple[str, set]] = []
    unique = []
    duplicates = 0

    for finding in data["all_findings"]:
        title = finding.get("title", "").lower().strip()
        files = set(finding.get("files_examined", []))

        is_dup = False
        for seen_title, seen_files in seen:
            # Exact or substring title match
            if title == seen_title or title in seen_title or seen_title in title:
                is_dup = True
                break
            # High file overlap + shared title words
            if files and seen_files:
                intersection = files & seen_files
                union = files | seen_files
                if union and len(intersection) / len(union) > 0.6:
                    title_words = set(title.split())
                    seen_words = set(seen_title.split())
                    if len(title_words & seen_words) >= 2:
                        is_dup = True
                        break

        if is_dup:
            duplicates += 1
        else:
            unique.append(finding)
            seen.append((title, files))

    # Update report
    data["all_findings"] = unique
    data["total_findings"] = len(unique)
    data["duplicates_removed"] = duplicates
    data["findings_by_severity"] = {
        "critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0
    }
    for f in unique:
        sev = f.get("severity", "info").lower()
        if sev in data["findings_by_severity"]:
            data["findings_by_severity"][sev] += 1

    deduped_path = Path(project_root) / OUTPUT_DIR / "deduplicated-report.yml"
    with open(deduped_path, "w") as f:
        pyyaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"[deep-audit] Deduplicated: {duplicates} removed, {len(unique)} unique findings")
    return data


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    project_root = os.environ.get("PROJECT_ROOT", "")
    single_folder = os.environ.get("SINGLE_FOLDER", "")
    priority_filter = os.environ.get("PRIORITY_FILTER", "")
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if not project_root:
        print("[deep-audit] ERROR: PROJECT_ROOT not set.", file=sys.stderr)
        sys.exit(1)

    # Load and filter folder config
    all_folders = _load_folder_config(script_dir)
    folders = _filter_folders(all_folders, priority_filter, single_folder)

    if not folders:
        print("[deep-audit] No folders match the filter criteria.")
        return

    # Discover files per folder
    folder_files: dict[str, list[str]] = {}
    for fc in folders:
        files = _find_files(project_root, fc)
        if files:
            folder_files[fc["path"]] = files
        else:
            print(f"[deep-audit] Skipping {fc['path']} (no auditable files)")

    total_files = sum(len(f) for f in folder_files.values())
    total_batches = sum(
        (len(f) + AGENTS_PER_BATCH - 1) // AGENTS_PER_BATCH
        for f in folder_files.values()
    )

    print(f"[deep-audit] Plan: {len(folder_files)} folders, {total_files} files, ~{total_batches} agent batches")

    if dry_run:
        for folder, files in folder_files.items():
            priority = next(
                (fc.get("priority", "?") for fc in folders if fc["path"] == folder), "?"
            )
            print(f"\n  [{priority}] {folder}/ ({len(files)} files)")
            for f in files:
                print(f"    {f}")
        print(f"\n[deep-audit] DRY RUN complete. Would spawn {len(folder_files)} sessions.")
        return

    # Create worktree
    worktree_path = _create_worktree(project_root)

    # Ensure output directory in worktree
    (Path(worktree_path) / OUTPUT_DIR / "findings").mkdir(parents=True, exist_ok=True)

    # Run folder sessions sequentially
    results = {}
    start_time = time.monotonic()

    try:
        for folder, files in folder_files.items():
            try:
                rc, sid = _run_folder_session(worktree_path, folder, files)
                results[folder] = {
                    "returncode": rc, "session_id": sid, "files": len(files)
                }
                if rc != 0:
                    print(f"[deep-audit] WARNING: {folder} exited with code {rc}")
            except Exception as e:
                print(f"[deep-audit] ERROR: {folder} failed: {e}", file=sys.stderr)
                results[folder] = {
                    "returncode": -1, "error": str(e), "files": len(files)
                }

        # Copy results from worktree to main repo
        _copy_results(worktree_path, project_root)

    finally:
        # Always clean up worktree
        _cleanup_worktree(project_root, worktree_path)

    duration = int(time.monotonic() - start_time)

    # Merge and deduplicate
    print("\n[deep-audit] Merging findings...")
    try:
        merged = _merge_findings(project_root)
        deduped = _deduplicate_findings(project_root)
    except Exception as e:
        print(f"[deep-audit] WARNING: merge failed: {e}", file=sys.stderr)
        merged = {"total_findings": "unknown", "findings_by_severity": {}}
        deduped = merged

    # Summary
    successful = sum(1 for r in results.values() if r["returncode"] == 0)
    failed = len(results) - successful
    total_findings = deduped.get("total_findings", merged.get("total_findings", "?"))
    by_severity = deduped.get(
        "findings_by_severity", merged.get("findings_by_severity", {})
    )

    # Build security disclosure for daily meeting
    severity_summary = ", ".join(
        f"{count} {sev}" for sev, count in by_severity.items() if count > 0
    )

    write_nightly_report(
        job="security-deep-audit",
        status="error" if failed > 0 else ("warning" if by_severity.get("critical", 0) > 0 else "ok"),
        summary=(
            f"Deep security audit: {successful}/{len(results)} folders, "
            f"{total_files} files audited in {duration // 60}m{duration % 60}s. "
            f"{total_findings} unique findings ({severity_summary or 'none'})."
        ),
        details={
            "folders_audited": successful,
            "folders_failed": failed,
            "total_files": total_files,
            "total_findings": total_findings,
            "by_severity": by_severity,
            "duration_seconds": duration,
            "duplicates_removed": deduped.get("duplicates_removed", 0),
        },
        security_disclosure={
            "risk_summary": (
                f"Agent-based deep audit found {total_findings} unique security findings "
                f"across {total_files} files. Severity breakdown: {severity_summary or 'none'}. "
                f"Full report: security-audit/deduplicated-report.yml"
            ),
        } if total_findings and total_findings != "unknown" and total_findings > 0 else None,
    )

    if failed > 0:
        print(f"\n[deep-audit] WARNING: {failed} folder(s) failed", file=sys.stderr)
        sys.exit(1)

    print(f"\n[deep-audit] Complete. {total_findings} unique findings in {duration // 60}m{duration % 60}s.")


if __name__ == "__main__":
    main()
