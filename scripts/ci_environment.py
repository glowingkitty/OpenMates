"""Disposable OpenMates application stack for GitHub-hosted test jobs.

The GitHub VM supplies isolation. Images use cached dependencies and the exact
checkout supplies source; no dev-server environment or database is loaded.
Credentials are generated per environment and never returned in status output.
See docs/plans/isolated-github-tests/plan.yml.
"""

from __future__ import annotations

from copy import deepcopy
import secrets
import json
import os
from pathlib import Path
import subprocess
import sys

MIB = 1024**2
SOURCE = os.environ.get(
    "OPENMATES_CI_SOURCE_ROOT", str(Path(__file__).resolve().parent.parent)
)
QUEUES = "persistence,health_check,server_stats,user_init,user_tasks,email,push"
VAULT_INITIALIZE = """import asyncio, os, pathlib, requests
from backend.core.vault.setup.vault_setup.policies import PolicyManager
from backend.core.api.app.utils.vault_token_check import validate_token_file
url='http://vault:8200/v1/'
token=os.environ['VAULT_TOKEN']
headers={'X-Vault-Token':token}
for mount,body in [('kv',{'type':'kv','options':{'version':'2'}}),('transit',{'type':'transit'})]:
    response=requests.post(url+'sys/mounts/'+mount,headers=headers,json=body,timeout=15)
    if response.status_code != 204: response.raise_for_status()
data={'admin_log_api_key':os.environ['INTERNAL_API_SHARED_TOKEN']}
response=requests.post(url+'kv/data/providers/core_server',headers=headers,json={'data':data},timeout=15)
response.raise_for_status()
class Client:
    async def vault_request(self, method, path, data):
        response=requests.request(method, url+path, headers=headers, json=data, timeout=15)
        response.raise_for_status()
async def policies():
    manager=PolicyManager(Client())
    assert await manager.create_api_policy(), 'API service policy setup failed'
    assert await manager.create_api_encryption_policy(), 'API encryption policy setup failed'
asyncio.run(policies())
response=requests.post(url+'auth/token/create',headers=headers,json={'policies':['api-service','api-encryption'],'ttl':'2h','renewable':True},timeout=15)
response.raise_for_status()
pathlib.Path('/vault-data/api.token').write_text(response.json()['auth']['client_token'])
validation=asyncio.run(validate_token_file('http://vault:8200','/vault-data/api.token'))
assert validation.valid, 'Synthetic API token failed canonical startup validation: '+validation.reason
pathlib.Path('/vault-data/token.ready').write_text('synthetic runtime')
"""


def compose_profile(source_hash: str, *, ai_fixtures: bool = False) -> dict:
    """Return an independent profile; never interpolate the operator environment."""
    credentials = {
        name: secrets.token_hex(24)
        for name in (
            "database",
            "directus",
            "key",
            "cache",
            "internal",
            "admin",
            "vault",
        )
    }
    common = {
        "PYTHONPATH": "/app",
        "BUILD_COMMIT_SHA": source_hash,
        "PYTHONDONTWRITEBYTECODE": "1",
        "CMS_URL": "http://cms:8055",
        "DIRECTUS_TOKEN": credentials["directus"],
        "DATABASE_ADMIN_EMAIL": "runtime@example.com",
        "DATABASE_ADMIN_PASSWORD": credentials["admin"],
        "DRAGONFLY_URL": "cache:6379",
        "DRAGONFLY_PASSWORD": credentials["cache"],
        "VAULT_URL": "http://vault:8200",
        "INTERNAL_API_SHARED_TOKEN": credentials["internal"],
        "SERVER_ENVIRONMENT": "development",
        "OPENMATES_DEPLOYMENT_MODE": "self_host",
        "MOCK_EXTERNAL_APIS": "true",
        "SIGNUP_TEST_EMAIL_DOMAINS": "example.com",
        "SELF_HOST_SIGNUP_MODE": "invite_only",
        "TRANSLATIONS_DIR": "/translations",
        "APPLICATION_PREVIEW_ORIGIN": "http://localhost:5173",
        "FRONTEND_URLS": "http://localhost:5173",
        "PRODUCTION_URL": "http://localhost:5173",
        "E2E_TEST_DEV_ENABLED": "false",
        "E2E_TEST_PROD_ENABLED": "false",
        "CELERY_AUTOSCALE_MAX": "1",
    }
    source_mounts = [
        f"{SOURCE}/backend:/app/backend:ro",
        f"{SOURCE}/shared:/shared:ro",
        f"{SOURCE}/backend/config:/config:ro",
        f"{SOURCE}/frontend/packages/ui/src/i18n/locales:/translations:ro",
        f"{SOURCE}/frontend/packages/ui/src/i18n:/app/frontend/packages/ui/src/i18n:ro",
        "api-logs:/app/logs",
        "backend-logs:/app/backend/core/api/logs",
        "api-cache:/app/backend/apps/ai/testing/api_cache",
        "vault-tokens:/vault-data",
    ]
    api = {
        "build": {"context": SOURCE, "dockerfile": "backend/core/api/Dockerfile"},
        "image": "openmates-ci-api:local",
        "environment": common,
        "volumes": source_mounts,
        "command": ["sh", "/app/backend/core/api/wait-for-vault.sh"],
        "ports": ["8000:8000"],
        "mem_limit": 1536 * MIB,
        "depends_on": {
            "cms-setup": {"condition": "service_completed_successfully"},
            "vault-init": {"condition": "service_completed_successfully"},
            "fixture-init": {"condition": "service_completed_successfully"},
        },
        "healthcheck": {
            "test": ["CMD", "curl", "-f", "http://localhost:8000/health"],
            "interval": "5s",
            "timeout": "5s",
            "retries": 24,
        },
    }
    worker = deepcopy(api)
    worker.pop("build")
    worker.pop("ports")
    worker.pop("healthcheck")
    worker["environment"] = {**common, "CELERY_QUEUES": QUEUES}
    worker["command"] = [
        "python",
        "-m",
        "celery",
        "-A",
        "backend.core.api.app.tasks.celery_config",
        "worker",
        "--loglevel=warning",
        f"--queues={QUEUES}",
        "--concurrency=1",
        "--max-tasks-per-child=50",
    ]
    worker["mem_limit"] = 1536 * MIB
    services = {
        "api": api,
        "core-worker": worker,
        "cms-database": {
            "image": "postgres:13-alpine",
            "mem_limit": 512 * MIB,
            "environment": {
                "POSTGRES_DB": "openmates",
                "POSTGRES_USER": "openmates",
                "POSTGRES_PASSWORD": credentials["database"],
            },
            "volumes": ["postgres:/var/lib/postgresql/data"],
            "healthcheck": {
                "test": ["CMD-SHELL", "pg_isready -U openmates"],
                "interval": "3s",
                "timeout": "3s",
                "retries": 30,
            },
        },
        "cache": {
            "image": "redis:7-alpine",
            "mem_limit": 384 * MIB,
            "command": [
                "redis-server",
                "--requirepass",
                credentials["cache"],
                "--maxmemory",
                "256mb",
                "--maxmemory-policy",
                "noeviction",
            ],
            "volumes": ["redis:/data"],
            "healthcheck": {
                "test": ["CMD", "redis-cli", "-a", credentials["cache"], "ping"],
                "interval": "3s",
                "timeout": "3s",
                "retries": 30,
            },
        },
        "cms": {
            "build": {"context": f"{SOURCE}/backend/core/directus"},
            "image": "openmates-ci-cms:local",
            "mem_limit": 768 * MIB,
            "environment": {
                "KEY": credentials["key"],
                "SECRET": credentials["key"],
                "ADMIN_EMAIL": "runtime@example.com",
                "ADMIN_PASSWORD": credentials["admin"],
                "DB_CLIENT": "pg",
                "DB_HOST": "cms-database",
                "DB_PORT": "5432",
                "DB_DATABASE": "openmates",
                "DB_USER": "openmates",
                "DB_PASSWORD": credentials["database"],
                "INTERNAL_API_SHARED_TOKEN": credentials["internal"],
                "PUBLIC_URL": "http://localhost:8055",
                "CACHE_ENABLED": "false",
                "TELEMETRY": "false",
            },
            "volumes": ["uploads:/directus/uploads"],
            "ports": ["8055:8055"],
            "depends_on": {"cms-database": {"condition": "service_healthy"}},
        },
        "cms-setup": {
            "build": {"context": f"{SOURCE}/backend/core/directus/setup"},
            "image": "openmates-ci-setup:local",
            "mem_limit": 512 * MIB,
            "environment": {
                "DATABASE_ADMIN_EMAIL": "runtime@example.com",
                "DATABASE_ADMIN_PASSWORD": credentials["admin"],
                "ADMIN_EMAIL": "runtime@example.com",
                "ADMIN_PASSWORD": credentials["admin"],
                "DIRECTUS_TOKEN": credentials["directus"],
                "INTERNAL_API_SHARED_TOKEN": credentials["internal"],
                "SCHEMAS_DIR": "/usr/src/app/schemas",
                "DB_HOST": "cms-database",
                "DB_DATABASE": "openmates",
                "DB_USER": "openmates",
                "DB_PASSWORD": credentials["database"],
            },
            "volumes": [
                f"{SOURCE}/backend/core/directus/schemas:/usr/src/app/schemas:ro",
                f"{SOURCE}/backend/core/directus/setup:/usr/src/app/migrations:ro",
            ],
            "depends_on": {"cms": {"condition": "service_started"}},
        },
        "vault": {
            "image": "hashicorp/vault:1.19",
            "mem_limit": 512 * MIB,
            "environment": {
                "VAULT_DEV_ROOT_TOKEN_ID": credentials["vault"],
                "GOMEMLIMIT": "384MiB",
                "VAULT_DEV_LISTEN_ADDRESS": "0.0.0.0:8200",
            },
            "command": ["server", "-dev", "-log-level=warn"],
            "cap_add": ["IPC_LOCK"],
            "healthcheck": {
                "test": [
                    "CMD",
                    "wget",
                    "-q",
                    "--spider",
                    "http://127.0.0.1:8200/v1/sys/health",
                ],
                "interval": "3s",
                "timeout": "3s",
                "retries": 30,
            },
        },
        "vault-init": {
            "image": "openmates-ci-api:local",
            "mem_limit": 128 * MIB,
            "command": ["python", "-c", VAULT_INITIALIZE],
            "environment": {
                "VAULT_TOKEN": credentials["vault"],
                "INTERNAL_API_SHARED_TOKEN": credentials["internal"],
            },
            "volumes": ["vault-tokens:/vault-data"],
            "depends_on": {"vault": {"condition": "service_healthy"}},
        },
    }
    if ai_fixtures:
        # Existing committed TEST_MOCK fixtures still traverse the real API/worker.
        # The internal network prevents paid providers or shared-server egress.
        ai_worker = deepcopy(worker)
        ai_worker["environment"]["CELERY_QUEUES"] = "app_ai"
        ai_worker["command"] = [part.replace(f"--queues={QUEUES}", "--queues=app_ai") for part in worker["command"]]
        ai_worker["mem_limit"] = 1536 * MIB
        services["ai-worker"] = ai_worker

    services["fixture-init"] = {
        "image": "openmates-ci-api:local",
        "mem_limit": 128 * MIB,
        "command": [
            "sh",
            "-ec",
            "cp -a /app/backend/apps/ai/testing/api_cache/. /fixtures/",
        ],
        "volumes": ["api-cache:/fixtures"],
    }
    volumes = {}
    for service in services.values():
        service.update(
            labels={"org.openmates.source": source_hash},
            extra_hosts={
                "api.dev.openmates.org": "127.0.0.2",
                "app.dev.openmates.org": "127.0.0.2",
            },
            restart="no",
            pids_limit=512,
            logging={
                "driver": "json-file",
                "options": {"max-size": "5m", "max-file": "2"},
            },
        )
        mounts = []
        for mount in service.get("volumes", []):
            if not mount.startswith("/"):
                name, target = mount.split(":", 1)
                volumes[name] = {}
                mounts.append(
                    {
                        "type": "volume",
                        "source": name,
                        "target": target,
                        "volume": {"nocopy": True},
                    }
                )
            else:
                mounts.append(mount)
        if mounts:
            service["volumes"] = mounts
    profile = {"name": "openmates-ci", "services": services, "volumes": volumes}
    if ai_fixtures:
        profile["networks"] = {"default": {"internal": True}}
    return profile


COMPOSE_PATH = Path(SOURCE) / "test-results/ci-private/compose.json"


def require_runner():
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
    ):
        raise RuntimeError("Isolated test stacks run only on GitHub-hosted runners")


def compose(*args, capture=False, timeout=90):
    require_runner()
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_PATH), *args],
        cwd=SOURCE,
        check=True,
        text=True,
        capture_output=capture,
        timeout=timeout,
    )


def main():
    require_runner()
    action = sys.argv[1]
    if action == "prepare":
        source = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True
        ).strip()
        manifest = json.loads(Path(__file__).with_name("ci_coverage_manifest.json").read_text())
        fixture_specs = set(manifest["groups"].get("ai_committed_fixtures", {}).get("specs", []))
        selected = json.loads(os.environ.get("CI_SPECS_JSON", "[]"))
        data = compose_profile(source, ai_fixtures=bool(fixture_specs.intersection(selected)))
        # Docker cannot create nested mountpoints inside a read-only bind.
        # These ignored directories contain only runner-local runtime output.
        for relative in ("backend/core/api/logs", "backend/apps/ai/testing/api_cache"):
            (Path(SOURCE) / relative).mkdir(parents=True, exist_ok=True)
        COMPOSE_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        COMPOSE_PATH.write_text(json.dumps(data))
        COMPOSE_PATH.chmod(0o600)
        evidence = {
            "source_commit": source,
            "run_id": os.environ["GITHUB_RUN_ID"],
            "environment": "github-isolated",
            "harness_commit": os.environ.get("CI_HARNESS_COMMIT"),
        }
        (Path(SOURCE) / "test-results/ci-environment.json").write_text(
            json.dumps(evidence)
        )
    elif action == "start":
        # Compose's wait limit may not bound one-shot dependency startup.
        compose(
            "up", "-d", "--no-build", "--wait", "--wait-timeout", "600", timeout=720
        )
    elif action == "verify":
        import socket
        import urllib.request

        evidence_path = Path(SOURCE) / "test-results/ci-environment.json"
        evidence = json.loads(evidence_path.read_text())
        for host in ("api.dev.openmates.org", "app.dev.openmates.org"):
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            }
            if addresses != {"127.0.0.2"}:
                raise RuntimeError("Shared dev DNS isolation was not installed")
            try:
                connection = socket.create_connection((host, 443), timeout=2)
            except OSError:
                pass
            else:
                connection.close()
                raise RuntimeError("Shared dev HTTPS egress was unexpectedly reachable")
        with urllib.request.urlopen(
            "http://localhost:8000/health", timeout=10
        ) as response:
            if response.status != 200:
                raise RuntimeError("Runner-local API is not healthy")
        identities = {}
        profile = json.loads(COMPOSE_PATH.read_text())
        required = ["api", "core-worker", "cms", "cms-database", "cache", "vault"]
        if "ai-worker" in profile["services"]:
            required.append("ai-worker")
            network = json.loads(subprocess.check_output(["docker", "network", "inspect", "openmates-ci_default"], text=True))[0]
            if network.get("Internal") is not True:
                raise RuntimeError("Fixture AI profile must reject external network access")
            evidence["provider_egress"] = "rejected-internal-network"
        for service in required:
            container = compose("ps", "-q", service, capture=True).stdout.strip()
            if not container:
                raise RuntimeError("Required private service is missing: " + service)
            raw = subprocess.check_output(["docker", "inspect", container], text=True)
            info = json.loads(raw)[0]
            if (
                info["Config"]["Labels"].get("org.openmates.source")
                != evidence["source_commit"]
            ):
                raise RuntimeError("Runtime source identity mismatch")
            identities[service] = {
                "container": container,
                "image": info["Image"],
                "running": info["State"]["Running"],
            }
            if not info["State"]["Running"]:
                raise RuntimeError("Private service exited: " + service)
            if service in ("api", "core-worker", "ai-worker"):
                mounts = [
                    mount
                    for mount in info["Mounts"]
                    if mount["Destination"] == "/app/backend"
                ]
                if (
                    len(mounts) != 1
                    or Path(mounts[0]["Source"]).resolve()
                    != Path(SOURCE, "backend").resolve()
                    or mounts[0]["RW"]
                ):
                    raise RuntimeError(
                        "Backend must mount the exact candidate source read-only"
                    )
                identities[service]["backend_source"] = mounts[0]["Source"]
        evidence.update(
            services=identities,
            api_url="http://localhost:8000",
            web_url="http://localhost:5173",
            shared_dev_dns="rejected",
            shared_dev_https="rejected",
            runner_environment=os.environ["RUNNER_ENVIRONMENT"],
        )
        evidence_path.write_text(json.dumps(evidence, indent=2))
    elif action == "stop":
        if COMPOSE_PATH.exists():
            compose("down", "--volumes", "--remove-orphans", "--timeout", "20")
    elif action == "logs":
        if COMPOSE_PATH.exists():
            result = compose("logs", "--no-color", "--tail", "150", capture=True)
            # Generated secrets are replaced before logs become uploaded artifacts.
            profile = json.loads(COMPOSE_PATH.read_text())
            output = result.stdout
            containers = compose("ps", "-aq", capture=True).stdout.split()
            for container in containers:
                state = subprocess.check_output(
                    ["docker", "inspect", "--format", "{{json .State}}", container],
                    text=True, timeout=20,
                )
                output += "\nContainer " + container + " state: " + state
            for service in profile["services"].values():
                for key, value in service.get("environment", {}).items():
                    if (
                        any(
                            word in key
                            for word in ("TOKEN", "PASSWORD", "SECRET", "KEY")
                        )
                        and len(str(value)) > 8
                    ):
                        output = output.replace(str(value), "<REDACTED>")
            (Path(SOURCE) / "test-results/ci-stack.log").write_text(output)
    else:
        raise ValueError("Unknown CI environment action")


if __name__ == "__main__":
    main()
