"""Enable recovery only for the exact isolated voice and authored media specs."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Callable

VOICE_RECOVERY_SPEC = "voice-call.spec.ts"
_PRIVATE_ENDPOINTS = {
    "S3_ENDPOINT_URL": "http://storage.ci.test:9000",
    "CMS_URL": "http://cms:8055",
    "VAULT_URL": "http://vault:8200",
}
_FIXTURE_ENV = {
    "CI": "true",
    "OPENMATES_CI_ISOLATED": "1",
    "OPENMATES_CI_AI_FIXTURES": "1",
    "MOCK_EXTERNAL_APIS": "true",
    "SERVER_ENVIRONMENT": "development",
}
_PROXY_KEYS = {
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "ALL_PROXY",
    "https_proxy",
    "http_proxy",
    "all_proxy",
}
_RECEIPT = {"protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": 0}

# The same canonical transition used by the existing capacity/marker fixtures.
# The voice profile has its own guards; it never opts into capacity fixtures.
VOICE_EPOCH_PROGRAM = r"""
import asyncio
import json
import os
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
from backend.core.api.app.services.chat_recovery_cutover import ChatRecoveryCutoverController
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService

EXPECTED = {
    'CI': 'true', 'OPENMATES_CI_ISOLATED': '1', 'OPENMATES_CI_AI_FIXTURES': '1',
    'MOCK_EXTERNAL_APIS': 'true', 'SERVER_ENVIRONMENT': 'development',
    'OPENMATES_CI_VOICE_RECOVERY_EPOCH_FIXTURE': '1',
    'S3_ENDPOINT_URL': 'http://storage.ci.test:9000',
    'CMS_URL': 'http://cms:8055', 'VAULT_URL': 'http://vault:8200',
}

def state_is(state, epoch, paused):
    return (type(state.get('protocol_epoch')) is int and state['protocol_epoch'] == epoch
            and state.get('sends_paused') is paused
            and type(state.get('legacy_in_flight')) is int and state['legacy_in_flight'] == 0)

async def main():
    if (any(os.getenv(key) != value for key, value in EXPECTED.items())
            or os.getenv('OPENMATES_STORAGE_CAPACITY_FIXTURES') is not None
            or any(key in os.environ for key in
                   ('HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'https_proxy', 'http_proxy', 'all_proxy'))):
        raise RuntimeError('Voice recovery activation requires the isolated full-storage voice fixture')
    cache = CacheService()
    directus = DirectusService(cache_service=cache)
    try:
        service = ChatRecoveryService(directus)
        state = await service.execute('get_cutover_state', {'protocol_version': 1})
        if not state_is(state, 0, False):
            raise RuntimeError('Voice recovery state is not fresh idle epoch zero')
        pause_attempted = False
        try:
            pause_attempted = True
            paused = await service.execute('set_sends_paused',
                                           {'protocol_version': 1, 'sends_paused': True})
            if not state_is(paused, 0, True):
                raise RuntimeError('Voice recovery pause was not acknowledged')
            activated = await service.execute('activate_protocol_epoch',
                                              {'protocol_version': 1, 'target_epoch': 1})
            if not state_is(activated, 1, True) or activated.get('activated') is not True:
                raise RuntimeError('Voice recovery epoch one was not activated')
        finally:
            if pause_attempted:
                resumed = await service.execute('set_sends_paused',
                                                {'protocol_version': 1, 'sends_paused': False})
                # On an activation failure, resume safely but still propagate
                # the failure. Never reset an epoch or declare success for it.
                epoch = resumed.get('protocol_epoch')
                if type(epoch) is not int or epoch not in (0, 1) or not state_is(resumed, epoch, False):
                    raise RuntimeError('Voice recovery sends were not safely resumed')
        controller = ChatRecoveryCutoverController(cache, directus)
        if not state_is(await controller.get_state(authoritative=True), 1, False):
            raise RuntimeError('Voice recovery durable epoch one is not open for sends')
        if not state_is(await controller.get_state(), 1, False):
            raise RuntimeError('Voice recovery cached epoch one is not open for sends')
    finally:
        await directus.close()
        await cache.close()
    print(json.dumps({'protocol_epoch': 1, 'sends_paused': False, 'legacy_in_flight': 0}))

asyncio.run(main())
"""


def activate_isolated_voice_recovery_epoch(
    spec_name: str,
    *,
    compose_path: Path,
    require_runner: Callable[[], None],
    compose: Callable,
) -> dict:
    """Require the exact isolated voice stack before invoking product cutover."""
    require_runner()
    if spec_name != VOICE_RECOVERY_SPEC:
        raise RuntimeError("Voice recovery epoch requires the exact voice browser spec")
    profile = json.loads(compose_path.read_text())
    services = profile.get("services", {})
    required = {
        "api",
        "core-worker",
        "ai-worker",
        "speech-worker",
        "object-storage",
        "uploads",
        "clamav",
        "runner-gateway",
    }
    if (
        not required.issubset(services)
        or profile.get("networks", {}).get("default", {}).get("internal") is not True
    ):
        raise RuntimeError(
            "Voice recovery epoch requires the isolated full-storage voice profile"
        )
    for name in ("api", "core-worker", "ai-worker", "speech-worker"):
        service = services[name]
        if service.get("network_mode") is not None or set(
            service.get("networks", ["default"])
        ) != {"default"}:
            raise RuntimeError(
                "Voice recovery epoch requires private processing workers"
            )
    for name in ("api", "ai-worker", "speech-worker"):
        environment = services[name].get("environment", {})
        if (
            any(
                environment.get(key) != value
                for key, value in {**_FIXTURE_ENV, **_PRIVATE_ENDPOINTS}.items()
            )
            or environment.get("OPENMATES_STORAGE_CAPACITY_FIXTURES") is not None
        ):
            raise RuntimeError(
                "Voice recovery epoch requires the isolated full-storage voice profile"
            )
    for name, queues in (
        ("ai-worker", "app_ai,app_ai_routing,app_videos"),
        ("speech-worker", "app_music"),
    ):
        queue_options = [
            part
            for part in services[name].get("command", [])
            if part.startswith("--queues=")
        ]
        if queue_options != [f"--queues={queues}"]:
            raise RuntimeError(
                "Voice recovery epoch requires the exact voice worker queues"
            )
    if (
        services["ai-worker"]["environment"].get("CELERY_QUEUES")
        != "app_ai,app_ai_routing,app_videos"
        or services["speech-worker"]["environment"].get("CELERY_QUEUES") != "app_music"
        or "storage.ci.test"
        not in services["object-storage"]
        .get("networks", {})
        .get("default", {})
        .get("aliases", [])
        or services["uploads"].get("environment", {}).get("S3_ENDPOINT_URL")
        != _PRIVATE_ENDPOINTS["S3_ENDPOINT_URL"]
    ):
        raise RuntimeError(
            "Voice recovery epoch requires the isolated voice workers and storage"
        )
    for service in services.values():
        environment = service.get("environment", {})
        if (
            _PROXY_KEYS.intersection(environment)
            or environment.get("OPENMATES_CI_PUBLIC_PROVIDER_PROXY") is not None
        ):
            raise RuntimeError("Voice recovery epoch rejects public provider egress")
    try:
        result = compose(
            "exec",
            "-T",
            "-e",
            "OPENMATES_CI_VOICE_RECOVERY_EPOCH_FIXTURE=1",
            "api",
            "python",
            "-c",
            VOICE_EPOCH_PROGRAM,
            capture=True,
            timeout=60,
        )
    except subprocess.CalledProcessError:
        raise RuntimeError(
            "Disposable voice recovery epoch activation failed"
        ) from None
    try:
        receipt = json.loads(result.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Disposable voice recovery epoch omitted its receipt"
        ) from exc
    if (
        receipt != _RECEIPT
        or type(receipt.get("protocol_epoch")) is not int
        or type(receipt.get("legacy_in_flight")) is not int
        or receipt.get("sends_paused") is not False
    ):
        raise RuntimeError("Disposable voice recovery epoch activation was incomplete")
    return receipt


AUTHORED_MEDIA_RECOVERY_SPEC = "authored-results-media.spec.ts"
_AUTHORED_MEDIA_GUARD = "OPENMATES_CI_AUTHORED_MEDIA_RECOVERY_EPOCH_FIXTURE"
_OTHER_EPOCH_GUARDS = {
    "OPENMATES_CI_VOICE_RECOVERY_EPOCH_FIXTURE",
    "OPENMATES_CI_MARKER_CHAT_EPOCH_FIXTURE",
    "OPENMATES_CI_RECOVERY_EPOCH_FIXTURE",
}

# Reuse the existing canonical pause/activate/resume program verbatim, with a
# fixed separate fixture identity. This is not a caller-selectable cutover mode;
# voice retains its original program and entry point unchanged.
AUTHORED_MEDIA_EPOCH_PROGRAM = (
    VOICE_EPOCH_PROGRAM.replace(
        "OPENMATES_CI_VOICE_RECOVERY_EPOCH_FIXTURE", _AUTHORED_MEDIA_GUARD
    )
    .replace("Voice recovery", "Authored media recovery")
    .replace(
        "isolated full-storage voice fixture",
        "isolated full-storage authored media fixture",
    )
    .replace(
        "or os.getenv('OPENMATES_STORAGE_CAPACITY_FIXTURES') is not None",
        "or any(os.getenv(key) is not None for key in "
        + repr(
            tuple(
                sorted(
                    _OTHER_EPOCH_GUARDS
                    | {
                        "OPENMATES_STORAGE_CAPACITY_FIXTURES",
                        "OPENMATES_CI_PUBLIC_PROVIDER_PROXY",
                    }
                )
            )
        )
        + ")",
    )
)


def activate_isolated_authored_media_recovery_epoch(
    spec_name: str,
    *,
    compose_path: Path,
    require_runner: Callable[[], None],
    compose: Callable,
) -> dict:
    """Activate only the exact selected-media fixture's private upload stack."""
    require_runner()
    if spec_name != AUTHORED_MEDIA_RECOVERY_SPEC:
        raise RuntimeError(
            "Authored media recovery epoch requires the exact media browser spec"
        )
    profile = json.loads(compose_path.read_text())
    services = profile.get("services", {})
    networks = profile.get("networks", {})
    required = {
        "api",
        "core-worker",
        "ai-worker",
        "object-storage",
        "uploads",
        "clamav",
        "runner-gateway",
    }
    if (
        not required.issubset(services)
        or set(networks) != {"default", "ingress"}
        or networks["default"].get("internal") is not True
        or any(network.get("external") is not None for network in networks.values())
    ):
        raise RuntimeError(
            "Authored media recovery epoch requires the isolated full-storage upload profile"
        )
    for name in required:
        service = services[name]
        expected_networks = (
            {"default"}
            if name in {"api", "core-worker", "ai-worker"}
            else {"default", "ingress"}
        )
        if (
            service.get("network_mode") is not None
            or set(service.get("networks", ["default"])) != expected_networks
        ):
            raise RuntimeError(
                "Authored media recovery epoch requires private processing and upload networks"
            )
        ports = service.get("ports", [])
        if (name in {"api", "core-worker", "ai-worker"} and ports) or any(
            not isinstance(port, str) or not port.startswith("127.0.0.1:")
            for port in ports
        ):
            raise RuntimeError(
                "Authored media recovery epoch rejects public service ports"
            )
    for name in ("api", "ai-worker"):
        environment = services[name].get("environment", {})
        if any(
            environment.get(key) != value
            for key, value in {**_FIXTURE_ENV, **_PRIVATE_ENDPOINTS}.items()
        ):
            raise RuntimeError(
                "Authored media recovery epoch requires private fixture endpoints"
            )
    for name in ("core-worker", "uploads"):
        environment = services[name].get("environment", {})
        if any(
            environment.get(key) != value
            for key, value in {
                **_PRIVATE_ENDPOINTS,
                "SERVER_ENVIRONMENT": "development",
                "MOCK_EXTERNAL_APIS": "true",
            }.items()
        ):
            raise RuntimeError(
                "Authored media recovery epoch requires private upload endpoints"
            )
    queue_options = [
        part
        for part in services["ai-worker"].get("command", [])
        if isinstance(part, str) and part.startswith("--queues=")
    ]
    if (
        queue_options != ["--queues=app_ai,app_ai_routing"]
        or services["ai-worker"]["environment"].get("CELERY_QUEUES")
        != "app_ai,app_ai_routing"
    ):
        raise RuntimeError(
            "Authored media recovery epoch requires the exact ordinary AI worker queues"
        )
    upload_env = services["uploads"].get("environment", {})
    if (
        any(
            upload_env.get(key) != value
            for key, value in {
                "CLAMAV_HOST": "clamav",
                "CLAMAV_PORT": "3310",
                "DEV_CORE_API_URL": "http://api:8000",
                "PROD_CORE_API_URL": "http://api:8000",
            }.items()
        )
        or services["clamav"].get("environment", {}).get("CLAMAV_NO_CLAMD") != "false"
        or services["uploads"].get("depends_on", {}).get("clamav")
        != {"condition": "service_healthy"}
        or "storage.ci.test"
        not in services["object-storage"]
        .get("networks", {})
        .get("default", {})
        .get("aliases", [])
    ):
        raise RuntimeError(
            "Authored media recovery epoch requires real isolated upload scanning and storage"
        )
    forbidden_flags = _OTHER_EPOCH_GUARDS | {
        _AUTHORED_MEDIA_GUARD,
        "OPENMATES_STORAGE_CAPACITY_FIXTURES",
        "OPENMATES_CI_PUBLIC_PROVIDER_PROXY",
    }
    for service in services.values():
        environment = service.get("environment", {})
        if (
            _PROXY_KEYS.intersection(environment)
            or forbidden_flags.intersection(environment)
            or service.get("network_mode") is not None
        ):
            raise RuntimeError(
                "Authored media recovery epoch rejects proxies, other fixtures and network modes"
            )
    try:
        result = compose(
            "exec",
            "-T",
            "-e",
            f"{_AUTHORED_MEDIA_GUARD}=1",
            "api",
            "python",
            "-c",
            AUTHORED_MEDIA_EPOCH_PROGRAM,
            capture=True,
            timeout=60,
        )
    except subprocess.CalledProcessError:
        raise RuntimeError(
            "Disposable authored media recovery epoch activation failed"
        ) from None
    try:
        receipt = json.loads(result.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Disposable authored media recovery epoch omitted its receipt"
        ) from exc
    if (
        receipt != _RECEIPT
        or type(receipt.get("protocol_epoch")) is not int
        or type(receipt.get("legacy_in_flight")) is not int
        or receipt.get("sends_paused") is not False
    ):
        raise RuntimeError(
            "Disposable authored media recovery epoch activation was incomplete"
        )
    return receipt
