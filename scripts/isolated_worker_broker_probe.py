#!/usr/bin/env python3
"""Backend-only, source-bound CI diagnostic; never admits a chat or inference task.

The fixture selector configures the same isolated AI worker as recovery E2E.
This probe only inspects worker/broker bindings and empty-table availability.
Its receipt is diagnostic health, not recovery behavior or latency acceptance.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable

try:
    from scripts.ci_environment import COMPOSE_PATH, SOURCE, require_runner, select_runtime_profile
except ModuleNotFoundError:
    from ci_environment import COMPOSE_PATH, SOURCE, require_runner, select_runtime_profile

SELECTOR = "cli-recovery-discovery.spec.ts"
REQUIRED_IMAGES = frozenset({"api", "cms", "setup", "schema"})
STAGES = frozenset({"bootstrap", "app_imported", "worker_inspected", "broker_checked", "redis_checked", "cms_checked"})
PROBE_SECONDS = 35
SAFE_FAILURES = frozenset({
    "source_identity", "run_identity", "fixture_selector", "runtime_image_inventory",
    "compatible_image_cache_miss", "backend_network_not_internal", "fixture_services_missing",
    "prepared_schema_not_selected", "routing_worker_profile", "provider_credentials_present",
    "routing_proof_schema_missing", "prepared_schema_incompatible",
    "backend_verification_missing",
})
PROBE_CODE = r'''
import asyncio,json,logging,os,signal
print("OPENMATES_PROBE_STAGE:bootstrap",flush=True)
assert os.environ.get("OPENMATES_CI_ISOLATED")=="1"
logging.disable(logging.CRITICAL)
from backend.core.api.app.tasks.celery_config import app
print("OPENMATES_PROBE_STAGE:app_imported",flush=True)
def alarm(*_): raise TimeoutError()
def bounded(operation):
    previous=signal.signal(signal.SIGALRM,alarm);signal.setitimer(signal.ITIMER_REAL,2.5)
    try: return operation()
    finally: signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)
registered=bounded(lambda: app.control.inspect(timeout=1.5).registered())
queues=bounded(lambda: app.control.inspect(timeout=1.5).active_queues())
stats=bounded(lambda: app.control.inspect(timeout=1.5).stats())
registered=registered if isinstance(registered,dict) else {}
queues=queues if isinstance(queues,dict) else {}
stats=stats if isinstance(stats,dict) else {}
consumers={name for name,items in queues.items() if isinstance(items,list) and any(isinstance(item,dict) and item.get("name")=="app_ai_routing" for item in items)}
combined={name for name in consumers if any(isinstance(item,dict) and item.get("name")=="app_ai" for item in queues[name])}
stage_one={name for name in consumers if "apps.ai.tasks.stage_one" in registered.get(name,[])}
children={name for name in consumers if isinstance(stats.get(name),dict) and len((stats[name].get("pool") or {}).get("processes") or [])>0}
route=app.conf.task_routes.get("apps.ai.tasks.stage_one") if isinstance(app.conf.task_routes,dict) else None
binding=bool(isinstance(route,dict) and route.get("queue")=="app_ai_routing")
print("OPENMATES_PROBE_STAGE:worker_inspected",flush=True)
def depth():
    with app.connection_for_read(connect_timeout=1.5,transport_options={"socket_timeout":1.5,"socket_connect_timeout":1.5}) as connection:
        channel=connection.channel()
        try:
            if not channel.__class__.__module__.startswith("kombu.transport.redis") or tuple(channel.priority_steps)!=(0,3,6,9): raise RuntimeError("unsupported broker transport")
            with channel.client.pipeline() as pipeline:
                for name in ("app_ai","app_ai_routing"):
                    for priority in (0,3,6,9): pipeline.llen(channel._q_for_pri(name,priority))
                counts=pipeline.execute()
            if len(counts)!=8 or any(type(count) is not int or count<0 for count in counts): raise RuntimeError("invalid broker depths")
            return {"appAi":sum(counts[:4]),"appAiRouting":sum(counts[4:])}
        finally: channel.close()
depths=bounded(depth)
print("OPENMATES_PROBE_STAGE:broker_checked",flush=True)
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
async def check_dependencies():
    cache=CacheService();directus=DirectusService(cache_service=cache)
    try:
        redis=await asyncio.wait_for(cache.client,2.5)
        if not await asyncio.wait_for(redis.ping(),2.5): raise RuntimeError("redis unavailable")
        print("OPENMATES_PROBE_STAGE:redis_checked",flush=True)
        for table in ("chat_routing_proofs","chat_turn_preflights","chat_inference_outbox"):
            rows=await asyncio.wait_for(directus.get_items(table,params={"limit":1},no_cache=True,admin_required=True,raise_on_error=True),2.5)
            if not isinstance(rows,list): raise RuntimeError("required table unavailable")
        print("OPENMATES_PROBE_STAGE:cms_checked",flush=True)
    finally:
        await directus.close();await cache.close()
asyncio.run(check_dependencies())
result={"registeredRoutingConsumers":len(stage_one),"routingConsumers":len(consumers),"combinedConsumers":len(combined),"livePoolConsumers":len(children),"registrationReplies":len(registered),"queueReplies":len(queues),"statsReplies":len(stats),"routeBinding":binding,"queueDepths":depths,"redis":True,"cmsTables":True}
print("OPENMATES_PROBE_JSON:"+json.dumps(result,sort_keys=True),flush=True)
'''


def validate_cache_evidence(root: Path, source: str, profile: dict, runtime: dict, environment: dict) -> None:
    """Fail before stack startup if any compatible published image/schema is absent."""
    if not re.fullmatch(r"[0-9a-f]{40}", source) or environment.get("source_commit") != source:
        raise ValueError("source_identity")
    if environment.get("run_id") != os.environ.get("GITHUB_RUN_ID"):
        raise ValueError("run_identity")
    if json.loads(os.environ.get("CI_SPECS_JSON", "[]")) != [SELECTOR]:
        raise ValueError("fixture_selector")
    entries = runtime.get("images")
    if not isinstance(entries, list) or len(entries) != len(REQUIRED_IMAGES):
        raise ValueError("runtime_image_inventory")
    images = {entry.get("kind"): entry for entry in entries if isinstance(entry, dict)}
    if set(images) != REQUIRED_IMAGES or any(image.get("reused") is not True for image in images.values()):
        raise ValueError("compatible_image_cache_miss")
    if profile.get("networks", {}).get("default", {}).get("internal") is not True:
        raise ValueError("backend_network_not_internal")
    services = profile.get("services", {})
    if not isinstance(services, dict) or not {"api", "ai-worker", "runner-gateway", "cms", "cms-database", "cache", "vault"}.issubset(services):
        raise ValueError("fixture_services_missing")
    if services["cms-database"].get("image") != "openmates-ci-database:local":
        raise ValueError("prepared_schema_not_selected")
    worker = services["ai-worker"]
    worker_env = worker.get("environment", {})
    if (worker_env.get("OPENMATES_CI_AI_FIXTURES") != "1"
            or worker_env.get("CELERY_QUEUES") != "app_ai,app_ai_routing"
            or "--queues=app_ai,app_ai_routing" not in worker.get("command", [])):
        raise ValueError("routing_worker_profile")
    providers = {"OPENAI", "ANTHROPIC", "GOOGLE", "GEMINI", "OPENROUTER",
                 "GROQ", "CEREBRAS", "TOGETHER", "MISTRAL"}
    forbidden = {provider + "_API_KEY" for provider in providers}
    for name in ("api", "ai-worker", "core-worker"):
        names = set(services[name].get("environment", {}))
        if names & forbidden or any(item.startswith("SECRET__") and any(provider in item.upper() for provider in providers) for item in names):
            raise ValueError("provider_credentials_present")
    if not (root / "backend/core/directus/schemas/chat_routing_proofs.yml").is_file():
        raise ValueError("routing_proof_schema_missing")


def parse_probe_output(raw: bytes) -> tuple[dict | None, str]:
    lines = raw.decode("utf-8", "replace").splitlines()
    stages = [line.removeprefix("OPENMATES_PROBE_STAGE:") for line in lines
              if line.startswith("OPENMATES_PROBE_STAGE:")]
    last_stage = next((stage for stage in reversed(stages) if stage in STAGES), "not_started")
    markers = [line.removeprefix("OPENMATES_PROBE_JSON:") for line in lines
               if line.startswith("OPENMATES_PROBE_JSON:")]
    if len(markers) != 1:
        return None, last_stage
    try:
        result = json.loads(markers[0])
        counts = ("registeredRoutingConsumers", "routingConsumers", "combinedConsumers",
                  "livePoolConsumers", "registrationReplies", "queueReplies", "statsReplies")
        if not isinstance(result, dict) or any(type(result.get(key)) is not int or result[key] < 0 for key in counts):
            raise ValueError("invalid counts")
        depths = result.get("queueDepths")
        if (not isinstance(depths, dict) or set(depths) != {"appAi", "appAiRouting"}
                or any(type(value) is not int or value < 0 for value in depths.values())
                or any(result.get(key) is not True for key in ("routeBinding", "redis", "cmsTables"))):
            raise ValueError("invalid dependency result")
        if any(result[key] < 1 for key in ("registeredRoutingConsumers", "routingConsumers",
                                            "combinedConsumers", "livePoolConsumers")):
            raise ValueError("worker not ready")
        return result, last_stage
    except (TypeError, ValueError):
        return None, last_stage


def report(root: Path, *, success: bool, stage: str, category: str, health: dict | None = None) -> None:
    safe = {
        "source_commit": os.environ.get("BUILD_COMMIT_SHA"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "harness_commit": os.environ.get("CI_HARNESS_COMMIT"),
        "proof_profile": "", "runtime_profile": "backend-probe",
        "diagnostic_only": True, "recovery_e2e_verified": False,
        "latency_acceptance_verified": False, "success": success,
        "results": [{"spec": "backend-worker-broker-probe", "exit_code": 0 if success else 1,
                     "status": "passed" if success else "failed", "stage": stage,
                     "category": category, "health": health or {}}],
    }
    path = root / "test-results/ci-results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(safe, indent=2))


def private_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    return path.open("xb")


def run_probe(root: Path, runner: Callable = subprocess.run, *, timeout: int = PROBE_SECONDS) -> tuple[dict | None, str, str]:
    private = root / "test-results/ci-backend-probe-private"
    compose = root / "test-results/ci-private/compose.json"
    stdout_path = private / "probe.stdout.log"
    stderr_path = private / "probe.stderr.log"
    with private_file(stdout_path) as stdout, private_file(stderr_path) as stderr:
        os.chmod(stdout_path, 0o600)
        os.chmod(stderr_path, 0o600)
        try:
            completed = runner(
                ["docker", "compose", "-f", str(compose), "exec", "-T", "-e",
                 "OPENMATES_CI_ISOLATED=1", "api", "python", "-u", "-c", PROBE_CODE],
                cwd=root, stdout=stdout, stderr=stderr, timeout=timeout, check=False,
            )
            category = "ok" if completed.returncode == 0 else "nonzero_exit"
        except subprocess.TimeoutExpired:
            category = "timeout"
        except OSError:
            category = "spawn_error"
    raw = stdout_path.read_bytes()
    result, stage = parse_probe_output(raw)
    if category == "ok" and result is None:
        category = "invalid_probe_result"
    return result if category == "ok" else None, stage, category


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args not in (["preflight"], ["probe"]):
        raise SystemExit("Usage: isolated_worker_broker_probe.py preflight|probe")
    require_runner()
    if os.environ.get("CI_TEST_MODE") != "backend-probe":
        raise RuntimeError("Backend probe requires its dedicated isolated CI mode")
    root = Path(SOURCE)
    if args == ["preflight"]:
        try:
            source = os.environ["BUILD_COMMIT_SHA"]
            runtime = json.loads((root / "test-results/ci-runtime-images.json").read_text())
            environment = json.loads((root / "test-results/ci-environment.json").read_text())
            if not select_runtime_profile():
                raise ValueError("prepared_schema_incompatible")
            profile = json.loads(COMPOSE_PATH.read_text())
            validate_cache_evidence(root, source, profile, runtime, environment)
        except (OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
            category = (str(exc) if type(exc) is ValueError and str(exc) in SAFE_FAILURES
                        else type(exc).__name__)
            report(root, success=False, stage="cache_preflight", category=category)
            print("Backend diagnostic cache preflight failed: " + category, file=sys.stderr)
            return 1
        report(root, success=False, stage="awaiting_backend_start", category="pending")
        print("Backend diagnostic cache preflight passed")
        return 0
    try:
        environment = json.loads((root / "test-results/ci-environment.json").read_text())
        if (environment.get("source_commit") != os.environ.get("BUILD_COMMIT_SHA")
                or environment.get("provider_egress") != "rejected-internal-network"
                or environment.get("shared_dev_https") != "rejected"):
            raise ValueError("backend_verification_missing")
        result, stage, category = run_probe(root)
    except (OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        result, stage = None, "host_probe"
        category = (str(exc) if type(exc) is ValueError and str(exc) in SAFE_FAILURES
                        else type(exc).__name__)
    passed = result is not None and category == "ok"
    report(root, success=passed, stage=stage, category=category, health=result)
    print("Backend diagnostic " + ("healthy" if passed else "failed") + ": " + category)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
