# contract-test-file: tooling
"""Only the reviewed web voice case receives the separate runner credentials."""

import json
from pathlib import Path

import pytest
import yaml

from scripts import ci_environment as ci
from scripts import ci_results
from scripts import ci_tcp_gateway as gateway

SPEC = ci.CODEX_WEB_VOICE_SPEC
SELECTED = {"CI_CODEX_WEB_VOICE": "1", "CI_TEST_MODE": "e2e", "CI_SPECS_JSON": json.dumps([SPEC])}
KEY_NAMES = {name for _, name in ci.CODEX_WEB_VOICE_PROVIDERS.values()}
NARROW_KEYS = {name for _, name in ci.CODEX_REAL_INFERENCE_PROVIDERS.values()}
LEGACY_KEYS = {name for _, name in ci.REAL_INFERENCE_PROVIDERS.values()}


@pytest.mark.parametrize("selected,environ", [
    ([SPEC], {"CI_TEST_MODE": "e2e"}),
    ([SPEC, "another.spec.ts"], SELECTED),
    (["another.spec.ts"], SELECTED),
    ([SPEC], {**SELECTED, "CI_TEST_MODE": "visual-smoke"}),
    ([SPEC], {**SELECTED, "CI_CODEX_REAL_INFERENCE": "1"}),
])
def test_only_exact_signed_in_web_voice_spec_enters_the_lane(selected, environ):
    assert ci.selects_codex_web_voice([SPEC], {SPEC}, SELECTED)
    with pytest.raises(RuntimeError, match="one exact"):
        ci.selects_codex_web_voice(selected, {SPEC}, environ)
    with pytest.raises(RuntimeError, match="one exact"):
        ci.selects_codex_web_voice([SPEC], set(), SELECTED)


def test_provider_credentials_need_all_four_separate_names_and_live_speech_worker():
    profile = ci.compose_profile("a" * 40, real_inference=True, codex_web_voice=True)
    services = profile["services"]
    vault = services["vault-init"]["environment"]
    assert set(json.loads(vault["CI_REAL_INFERENCE_PROVIDERS"])) == {
        "inception_labs", "typesafe", "mistral_ai", "elevenlabs",
    }
    assert KEY_NAMES <= set(vault) and all(vault[name] is None for name in KEY_NAMES)
    assert not (LEGACY_KEYS | NARROW_KEYS) & set(vault)
    assert services["speech-worker"]["environment"]["CELERY_QUEUES"] == "app_music"
    assert ci.verify_web_voice_services(services)
    assert "images-worker" not in services
    assert profile["networks"]["default"]["internal"] is True
    supplied = {**SELECTED, **dict.fromkeys(KEY_NAMES, "synthetic-protected-credential")}
    ci.validate_real_inference_start(profile, supplied, {SPEC})
    for key in KEY_NAMES:
        with pytest.raises(RuntimeError, match=key):
            ci.validate_real_inference_start(profile, {**supplied, key: ""}, {SPEC})
    services["speech-worker"]["environment"]["OPENMATES_CI_AI_FIXTURES"] = "1"
    with pytest.raises(RuntimeError, match="dedicated isolated provider profile"):
        ci.validate_real_inference_start(profile, supplied, {SPEC})


def test_web_voice_connect_is_closed_to_other_providers_and_redacts_all_values():
    env = {"OPENMATES_CI_REAL_INFERENCE_PROXY": "codex-web-voice"}
    assert gateway.provider_proxy_hosts(env) == {
        "api.inceptionlabs.ai", "api.typesafe.ai", "api.mistral.ai", "api.elevenlabs.io",
    }
    assert gateway.provider_proxy_hosts({"OPENMATES_CI_REAL_INFERENCE_PROXY": "codex"}) == {
        "api.inceptionlabs.ai", "api.typesafe.ai",
    }
    with pytest.raises(RuntimeError, match="never share"):
        gateway.provider_proxy_hosts({**env, "OPENMATES_CI_PUBLIC_PROVIDER_PROXY": "1"})
    profile = ci.compose_profile("a" * 40, real_inference=True, codex_web_voice=True)
    synthetic = {name: "synthetic-secret-" + str(i) for i, name in enumerate(sorted(KEY_NAMES))}
    text = ci.redact_real_inference_logs(" ".join(synthetic.values()), profile, synthetic)
    assert text == " ".join(["<REDACTED>"] * 4)


def test_verified_workflow_pins_tooling_and_keeps_speech_secrets_in_one_step():
    root = Path(__file__).resolve().parents[2]
    job = yaml.safe_load((root / ".github/workflows/isolated-tests.yml").read_text())["jobs"]["test"]
    steps = job["steps"]
    exact = f"inputs.specs_json == '[{json.dumps(SPEC)}]'"
    dedicated = next(step for step in steps if step.get("name") == "Start isolated signed-in web voice backend")
    assert exact in dedicated["if"] and exact in job["environment"] and "'codex-web-voice'" in job["environment"]
    assert exact in job["env"]["CI_HARNESS_COMMIT"] and exact in job["env"]["CI_CODEX_WEB_VOICE"]
    assert {name for name in dedicated["env"] if name.endswith("_API_KEY")} == KEY_NAMES
    assert "refs/heads/dev" in dedicated["run"] and '"$GITHUB_SHA"' in dedicated["run"]
    assert "OPENMATES_CODEX_WEB_VOICE" not in repr([step for step in steps if step is not dedicated])
    assert any(step.get("name") == "Start isolated terminal real-inference backend" for step in steps)


def test_web_voice_evidence_requires_the_workflow_sha_and_its_own_runtime():
    source, preparation, workflow = "a" * 40, "b" * 40, "c" * 40
    job = {"mode": "e2e", "specs": json.dumps([SPEC]), "source": source,
           "preparation_harness_commit": preparation}
    evidence = {
        "source_commit": source, "harness_commit": workflow,
        "frontend": {"source_commit": source}, "shared_dev_https": "rejected",
        "services": {"speech-worker": {"running": True}},
        "provider_egress": "real-inference-allowlist", "real_inference_profile": "codex-real-web-voice",
        "real_inference_providers": ["elevenlabs", "inception_labs", "mistral_ai", "typesafe"],
    }
    assert ci_results.expected_job_harness_commit(job, workflow) == workflow
    assert ci_results.green_e2e_source_and_egress_verified(evidence, job, expected_harness_commit=workflow)
    evidence["real_inference_profile"] = "codex-real-inference"
    assert not ci_results.green_e2e_source_and_egress_verified(evidence, job, expected_harness_commit=workflow)
