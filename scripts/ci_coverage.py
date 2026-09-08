"""Declare the runtime coverage available during the GitHub CI cutover.

The current public runner supplies core self-host services and fresh accounts.
Official-cloud and provider-backed behavior require their own verified profile.
Unknown requirements remain visible holds instead of silently changing semantics.
See docs/architecture/isolated-github-tests.md.
"""

CORE_SPECS = frozenset({
    "test-account-preflight.spec.ts",
    "tasks-flow.spec.ts",
    "task-detail-fullscreen.spec.ts",
    "task-blocked-reason.spec.ts",
    "task-activity.spec.ts",
})
ARTIFACT_SPECS = frozenset({"security-reporting-email-proof.spec.ts"})


def execution_mode(spec: str) -> str:
    return "artifact" if spec in ARTIFACT_SPECS else "e2e"


HOLD_REASONS = {
    "anonymous-production-repair.spec.ts": "Requires official-cloud eligibility, inference and budget isolation",
    "anonymous-free-chat.spec.ts": "Browser mock coverage must retain its separate official-cloud contract; profile review pending",
    "chat-scroll-streaming.spec.ts": "Requires the AI worker/provider profile and preserved inference budget controls",
}


def partition(specs: list[str]) -> tuple[list[str], dict[str, str]]:
    supported = []
    held = {}
    for spec in specs:
        if spec in CORE_SPECS or spec in ARTIFACT_SPECS:
            supported.append(spec)
        else:
            held[spec] = HOLD_REASONS.get(
                spec, "Runtime requirements have not been ported to a verified isolated profile"
            )
    return supported, held


def verify_pilot(receipt: dict) -> dict:
    report = receipt.get("report") or {}
    environment = receipt.get("environment") or {}
    preflight = next((item for item in report.get("results", [])
                      if item.get("spec") == "test-account-preflight.spec.ts"), {})
    stats = preflight.get("stats") or {}
    if (receipt.get("state") != "success" or report.get("success") is not True
            or preflight.get("exit_code") != 0 or stats.get("expected", 0) < 1
            or any(stats.get(key, 0) for key in ("skipped", "unexpected", "flaky"))):
        raise RuntimeError("Cutover requires a successful GitHub job and real account preflight without skipped assertions")
    required = {"api", "core-worker", "cms", "cms-database", "cache", "vault"}
    if (environment.get("runner_environment") != "github-hosted"
            or not required.issubset(environment.get("services", {}))
            or environment.get("shared_dev_https") != "rejected"
            or environment.get("frontend", {}).get("source_commit") != receipt.get("source_commit")):
        raise RuntimeError("Cutover requires verified local frontend/backend and shared-dev rejection")
    return {
        "ready": True,
        "profile": "public-self-host-core",
        "run_id": receipt["run_id"],
        "source_commit": receipt["source_commit"],
        "harness_commit": receipt["harness_commit"],
        "artifact_url": receipt["artifact_url"],
        "supported_specs": sorted(CORE_SPECS),
        "all_e2e_migrated": False,
        "held_coverage": HOLD_REASONS,
    }
