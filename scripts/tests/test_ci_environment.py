# contract-test-file: tooling
"""Validate disposable CI environment boundaries without starting Docker.

The runner profile must never mount operator secrets or the Docker socket.
All API and worker source mounts must identify the same checkout revision.
A local invocation must fail before invoking any Docker command.
See docs/plans/isolated-github-tests/plan.yml.
"""

import json

import pytest
from scripts.ci_environment import (
    PREPARED_SCHEMA_ADMIN_PASSWORD,
    POSTGRES_IMAGE,
    SCHEMA_BUNDLE_FORMAT,
    SCHEMA_RESTORE_SEMANTICS,
    SOURCE,
    apply_prepared_schema,
    compose_profile,
    mail_capture_specs,
    upload_specs,
    workflow_specs,
    require_runner,
    start_stack,
)


def test_profile_is_private_and_source_bound():
    profile = compose_profile("a" * 40)
    assert profile["name"] == "openmates-ci"
    for service in profile["services"].values():
        assert service["labels"]["org.openmates.source"] == "a" * 40
        assert service["extra_hosts"]["api.dev.openmates.org"] == "127.0.0.2"
        assert not service.get("privileged")
        assert not service.get("env_file")
        assert all(
            ".env:" not in str(mount) and "docker.sock" not in str(mount)
            for mount in service.get("volumes", [])
        )
    assert (
        profile["services"]["api"]["image"]
        == profile["services"]["core-worker"]["image"]
    )
    api_mounts = profile["services"]["api"]["volumes"]
    for target in (
        "/app/backend",
        "/shared",
        "/app/scripts",
        "/app/config",
        "/app/frontend/apps/web_app/static",
        "/translations",
        "/app/frontend/packages/ui/src/i18n",
    ):
        assert any(target in str(mount) for mount in api_mounts), target


def test_vault_image_uses_verified_pinned_mirror():
    image = compose_profile("a" * 40)["services"]["vault"]["image"]
    assert image == (
        "mirror.gcr.io/hashicorp/vault:1.19@sha256:"
        "c4298db7f9b2ea8cab452cbff5877749087913aa035fcae62026cf16132929f5"
    )


def test_signup_mail_capture_stays_on_disposable_internal_network():
    normal = compose_profile("a" * 40)
    assert "mailpit" not in normal["services"]
    assert "OPENMATES_CI_MAIL_CAPTURE" not in normal["services"]["api"]["environment"]
    assert "OPENMATES_TEST_ACCOUNT_API_KEY" not in normal["services"]["api"]["environment"]

    profile = compose_profile("a" * 40, mail_capture=True)
    assert profile["networks"]["default"]["internal"] is True
    assert "ports" not in profile["services"]["mailpit"]
    assert profile["services"]["mailpit"].get("networks") is None
    gateway = profile["services"]["runner-gateway"]
    assert "127.0.0.1:8025:8025" in gateway["ports"]
    assert gateway["environment"]["OPENMATES_CI_MAIL_CAPTURE"] == "1"
    for name in ("api", "core-worker"):
        service = profile["services"][name]
        assert service["environment"]["OPENMATES_CI_MAIL_CAPTURE"] == "1"
        assert service["environment"]["OPENMATES_CI_ISOLATED"] == "1"
        assert len(service["environment"]["OPENMATES_TEST_ACCOUNT_API_KEY"]) == 48
        assert service["environment"]["SELF_HOST_SIGNUP_MODE"] == "invite_and_domain"
        assert service["depends_on"]["mailpit"]["condition"] == "service_started"
        assert "BREVO_API_KEY" not in service["environment"]


@pytest.mark.parametrize("service_name", ["api", "core-worker"])
def test_worker_email_links_resolve_to_disposable_frontend(monkeypatch, service_name):
    from backend.shared.python_utils.frontend_url import get_frontend_base_url

    environment = compose_profile("a" * 40, mail_capture=True)["services"][service_name]["environment"]
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    monkeypatch.setenv("FRONTEND_URLS", environment["FRONTEND_URLS"])
    if "FRONTEND_URL" in environment:
        monkeypatch.setenv("FRONTEND_URL", environment["FRONTEND_URL"])
    assert get_frontend_base_url() == environment["APPLICATION_PREVIEW_ORIGIN"]


def test_candidate_upload_dependencies_keep_harness_requirements(tmp_path):
    (tmp_path / "scripts").mkdir()
    candidate_manifest = tmp_path / "scripts/ci_coverage_manifest.json"
    candidate_manifest.write_text(json.dumps({"groups": {"uploads": {
        "specs": ["teams-management-flow.spec.ts"]
    }}}))
    harness = {"groups": {"uploads": {"specs": ["profile-image-recovery.spec.ts"]}}}
    assert upload_specs(harness, tmp_path) == {
        "profile-image-recovery.spec.ts", "teams-management-flow.spec.ts"
    }
    candidate_manifest.write_text(json.dumps({"groups": {}}))
    assert upload_specs(harness, tmp_path) == {"profile-image-recovery.spec.ts"}
    candidate_manifest.write_text(json.dumps({"groups": {"uploads": {"specs": "bad"}}}))
    with pytest.raises(RuntimeError, match="Invalid uploads specs"):
        upload_specs(harness, tmp_path)


def test_candidate_mail_dependencies_add_only_mail_capture(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/ci_coverage_manifest.json").write_text(
        json.dumps({"groups": {
            "local_email_signup": {"specs": ["teams-invite-acceptance.spec.ts"]},
            "ai_committed_fixtures": {"specs": ["teams-invite-acceptance.spec.ts"]},
        }})
    )
    harness = {"groups": {"local_email_signup": {"specs": ["signup-flow.spec.ts"]}}}
    assert mail_capture_specs(harness, tmp_path) == {
        "signup-flow.spec.ts",
        "teams-invite-acceptance.spec.ts",
    }


def test_candidate_cannot_remove_harness_mail_capture_or_supply_bad_specs(tmp_path):
    (tmp_path / "scripts").mkdir()
    candidate_manifest = tmp_path / "scripts/ci_coverage_manifest.json"
    harness = {"groups": {"local_email_signup": {"specs": ["signup-flow.spec.ts"]}}}
    candidate_manifest.write_text(json.dumps({"groups": {}}))
    assert mail_capture_specs(harness, tmp_path) == {"signup-flow.spec.ts"}
    candidate_manifest.write_text(
        json.dumps({"groups": {"local_email_signup": {"specs": "bad"}}})
    )
    with pytest.raises(RuntimeError, match="Invalid local_email_signup specs"):
        mail_capture_specs(harness, tmp_path)


def test_candidate_workflow_dependencies_enable_runtime_without_removing_harness_specs(tmp_path):
    (tmp_path / "scripts").mkdir()
    candidate_manifest = tmp_path / "scripts/ci_coverage_manifest.json"
    harness = {"groups": {"workflow_weather": {"specs": ["cli-workflows-rain-real.spec.ts"]}}}
    candidate_manifest.write_text(json.dumps({"groups": {"workflow_weather": {
        "specs": ["workflow-completion-notifications.spec.ts", "workflow-completion-notification-route.spec.ts"]
    }}}))
    assert workflow_specs(harness, tmp_path) == {
        "cli-workflows-rain-real.spec.ts",
        "workflow-completion-notifications.spec.ts",
        "workflow-completion-notification-route.spec.ts",
    }
    candidate_manifest.write_text(json.dumps({"groups": {}}))
    assert workflow_specs(harness, tmp_path) == {"cli-workflows-rain-real.spec.ts"}


@pytest.mark.parametrize("bad_specs", ["bad", ["valid.spec.ts", 42], {"spec.ts": True}])
def test_candidate_workflow_dependencies_reject_bad_declarations(tmp_path, bad_specs):
    (tmp_path / "scripts").mkdir()
    candidate_manifest = tmp_path / "scripts/ci_coverage_manifest.json"
    candidate_manifest.write_text(json.dumps({"groups": {"workflow_weather": {"specs": bad_specs}}}))
    with pytest.raises(RuntimeError, match="Invalid workflow_weather specs"):
        workflow_specs({"groups": {}}, tmp_path)
    candidate_manifest.write_text(json.dumps({"groups": {}}))
    with pytest.raises(RuntimeError, match="Invalid workflow_weather specs"):
        workflow_specs({"groups": {"workflow_weather": {"specs": bad_specs}}}, tmp_path)


def test_fresh_credentials_and_runner_only(monkeypatch):
    a = compose_profile("a" * 40)
    b = compose_profile("a" * 40)
    assert (
        a["services"]["cms-database"]["environment"]
        != b["services"]["cms-database"]["environment"]
    )
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(RuntimeError, match="GitHub-hosted"):
        require_runner()
    assert a["services"]["cms-database"]["image"] == POSTGRES_IMAGE
    assert "@sha256:" in POSTGRES_IMAGE
    assert a["services"]["cms-database"]["healthcheck"]["test"] == [
        "CMD",
        "pg_isready",
        "-h",
        "127.0.0.1",
        "-U",
        "openmates",
    ]


def test_stack_start_retries_only_transient_registry_failures():
    import subprocess

    calls = []
    delays = []

    def transient_then_success(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) == 1:
            raise subprocess.CalledProcessError(
                1,
                ["docker", "compose", "up"],
                stderr="registry request failed: connection reset by peer",
            )
        return subprocess.CompletedProcess(args, 0, stdout="started\n", stderr="")

    start_stack(compose_runner=transient_then_success, sleep=delays.append)
    assert len(calls) == 2
    assert delays == [5]
    assert calls[0][1]["capture"] is True

    permanent_calls = []

    def permanent_failure(*args, **kwargs):
        permanent_calls.append((args, kwargs))
        raise subprocess.CalledProcessError(
            1,
            ["docker", "compose", "up"],
            stderr="api container is unhealthy",
        )

    with pytest.raises(subprocess.CalledProcessError):
        start_stack(compose_runner=permanent_failure, sleep=delays.append)
    assert len(permanent_calls) == 1


def test_named_volumes_have_one_explicit_fixture_writer():
    services = compose_profile("a" * 40)["services"]
    for service in services.values():
        for mount in service.get("volumes", []):
            if isinstance(mount, dict):
                assert mount["volume"]["nocopy"] is True
    for name in ("api", "core-worker"):
        assert (
            services[name]["depends_on"]["fixture-init"]["condition"]
            == "service_completed_successfully"
        )
    assert services["fixture-init"]["volumes"][0]["source"] == "api-cache"


def test_vault_initializer_issues_scoped_token_and_uses_startup_validator(
    tmp_path, monkeypatch
):
    import httpx
    import requests
    from scripts.ci_environment import VAULT_INITIALIZE

    policies = {}

    class Response:
        status_code = 204

        def raise_for_status(self):
            return None

        def json(self):
            return {"auth": {"client_token": "scoped-ci-token"}}

    def request(method, url, **kwargs):
        if "/sys/policies/acl/" in url:
            policies[url.rsplit("/", 1)[1]] = kwargs["json"]["policy"]
        if url.endswith("auth/token/create"):
            assert set(kwargs["json"]["policies"]) == {"api-service", "api-encryption"}
            assert kwargs["json"]["ttl"] == "2h"
        return Response()

    monkeypatch.setattr(requests, "request", request)
    monkeypatch.setattr(
        requests, "post", lambda url, **kwargs: request("post", url, **kwargs)
    )

    def lookup(request):
        assert request.headers["X-Vault-Token"] == "scoped-ci-token"
        return httpx.Response(
            200, json={"data": {"policies": list(policies), "ttl": 7200}}
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(lookup)),
    )
    monkeypatch.setenv("VAULT_TOKEN", "synthetic-root-token")
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "synthetic-internal-token")
    program = VAULT_INITIALIZE.replace("/vault-data/", str(tmp_path) + "/")
    exec(compile(program, "<ci-vault-init>", "exec"), {})
    assert (tmp_path / "api.token").read_text() == "scoped-ci-token"
    assert "transit/encrypt/*" in policies["api-encryption"]
    assert "kv/data/providers/*" in policies["api-service"]


def test_upload_vault_initializer_issues_a_separate_renewable_token(tmp_path, monkeypatch):
    import httpx
    import requests
    from backend.upload.vault import setup_vault
    from scripts.ci_environment import VAULT_INITIALIZE

    core_dir = tmp_path / "core"
    core_dir.mkdir()
    upload_token_path = tmp_path / "upload" / "api.token"
    monkeypatch.setattr(setup_vault, "API_TOKEN_FILE", str(upload_token_path))
    monkeypatch.setenv("VAULT_TOKEN", "ephemeral-root")
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "ephemeral-internal")
    monkeypatch.setenv("CI_UPLOADS", "1")
    calls = []

    class Response:
        status_code = 204

        def raise_for_status(self):
            return None

        def json(self):
            return {"auth": {"client_token": "core-token"}}

    def core_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return Response()

    monkeypatch.setattr(requests, "request", core_request)
    monkeypatch.setattr(requests, "post", lambda url, **kwargs: core_request("post", url, **kwargs))

    def vault_api(request: httpx.Request) -> httpx.Response:
        token = request.headers["X-Vault-Token"]
        calls.append((request.method, request.url.path, token))
        if token == "core-token" and request.url.path.endswith("lookup-self"):
            return httpx.Response(200, json={"data": {"policies": ["api-service", "api-encryption"], "ttl": 7200}})
        if token == "ephemeral-root" and request.url.path.endswith("sys/policies/acl/uploads-service"):
            assert b'auth/token/renew-self' in request.content
            return httpx.Response(204)
        if token == "ephemeral-root" and request.url.path.endswith("auth/token/create"):
            import json
            payload = json.loads(request.content)
            assert payload["period"] == "168h"
            assert payload["policies"] == ["uploads-service"]
            assert payload["no_default_policy"] is True
            return httpx.Response(200, json={"auth": {"client_token": "upload-token"}})
        if token == "upload-token" and request.url.path.endswith("lookup-self"):
            return httpx.Response(200, json={"data": {
                "ttl": 604800, "renewable": True, "policies": ["uploads-service"],
                "meta": {"uploads_token_kind": "periodic_v1"}, "explicit_max_ttl": 0,
            }})
        if token == "upload-token" and request.url.path.endswith("renew-self"):
            return httpx.Response(200, json={"auth": {"lease_duration": 604800, "renewable": True}})
        raise AssertionError(f"Unexpected Vault request: {request.method} {request.url.path}")

    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(vault_api), **kwargs))
    program = VAULT_INITIALIZE.replace("/vault-data/", str(core_dir) + "/")
    exec(compile(program, "<ci-vault-init>", "exec"), {})

    assert (core_dir / "api.token").read_text() == "core-token"
    assert upload_token_path.read_text() == "upload-token"
    assert upload_token_path.stat().st_mode & 0o777 == 0o600
    assert any(call == ("POST", "/v1/auth/token/renew-self", "upload-token") for call in calls)


def test_api_and_worker_receive_the_private_cms_admin_identity():
    services = compose_profile("a" * 40)["services"]
    cms = services["cms"]["environment"]
    for service in ("api", "core-worker", "cms-setup"):
        environment = services[service]["environment"]
        assert environment["DATABASE_ADMIN_EMAIL"] == cms["ADMIN_EMAIL"]
        assert environment["DATABASE_ADMIN_PASSWORD"] == cms["ADMIN_PASSWORD"]


def test_committed_ai_fixtures_have_worker_and_no_external_network():
    profile = compose_profile("a" * 40, ai_fixtures=True)
    assert profile["networks"]["default"]["internal"] is True
    worker = profile["services"]["ai-worker"]
    assert worker["environment"]["CELERY_QUEUES"] == "app_ai"
    assert "--queues=app_ai" in worker["command"]
    assert worker["image"] == profile["services"]["api"]["image"]
    assert "ai-worker" not in compose_profile("a" * 40)["services"]


def test_cleanup_removes_only_disposable_accounts_and_records_evidence(tmp_path, monkeypatch):
    from scripts import ci_environment as runtime
    import json
    private = tmp_path / "test-results/ci-private"
    private.mkdir(parents=True)
    (private / "compose.json").write_text("{}")
    (private / "account.env").write_text("synthetic")
    monkeypatch.setattr(runtime, "SOURCE", str(tmp_path))
    monkeypatch.setattr(runtime, "COMPOSE_PATH", private / "compose.json")
    monkeypatch.setattr(runtime, "require_runner", lambda: None)
    monkeypatch.setattr(runtime, "compose", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime.subprocess, "check_output", lambda *args, **kwargs: "")
    monkeypatch.setattr(runtime.sys, "argv", ["ci_environment.py", "stop"])
    monkeypatch.setenv("GITHUB_RUN_ID", "synthetic-run")
    runtime.main()
    assert not private.exists()
    assert json.loads((tmp_path / "test-results/ci-cleanup.json").read_text())["private_account_files_removed"] is True


def test_runtime_uses_candidate_development_feature_configuration():
    profile = compose_profile("a" * 40, ai_fixtures=True)
    for service in ("api", "core-worker", "ai-worker"):
        assert profile["services"][service]["environment"]["BACKEND_CONFIG_FILE"] == "/app/backend/config/backend_config.dev.yml"


def test_fixture_network_only_exposes_uncredentialed_tcp_gateway():
    profile = compose_profile("a" * 40, ai_fixtures=True)
    services = profile["services"]
    assert "ports" not in services["api"] and "ports" not in services["cms"]
    assert services["runner-gateway"]["ports"] == ["127.0.0.1:8000:8000", "127.0.0.1:8055:8055"]
    assert services["runner-gateway"]["environment"] == {"OPENMATES_CI_GATEWAY": "github-isolated"}
    assert all("ingress" not in service.get("networks", []) for name, service in services.items() if name != "runner-gateway")


def test_replay_allowlist_contains_only_this_runs_new_identities(monkeypatch):
    from backend.shared.python_utils.e2e_user_detection import is_configured_test_account_profile
    import hashlib
    import base64
    import os
    monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_1_EMAIL", "legacy@example.net")
    fresh = ["ci-first@example.com", "ci-second@example.com"]
    profile = compose_profile("a" * 40, ai_fixtures=True, account_emails=fresh)
    env = profile["services"]["api"]["environment"]
    assert "OPENMATES_TEST_ACCOUNT_1_EMAIL" not in env
    for key in list(os.environ):
        if key.startswith("OPENMATES_TEST_ACCOUNT"):
            monkeypatch.delenv(key)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    def hashed(email):
        return base64.b64encode(hashlib.sha256(email.encode()).digest()).decode()
    assert is_configured_test_account_profile({"hashed_email": hashed(fresh[0])})
    assert not is_configured_test_account_profile({"hashed_email": hashed("legacy@example.net")})
    assert not is_configured_test_account_profile({"hashed_email": hashed("ci-other-run@example.com")})
    with pytest.raises(ValueError, match="unique generated"):
        compose_profile("a" * 40, account_emails=[fresh[0], fresh[0]])


def test_object_storage_uses_fresh_local_credentials_and_real_pinned_server():
    a = compose_profile("a" * 40, object_storage=True)
    b = compose_profile("a" * 40, object_storage=True)
    services = a["services"]
    store = services["object-storage"]
    assert "@sha256:" in store["image"]
    assert store["ports"] == ["127.0.0.1:9000:9000"]
    assert store["environment"] != b["services"]["object-storage"]["environment"]
    for name in ("api", "core-worker"):
        assert services[name]["environment"]["S3_ENDPOINT_URL"] == "http://storage.ci.test:9000"
        assert services[name]["environment"]["S3_REGIONS"] == "nbg1"
        assert services[name]["depends_on"]["object-storage"]["condition"] == "service_healthy"
    assert services["vault-init"]["environment"]["CI_STORAGE_ACCESS_KEY"] == store["environment"]["AWS_ACCESS_KEY_ID"]
    assert "object-storage" not in compose_profile("a" * 40)["services"]


def test_upload_profile_requires_real_scanner_and_isolated_api_targets():
    profile = compose_profile("a" * 40, uploads=True)
    services = profile["services"]
    upload = services["uploads"]
    assert upload["depends_on"]["clamav"] == {"condition": "service_healthy"}
    assert services["clamav"]["healthcheck"]["test"] == ["CMD", "/usr/local/bin/clamdcheck.sh"]
    assert "@sha256:" in services["clamav"]["image"]
    assert upload["environment"]["DEV_CORE_API_URL"] == upload["environment"]["PROD_CORE_API_URL"] == "http://api:8000"
    assert upload["environment"]["S3_ENDPOINT_URL"] == "http://storage.ci.test:9000"
    assert upload["ports"] == ["127.0.0.1:8001:8000"]
    token_mount = next(
        mount for mount in upload["volumes"]
        if isinstance(mount, dict) and mount["target"] == "/vault-data"
    )
    assert token_mount["read_only"] is True
    assert token_mount["source"] == "upload-vault-token"
    assert "vault-tokens" not in [mount["source"] for mount in upload["volumes"] if isinstance(mount, dict)]
    init = services["vault-init"]
    assert init["environment"]["CI_UPLOADS"] == "1"
    assert {mount["source"] for mount in init["volumes"] if isinstance(mount, dict)} == {"vault-tokens", "upload-vault-token"}
    assert f"{SOURCE}/backend:/app/backend:ro" in init["volumes"]
    for target in (
        "/app/backend",
        "/app/backend_shared/python_schemas",
        "/app/backend_shared/python_utils",
        "/app/config/media_encryption_rollout.yml",
    ):
        assert any(target in str(mount) for mount in upload["volumes"]), target
    assert "object-storage" in services
    assert profile["networks"]["default"]["internal"] is True
    assert services["runner-gateway"]["ports"] == ["127.0.0.1:8000:8000", "127.0.0.1:8055:8055"]
    assert services["clamav"]["networks"] == ["default", "ingress"]


def test_workflow_scheduler_keeps_only_original_workflow_scan(monkeypatch):
    import sys
    from types import SimpleNamespace
    from scripts.ci_environment import WORKFLOW_SCHEDULER

    calls = []
    entry = {"task": "workflows.scan_due_triggers", "schedule": 60}
    app = SimpleNamespace(conf=SimpleNamespace(beat_schedule={"workflow":entry, "dangerous":{"task":"user_tasks.process_due_ai_tasks"}}), start=calls.append)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.celery_config", SimpleNamespace(app=app))
    exec(WORKFLOW_SCHEDULER, {})
    assert app.conf.beat_schedule == {"workflow":entry}
    assert calls[0][0] == "beat"
    profile = compose_profile("a" * 40, workflows=True)
    assert profile["services"]["core-worker"]["environment"]["CELERY_QUEUES"].endswith(",workflow")
    assert profile["services"]["workflow-scheduler"]["command"] == ["python", "-c", WORKFLOW_SCHEDULER]
    with pytest.raises(ValueError, match="separate batch"):
        compose_profile("a" * 40, workflows=True, ai_fixtures=True)


def test_public_replay_keeps_workers_internal_and_proxy_unpublished():
    from scripts.ci_environment import compose_profile
    profile = compose_profile('a' * 40, public_provider=True)
    assert profile['networks']['default']['internal'] is True
    proxy = profile['services']['runner-gateway']
    assert proxy['environment']['OPENMATES_CI_PUBLIC_PROVIDER_PROXY'] == '1'
    assert all('3128' not in port for port in proxy['ports'])
    for name in ('api', 'core-worker', 'ai-worker'):
        service = profile['services'][name]
        assert service['environment']['HTTPS_PROXY'] == 'http://runner-gateway:3128'
        assert 'ingress' not in service.get('networks', ['default'])
    ordinary = compose_profile('a' * 40, ai_fixtures=True)
    assert 'HTTPS_PROXY' not in ordinary['services']['api']['environment']


def test_only_isolated_ai_profile_advertises_fixture_model_readiness():
    ordinary = compose_profile('a' * 40)
    for service in ('api', 'core-worker'):
        assert 'OPENMATES_CI_AI_FIXTURES' not in ordinary['services'][service]['environment']
    assert 'ai-worker' not in ordinary['services']
    replay = compose_profile('a' * 40, ai_fixtures=True)
    for service in ('api', 'ai-worker'):
        environment = replay['services'][service]['environment']
        assert environment['CI'] == 'true'
        assert environment['OPENMATES_CI_ISOLATED'] == '1'
        assert environment['OPENMATES_CI_AI_FIXTURES'] == '1'
        assert not any(key.startswith('SECRET__') for key in environment)
    assert 'OPENMATES_CI_AI_FIXTURES' not in replay['services']['core-worker']['environment']
    assert replay['networks']['default']['internal'] is True
    assert 'ai-worker' in replay['services']


def test_schema_setup_mounts_exact_candidate_and_enables_ci_fast_settle():
    setup = compose_profile("a" * 40)["services"]["cms-setup"]
    assert setup["environment"]["CI_FAST_SCHEMA_SETUP"] == "1"
    for filename in ("setup_schemas.py", "accountability_policy.py"):
        assert any(
            f"/setup/{filename}:/usr/src/app/{filename}:ro" in str(mount)
            for mount in setup["volumes"]
        )


def test_compatible_prepared_schema_keeps_fresh_state_but_skips_full_initializer():
    profile = compose_profile("a" * 40)
    original_password = profile["services"]["cms-database"]["environment"][
        "POSTGRES_PASSWORD"
    ]
    assert apply_prepared_schema(
        profile,
        {
            "images": [
                {
                    "kind": "schema",
                    "reused": True,
                    "bundle_format": SCHEMA_BUNDLE_FORMAT,
                    "restore_semantics": SCHEMA_RESTORE_SEMANTICS,
                }
            ]
        },
    )
    database = profile["services"]["cms-database"]
    setup = profile["services"]["cms-setup"]["environment"]
    assert database["image"] == "openmates-ci-database:local"
    assert database["environment"]["POSTGRES_PASSWORD"] == original_password
    assert setup["CI_PREPARED_SCHEMA"] == "1"
    assert setup["CI_PREPARED_SCHEMA_ADMIN_PASSWORD"] == PREPARED_SCHEMA_ADMIN_PASSWORD


def test_missing_or_incompatible_schema_uses_cold_initializer():
    profile = compose_profile("a" * 40)
    assert not apply_prepared_schema(
        profile, {"images": [{"kind": "schema", "reused": False}]}
    )
    assert profile["services"]["cms-database"]["image"] == POSTGRES_IMAGE
    assert "CI_PREPARED_SCHEMA" not in profile["services"]["cms-setup"]["environment"]

    stale = compose_profile("a" * 40)
    assert not apply_prepared_schema(
        stale,
        {
            "images": [
                {
                    "kind": "schema",
                    "reused": True,
                    "bundle_format": "old-format",
                    "restore_semantics": SCHEMA_RESTORE_SEMANTICS,
                }
            ]
        },
    )


def test_capacity_fixture_binds_application_before_real_celery_request_access(monkeypatch, capsys):
    import json
    import sys
    from types import ModuleType
    from celery import Celery, Task
    from scripts.ci_environment import CAPACITY_FIXTURE_SETUP

    app = Celery("ci-fixture-request-contract", broker="memory://", backend="cache+memory://")
    events = []
    directus = object()

    class FixtureTask(Task):
        request_stack = None
        __bound__ = False

        def __init__(self):
            self.directus_service = directus

        @classmethod
        def bind(cls, actual_app):
            assert actual_app is app
            events.append("bind_application")
            return super().bind(actual_app)

        async def initialize_core_services(self):
            assert self.app is app
            # Use Celery's real request property, including its LocalStack lookup.
            assert self.request.id is None
            events.append("request_access")

        async def cleanup_services(self):
            events.append("cleanup")

    # Reproduce the unbound contract that broke the real fixture bootstrap.
    with pytest.raises(AttributeError):
        _ = FixtureTask().request.id

    async def write_rollout(actual_directus, name, fields):
        assert actual_directus is directus and name == "synthetic-rollout"
        assert fields["reader_receipt"] == "ci-storage-capacity:" + "a" * 40
        events.append("write_synthetic_rollout")

    for name, values in (
        ("backend.core.api.app.tasks.base_task", {"BaseServiceTask": FixtureTask}),
        ("backend.core.api.app.tasks.celery_config", {"app": app}),
        ("scripts.storage_rollout", {"COLLECTIONS": ["synthetic-rollout"], "write_rollout": write_rollout}),
    ):
        module = ModuleType(name)
        for key, value in values.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv("BUILD_COMMIT_SHA", "a" * 40)
    exec(compile(CAPACITY_FIXTURE_SETUP, "capacity-fixture-setup", "exec"), {})
    receipt = json.loads(capsys.readouterr().out)
    assert receipt == {"status": "ready", "source_commit": "a" * 40, "collections_count": 1}
    assert events == ["bind_application", "request_access", "write_synthetic_rollout", "cleanup"]


@pytest.mark.parametrize("fails", [False, True])
def test_startup_evidence_survives_failure_without_private_output(tmp_path, monkeypatch, fails):
    import json
    from scripts import ci_environment as environment
    monkeypatch.setattr(environment, "SOURCE", str(tmp_path))
    monkeypatch.setattr(environment, "select_runtime_profile", lambda: True)
    def start():
        if fails:
            raise RuntimeError("private startup failure detail")
    monkeypatch.setattr(environment, "start_stack", start)
    monkeypatch.setattr(environment, "startup_service_timings", lambda began: [{"service": "cms-setup", "execution_seconds": 12}])
    if fails:
        with pytest.raises(RuntimeError, match="private startup failure"):
            environment.start_with_evidence()
    else:
        environment.start_with_evidence()
    raw = (tmp_path / "test-results/ci-startup-phases.json").read_text()
    report = json.loads(raw)
    assert report["outcome"] == ("failed" if fails else "ready")
    assert report["schema_mode"] == "prepared"
    assert report["services"][0]["service"] == "cms-setup"
    assert "private startup failure" not in raw


def test_startup_service_timings_retain_gates_without_health_logs(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from scripts import ci_environment as environment
    profile = tmp_path / "compose.json"
    profile.write_text(json.dumps({"services": {"cms-setup": {}}}))
    monkeypatch.setattr(environment, "COMPOSE_PATH", profile)
    monkeypatch.setattr(environment, "compose", lambda *args, **kwargs: SimpleNamespace(stdout="a" * 64))
    def inspect(command, **kwargs):
        assert ".Config.Env" not in command[3]
        assert ".Health.Log" not in command[3]
        return json.dumps({"service": "cms-setup", "started": "2026-10-05T10:00:10Z", "finished": "2026-10-05T10:00:32Z", "status": "exited", "exit_code": 0, "health": None})
    monkeypatch.setattr(environment.subprocess, "check_output", inspect)
    begin = datetime(2026, 10, 5, 10, tzinfo=timezone.utc).timestamp()
    result = environment.startup_service_timings(begin)[0]
    assert result["execution_seconds"] == 22
    assert result["started_after_stack_seconds"] == 10
    assert result["finished_after_stack_seconds"] == 32


@pytest.mark.parametrize("collection", [
    "team_storage_billing_periods",
    "team_storage_billing_owner_state",
    "team_storage_billing_warning_units",
])
def test_schema_setup_loads_candidate_policy_instead_of_cached_image(tmp_path, monkeypatch, collection):
    import runpy
    from scripts import ci_environment

    # A cached dependency image predates candidate collection policy additions.
    cached_policy = tmp_path / "cached-image/accountability_policy.py"
    cached_policy.parent.mkdir()
    cached_policy.write_text(
        "REDUCED_ACCOUNTABILITY = {}\n"
        "def configured_accountability(name, config):\n"
        "    value = config['meta']['accountability']\n"
        "    if name not in REDUCED_ACCOUNTABILITY or value != REDUCED_ACCOUNTABILITY[name]:\n"
        "        raise ValueError('Unreviewed Directus accountability override')\n"
        "    return True, value\n"
    )
    candidate_root = tmp_path / "candidate"
    candidate_policy = candidate_root / "backend/core/directus/setup/accountability_policy.py"
    candidate_policy.parent.mkdir(parents=True)
    candidate_policy.write_text(
        cached_policy.read_text() + f"\nREDUCED_ACCOUNTABILITY[{collection!r}] = None\n"
    )
    config = {"meta": {"accountability": None}}
    with pytest.raises(ValueError, match="Unreviewed Directus accountability override"):
        runpy.run_path(str(cached_policy))["configured_accountability"](collection, config)
    monkeypatch.setattr(ci_environment, "SOURCE", str(candidate_root))
    setup = compose_profile("a" * 40)["services"]["cms-setup"]
    policy_mounts = [mount.split(":") for mount in setup["volumes"]
                     if isinstance(mount, str) and ":/usr/src/app/accountability_policy.py:" in mount]
    assert policy_mounts == [[str(candidate_policy), "/usr/src/app/accountability_policy.py", "ro"]]
    mounted_policy = runpy.run_path(policy_mounts[0][0])
    assert mounted_policy["configured_accountability"](collection, config) == (True, None)


@pytest.mark.parametrize("team_source", [False, True])
@pytest.mark.parametrize("billing_profile", [None, "legacy", "logical"])
def test_team_billing_readiness_uses_frozen_source_capability(tmp_path, monkeypatch, team_source, billing_profile):
    from scripts import ci_environment
    monkeypatch.setattr(ci_environment, "SOURCE", str(tmp_path))
    if team_source:
        schema = tmp_path / "backend/core/directus/schemas/team_storage_billing.yml"
        schema.parent.mkdir(parents=True)
        schema.write_text("team_storage_billing_periods: {}\n")
    profile = compose_profile("a" * 40, storage_capacity=True, billing_profile=billing_profile)
    expected = ("0" if billing_profile == "legacy" else "1") if team_source else None
    for service in ("api", "core-worker", "ai-worker", "cms"):
        assert profile["services"][service]["environment"].get("TEAM_STORAGE_BILLING_ENABLED") == expected
    assert profile["networks"]["default"]["internal"] is True
    ordinary = compose_profile("a" * 40)
    for service in ("api", "core-worker", "cms"):
        assert "TEAM_STORAGE_BILLING_ENABLED" not in ordinary["services"][service]["environment"]
