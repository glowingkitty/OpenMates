#!/usr/bin/env python3
"""
Audit cost-safety contracts for scheduled AI tests.

The audit rejects unmarked chat-driving specs from scheduled discovery, checks
all referenced fixture/cache groups exist, and verifies the two paid canaries
use only the bounded real marker. It never calls a provider.
"""

from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import daily_ai_test_policy  # noqa: E402


SPEC_DIR = PROJECT_ROOT / "frontend" / "apps" / "web_app" / "tests"
CACHE_DIR = PROJECT_ROOT / "backend" / "apps" / "ai" / "testing" / "api_cache"
PLAN_PATH = PROJECT_ROOT / "docs" / "plans" / "cost-safe-daily-ai-tests" / "plan.yml"
MOCK_CONTEXT_PATH = PROJECT_ROOT / "backend" / "shared" / "testing" / "mock_context.py"
BACKFILL_PATH = PROJECT_ROOT / "scripts" / "daily_ai_cache_backfill.py"
RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_tests.py"
COMPOSE_PATH = PROJECT_ROOT / "backend" / "core" / "docker-compose.yml"
WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "playwright-spec.yml"
API_CACHE_PATH = PROJECT_ROOT / "backend" / "shared" / "testing" / "api_response_cache.py"
CHAT_TEST_HELPER_PATH = PROJECT_ROOT / "frontend" / "apps" / "web_app" / "tests" / "helpers" / "chat-test-helpers.ts"
PLAYWRIGHT_CONFIG_PATH = PROJECT_ROOT / "frontend" / "apps" / "web_app" / "playwright.config.ts"
LIVE_RE = re.compile(r"withLiveMockMarker\([^;]*?,\s*['\"]([A-Za-z0-9_-]+)['\"]", re.DOTALL)
PATHLIKE_SUFFIXES = (".py", ".ts", ".svelte", ".yml", ".yaml", ".json", ".md")


def audit() -> list[str]:
    errors: list[str] = []
    manifest = daily_ai_test_policy.load_manifest()
    spec_files = sorted(SPEC_DIR.glob("*.spec.ts"))
    scheduled = set(
        daily_ai_test_policy.discover_specs(
            (path.name for path in spec_files), manifest=manifest, spec_dir=SPEC_DIR
        )
    )

    fixed = manifest["daily_canaries"]["fixed"]
    rotating = manifest["daily_canaries"]["rotating"]
    if len(fixed) != 1:
        errors.append(f"expected exactly one fixed canary, found {len(fixed)}")
    if not rotating:
        errors.append("expected at least one rotating canary")

    for canary in [*fixed, *rotating]:
        path = SPEC_DIR / canary
        source = _read(path, errors)
        if "withLiveRealMarker" not in source:
            errors.append(f"{canary}: bounded real marker helper is required")
        if "withLiveMockMarker" in source or "withMockMarker" in source:
            errors.append(f"{canary}: replay markers are forbidden in a real canary")
        if "test.skip(" in source:
            errors.append(f"{canary}: paid daily canaries must fail, not skip, when prerequisites are absent")

    for path in spec_files:
        source = path.read_text(encoding="utf-8")
        drives_ai = any(marker in source for marker in daily_ai_test_policy._AI_ACTION_MARKERS)
        has_replay = any(marker in source for marker in daily_ai_test_policy._REPLAY_MARKERS)
        explicitly_classified = path.name in manifest["specs"] or path.name in fixed or path.name in rotating
        if drives_ai and not has_replay and not explicitly_classified:
            errors.append(f"{path.name}: AI activity lacks an explicit manifest classification")
        if "real-inference" in path.name and path.name in scheduled:
            errors.append(f"{path.name}: expensive real-inference spec entered scheduled discovery")
        if path.name in scheduled:
            for group_id in LIVE_RE.findall(source):
                if not (CACHE_DIR / group_id).is_dir():
                    errors.append(f"{path.name}: missing live cache group {group_id}")

    errors.extend(_audit_plan_references())
    errors.extend(_audit_raw_http_dispatch_guard())
    errors.extend(_audit_backfill_guards())

    return errors


def _audit_plan_references() -> list[str]:
    """Reject stale implementation file and command references in the Plan."""
    errors: list[str] = []
    if not PLAN_PATH.is_file():
        return [f"missing executable Plan: {PLAN_PATH.relative_to(PROJECT_ROOT)}"]
    try:
        document = yaml.safe_load(PLAN_PATH.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return [f"could not parse executable Plan: {exc}"]

    def walk(node: object, path: tuple[str, ...]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                child_path = (*path, str(key))
                if key in {"file", "expected_files"} or (
                    len(path) >= 1 and path[-1] == "ownership" and key in {"files", "shared_files"}
                ):
                    _validate_spec_file_refs(value, ".".join(child_path), errors)
                if key == "command" and isinstance(value, str):
                    _validate_spec_command(value, ".".join(child_path), errors)
                walk(value, child_path)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, (*path, str(index)))

    walk(document, (PLAN_PATH.relative_to(PROJECT_ROOT).as_posix(),))
    return errors


def _validate_spec_file_refs(value: object, location: str, errors: list[str]) -> None:
    for ref in _iter_file_refs(value):
        if not (PROJECT_ROOT / ref).exists():
            errors.append(f"{location}: missing referenced file {ref}")


def _iter_file_refs(value: object) -> list[str]:
    if isinstance(value, str):
        refs = value.split(";")
    elif isinstance(value, list):
        refs = [str(item) for item in value]
    else:
        return []
    return [ref.strip() for ref in refs if _is_repo_file_ref(ref.strip())]


def _validate_spec_command(command: str, location: str, errors: list[str]) -> None:
    for raw_part in re.split(r"\s+&&\s+", command):
        try:
            tokens = shlex.split(raw_part)
        except ValueError as exc:
            errors.append(f"{location}: invalid command syntax: {exc}")
            continue
        if not tokens:
            continue
        if tokens[0] not in {"python", "python3", sys.executable}:
            continue
        if len(tokens) < 2:
            errors.append(f"{location}: python command has no target")
            continue
        if tokens[1] == "-m":
            _validate_pytest_file_args(tokens[3:], location, errors)
            continue

        script = tokens[1]
        if _is_repo_file_ref(script) and not (PROJECT_ROOT / script).exists():
            errors.append(f"{location}: missing command script {script}")
        if script == "scripts/tests.py" and len(tokens) >= 3:
            command_name = tokens[2]
            commands = _scripts_tests_commands()
            if command_name not in commands:
                errors.append(f"{location}: unknown scripts/tests.py command {command_name!r}")
            if command_name == "run":
                _validate_tests_py_run_spec(tokens[3:], location, errors)

        for token in tokens[2:]:
            if token.endswith(".spec.ts") and "/" not in token:
                continue
            if _is_repo_file_ref(token) and not (PROJECT_ROOT / token).exists():
                errors.append(f"{location}: missing command file {token}")


def _validate_pytest_file_args(tokens: list[str], location: str, errors: list[str]) -> None:
    for token in tokens:
        if token.startswith("-"):
            continue
        if _is_repo_file_ref(token) and not (PROJECT_ROOT / token).exists():
            errors.append(f"{location}: missing pytest target {token}")


def _validate_tests_py_run_spec(tokens: list[str], location: str, errors: list[str]) -> None:
    for index, token in enumerate(tokens[:-1]):
        if token != "--spec":
            continue
        spec = tokens[index + 1]
        if spec.startswith("<"):
            continue
        if not (SPEC_DIR / spec).is_file():
            errors.append(f"{location}: missing Playwright spec {spec}")


def _scripts_tests_commands() -> set[str]:
    source = (PROJECT_ROOT / "scripts" / "tests.py").read_text(encoding="utf-8")
    return set(re.findall(r"sub\.add_parser\(['\"]([^'\"]+)", source))


def _is_repo_file_ref(ref: str) -> bool:
    if not ref or ref == "none" or ref.startswith("<") or "://" in ref:
        return False
    if ref.startswith("-") or "*" in ref:
        return False
    return ref.endswith(PATHLIKE_SUFFIXES) or "/" in ref


def _audit_raw_http_dispatch_guard() -> list[str]:
    try:
        source = MOCK_CONTEXT_PATH.read_text(encoding="utf-8")
    except OSError:
        return [f"missing HTTP guard source: {MOCK_CONTEXT_PATH.relative_to(PROJECT_ROOT)}"]
    required_fragments = (
        "httpx.AsyncHTTPTransport.handle_async_request = guarded_async",
        "httpx.HTTPTransport.handle_request = guarded_sync",
        "aiohttp.ClientSession._request = guarded_request",
        "requests.sessions.Session.request = guarded_request",
        "requests.sessions.Session.send = guarded_send",
        "unregistered raw HTTP provider dispatch",
        "if is_mock_active():",
    )
    missing = [fragment for fragment in required_fragments if fragment not in source]
    if missing:
        return ["raw httpx transport guard is incomplete in backend/shared/testing/mock_context.py"]
    return []


def _audit_backfill_guards() -> list[str]:
    """Reject drift in the bounded candidate-to-promotion control path."""
    sources: dict[Path, str] = {}
    for path in (BACKFILL_PATH, RUNNER_PATH, COMPOSE_PATH, WORKFLOW_PATH, API_CACHE_PATH, CHAT_TEST_HELPER_PATH, PLAYWRIGHT_CONFIG_PATH):
        try:
            sources[path] = path.read_text(encoding="utf-8")
        except OSError:
            return [f"missing backfill control source: {path.relative_to(PROJECT_ROOT)}"]
    required = {
        BACKFILL_PATH: (
            "os.O_EXCL",
            '"cache_sha256"',
            "SENSITIVE_CONTENT_PATTERN",
            "SAFE_GROUP_PATTERN",
            "persist(expected_cache_sha256)",
        ),
        RUNNER_PATH: (
            "claim_root=paths.claim_root",
            "candidate_run_root=run_root",
            "persist=persist",
            "DAILY_AI_BACKFILL_PATH_ENV_VARS",
            "_daily_cache_backfill_preflight",
            "DailyRunInterrupted",
            "class DailyRunInterrupted(BaseException)",
            "_source_root_commit(paths.source_root) != full_sha",
            "and not self.record_live_fixtures",
            '_cache_backfill_suite(self.cache_backfill)',
        ),
        COMPOSE_PATH: (
            "../../test-results/live-mock-candidates:/live-mock-candidates",
            'LIVE_MOCK_CANDIDATE_ROOT: "/live-mock-candidates"',
        ),
        WORKFLOW_PATH: ("E2E_DAILY_AI_RUN_ID: ${{ inputs.daily_ai_run_id }}",),
        API_CACHE_PATH: ("root=selected_run_root",),
        CHAT_TEST_HELPER_PATH: (
            "TRAILING_LIVE_TEST_MARKER",
            "extractLiveTestMarker(message)",
            "options.testMockMarker ?? extractedMessage.testMockMarker",
        ),
        PLAYWRIGHT_CONFIG_PATH: (
            "E2E_RECORD_LIVE_FIXTURES",
            "retries: isLiveFixtureRecording ? 0 : 1",
        ),
    }
    errors: list[str] = []
    for path, fragments in required.items():
        if any(fragment not in sources[path] for fragment in fragments):
            errors.append(f"bounded backfill guard is incomplete in {path.relative_to(PROJECT_ROOT)}")
    if "shutil.rmtree(run_root" in sources[RUNNER_PATH]:
        errors.append("daily runner must not delete the durable per-day backfill claim")
    if 'PROJECT_ROOT.parent / ".openmates-runtime/product-stack/test-results/live-mock-candidates"' in sources[RUNNER_PATH]:
        errors.append("daily runner must not infer checkout-dependent backfill roots")
    backfill_call = sources[RUNNER_PATH].find("self._run_daily_cache_backfill()")
    playwright_call = sources[RUNNER_PATH].find('suites["playwright"] = self._run_playwright()')
    if backfill_call < 0 or playwright_call < 0 or backfill_call > playwright_call:
        errors.append("daily cache backfill must run before the broad Playwright queue")
    return errors


def _read(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        errors.append(f"missing spec: {path.name}")
        return ""


def main() -> int:
    errors = audit()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: daily AI tests are explicitly replayed or bounded real canaries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
