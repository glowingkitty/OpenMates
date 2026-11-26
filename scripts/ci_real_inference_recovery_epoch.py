"""Enable recovery for selected real-inference specs in disposable stacks."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Callable

if __package__:
    from .ci_environment import CODEX_REAL_INFERENCE_SPECS
else:
    from ci_environment import CODEX_REAL_INFERENCE_SPECS

REAL_INFERENCE_RECOVERY_SPECS = CODEX_REAL_INFERENCE_SPECS | {
    "real-inference-task-inline-embeds.spec.ts",
}
FIXTURE_FLAG = "OPENMATES_CI_REAL_INFERENCE_RECOVERY_FIXTURE"
EXPECTED_ENV = {
    "OPENMATES_CI_REAL_INFERENCE": "1",
    "MOCK_EXTERNAL_APIS": "true",
    "SERVER_ENVIRONMENT": "development",
    "OPENMATES_DEPLOYMENT_MODE": "self_host",
    "CMS_URL": "http://cms:8055",
    "VAULT_URL": "http://vault:8200",
    "HTTPS_PROXY": "http://runner-gateway:3128",
}
READY = {"protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": 0}

ACTIVATE = f"""
import asyncio
import json
import os
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.chat_recovery_cutover import ChatRecoveryCutoverController
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
from backend.core.api.app.services.directus import DirectusService

async def activate():
    expected = {dict(EXPECTED_ENV, **{FIXTURE_FLAG: "1"})!r}
    if any(os.getenv(key) != value for key, value in expected.items()):
        raise RuntimeError("Chat recovery requires the disposable real-inference runtime")
    cache = CacheService()
    directus = DirectusService(cache_service=cache)
    try:
        service = ChatRecoveryService(directus)
        state = await service.execute("get_cutover_state", {{"protocol_version": 1}})
        if state != {{"protocol_epoch": 0, "sends_paused": False, "legacy_in_flight": 0}}:
            raise RuntimeError("Disposable Chat recovery did not start at idle epoch zero")
        try:
            await service.execute("set_sends_paused", {{"protocol_version": 1, "sends_paused": True}})
            result = await service.execute("activate_protocol_epoch", {{"protocol_version": 1, "target_epoch": 1}})
            if result.get("activated") is not True:
                raise RuntimeError("Disposable Chat recovery activation was refused")
        finally:
            await service.execute("set_sends_paused", {{"protocol_version": 1, "sends_paused": False}})
        controller = ChatRecoveryCutoverController(cache, directus)
        durable = await controller.get_state(authoritative=True)
        cached = await controller.get_state()
        if durable != {READY!r} or cached != durable:
            raise RuntimeError("Disposable Chat recovery is not ready")
        print(json.dumps(durable))
    finally:
        await directus.close()
        await cache.close()

asyncio.run(activate())
"""


def activate_real_inference_recovery(
    spec_name: str, *, compose_path: Path, require_runner: Callable[[], None], compose: Callable,
) -> dict:
    """Use the existing cutover transaction after checking the real-inference fixture."""
    require_runner()
    if spec_name not in REAL_INFERENCE_RECOVERY_SPECS:
        raise RuntimeError("Chat recovery requires an approved real-inference spec")
    profile = json.loads(compose_path.read_text())
    services = profile.get("services", {})
    api = services.get("api", {})
    gateway_env = services.get("runner-gateway", {}).get("environment", {})
    proxy_policy = "codex" if spec_name in CODEX_REAL_INFERENCE_SPECS else "1"
    if (
        profile.get("name") != "openmates-ci"
        or profile.get("networks", {}).get("default", {}).get("internal") is not True
        or api.get("network_mode") is not None
        or set(api.get("networks", ["default"])) != {"default"}
        or api.get("ports")
        or gateway_env.get("OPENMATES_CI_REAL_INFERENCE_PROXY") != proxy_policy
        or gateway_env.get("OPENMATES_CI_PUBLIC_PROVIDER_PROXY") == "1"
        or any(api.get("environment", {}).get(key) != value for key, value in EXPECTED_ENV.items())
    ):
        raise RuntimeError("Chat recovery requires the private real-inference profile")
    try:
        result = compose(
            "exec", "-T", "-e", f"{FIXTURE_FLAG}=1", "api", "python", "-c", ACTIVATE,
            capture=True, timeout=60,
        )
        receipt = json.loads(result.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError, subprocess.CalledProcessError):
        raise RuntimeError("Disposable Chat recovery activation omitted its receipt") from None
    if receipt != READY:
        raise RuntimeError("Disposable Chat recovery activation was incomplete")
    return receipt
