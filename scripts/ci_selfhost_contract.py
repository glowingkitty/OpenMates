"""Closed self-host recipe scopes and fail-closed aggregate acceptance.

Selectors are recipe targets, never Playwright spec aliases. Each occupies one
ordinary coordinator job. Only the image target owns all four browser cases.
"""
from __future__ import annotations

import hashlib
import json
import re

TARGETS = ("selfhost-source", "selfhost-image", "selfhost-legacy")
RECIPE = ".github/workflows/selfhost-smoke-rust.yml"
# Every command step is classified, including diagnostics and teardown.
STEPS = {
    "dependencies": ("Install workspace dependencies", TARGETS),
    "typescript-cli": ("Build current branch CLI", ("selfhost-image", "selfhost-legacy")),
    "rust-cli": ("Build exact-source Rust self-host CLI", ("selfhost-source", "selfhost-image")),
    "published-cli": ("Install published CLI from npm", ("selfhost-legacy",)),
    "openobserve": ("Stage OpenObserve image for self-hosted install", TARGETS),
    "legacy-source": ("Source-mode timing baseline", ("selfhost-legacy",)),
    "native-source": ("Native source-mode install lifecycle", ("selfhost-source",)),
    "images": ("Build local image-mode images", ("selfhost-image",)),
    "native-image": ("Image-mode self-hosted install and timing", ("selfhost-image",)),
    "epoch0-restart": ("Preserve epoch 0 across restart", ("selfhost-image",)),
    "epoch0-update": ("Preserve epoch 0 across update", ("selfhost-image",)),
    "epoch1-restart": ("Preserve epoch 1 across restart", ("selfhost-image",)),
    "epoch1-update": ("Preserve epoch 1 across update", ("selfhost-image",)),
    "restore-ready": ("Restore ready epoch fixture", ("selfhost-image",)),
    "timing": ("Summarize setup timing", TARGETS),
    "server-status": ("Check server status JSON", ("selfhost-image",)),
    "containers": ("Check backend and web Docker containers", ("selfhost-image",)),
    "chrome": ("Verify Chrome browser", ("selfhost-image",)),
    "browser": ("Run self-hosted smoke spec", ("selfhost-image",)),
    "diagnostics": ("Show self-hosted status and logs", TARGETS),
    "uninstall": ("Uninstall self-hosted edition", TARGETS),
}
STEPS = {"selfhost-" + key: value for key, value in STEPS.items()}


def validate_targets(targets):
    if not isinstance(targets, list) or len(targets) != 1 or targets[0] not in TARGETS:
        raise ValueError("Self-host requires exactly one closed recipe target")
    return targets[0]


def recipe_steps(steps, target):
    validate_targets([target])
    seen = []
    selected = []
    for step in steps:
        if "run" not in step:
            if step.get("uses") not in {"actions/checkout@v4", "actions/setup-node@v4",
                    "pnpm/action-setup@v4", "actions/upload-artifact@v4"}:
                raise ValueError("Unclassified self-host step")
            continue
        identifier = step.get("id")
        if (identifier not in STEPS or identifier in seen
                or step.get("name") != STEPS[identifier][0]):
            raise ValueError("Missing, duplicate or unclassified self-host command step")
        seen.append(identifier)
        if target in STEPS[identifier][1]:
            selected.append(step)
    if seen != list(STEPS):
        raise ValueError("Self-host command dependency order/inventory changed")
    return selected


def identity(commit, tree, recipe_hash, harness):
    for value, length in ((commit, 40), (tree, 40), (recipe_hash, 64), (harness, 40)):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{%d}" % length, value):
            raise ValueError("Self-host immutable identity missing")
    fields = dict(source_commit=commit, product_tree=tree,
                  recipe_sha256=recipe_hash, harness_commit=harness)
    fields["input_set_sha256"] = hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()
    return fields


def valid_scope(receipt, target):
    try:
        validate_targets([target])
        fields = identity(*(receipt[key] for key in (
            "source_commit", "product_tree", "recipe_sha256", "harness_commit")))
        run_id = receipt["run_id"]
        if not isinstance(run_id, str) or not re.fullmatch(r"[1-9][0-9]{0,20}", run_id):
            return False
        expected = [key for key, value in STEPS.items() if target in value[1]]
        rows = receipt["steps"]
        return (all(receipt.get(key) == value for key, value in fields.items())
                and receipt.get("target") == target and type(receipt.get("exit_code")) is int
                and receipt.get("exit_code") == 0
                and receipt.get("cleanup") == {"containers_remaining": 0, "volumes_remaining": 0,
                    "private_account_files_removed": True, "errors": []}
                and receipt.get("coverage_scope") == "recipe-target"
                and receipt.get("coverage_complete") is False
                and [row.get("id") for row in rows] == expected
                and all(row.get("phase") == "completed" and type(row.get("exit_code")) is int
                    and row.get("exit_code") == 0 and row.get("run_id") == run_id
                    and row.get("source_commit") == receipt["source_commit"] for row in rows)
                and receipt.get("browser_coverage_scope") == ("full-spec" if target == "selfhost-image" else "none")
                and (target != "selfhost-image" or receipt.get("stats") == {
                    "expected": 4, "unexpected": 0, "flaky": 0, "skipped": 0}))
    except (KeyError, TypeError, ValueError):
        return False


def aggregate_acceptance(receipts):
    """Missing, duplicate and mixed-input scope receipts remain open."""
    if not isinstance(receipts, list) or len(receipts) != len(TARGETS):
        return False
    indexed = {row.get("target"): row for row in receipts if isinstance(row, dict)}
    if set(indexed) != set(TARGETS) or not all(valid_scope(indexed[t], t) for t in TARGETS):
        return False
    keys = ("source_commit", "product_tree", "input_set_sha256", "recipe_sha256", "harness_commit")
    return len({tuple(row[key] for key in keys) for row in receipts}) == 1


JOURNAL_STAGES = frozenset(("backup", "pull", "build", "stop-email-consumers", "stage-cms",
    "cms-setup", "up", "health-check", "caddy-update", "runtime-verification",
    "monitoring-service", "completion-email", "complete"))
JOURNAL_STATUSES = frozenset(("in_progress", "success", "degraded", "failed", "cancelled"))


def sanitize_journal(value, elapsed_ms):
    """Copy only enum-valued progress; never retain paths, errors or delivery IDs."""
    if not isinstance(value, dict):
        return None
    stage, status = value.get("step"), value.get("status")
    if not isinstance(stage, str) or not isinstance(status, str) or stage not in JOURNAL_STAGES or status not in JOURNAL_STATUSES:
        return None
    return {"stage": stage, "status": status, "observed_elapsed_ms": max(0, int(elapsed_ms))}


RUST_INPUTS = (
    "frontend/packages/openmates-tui-native/Cargo.toml",
    "frontend/packages/openmates-tui-native/Cargo.lock",
    "frontend/packages/openmates-tui-native/src/main.rs",
    "frontend/packages/openmates-tui-native/src/server/update.rs",
    "packages/openmates-rust/Cargo.toml",
    "scripts/check_selfhost_chat_readiness.py",
    "scripts/selfhost_chat_epoch_fixture.py",
)


def source_activation(read_file):
    """Decide from the immutable subject, never the current checkout/harness."""
    missing = []
    contents = {}
    for path in (RECIPE, *RUST_INPUTS):
        try:
            value = read_file(path)
        except (FileNotFoundError, KeyError):
            missing.append(path)
        else:
            if not value:
                missing.append(path)
            contents[path] = value
    if missing:
        return {"status": "not-yet-rust-activated", "missing_inputs": missing,
                "targets": ["selfhost-smoke.spec.ts"]}
    import yaml
    recipe = yaml.safe_load(contents[RECIPE])["jobs"]["install-smoke"]
    for target in TARGETS:
        recipe_steps(recipe["steps"], target)
    return {"status": "rust-scopes-required", "missing_inputs": [], "targets": list(TARGETS)}


def validate_result(report, job, expected_identity):
    """Validate externally observed subject/recipe and GitHub run, not self-consistency."""
    try:
        target = validate_targets(json.loads(job["specs"]))
        rows = report["results"]
        if len(rows) != 1 or not valid_scope(rows[0], target):
            return False
        row = rows[0]
        return (report.get("coverage_scope") == "recipe-target"
                and report.get("source_commit") == job["source"]
                and str(report.get("run_id")) == str(job["run_id"])
                and report.get("harness_commit") == expected_identity["harness_commit"]
                and row.get("run_id") == str(job["run_id"])
                and all(row.get(key) == value for key, value in expected_identity.items()))
    except (KeyError, TypeError, ValueError):
        return False


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description="Accept only the three matching self-host scope receipts")
    parser.add_argument("receipts", nargs=3, type=Path)
    arguments = parser.parse_args()
    accepted = aggregate_acceptance([json.loads(path.read_text()) for path in arguments.receipts])
    print("Self-host acceptance: " + ("complete" if accepted else "open"))
    raise SystemExit(0 if accepted else 1)
