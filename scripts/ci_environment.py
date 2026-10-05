"""Disposable OpenMates application stack for GitHub-hosted test jobs.

The GitHub VM supplies isolation. Images use cached dependencies and the exact
checkout supplies source; no dev-server environment or database is loaded.
Credentials are generated per environment and never returned in status output.
See docs/plans/isolated-github-tests/plan.yml.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import math
import secrets
import shutil
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import signal

MIB = 1024**2
GIB = 1024**3
TARGET_SLOTS = 500
TARGET_SLOTS_PER_WORKER = 4
TARGET_OPERATIONS = 1_700_000
STORAGE_CAPACITY_SPECS = frozenset({
    "storage-capacity-replay.spec.ts",
    "storage-capacity-calibration.spec.ts",
    "storage-message-embed-bundle.spec.ts",
    "storage-capacity-target.spec.ts",
    "storage-recovery-replay.spec.ts",
    "storage-recovery-canonical-receipts.spec.ts",
    "storage-detached-producer.spec.ts",
    "wiki-learning-flow.spec.ts",
})
ACCOUNTABILITY_SPEC = "storage-accountability-integration.spec.ts"
BILLING_STORAGE_PROFILES = {
    "billing-storage-legacy.spec.ts": "legacy",
    "billing-storage-logical.spec.ts": "logical",
}
CAPACITY_WORKLOAD_SPECS = frozenset({
    "storage-capacity-replay.spec.ts", "storage-capacity-calibration.spec.ts",
    "storage-capacity-target.spec.ts",
})
SOURCE = os.environ.get(
    "OPENMATES_CI_SOURCE_ROOT", str(Path(__file__).resolve().parent.parent)
)
QUEUES = "persistence,health_check,server_stats,user_init,user_tasks,email,push"
STACK_START_RETRY_DELAYS = (5, 15)
TRANSIENT_REGISTRY_FAILURE = re.compile(
    r"connection reset by peer|tls handshake timeout|i/o timeout|"
    r"timeout awaiting response headers|unexpected eof|temporary failure|"
    r"too many requests",
    re.IGNORECASE,
)
PREPARED_SCHEMA_ADMIN_PASSWORD = "openmates-ci-prepared-schema-admin-v1"
# These values are part of the prepared-schema compatibility contract. Bump the
# bundle format when the carrier contents change, and the restore semantics when
# a consumer interprets or activates those contents differently.
SCHEMA_BUNDLE_FORMAT = "openmates-postgres-plain-gzip-v3"
SCHEMA_RESTORE_SEMANTICS = "fresh-volume-directus-credential-rotation-v2"
POSTGRES_IMAGE = (
    "postgres:13-alpine@sha256:"
    "fb9065b6e3e213bdc07edd372a5b2a26245840b7fb65d1fd8b6700106d51805c"
)
MAILPIT_IMAGE = "axllent/mailpit:v1.27.4@sha256:df6c2541907e1be6fac21f509927cf6ed771617a1f4b361ef66d97bd05593d2d"
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
if os.environ.get('CI_UPLOADS') == '1':
    import httpx
    from backend.upload.vault import setup_vault
    from backend.upload.vault.token_maintenance import renew_api_token
    async def upload_token():
        async with httpx.AsyncClient(timeout=15) as client:
            await setup_vault.create_policy(client, token)
            await setup_vault.create_or_reuse_api_token(client, token)
            await renew_api_token(client, 'http://vault:8200', setup_vault.API_TOKEN_FILE)
    asyncio.run(upload_token())
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


def admit_target_capacity(
    calibration: dict, *, source_commit: str, runner_environment: str,
    profile: str, available_memory_bytes: int, available_disk_bytes: int,
    job_timeout_seconds: int,
) -> dict:
    """Calculate a target gate from same-source, measured aggregate peaks.

    A trusted CI producer must supply this schema; hand-authored values are not
    an admission receipt. The final acceptance still needs 500 overlapping
    server task intervals on the isolated host.
    """
    if runner_environment != "self-hosted":
        raise RuntimeError("Full capacity target requires a dedicated self-hosted runner")
    if not isinstance(calibration, dict):
        raise RuntimeError("Full capacity calibration must be a JSON object")
    if (type(calibration.get("schema")) is not int or calibration["schema"] != 2
            or calibration.get("source_commit") != source_commit
            or calibration.get("pilot_passed") is not True):
        raise RuntimeError("Full capacity target needs passing same-source measured calibration v2")
    if (calibration.get("worker_container_peak_metric") not in
            {"cgroup_v2_memory_peak", "cgroup_v1_max_usage"}
            or calibration.get("driver_peak_metric") != "process_rss_peak"
            or calibration.get("fixed_stack_peak_metric") != "sum_cgroup_memory_peak"
            or type(calibration.get("observed_worker_slots")) is not int
            or calibration["observed_worker_slots"] != TARGET_SLOTS_PER_WORKER
            or type(calibration.get("observed_worker_task_receipts")) is not int
            or calibration["observed_worker_task_receipts"] < 16
            or type(calibration.get("driver_sample_threads")) is not int
            or calibration["driver_sample_threads"] < 2):
        raise RuntimeError("Full capacity calibration lacks four-slot cgroup and driver sampling provenance")
    fields = ("worker_container_peak_bytes", "driver_idle_peak_bytes",
              "driver_sample_peak_bytes", "fixed_stack_peak_bytes",
              "disk_bytes_per_operation", "measured_operations_per_second")
    if any(type(calibration.get(field)) not in (int, float)
           or not 0 < calibration[field] <= 2**63 - 1
           or not math.isfinite(calibration[field]) for field in fields):
        raise RuntimeError("Full capacity calibration lacks finite measured resource values")
    if calibration["driver_sample_peak_bytes"] <= calibration["driver_idle_peak_bytes"]:
        raise RuntimeError("Full capacity driver sample must exceed its measured idle baseline")
    if any(type(value) is not int or value <= 0 for value in
           (available_memory_bytes, available_disk_bytes, job_timeout_seconds)):
        raise RuntimeError("Full capacity target resource measurements must be positive integers")
    worker_limit = 1536 * MIB  # A ceiling for each replica, not a RAM reservation.
    replicas = TARGET_SLOTS // TARGET_SLOTS_PER_WORKER
    worker_peak = calibration["worker_container_peak_bytes"]
    headroom = 1.5
    if worker_peak * headroom > worker_limit:
        raise RuntimeError("Measured four-slot worker cannot fit its container ceiling with headroom")
    driver_increment_per_thread = ((calibration["driver_sample_peak_bytes"] -
                                    calibration["driver_idle_peak_bytes"]) /
                                   calibration["driver_sample_threads"])
    projected_driver_peak = calibration["driver_idle_peak_bytes"] + TARGET_SLOTS * driver_increment_per_thread
    memory_required = math.ceil(headroom * (
        replicas * worker_peak + projected_driver_peak + calibration["fixed_stack_peak_bytes"]
    ))
    disk_required = math.ceil(max(20 * GIB, 2 * TARGET_OPERATIONS * calibration["disk_bytes_per_operation"]))
    # Pilot rate is only a planning bound; actual target throughput is measured.
    time_required = max(7200, math.ceil(2 * TARGET_OPERATIONS /
        calibration["measured_operations_per_second"]))
    if profile not in {"accelerated", "burst", "sustained"}:
        raise RuntimeError("Unsupported target rate profile")
    if available_memory_bytes < memory_required:
        raise RuntimeError("Full capacity target has insufficient measured available memory")
    if available_disk_bytes < disk_required:
        raise RuntimeError("Full capacity target has insufficient measured free disk")
    if job_timeout_seconds < time_required:
        raise RuntimeError("Full capacity target job timeout is shorter than measured workload allowance")
    return {"worker_slots": TARGET_SLOTS, "worker_replicas": replicas,
            "memory_required_bytes": memory_required, "disk_required_bytes": disk_required,
            "job_timeout_required_seconds": time_required, "profile": profile,
            "source_commit": source_commit, "worker_container_peak_bytes": worker_peak,
            "worker_container_peak_metric": calibration["worker_container_peak_metric"]}


def _available_target_memory_bytes() -> int:
    try:
        available = next(
            int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines()
            if line.startswith("MemAvailable:")
        )
    except (OSError, ValueError, StopIteration) as exc:
        raise RuntimeError("Cannot measure available host memory for target admission") from exc
    cgroup = Path("/sys/fs/cgroup")
    v2_limit = cgroup / "memory.max"
    v1_limit = cgroup / "memory/memory.limit_in_bytes"
    try:
        if v2_limit.exists():
            limit_text = v2_limit.read_text().strip()
            if limit_text != "max":
                remaining = int(limit_text) - int((cgroup / "memory.current").read_text().strip())
                available = min(available, max(0, remaining))
        elif v1_limit.exists():
            limit = int(v1_limit.read_text().strip())
            if limit < 2**60:  # v1's enormous sentinel denotes no memory limit.
                remaining = limit - int((cgroup / "memory/memory.usage_in_bytes").read_text().strip())
                available = min(available, max(0, remaining))
        else:
            raise RuntimeError("Cannot identify memory cgroup for target admission")
    except (OSError, ValueError) as exc:
        raise RuntimeError("Cannot measure memory cgroup for target admission") from exc
    return available


def require_target_admission(source_commit: str) -> dict:
    # A dedicated workflow stages the prior isolated calibration job's three
    # exact artifacts privately. The normal 60-minute runner cannot opt in.
    private = Path(SOURCE) / "test-results/ci-private"
    names = ("capacity-target-calibration.json", "capacity-target-pilot-report.json",
             "capacity-target-ci-environment.json")
    raw = {}
    try:
        for name in names:
            path = private / name
            if (path.is_symlink() or not path.is_file()
                    or path.stat().st_mode & 0o077 or path.stat().st_size > 1_000_000):
                raise RuntimeError("Full capacity target needs three private calibration artifacts")
            raw[name] = path.read_bytes()
        calibration, pilot, pilot_environment = (
            json.loads(raw[name]) for name in names
        )
        timeout = int(os.environ["CI_STORAGE_CAPACITY_JOB_TIMEOUT_SECONDS"])
    except (OSError, ValueError, KeyError, UnicodeError, TypeError) as exc:
        raise RuntimeError("Full capacity target lacks measured calibration or declared dedicated timeout") from exc
    if any(not isinstance(value, dict) for value in (calibration, pilot, pilot_environment)):
        raise RuntimeError("Full capacity target calibration artifacts must be JSON objects")
    run_id = os.environ.get("CI_STORAGE_CAPACITY_CALIBRATION_RUN_ID", "")
    harness = os.environ.get("CI_HARNESS_COMMIT", "")
    if (not run_id.isdecimal() or int(run_id) <= 0
            or not re.fullmatch(r"[a-f0-9]{40}", harness)
            or any(entry.get("source_commit") != source_commit for entry in
                   (calibration, pilot_environment))
            or any(entry.get("harness_commit") != harness for entry in
                   (calibration, pilot_environment))
            or any(str(entry.get("run_id")) != run_id for entry in
                   (calibration, pilot_environment))
            or calibration.get("pilot_report_sha256") !=
            hashlib.sha256(raw[names[1]]).hexdigest()
            or calibration.get("ci_environment_sha256") !=
            hashlib.sha256(raw[names[2]]).hexdigest()):
        raise RuntimeError("Full capacity calibration source, harness, run or report digest differs")
    capacity = pilot_environment.get("storage_capacity") or {}
    counts = pilot.get("counts") or {}
    provider = pilot.get("provider") or {}
    hardware = pilot.get("hardware") or {}
    if (not all(isinstance(value, dict) for value in (capacity, counts, provider, hardware))
            or pilot.get("passed") is not True
            or pilot.get("validation_level") != "pilot"
            or counts != {"round": 240, "embed": 32, "version": 32}
            or type(pilot.get("server_task_peak_concurrency")) is not int
            or pilot["server_task_peak_concurrency"] < 4
            or type(pilot.get("task_receipt_count")) is not int
            or pilot["task_receipt_count"] < 16
            or capacity.get("provider_credentials") != "absent"
            or capacity.get("provider_network") != "internal"
            or capacity.get("observed_worker_processes") != 4
            or capacity.get("worker_replicas") != 1
            or any(provider.get(name) != 0 for name in (
                "real_provider_calls", "blocked_provider_calls", "cache_misses"))
            or type(provider.get("cache_hits")) is not int
            or provider["cache_hits"] <= 0
            or hardware.get("worker_threads") != 4
            or hardware.get("driver_idle_peak_bytes") != calibration.get("driver_idle_peak_bytes")
            or hardware.get("driver_sample_peak_bytes") != calibration.get("driver_sample_peak_bytes")
            or hardware.get("driver_peak_metric") != calibration.get("driver_peak_metric")
            or pilot.get("task_receipt_count") != calibration.get("observed_worker_task_receipts")):
        raise RuntimeError("Full capacity target lacks a verified zero-provider four-slot calibration pilot")
    try:
        docker_root = subprocess.check_output(
            ["docker", "info", "--format", "{{.DockerRootDir}}"], text=True, timeout=10,
        ).strip()
        if not docker_root or not Path(docker_root).is_dir():
            raise RuntimeError("Cannot measure Docker volume disk for target admission")
        available_disk = min(shutil.disk_usage(SOURCE).free, shutil.disk_usage(docker_root).free)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Cannot measure Docker volume disk for target admission") from exc
    return admit_target_capacity(
        calibration, source_commit=source_commit,
        runner_environment=os.environ.get("RUNNER_ENVIRONMENT", ""),
        profile=os.environ.get("CI_STORAGE_CAPACITY_PROFILE", "accelerated"),
        available_memory_bytes=_available_target_memory_bytes(),
        available_disk_bytes=available_disk,
        job_timeout_seconds=timeout,
    )


def compose_profile(
    source_hash: str,
    *,
    ai_fixtures: bool = False,
    object_storage: bool = False,
    uploads: bool = False,
    public_provider: bool = False,
    workflows: bool = False,
    account_emails: list[str] | None = None,
    offline_preview: bool = False,
    mail_capture: bool = False,
    credential_overrides: dict[str, str] | None = None,
    storage_capacity: bool = False,
    detached_docs: bool = False,
    storage_accountability: bool = False,
    capacity_concurrency: int = 2,
    capacity_target: bool = False,
    billing_profile: str | None = None,
) -> dict:
    """Return an independent profile; never interpolate the operator environment."""
    if billing_profile not in (None, "legacy", "logical"):
        raise ValueError("Unknown isolated storage billing profile")
    storage_capacity = storage_capacity or billing_profile is not None
    ai_fixtures = ai_fixtures or public_provider or storage_capacity
    object_storage = object_storage or uploads or storage_capacity
    if storage_accountability and (ai_fixtures or object_storage or uploads or public_provider or workflows):
        raise ValueError("Storage accountability requires its standalone zero-provider profile")
    if storage_accountability and (not 1000 <= os.getuid() <= 60000 or not 1 <= os.getgid() <= 60000):
        raise ValueError("Storage accountability requires a nonroot isolated runner owner")
    if storage_capacity and public_provider:
        raise ValueError("Storage capacity cannot enable public-provider proxy")
    if detached_docs and not storage_capacity:
        raise ValueError("Detached Docs worker requires isolated storage capacity profile")
    if storage_capacity and not 1 <= capacity_concurrency <= 500:
        raise ValueError("Capacity worker concurrency must be 1..500")
    if capacity_target and (not storage_capacity or capacity_concurrency != TARGET_SLOTS):
        raise ValueError("Target profile requires exactly 500 isolated worker slots")
    isolate_backend = ai_fixtures or object_storage or offline_preview or mail_capture or storage_accountability
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
            "signup_cleanup",
        )
    }
    credentials.update(credential_overrides or {})
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
    if mail_capture:
        common.update(
            CI="true", OPENMATES_CI_ISOLATED="1", OPENMATES_CI_MAIL_CAPTURE="1",
            OPENMATES_TEST_ACCOUNT_API_KEY=credentials["signup_cleanup"],
            SELF_HOST_SIGNUP_MODE="invite_and_domain",
        )
    if object_storage:
        common.update(S3_ENDPOINT_URL="http://storage.ci.test:9000", S3_REGIONS="nbg1")
    if storage_capacity:
        common.update(OPENMATES_CI_ISOLATED="1", OPENMATES_STORAGE_CAPACITY_FIXTURES="true",
                      OPENMATES_CAPACITY_RECEIPT_ROOT="/app/capacity-receipts",
                      CHAT_MESSAGE_ARCHIVE_COPY_ENABLED="1", CHAT_MESSAGE_ARCHIVE_READS_ENABLED="1")
    source_mounts = [
        f"{SOURCE}/backend:/app/backend:ro",
        f"{SOURCE}/shared:/shared:ro",
        f"{SOURCE}/scripts:/app/scripts:ro",
        f"{SOURCE}/config:/app/config:ro",
        f"{SOURCE}/backend/config:/config:ro",
        f"{SOURCE}/frontend/apps/web_app/static:/app/frontend/apps/web_app/static:ro",
        f"{SOURCE}/frontend/packages/ui/src/i18n/locales:/translations:ro",
        f"{SOURCE}/frontend/packages/ui/src/i18n:/app/frontend/packages/ui/src/i18n:ro",
        "api-logs:/app/logs",
        "backend-logs:/app/backend/core/api/logs",
        "api-cache:/app/backend/apps/ai/testing/api_cache",
        "vault-tokens:/vault-data",
    ]
    if storage_capacity:
        source_mounts.append(f"{SOURCE}/test-results/ci-private/capacity-receipts:/app/capacity-receipts")
        source_mounts.append(f"{SOURCE}/test-results/ci-private/storage-isolation:/app/ci-storage-isolation:ro")
    if storage_accountability:
        source_mounts.append(f"{SOURCE}/test-results/ci-private/accountability:/app/ci-accountability")
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
    if billing_profile is not None:
        api["environment"] = {
            **api["environment"],
            "STORAGE_LOGICAL_S3_BILLING_ENABLED": "1" if billing_profile == "logical" else "0",
        }
        api["volumes"].append(
            f"{SOURCE}/test-results/ci-private/storage-billing:/app/ci-storage-billing"
        )
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
            "image": POSTGRES_IMAGE,
            "mem_limit": 512 * MIB,
            "environment": {
                "POSTGRES_DB": "openmates",
                "POSTGRES_USER": "openmates",
                "POSTGRES_PASSWORD": credentials["database"],
            },
            "volumes": ["postgres:/var/lib/postgresql/data"],
            "healthcheck": {
                "test": [
                    "CMD",
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    "openmates",
                ],
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
                "CI_FAST_SCHEMA_SETUP": "1",
            },
            "volumes": [
                f"{SOURCE}/backend/core/directus/schemas:/usr/src/app/schemas:ro",
                f"{SOURCE}/backend/core/directus/setup:/usr/src/app/migrations:ro",
                f"{SOURCE}/backend/core/directus/setup/setup_schemas.py:/usr/src/app/setup_schemas.py:ro",
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
    if mail_capture:
        services["mailpit"] = {
            "image": MAILPIT_IMAGE,
            "mem_limit": 128 * MIB,
            "environment": {"MP_MAX_MESSAGES": "1000"},
        }
        for name in ("api", "core-worker"):
            services[name]["depends_on"]["mailpit"] = {"condition": "service_started"}
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
        services["vault-init"]["environment"]["CI_UPLOADS"] = "1"
        # The API image may be reused when only upload code changes. The init
        # script must import the candidate's token setup and renewal modules.
        services["vault-init"]["volumes"].append(f"{SOURCE}/backend:/app/backend:ro")
        services["vault-init"]["volumes"].append("upload-vault-token:/app/app-data")
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
            "volumes": [
                f"{SOURCE}/backend:/app/backend:ro",
                f"{SOURCE}/backend/apps/base_app.py:/app/apps/base_app.py:ro",
                f"{SOURCE}/backend/apps/base_skill.py:/app/apps/base_skill.py:ro",
                f"{SOURCE}/backend/shared/python_schemas:/app/backend_shared/python_schemas:ro",
                f"{SOURCE}/backend/shared/python_utils:/app/backend_shared/python_utils:ro",
                f"{SOURCE}/config/media_encryption_rollout.yml:/app/config/media_encryption_rollout.yml:ro",
                f"{SOURCE}/backend/upload/vault/wait-for-vault.sh:/app/wait-for-vault.sh:ro",
                {"type": "volume", "source": "upload-vault-token", "target": "/vault-data", "read_only": True, "volume": {"nocopy": True}},
            ],
            "ports": ["127.0.0.1:8001:8000"], "mem_limit": 1024 * MIB,
            "depends_on": {"clamav": {"condition": "service_healthy"}, "object-storage": {"condition": "service_healthy"}, "vault-init": {"condition": "service_completed_successfully"}, "api": {"condition": "service_healthy"}},
            "healthcheck": {"test": ["CMD", "curl", "-f", "http://localhost:8000/health"], "interval": "5s", "timeout": "5s", "retries": 30},
        }
    if storage_accountability:
        api["environment"].update(
            CI="true", OPENMATES_CI_ISOLATED="1",
            OPENMATES_CI_STORAGE_ACCOUNTABILITY="1",
            DB_HOST="cms-database", DB_DATABASE="openmates", DB_USER="openmates",
            OPENMATES_CI_PRIVATE_HOST_UID=str(os.getuid()),
            OPENMATES_CI_PRIVATE_HOST_GID=str(os.getgid()),
        )
    if ai_fixtures:
        # The real status API must advertise the installed replay engine; no
        # fake provider key or browser response interception is needed.
        api["environment"].update(
            CI="true", OPENMATES_CI_ISOLATED="1", OPENMATES_CI_AI_FIXTURES="1"
        )
        # Existing committed TEST_MOCK fixtures still traverse the real API/worker.
        # The internal network prevents paid providers or shared-server egress.
        ai_worker = deepcopy(worker)
        ai_worker["environment"]["CELERY_QUEUES"] = "app_ai"
        ai_worker["command"] = [part.replace(f"--queues={QUEUES}", "--queues=app_ai") for part in worker["command"]]
        ai_worker["mem_limit"] = 1536 * MIB
        services["ai-worker"] = ai_worker
        if storage_capacity:
            ai_worker["command"] = [part.replace("--concurrency=1", f"--concurrency={TARGET_SLOTS_PER_WORKER if capacity_target else capacity_concurrency}")
                                    for part in ai_worker["command"]]
            if capacity_target:
                for index in range(1, TARGET_SLOTS // TARGET_SLOTS_PER_WORKER):
                    services[f"ai-worker-{index:03d}"] = deepcopy(ai_worker)
    if detached_docs:
        # The signed recovery scenario dispatches the actual local DOCX worker.
        # It generates no paid provider output and uses the isolated Vault/S3.
        docs_queues = f"{QUEUES},app_docs"
        worker["environment"]["CELERY_QUEUES"] = docs_queues
        worker["command"] = [
            part.replace(f"--queues={QUEUES}", f"--queues={docs_queues}")
            for part in worker["command"]
        ]
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
        if mail_capture:
            services["runner-gateway"]["ports"].append("127.0.0.1:8025:8025")
            services["runner-gateway"]["environment"]["OPENMATES_CI_MAIL_CAPTURE"] = "1"

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
    dedicated_capacity = (
        os.environ.get("RUNNER_ENVIRONMENT") == "self-hosted"
        and os.environ.get("OPENMATES_CI_CAPACITY_DEDICATED") == "1"
        and json.loads(os.environ.get("CI_SPECS_JSON", "[]")) == ["storage-capacity-target.spec.ts"]
    )
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or (os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted" and not dedicated_capacity)
    ):
        raise RuntimeError("Isolated stacks require GitHub-hosted or dedicated capacity runners")


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


def start_stack(*, compose_runner=None, sleep=time.sleep):
    """Start once, retrying only bounded registry/network pull failures."""
    compose_runner = compose if compose_runner is None else compose_runner
    attempts = len(STACK_START_RETRY_DELAYS) + 1
    for attempt in range(attempts):
        try:
            result = compose_runner(
                "up",
                "-d",
                "--no-build",
                "--wait",
                "--wait-timeout",
                "600",
                capture=True,
                timeout=720,
            )
        except subprocess.CalledProcessError as exc:
            stdout = exc.stdout or exc.output or ""
            stderr = exc.stderr or ""
            if stdout:
                sys.stdout.write(stdout)
            if stderr:
                sys.stderr.write(stderr)
            combined = stdout + "\n" + stderr
            if attempt >= len(STACK_START_RETRY_DELAYS) or not TRANSIENT_REGISTRY_FAILURE.search(combined):
                raise
            delay = STACK_START_RETRY_DELAYS[attempt]
            print(
                f"Transient container registry failure; retrying isolated stack start "
                f"in {delay}s ({attempt + 2}/{attempts}).",
                file=sys.stderr,
            )
            sleep(delay)
            continue
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
        return result
    raise AssertionError("unreachable")


def apply_prepared_schema(profile: dict, runtime_evidence: dict) -> bool:
    """Select the compatible schema image without sharing a database or volume."""
    schema_image = next(
        (
            image
            for image in runtime_evidence.get("images", [])
            if image.get("kind") == "schema" and image.get("reused") is True
        ),
        None,
    )
    if not schema_image:
        return False
    if (
        schema_image.get("bundle_format") != SCHEMA_BUNDLE_FORMAT
        or schema_image.get("restore_semantics") != SCHEMA_RESTORE_SEMANTICS
    ):
        return False
    services = profile["services"]
    services["cms-database"]["image"] = "openmates-ci-database:local"
    services["cms-setup"]["environment"].update(
        CI_PREPARED_SCHEMA="1",
        CI_PREPARED_SCHEMA_ADMIN_PASSWORD=PREPARED_SCHEMA_ADMIN_PASSWORD,
    )
    return True


def select_runtime_profile() -> bool:
    evidence_path = Path(SOURCE) / "test-results/ci-runtime-images.json"
    if not evidence_path.is_file() or not COMPOSE_PATH.is_file():
        return False
    profile = json.loads(COMPOSE_PATH.read_text())
    evidence = json.loads(evidence_path.read_text())
    if not apply_prepared_schema(profile, evidence):
        return False
    COMPOSE_PATH.write_text(json.dumps(profile))
    COMPOSE_PATH.chmod(0o600)
    return True


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
        billing_selected = [BILLING_STORAGE_PROFILES[spec] for spec in selected
                            if spec in BILLING_STORAGE_PROFILES]
        if len(billing_selected) > 1 or (billing_selected and len(selected) != 1):
            raise RuntimeError("Storage billing profiles require separate exact-selector batches")
        billing_profile = billing_selected[0] if billing_selected else None
        if not (Path(SOURCE) / "backend/config/backend_config.dev.yml").is_file():
            raise RuntimeError("Candidate lacks committed development feature configuration")
        offline_preview = os.environ.get("CI_TEST_MODE") == "visual-smoke"
        if offline_preview:
            from ci_visual_smoke import validate_targets
            validate_targets(selected)
        storage_capacity = bool(STORAGE_CAPACITY_SPECS.intersection(selected)) or billing_profile is not None
        storage_accountability = ACCOUNTABILITY_SPEC in selected
        if storage_accountability and selected != [ACCOUNTABILITY_SPEC]:
            raise RuntimeError("Storage accountability requires its exact standalone selector")
        capacity_target = "storage-capacity-target.spec.ts" in selected
        capacity_calibration = "storage-capacity-calibration.spec.ts" in selected
        if capacity_calibration and selected != ["storage-capacity-calibration.spec.ts"]:
            raise RuntimeError("Capacity calibration requires its exact standalone selector")
        if capacity_target and "storage-capacity-replay.spec.ts" in selected:
            raise RuntimeError("Capacity pilot and target require separate isolated batches")
        target_admission = require_target_admission(source) if capacity_target else None
        requested_capacity_slots = int(os.environ.get("CI_STORAGE_CAPACITY_CONCURRENCY", "500" if capacity_target else "4" if capacity_calibration else "2"))
        if capacity_calibration and requested_capacity_slots != 4:
            raise RuntimeError("Capacity calibration requires exactly four worker slots")
        if capacity_target and requested_capacity_slots != TARGET_SLOTS:
            raise RuntimeError("Full capacity target must request exactly 500 worker slots")
        if not capacity_target and storage_capacity and not 1 <= requested_capacity_slots <= 4:
            raise RuntimeError("Pilot/recovery capacity profile supports only 1..4 worker slots")
        capacity_workload = bool(CAPACITY_WORKLOAD_SPECS.intersection(selected))
        capacity_users = int(os.environ.get("CI_STORAGE_CAPACITY_USERS", "1000" if capacity_target else "8" if capacity_calibration else "2")) if capacity_workload else 0
        if capacity_calibration and capacity_users != 8:
            raise RuntimeError("Capacity calibration requires exactly eight disposable users")
        if capacity_workload and not 1 <= capacity_users <= 1000:
            raise RuntimeError("Capacity user count must be 1..1000")
        account_count = 0 if storage_accountability else 2 * len(selected) + capacity_users
        account_emails = [] if offline_preview else [f"ci-{secrets.token_hex(16)}@example.com" for _ in range(account_count)]
        storage_specs = set(manifest["groups"].get("object_storage", {}).get("specs", []))
        upload_specs = set(manifest["groups"].get("uploads", {}).get("specs", []))
        needs_uploads = bool(upload_specs.intersection(selected))
        public_specs = set(manifest["groups"].get("ai_cached_public_provider", {}).get("specs", []))
        mail_specs = set(manifest["groups"].get("local_email_signup", {}).get("specs", []))
        needs_public_provider = bool(public_specs.intersection(selected))
        workflow_specs = set(manifest["groups"].get("workflow_weather", {}).get("specs", []))
        needs_workflows = bool(workflow_specs.intersection(selected))
        if needs_workflows and not set(selected).issubset(workflow_specs):
            raise RuntimeError("Credential-free weather workflows require their own batch")
        needs_storage = bool(storage_specs.intersection(selected)) or needs_uploads or storage_capacity
        if needs_storage:
            for relative in ("backend/core/api/app/services/s3/service.py", "backend/upload/services/s3_upload.py"):
                if "S3_ENDPOINT_URL" not in (Path(SOURCE) / relative).read_text():
                    raise RuntimeError("Candidate lacks isolated storage endpoint support; publish reviewed current-base integration before testing")
        data = compose_profile(source, ai_fixtures=bool(fixture_specs.intersection(selected)), object_storage=needs_storage, uploads=needs_uploads, public_provider=needs_public_provider, workflows=needs_workflows, account_emails=account_emails, offline_preview=offline_preview, mail_capture=bool(mail_specs.intersection(selected)), storage_capacity=storage_capacity, detached_docs="storage-detached-producer.spec.ts" in selected, storage_accountability=storage_accountability, capacity_concurrency=requested_capacity_slots, capacity_target=capacity_target, billing_profile=billing_profile)
        if os.environ.get("GITHUB_OUTPUT"):
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                output.write(f"uploads={'true' if needs_uploads else 'false'}\n")
        # Docker cannot create nested mountpoints inside a read-only bind.
        # These ignored directories contain only runner-local runtime output.
        for relative in ("backend/core/api/logs", "backend/apps/ai/testing/api_cache"):
            (Path(SOURCE) / relative).mkdir(parents=True, exist_ok=True)
        COMPOSE_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if storage_capacity:
            (COMPOSE_PATH.parent / "capacity-receipts").mkdir(parents=True, exist_ok=True, mode=0o700)
            isolation_private = COMPOSE_PATH.parent / "storage-isolation"
            isolation_private.mkdir(parents=True, exist_ok=True, mode=0o700)
            if isolation_private.is_symlink():
                raise RuntimeError("Storage isolation proof bind cannot be a symlink")
            isolation_private.chmod(0o700)
        if storage_accountability:
            private = COMPOSE_PATH.parent / "accountability"
            private.mkdir(parents=True, exist_ok=True, mode=0o700)
            if private.is_symlink():
                raise RuntimeError("Accountability fixture directory must not be a symlink")
            private.chmod(0o700)
        if billing_profile is not None:
            billing_private = COMPOSE_PATH.parent / "storage-billing"
            billing_private.mkdir(parents=True, exist_ok=True, mode=0o700)
            if billing_private.is_symlink():
                raise RuntimeError("Storage billing private mount cannot be a symlink")
            billing_private.chmod(0o700)
        COMPOSE_PATH.write_text(json.dumps(data))
        COMPOSE_PATH.chmod(0o600)
        evidence = {
            "source_commit": source,
            "target_capacity_admission": target_admission,
            "run_id": os.environ["GITHUB_RUN_ID"],
            "environment": "github-isolated",
            "harness_commit": os.environ.get("CI_HARNESS_COMMIT"),
        }
        (Path(SOURCE) / "test-results/ci-environment.json").write_text(
            json.dumps(evidence)
        )
    elif action == "start":
        # Compose's wait limit may not bound one-shot dependency startup.
        select_runtime_profile()
        start_stack()
    elif action == "verify":
        import socket
        import urllib.request

        evidence_path = Path(SOURCE) / "test-results/ci-environment.json"
        evidence = json.loads(evidence_path.read_text())
        runtime_images = Path(SOURCE) / "test-results/ci-runtime-images.json"
        if runtime_images.is_file():
            evidence["runtime_images"] = json.loads(runtime_images.read_text())[
                "images"
            ]
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
        if "mailpit" in profile["services"]:
            required.append("mailpit")
            network = json.loads(subprocess.check_output(["docker", "network", "inspect", "openmates-ci_default"], text=True))[0]
            if network.get("Internal") is not True:
                raise RuntimeError("Runner-local mail capture requires an internal network")
            with urllib.request.urlopen("http://127.0.0.1:8025/api/v1/messages", timeout=10) as response:
                if response.status != 200 or not isinstance(json.load(response).get("messages"), list):
                    raise RuntimeError("Runner-local mail capture is not ready")
            if profile["services"]["api"]["environment"].get("OPENMATES_CI_MAIL_CAPTURE") != "1":
                raise RuntimeError("Mail capture profile must bind the API to local delivery")
            evidence["email_capture"] = {"provider": "mailpit", "api": "runner-local", "external_delivery": False}
        if "ai-worker" in profile["services"]:
            required.extend(["ai-worker", "runner-gateway"])
            required.extend(sorted(name for name in profile["services"] if name.startswith("ai-worker-")))
            network = json.loads(subprocess.check_output(["docker", "network", "inspect", "openmates-ci_default"], text=True))[0]
            if network.get("Internal") is not True:
                raise RuntimeError("Fixture AI profile must reject external network access")
            evidence["provider_egress"] = "rejected-internal-network"
        if profile["services"]["api"]["environment"].get("OPENMATES_STORAGE_CAPACITY_FIXTURES") == "true":
            forbidden = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY", "TOGETHER_API_KEY"}
            for name in ("api", "core-worker", "ai-worker"):
                if forbidden.intersection(profile["services"][name]["environment"]):
                    raise RuntimeError("Capacity profile contains provider credentials")
            if evidence.get("provider_egress") != "rejected-internal-network":
                raise RuntimeError("Capacity profile has no independent provider network block")
            worker_names = [name for name in profile["services"] if name == "ai-worker" or name.startswith("ai-worker-")]
            worker_slots = sum(int(next(part.split("=", 1)[1] for part in profile["services"][name]["command"]
                                        if part.startswith("--concurrency="))) for name in worker_names)
            admission = evidence.get("target_capacity_admission")
            if admission and (worker_slots != TARGET_SLOTS or len(worker_names) != TARGET_SLOTS // TARGET_SLOTS_PER_WORKER):
                raise RuntimeError("Full capacity target configured worker slots differ from admission")
            evidence["storage_capacity"] = {"provider_credentials": "absent", "provider_network": "internal",
                                            "fixture_mode": "replay-only", "worker_slots": worker_slots,
                                            "worker_replicas": len(worker_names)}
        calibration_active = json.loads(os.environ.get("CI_SPECS_JSON", "[]")) == [
            "storage-capacity-calibration.spec.ts"
        ]
        observed_worker_slots = 0
        for service in required:
            container = compose("ps", "-q", service, capture=True).stdout.strip()
            if not container:
                raise RuntimeError("Required private service is missing: " + service)
            raw = subprocess.check_output(["docker", "inspect", container], text=True)
            info = json.loads(raw)[0]
            if evidence.get("storage_capacity") and (service in {"api", "core-worker"} or service.startswith("ai-worker")):
                runtime_names = {entry.split("=", 1)[0] for entry in info["Config"].get("Env", [])}
                forbidden = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY", "TOGETHER_API_KEY"}
                runtime_source = next((entry.partition("=")[2] for entry in info["Config"].get("Env", [])
                                       if entry.startswith("BUILD_COMMIT_SHA=")), "")
                if runtime_source != evidence["source_commit"]:
                    raise RuntimeError("Mounted candidate runtime source differs from verified source")
                if (runtime_names.intersection(forbidden) or any(
                        name.startswith("SECRET__") and any(provider in name.upper() for provider in (
                            "OPENAI", "ANTHROPIC", "GOOGLE", "GEMINI", "OPENROUTER", "GROQ", "CEREBRAS", "TOGETHER", "MISTRAL",
                        )) for name in runtime_names)):
                    raise RuntimeError("Capacity container has live inference credentials")
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
            if (evidence.get("target_capacity_admission") or calibration_active) and (
                    service == "ai-worker" or service.startswith("ai-worker-")):
                configured = profile["services"][service]["command"]
                if "--concurrency=4" not in configured or "--concurrency=4" not in info["Config"].get("Cmd", []):
                    raise RuntimeError("Target worker command differs from admitted four-slot profile")
                children = subprocess.check_output(
                    ["docker", "exec", container, "python", "-c",
                     "from pathlib import Path; print(len(Path('/proc/1/task/1/children').read_text().split()))"],
                    text=True, timeout=10,
                ).strip()
                if not children.isdecimal() or int(children) < TARGET_SLOTS_PER_WORKER:
                    raise RuntimeError("Target worker has fewer live prefork processes than admitted")
                observed_worker_slots += TARGET_SLOTS_PER_WORKER
            if (service in ("api", "core-worker", "uploads", "workflow-scheduler") or service.startswith("ai-worker")):
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
        if evidence.get("target_capacity_admission") or calibration_active:
            expected_slots = 4 if calibration_active else TARGET_SLOTS
            if observed_worker_slots != expected_slots:
                raise RuntimeError("Capacity profile lacks its expected live prefork worker slots")
            evidence["storage_capacity"]["observed_worker_processes"] = observed_worker_slots
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
        if evidence.get("storage_capacity"):
            # Reuse the verified network/source/runtime checks above. Vault
            # inspection returns only the provider key names, never values.
            vault_check = """import os, requests
response=requests.request('LIST','http://vault:8200/v1/kv/metadata/providers',headers={'X-Vault-Token':os.environ['VAULT_DEV_ROOT_TOKEN_ID']},timeout=10)
response.raise_for_status()
assert sorted(response.json().get('data',{}).get('keys',[])) == ['core_server','hetzner'], 'Unexpected provider key namespace in isolated Vault'
"""
            # The Vault image's busybox wget lacks portable LIST support. Use
            # the API image's requests client through a fresh one-shot runner
            # carrying only the generated CI root token from private profile.
            vault_keys = subprocess.run(
                ["docker", "run", "--rm", "--network", "openmates-ci_default", "-e", "VAULT_DEV_ROOT_TOKEN_ID",
                 "openmates-ci-api:local", "python", "-c", vault_check],
                env={**os.environ, "VAULT_DEV_ROOT_TOKEN_ID": profile["services"]["vault"]["environment"]["VAULT_DEV_ROOT_TOKEN_ID"]},
                capture_output=True, text=True, timeout=30,
            )
            if vault_keys.returncode:
                raise RuntimeError("Isolated storage Vault provider namespace is unverified")
            proof = {
                "schema": "agentic-storage-ci-isolation-v1", "source_commit": evidence["source_commit"],
                "harness_commit": evidence["harness_commit"], "run_id": str(evidence["run_id"]),
                "environment": "github-isolated", "observed_at": int(time.time()),
                "expires_at": int(time.time()) + 90000,
                "provider_network": "internal", "provider_credentials": "absent",
                "vault_provider_keys": ["core_server", "hetzner"],
                "source_mount": "read_only_exact_candidate", "shared_dev_dns": "rejected",
                "shared_dev_https": "rejected", "object_storage": "authenticated_disposable_roundtrip",
            }
            proof_path = COMPOSE_PATH.parent / "storage-isolation/proof.json"
            temporary_proof = proof_path.with_suffix(".tmp")
            temporary_proof.write_text(json.dumps(proof, sort_keys=True), encoding="utf-8")
            temporary_proof.chmod(0o444)
            temporary_proof.replace(proof_path)
            inventory_refresh = subprocess.run([sys.executable, str(Path(SOURCE) / "scripts/storage_runtime_inventory.py"),
                                                "refresh", "--compose-file", str(COMPOSE_PATH)],
                                               capture_output=True, text=True, timeout=90)
            if inventory_refresh.returncode or json.loads(inventory_refresh.stdout).get("status") != "published":
                raise RuntimeError("Isolated API process inventory is unverified")
            # CI does not install host systemd services. Its disposable runner
            # refreshes the same actual-process inventory throughout the job.
            inventory_log = COMPOSE_PATH.parent / "storage-inventory.log"
            with inventory_log.open("ab") as output:
                inventory_process = subprocess.Popen([sys.executable, str(Path(SOURCE) / "scripts/storage_runtime_inventory.py"),
                                                      "refresh", "--compose-file", str(COMPOSE_PATH), "--loop"],
                                                     stdout=output, stderr=output, start_new_session=True)
            inventory_pid = COMPOSE_PATH.parent / "storage-inventory.pid"
            inventory_pid.write_text(str(inventory_process.pid), encoding="ascii")
            inventory_pid.chmod(0o600)
            # Fixture gates are source-bound and remain usable only while the
            # independent isolation proof and real API runtime guard are live.
            fixture_setup = """import asyncio, os
from backend.core.api.app.tasks.base_task import BaseServiceTask
from scripts.storage_rollout import COLLECTIONS, write_rollout
async def run():
    task=BaseServiceTask()
    try:
        await task.initialize_core_services()
        receipt='ci-storage-capacity:'+os.environ['BUILD_COMMIT_SHA']
        for name in COLLECTIONS:
            await write_rollout(task.directus_service,name,{'read_enabled':True,'pruning_enabled':True,'initial_cohort':False,'compatibility_verified':True,'reader_receipt':receipt,'validation_receipt':receipt,'failure_code':None})
    finally:
        await task.cleanup_services()
asyncio.run(run())
"""
            compose("exec", "-T", "api", "python", "-c", fixture_setup, capture=True, timeout=60)
            evidence["storage_isolation_proof"] = {"source_bound": True, "read_only_bind": True, "vault_provider_namespace": "disposable_only"}
        evidence_path.write_text(json.dumps(evidence, indent=2))
    elif action == "stop":
        if COMPOSE_PATH.exists():
            inventory_pid = COMPOSE_PATH.parent / "storage-inventory.pid"
            if inventory_pid.is_file():
                try:
                    pid = int(inventory_pid.read_text())
                    args = Path(f"/proc/{pid}/cmdline").read_bytes().decode().split("\0")
                    if (str(Path(SOURCE) / "scripts/storage_runtime_inventory.py") in args
                            and str(COMPOSE_PATH) in args and "--loop" in args):
                        os.kill(pid, signal.SIGTERM)
                except (OSError, ValueError, UnicodeError):
                    pass
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
            label = os.environ.get("CI_DIAGNOSTIC_LABEL", "")
            if label and not re.fullmatch(r"spec-[0-9]{1,3}", label):
                raise ValueError("Invalid bounded diagnostic label")
            filename = f"ci-stack-{label}.log" if label else "ci-stack.log"
            (Path(SOURCE) / "test-results" / filename).write_text(output)
    else:
        raise ValueError("Unknown CI environment action")


if __name__ == "__main__":
    main()
