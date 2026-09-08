"""Disposable OpenMates application stack for GitHub-hosted test jobs.

The GitHub VM supplies isolation. Images use cached dependencies and the exact
checkout supplies source; no dev-server environment or database is loaded.
Credentials are generated per environment and never returned in status output.
See docs/plans/isolated-github-tests/plan.yml.
"""

from __future__ import annotations

from copy import deepcopy
import secrets
import shutil
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
if os.environ.get('CI_STORAGE_ACCESS_KEY'):
    data={'s3_access_key':os.environ['CI_STORAGE_ACCESS_KEY'],'s3_secret_key':os.environ['CI_STORAGE_SECRET_KEY'],'s3_region_name':'nbg1'}
    response=requests.post(url+'kv/data/providers/hetzner',headers=headers,json={'data':data},timeout=15)
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


STORAGE_VERIFY = """import os, pathlib, requests, boto3
from botocore.config import Config
token=pathlib.Path('/vault-data/api.token').read_text().strip()
response=requests.get('http://vault:8200/v1/kv/data/providers/hetzner',headers={'X-Vault-Token':token},timeout=10)
response.raise_for_status()
keys=response.json()['data']['data']
client=boto3.client('s3',endpoint_url=os.environ['S3_ENDPOINT_URL'],region_name='nbg1',aws_access_key_id=keys['s3_access_key'],aws_secret_access_key=keys['s3_secret_key'],config=Config(signature_version='s3v4',s3={'addressing_style':'path'},connect_timeout=5,read_timeout=10))
bucket='ci-probe'; key='protocol-proof'; content=b'isolated-s3-roundtrip'
try:
    client.put_object(Bucket=bucket,Key=key,Body=content)
    assert client.get_object(Bucket=bucket,Key=key)['Body'].read()==content
    client.put_bucket_cors(Bucket=bucket,CORSConfiguration={'CORSRules':[{'AllowedOrigins':['http://localhost:5173'],'AllowedMethods':['GET'],'AllowedHeaders':['*']}]})
    assert client.get_bucket_cors(Bucket=bucket)['CORSRules'][0]['AllowedOrigins']==['http://localhost:5173']
    signed=client.generate_presigned_url('get_object',Params={'Bucket':bucket,'Key':key},ExpiresIn=60)
    assert requests.get(signed,timeout=10).content==content
    assert requests.get(os.environ['S3_ENDPOINT_URL']+'/'+bucket+'/'+key,timeout=10).status_code==403
finally:
    client.delete_object(Bucket=bucket,Key=key)
print('authenticated-roundtrip-cors-presigned-and-private-access-passed')
"""


WORKFLOW_SCHEDULER = """from backend.core.api.app.tasks.celery_config import app
# Keep only the existing workflow scanner and its original interval. Never
# schedule user AI assignments, provider probes, email campaigns or other cron.
schedule={name:entry for name,entry in app.conf.beat_schedule.items() if entry.get('task')=='workflows.scan_due_triggers'}
assert len(schedule)==1, 'Canonical workflow scanner schedule is missing or ambiguous'
app.conf.beat_schedule=schedule
app.start(['beat','--loglevel=warning','--schedule=/tmp/ci-workflows-schedule','--pidfile=/tmp/ci-workflows.pid'])
"""


def compose_profile(source_hash: str, *, ai_fixtures: bool = False, object_storage: bool = False, uploads: bool = False, public_provider: bool = False, workflows: bool = False, account_emails: list[str] | None = None) -> dict:
    """Return an independent profile; never interpolate the operator environment."""
    ai_fixtures = ai_fixtures or public_provider
    object_storage = object_storage or uploads
    isolate_backend = ai_fixtures or object_storage
    if workflows and isolate_backend:
        raise ValueError("Credential-free weather workflows require a separate batch from offline replay/storage")
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
            "storage_key",
            "storage_secret",
        )
    }
    fresh_emails = account_emails or []
    if len(set(fresh_emails)) != len(fresh_emails) or any(not email.endswith("@example.com") or not email.startswith("ci-") for email in fresh_emails):
        raise ValueError("CI account allowlist requires unique generated example.com identities")
    common = {
        **{f"OPENMATES_TEST_ACCOUNT_CI_{index}_EMAIL": email for index, email in enumerate(fresh_emails)},
        "PYTHONPATH": "/app",
        "BACKEND_CONFIG_FILE": "/app/backend/config/backend_config.dev.yml",
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
    if object_storage:
        common.update(S3_ENDPOINT_URL="http://storage.ci.test:9000", S3_REGIONS="nbg1")
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
    if object_storage:
        # Real S3 SDK operations hit a disposable store, never shared buckets.
        services["object-storage"] = {
            "image": "chrislusf/seaweedfs@sha256:0a94aac557ead0a6b3350df86b2d4fea0a5793590e1fbf5f35d41cac0dc22b40",
            "command": ["mini", "-dir=/data", "-s3.port=9000"],
            "environment": {"AWS_ACCESS_KEY_ID": credentials["storage_key"], "AWS_SECRET_ACCESS_KEY": credentials["storage_secret"], "S3_BUCKET": "ci-probe"},
            "volumes": ["object-storage:/data"],
            "ports": ["127.0.0.1:9000:9000"],
            "networks": {"default": {"aliases": ["storage.ci.test"]}},
            "mem_limit": 512 * MIB,
            "healthcheck": {"test": ["CMD-SHELL", "curl -sS -o /dev/null -w '%{http_code}' http://localhost:9000/ | grep -q '^403$'"], "interval": "3s", "timeout": "3s", "retries": 30},
        }
        for name in ("api", "core-worker"):
            services[name]["depends_on"]["object-storage"] = {"condition": "service_healthy"}
        services["vault-init"]["environment"].update(CI_STORAGE_ACCESS_KEY=credentials["storage_key"], CI_STORAGE_SECRET_KEY=credentials["storage_secret"])
    if uploads:
        services["clamav"] = {
            "image": "clamav/clamav-debian@sha256:5037bae34bf7566052d18f30be1e351155bfce845a583f0c08027f9fcaa44b5d",
            "environment": {"CLAMAV_NO_FRESHCLAMD": "false", "CLAMAV_NO_CLAMD": "false", "CLAMAV_NO_MILTERD": "true"},
            "volumes": ["clamav-db:/var/lib/clamav"], "mem_limit": 2048 * MIB,
            "healthcheck": {"test": ["CMD", "/usr/local/bin/clamdcheck.sh"], "interval": "10s", "timeout": "10s", "retries": 30, "start_period": "120s"},
        }
        services["uploads"] = {
            "image": "openmates-ci-upload:local",
            "build": {"context": SOURCE, "dockerfile": "backend/upload/Dockerfile"},
            "environment": {**common, "CLAMAV_HOST": "clamav", "CLAMAV_PORT": "3310", "UPLOADS_APP_INTERNAL_PORT": "8000", "DEV_CORE_API_URL": "http://api:8000", "PROD_CORE_API_URL": "http://api:8000", "DEV_INTERNAL_API_SHARED_TOKEN": credentials["internal"], "PROD_INTERNAL_API_SHARED_TOKEN": credentials["internal"]},
            "volumes": [f"{SOURCE}/backend:/app/backend:ro", {"type": "volume", "source": "vault-tokens", "target": "/vault-data", "read_only": True, "volume": {"nocopy": True}}],
            "ports": ["127.0.0.1:8001:8000"], "mem_limit": 1024 * MIB,
            "depends_on": {"clamav": {"condition": "service_healthy"}, "object-storage": {"condition": "service_healthy"}, "vault-init": {"condition": "service_completed_successfully"}, "api": {"condition": "service_healthy"}},
            "healthcheck": {"test": ["CMD", "curl", "-f", "http://localhost:8000/health"], "interval": "5s", "timeout": "5s", "retries": 30},
        }
    if ai_fixtures:
        # Existing committed TEST_MOCK fixtures still traverse the real API/worker.
        # The internal network prevents paid providers or shared-server egress.
        ai_worker = deepcopy(worker)
        ai_worker["environment"]["CELERY_QUEUES"] = "app_ai"
        ai_worker["command"] = [part.replace(f"--queues={QUEUES}", "--queues=app_ai") for part in worker["command"]]
        ai_worker["mem_limit"] = 1536 * MIB
        services["ai-worker"] = ai_worker
    if isolate_backend:
        api.pop("ports")
        services["cms"].pop("ports")
        services["runner-gateway"] = {
            "image": "openmates-ci-api:local",
            "command": ["python", "/ci_tcp_gateway.py"],
            "environment": {"OPENMATES_CI_GATEWAY": "github-isolated"},
            "volumes": [str(Path(__file__).with_name("ci_tcp_gateway.py").resolve()) + ":/ci_tcp_gateway.py:ro"],
            "ports": ["127.0.0.1:8000:8000", "127.0.0.1:8055:8055"],
            "networks": ["default", "ingress"],
            "mem_limit": 64 * MIB,
        }

    if public_provider:
        services["runner-gateway"]["environment"]["OPENMATES_CI_PUBLIC_PROVIDER_PROXY"] = "1"
        for service in (api, worker, services["ai-worker"]):
            service["environment"]["HTTPS_PROXY"] = "http://runner-gateway:3128"
        # Port3128 is internal only. All other provider authorities are denied;
        # API/AI workers still cannot use direct outbound network connections.

    if workflows:
        workflow_queues = QUEUES + ",workflow"
        worker["environment"]["CELERY_QUEUES"] = workflow_queues
        worker["command"] = [part.replace(f"--queues={QUEUES}", f"--queues={workflow_queues}") for part in worker["command"]]
        scheduler = deepcopy(worker)
        scheduler["command"] = ["python", "-c", WORKFLOW_SCHEDULER]
        scheduler["mem_limit"] = 128 * MIB
        services["workflow-scheduler"] = scheduler
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
            if isinstance(mount, dict):
                volumes[mount["source"]] = {}
                mounts.append(mount)
            elif not mount.startswith("/"):
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
    if isolate_backend and object_storage:
        services["object-storage"]["networks"]["ingress"] = {}
    if isolate_backend and uploads:
        for name in ("uploads", "clamav"):
            services[name]["networks"] = ["default", "ingress"]
    if isolate_backend:
        profile["networks"] = {"default": {"internal": True}, "ingress": {}}
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
        fixture_specs = {spec for group in ("ai_committed_fixtures", "ai_cached_pipeline", "ai_cached_public_provider") for spec in manifest["groups"].get(group, {}).get("specs", [])}
        selected = json.loads(os.environ.get("CI_SPECS_JSON", "[]"))
        if not (Path(SOURCE) / "backend/config/backend_config.dev.yml").is_file():
            raise RuntimeError("Candidate lacks committed development feature configuration")
        account_emails = [f"ci-{secrets.token_hex(16)}@example.com" for _ in range(2 * len(selected))]
        storage_specs = set(manifest["groups"].get("object_storage", {}).get("specs", []))
        upload_specs = set(manifest["groups"].get("uploads", {}).get("specs", []))
        needs_uploads = bool(upload_specs.intersection(selected))
        public_specs = set(manifest["groups"].get("ai_cached_public_provider", {}).get("specs", []))
        needs_public_provider = bool(public_specs.intersection(selected))
        workflow_specs = set(manifest["groups"].get("workflow_weather", {}).get("specs", []))
        needs_workflows = bool(workflow_specs.intersection(selected))
        if needs_workflows and not set(selected).issubset(workflow_specs):
            raise RuntimeError("Credential-free weather workflows require their own batch")
        needs_storage = bool(storage_specs.intersection(selected)) or needs_uploads
        if needs_storage:
            for relative in ("backend/core/api/app/services/s3/service.py", "backend/upload/services/s3_upload.py"):
                if "S3_ENDPOINT_URL" not in (Path(SOURCE) / relative).read_text():
                    raise RuntimeError("Candidate lacks isolated storage endpoint support; publish reviewed current-base integration before testing")
        data = compose_profile(source, ai_fixtures=bool(fixture_specs.intersection(selected)), object_storage=needs_storage, uploads=needs_uploads, public_provider=needs_public_provider, workflows=needs_workflows, account_emails=account_emails)
        if os.environ.get("GITHUB_OUTPUT"):
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                output.write(f"uploads={'true' if needs_uploads else 'false'}\n")
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
        if "workflow-scheduler" in profile["services"]:
            required.append("workflow-scheduler")
            evidence["workflow_scheduler"] = {"task": "workflows.scan_due_triggers", "other_periodic_tasks": "excluded", "providers": ["Bright Sky / DWD", "Open-Meteo"], "paid_provider_credentials": "absent"}
        if "uploads" in profile["services"]:
            required.extend(["uploads", "clamav"])
        if "object-storage" in profile["services"]:
            required.append("object-storage")
        if "ai-worker" in profile["services"]:
            required.extend(["ai-worker", "runner-gateway"])
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
            if service in ("api", "core-worker", "ai-worker", "uploads", "workflow-scheduler"):
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
        if profile["services"].get("runner-gateway", {}).get("environment", {}).get("OPENMATES_CI_PUBLIC_PROVIDER_PROXY") == "1":
            compose("exec", "-T", "api", "python", "-c", "import socket; s=socket.create_connection(('runner-gateway',3128),timeout=5); s.sendall(b'CONNECT api.openai.com:443 HTTP/1.1\\r\\n\\r\\n'); assert b'403 Forbidden' in s.recv(256); s.close()", capture=True, timeout=10)
            evidence["public_provider_proxy"] = {"allowed_https_hosts": ["webench.ti.com"], "paid_provider_authority": "rejected before upstream connection", "direct_backend_egress": "internal Docker network", "tls": "end-to-end, no interception"}
        if "object-storage" in profile["services"]:
            if socket.gethostbyname("storage.ci.test") != "127.0.0.1":
                raise RuntimeError("Object storage must resolve on this runner")
            compose("exec", "-T", "api", "python", "-c", STORAGE_VERIFY, capture=True, timeout=60)
            evidence["object_storage"] = {"endpoint": "http://storage.ci.test:9000", "provider": "SeaweedFS", "protocol_probe": "authenticated-roundtrip-cors-presigned-and-private-access-passed", "region_scope": "single disposable region; Hetzner failover not covered"}
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
            for kind, command in (("containers", ["docker", "ps", "-aq"]), ("volumes", ["docker", "volume", "ls", "-q"])):
                remaining = subprocess.check_output([*command, "--filter", "label=com.docker.compose.project=openmates-ci"], text=True).strip()
                if remaining:
                    raise RuntimeError("Disposable runtime cleanup left " + kind)
            private = COMPOSE_PATH.parent.resolve()
            expected = (Path(SOURCE) / "test-results/ci-private").resolve()
            if private != expected or private == Path(SOURCE).resolve():
                raise RuntimeError("Refusing cleanup outside the runner-private account directory")
            shutil.rmtree(private)
            (Path(SOURCE) / "test-results/ci-cleanup.json").write_text(json.dumps({
                "run_id": os.environ["GITHUB_RUN_ID"], "harness_commit": os.environ.get("CI_HARNESS_COMMIT"),
                "containers_remaining": 0, "volumes_remaining": 0, "private_account_files_removed": True
            }))
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
