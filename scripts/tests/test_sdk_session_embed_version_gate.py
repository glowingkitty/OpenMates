"""Pure source registration checks; no SDK runtime or adapter is executed."""
# contract-test-file: tooling
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("version_gate", ROOT / "scripts/check_sdk_conformance.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
IDENTITY = "session.embeds.version-content.v1"
FIXTURE = "tests/sdk-conformance/fixtures/session-embed-version-content.json"


def cookie_registration_matrix():
    """Reverse exact later source witnesses for the original Cookie assertions only."""
    matrix = json.loads((ROOT / gate.MATRIX).read_bytes())

    def digest(value):
        return hashlib.sha256((json.dumps(value, indent=2) + "\n").encode()).hexdigest()

    # Tests-only exact selected foreground-recovery matrix inverse.
    assert digest(matrix) == "b86d42a082c938bbcba834d28f0b2e8c2b35f7e107241241e3a6e162212f06f0"
    family = next(row for row in matrix["capabilities"] if row["id"] == "session.foreground-completion-recovery.v1")
    assert family["languages"]["rust"]["api"].count("client.Client.completion_recovery_jobs_for_chat") == 1
    family["languages"]["rust"]["api"].remove("client.Client.completion_recovery_jobs_for_chat")
    for path in ['frontend/packages/openmates-tui-native/tests/test_saved_read_startup_discovery.py']:
        assert family["languages"]["rust"]["evidence"].pop() == path
    for language in ("rust", "npm", "python"):
        assert family["languages"][language]["gaps"].pop() == 'Selected-Chat foreground recovery discovery remains required partial: direct explicit-credential Rust/npm/Python operations must discover only the exact canonical Chat via existing authenticated foreground startup offers, retain original owner/master-key/Team/private-policy/request/operation-epoch fences across all IO and final output, preserve unrelated in-memory offers and durable pending journals, and never grant phased-sync inventory, global absence, freshness or completeness from selected offers. Selected main and Personal metadata jobs, missing metadata, unrelated output/delivery filtering, failed/incomplete transaction nonpublication, cancelled/denied reads, strict retained140-row continuation and save-before-output require equivalent shared executable vectors and genuine matching direct SDK runs; equivalent language operation shapes may differ. Newly authored native source tests and source review are not runtime/conformance/performance acceptance; three-language adapters/shared fixture work remains separately reviewed and UNRUN. Existing protocol/authority and every prior release obligation remain mandatory.'

    # Tests-only exact cache/embed successor inverse; original history below stays held.
    assert digest(matrix) == "46026d4d141528e94577fe0272b47caca3723ae50c2a8dac7b9f8af6b797d95e"
    family = next(row for row in matrix["capabilities"] if row["id"] == "sdk.session-client")
    for symbol in ['client.Client.browser_metadata_cache_json', 'client.Client.saved_embed', 'client.browser_cache_metadata.BrowserMetadataCacheMode', 'client.browser_cache_metadata.BrowserMetadataCacheMode.PersistCurrent', 'client.browser_cache_metadata.BrowserMetadataCacheMode.Restore', 'client.browser_cache_metadata.BrowserMetadataCacheScope', 'client.saved_embed.SavedEmbedRead', 'client.saved_embed.SavedEmbedRead.check', 'client.saved_embed.SavedEmbedRead.json']:
        assert family["languages"]["rust"]["api"].count(symbol) == 1
        family["languages"]["rust"]["api"].remove(symbol)
    suffix = ' Selected Personal metadata-cache restore/persist and full-ID saved-embed reads remain required partial session/state operations. New Rust public capabilities are classified here pending genuine three-SDK fixtures and runtime proof; no separate executable family is invented from core-only source.'
    assert family["description"].endswith(suffix)
    family["description"] = family["description"][:-len(suffix)]
    for language in ("rust", "npm", "python"):
        assert family["languages"][language]["gaps"].pop() == 'Selected Personal metadata-cache and saved-embed behavior remains required partial: restore/persist only selected existing encrypted metadata with independent monotonic counters, original owner/key/epoch/request/private-denial fences, bounded IO terminal/readback receipts, and no message/history/journal/unknown-field writes or native credential ACK; full-ID Personal Cookie saved-embed reads must retain original publication scope, negative-only source authorization and staged key isolation, fail closed for cached source/hash/global/overflow denial, reject Team/Direct/prefix substitution, and wipe plaintext on release failure. Equivalent direct explicit-credential Rust/npm/Python functionality and inverse/adversarial shared executable fixtures, compiled native/WASM/Worker/IndexedDB/HTTP/WS execution, packaging and matched CPU/end-to-end/RAM/size proof remain unverified; language API shapes may differ and matching helper/enum names are not required. Core synthetic Rust fixtures and source/pure checks grant no runtime, activation, performance or release acceptance.'

    # Restore only the exact later ordinary-retention API/description input.
    assert digest(matrix) == "cb10bffa6d3fbe448245415af5a220ba3b244295d028d68c13e574b311ef1edf"
    family = next(row for row in matrix["capabilities"] if row["id"] == "sdk.session-client")
    for symbol in ['client.Client.prepare_browser_ordinary_key_retention', 'client.browser_ordinary_retention.BrowserOrdinaryKeyRetention', 'client.browser_ordinary_retention.BrowserOrdinaryKeyRetention.effect_json', 'client.browser_ordinary_retention.BrowserOrdinaryKeyRetention.take_key']:
        family["languages"]["rust"]["api"].remove(symbol)
    family["description"] = 'Reviewed public SDK capability family: sdk.session-client; support must be proved by actual library conformance. Rust browser platform draft APIs belong to this Client session-authority family; actual browser/WASM runtime and storage integration remain unverified. Classification adds no npm/Python browser API or parity/release claim.'
    for language, obligation in {'rust': 'Ordinary fresh-password retention remains required partial: native policy/public-consumer and genuine WASM/CryptoKey/Worker/IndexedDB retention/read tests are authored unrun; executable shared three-SDK functional retention conformance and generated package/runtime/performance acceptance remain unverified.', 'npm': 'Ordinary fresh-password retention remains required partial: equivalent direct explicit-credential ordinary-retention behavior and executable shared three-SDK functional fixture/schema/driver remain missing or unverified; language API shapes may differ and no matching Rust helper/enum exports are required.', 'python': 'Ordinary fresh-password retention remains required partial: equivalent direct explicit-credential ordinary-retention behavior and executable shared three-SDK functional fixture/schema/driver remain missing or unverified; language API shapes may differ and no matching Rust helper/enum exports are required.'}.items():
        assert family["languages"][language]["gaps"].pop() == obligation
    assert digest(matrix) == "6d466f3806f59d5e69ef94072ed2c169ec9f539fc46531c75502a4dacab374e8"

    # Restore the exact removed unshipped Rust constant for history only.
    assert digest(matrix) == "6d466f3806f59d5e69ef94072ed2c169ec9f539fc46531c75502a4dacab374e8"
    family = next(row for row in matrix["capabilities"] if row["id"] == "sdk.session-client")
    assert "client.message_window.MAX_MESSAGE_ID_BYTES" not in family["languages"]["rust"]["api"]
    family["languages"]["rust"]["api"].append("client.message_window.MAX_MESSAGE_ID_BYTES")
    family["languages"]["rust"]["api"].sort()
    assert digest(matrix) == "2847dac0c6d45998e2ba0d39928fb39381a6ad0844cdfac523f287b86aaa3a90"

    # Reverse only the exact later first-page/browser registration.
    assert digest(matrix) == "2847dac0c6d45998e2ba0d39928fb39381a6ad0844cdfac523f287b86aaa3a90"
    assert matrix["capabilities"][-1]["id"] == "session.chat-first-page-continuation.v1"
    matrix["capabilities"].pop()
    for identity, added in [('sdk.session-client', ['client.Client.browser_saved_chat_read_json', 'client.Client.browser_local_checkpoint_summary_with_io_json']), ('session.saved-chat-read.v1', ['client.saved_chat_read.SavedChatReadAdmission.ensure_resource_current'])]:
        family = next(row for row in matrix["capabilities"] if row["id"] == identity)
        for api in added:
            assert family["languages"]["rust"]["api"].count(api) == 1
            family["languages"]["rust"]["api"].remove(api)
    assert digest(matrix) == "69bc6f28a82b296fa9f3a577b74eab8d127f449b276f301fcd66c27f3a4d5f98"

    # Classify the existing Rust bound without changing capability support.
    assert digest(matrix) == "69bc6f28a82b296fa9f3a577b74eab8d127f449b276f301fcd66c27f3a4d5f98"
    family = next(row for row in matrix["capabilities"] if row["id"] == "sdk.session-client")
    assert family["languages"]["rust"]["api"].count("client.message_window.MAX_MESSAGE_ID_BYTES") == 1
    family["languages"]["rust"]["api"].remove("client.message_window.MAX_MESSAGE_ID_BYTES")
    assert digest(matrix) == "9b62b9ea19a5503e42c2e926fe860c79557217352ebf736a0c1029538f3286e1"

    # Restore only the exact later bounded message-ID classification.
    assert digest(matrix) == "9b62b9ea19a5503e42c2e926fe860c79557217352ebf736a0c1029538f3286e1"
    for identity in ('sdk.session-client', 'session.message-window.v1', 'session.saved-chat-read.v1'):
        family = next(row for row in matrix["capabilities"] if row["id"] == identity)
        for language in gate.LANGUAGES:
            assert family["languages"][language]["gaps"].pop() == 'Read-message ID compatibility supports exact visible ASCII bytes 0x21..0x7e, length1–256, including deployed chat-suffix UUIDs; Chat UUID/send/recovery authority stays strict. Backend-permitted spaces, Unicode and IDs longer than256bytes, and dot-only exact-route IDs remain unsupported pending safe parser/transport proof. Equivalent bounded read-message ID behavior and executable three-SDK execution of the expanded27-window/66-saved-read fixtures remain unverified; language API shapes may differ. Source/pure checks establish no compiled/runtime, personal-account, ARM-package, performance, canonical-history or release acceptance.'
        if identity == "sdk.session-client":
            assert family["languages"]["rust"]["api"].count('client.message_window.valid_message_id') == 1
            family["languages"]["rust"]["api"].remove('client.message_window.valid_message_id')
    assert digest(matrix) == "084227e24aefab490b0b09e5da962df9a15ede999ad18a29f5821768f0463ea2"

    browser_raw = (ROOT / "scripts/tests/fixtures/sdk-conformance-trust-browser-local-wire-cursor-delta.json").read_bytes()
    assert hashlib.sha256(browser_raw).hexdigest() == "ce725e243ed00e27f69792e51415ee6fafb0e91c08f42a4a5a466c10bf0b7c1d"
    browser = json.loads(browser_raw)["matrixDelta"]
    assert digest(matrix) == browser["afterSha256"]
    family = next(row for row in matrix["capabilities"] if row["id"] == browser["family"])
    assert family["languages"]["rust"]["api"].count(browser["rustApiAdded"]) == 1
    family["languages"]["rust"]["api"].remove(browser["rustApiAdded"])
    for language in gate.LANGUAGES:
        assert family["languages"][language]["gaps"].pop() == browser["gapAddedEachLanguage"]
    assert digest(matrix) == browser["beforeSha256"]

    source_raw = (ROOT / "scripts/tests/fixtures/sdk-conformance-trust-cache-settlement-source-delta.json").read_bytes()
    assert hashlib.sha256(source_raw).hexdigest() == "68c1a85b9c676b9c66c80a0d67ccd7f953f665834071e4a87c7db37305f67ad5"
    source = json.loads(source_raw)["pinDeltas"]["contracts"][gate.MATRIX]
    # The appended capability owns its four npm and four Python cache APIs.
    # Its exact complete contents are bound by the immutable source-matrix digest.
    cache = matrix["capabilities"][-1]
    assert cache["id"] == "session.cache-preferred-settlement.v1"
    for language in gate.LANGUAGES:
        assert cache["languages"][language]["conformance"] is True
        cache["languages"][language]["conformance"] = False
    assert cache.pop("fixture") == "tests/sdk-conformance/fixtures/session-cache-preferred-settlement.json"
    assert digest(matrix) == source["after"]
    matrix["capabilities"].pop()
    assert digest(matrix) == source["before"]
    return matrix


def test_fixed_version_content_library_adapters():
    stem = "session-embed-version-content"
    assert gate.ADAPTER_OVERRIDES[("rust", IDENTITY)] == [*gate.RUST_SESSION_RUNNER[:-2], stem + "-conformance", "--"]
    assert gate.ADAPTER_OVERRIDES[("npm", IDENTITY)] == ["node", "tests/sdk-conformance/runners/" + stem + ".mjs"]
    assert gate.ADAPTER_OVERRIDES[("python", IDENTITY)] == [gate.sys.executable, "tests/sdk-conformance/runners/" + stem + ".py"]
    assert gate.FIXTURE_SCHEMAS[FIXTURE] == "tests/sdk-conformance/schemas/session-embed-version-content.schema.json"

def test_real_version_fixture_schema_and_complete_identity_set():
    raw = (ROOT / FIXTURE).read_bytes()
    document = json.loads(raw)
    gate.validate_fixture_document(FIXTURE, document)
    vectors = document["capabilities"][IDENTITY]["vectors"]
    assert len(vectors) == len({v["id"] for v in vectors}) == 21
    gate.validate_fixture_error_oracles(document["capabilities"])


def test_invalid_version_fixture_refused_before_adapter(tmp_path, monkeypatch):
    fixture = tmp_path / FIXTURE
    fixture.parent.mkdir(parents=True)
    fixture.write_text("{}")
    schema_name = gate.FIXTURE_SCHEMAS[FIXTURE]
    schema = tmp_path / schema_name
    schema.parent.mkdir(parents=True)
    schema.write_bytes((ROOT / schema_name).read_bytes())
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid version fixture must not start adapters")
    monkeypatch.setattr(gate.subprocess, "run", forbidden)
    with pytest.raises(jsonschema.ValidationError):
        gate.conformance({"fixture": FIXTURE, "capabilities": [{"id": IDENTITY}]}, tmp_path)


def test_version_registration_preserves_old_plans_and_partial_status():
    matrix = cookie_registration_matrix()
    version = next(c for c in matrix["capabilities"] if c["id"] == IDENTITY)
    assert version["fixture"] == FIXTURE
    assert all(version["languages"][lang]["status"] == "partial" and version["languages"][lang]["conformance"] and version["languages"][lang]["gaps"] for lang in gate.LANGUAGES)
    assert sum(s["conformance"] for c in matrix["capabilities"] for s in c["languages"].values()) == 87
    assert sum(s["status"] != "implemented" for c in matrix["capabilities"] for s in c["languages"].values()) == 174


def test_missing_version_vectors_fail_closed():
    raw = (ROOT / FIXTURE).read_bytes()
    vectors = json.loads(raw)["capabilities"][IDENTITY]["vectors"]
    result = {"capability": IDENTITY, "language": "rust", "status": "passed", "fixtureSha256": hashlib.sha256(raw).hexdigest(), "results": [{"id": v["id"], "status": "passed"} for v in vectors[:-1]]}
    with pytest.raises(ValueError, match="not fully executed"):
        gate.validate_result(result, IDENTITY, "rust", result["fixtureSha256"], {v["id"] for v in vectors})


def test_gate_dispatches_all_three_complete_version_plans(tmp_path, monkeypatch):
    fixture = tmp_path / FIXTURE
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes((ROOT / FIXTURE).read_bytes())
    schema_name = gate.FIXTURE_SCHEMAS[FIXTURE]
    schema = tmp_path / schema_name
    schema.parent.mkdir(parents=True)
    schema.write_bytes((ROOT / schema_name).read_bytes())
    vectors = json.loads(fixture.read_bytes())["capabilities"][IDENTITY]["vectors"]
    matrix = {"fixture": FIXTURE, "capabilities": [{"id": IDENTITY, "languages": {lang: {"status": "partial", "conformance": True} for lang in gate.LANGUAGES}}]}
    calls = []
    def simulated(command, **kwargs):
        language = gate.LANGUAGES[len(calls)]
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"capability": IDENTITY, "language": language, "status": "passed", "fixtureSha256": hashlib.sha256(fixture.read_bytes()).hexdigest(), "results": [{"id": v["id"], "status": "passed"} for v in vectors]}))
    monkeypatch.setattr(gate.subprocess, "run", simulated)
    results = gate.conformance(matrix, tmp_path)
    assert len(results) == 3
    assert calls == [gate.ADAPTER_OVERRIDES[(lang, IDENTITY)] + ["--fixture", str(fixture), "--capability", IDENTITY] for lang in gate.LANGUAGES]
    assert all(c["languages"][lang]["status"] == "partial" for c in matrix["capabilities"] for lang in gate.LANGUAGES)


@pytest.mark.parametrize("mutation", ["root-extra", "vector-extra", "error-extra", "vector-omission"])
def test_cookie_closed_fixture_rejects_unknown_fields_errors_and_missing_vectors(mutation):
    document = json.loads((ROOT / FIXTURE).read_bytes())
    vectors = document["capabilities"][IDENTITY]["vectors"]
    if mutation == "root-extra":
        document["unknown"] = True
    elif mutation == "vector-extra":
        vectors[0]["unknown"] = True
    elif mutation == "error-extra":
        vectors[0]["error"] = "unknown"
    else:
        vectors.pop()
    with pytest.raises(jsonschema.ValidationError):
        gate.validate_fixture_document(FIXTURE, document)


def test_cookie_registration_retains_exact_prior64_capabilities_and102_api_key_vectors():
    matrix = cookie_registration_matrix()
    prior = matrix["capabilities"][:-1]
    assert len(prior) == 64
    assert hashlib.sha256(json.dumps(prior, sort_keys=True).encode()).hexdigest() == "e0791e206d527537765361cb0ad51f1a488bb91b7a3a6dc3604fc673694e8fbf"
    assert sum(s["conformance"] for c in prior for s in c["languages"].values()) == 84
    assert sum(s["status"] != "implemented" for c in prior for s in c["languages"].values()) == 171
    raw = (ROOT / "tests/sdk-conformance/fixtures/sdk-embed-version-content.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "6f798513498497f0f7978e6afa2b504aa0e12a75ba40af5eff6e5cf2c91a1e7c"
    assert len(json.loads(raw)["capabilities"]["sdk.embeds.version-content"]["vectors"]) == 102


@pytest.mark.parametrize("language", ["rust", "npm", "python"])
def test_cookie_coordinator_emits_fixture_bound_result_without_sdk_execution(language, monkeypatch, capsys):
    """Exercise envelope serialization only; no SDK, subprocess or peer listener."""
    import sys
    from types import ModuleType

    runner_path = ROOT / "tests/sdk-conformance/runners/session-embed-version-content.py"
    runner_spec = importlib.util.spec_from_file_location("cookie_version_runner", runner_path)
    runner = importlib.util.module_from_spec(runner_spec)
    runner_spec.loader.exec_module(runner)
    raw = (ROOT / FIXTURE).read_bytes()
    vectors = json.loads(raw)["capabilities"][IDENTITY]["vectors"]
    checked, closed, invoked = [], [], []
    observation = object()

    class EnvelopePeer:
        def __init__(self, suite, vector, identity):
            self.vector = vector
            assert identity == {"rust": "rust", "npm": "npm", "python": "pip"}[language]
            self.endpoint = "http://127.0.0.1:1"

        def start(self):
            return self

        def check(self, observed):
            assert observed is observation
            checked.append(self.vector["id"])

        def close(self):
            closed.append(self.vector["id"])

    peer_module = ModuleType("session_embed_version_peer")
    peer_module.CookieVersionPeer = EnvelopePeer
    monkeypatch.setitem(sys.modules, "session_embed_version_peer", peer_module)

    def envelope_only(argv, case):
        invoked.append(case["vector"]["id"])
        return observation

    monkeypatch.setattr(runner, "invoke", envelope_only)
    def forbidden(*args, **kwargs):
        pytest.fail("Envelope check must not start product adapters or subprocesses")
    monkeypatch.setattr(runner.subprocess, "Popen", forbidden)
    monkeypatch.setattr(runner, "python_case", forbidden)
    monkeypatch.setattr(sys, "argv", [str(runner_path), "--fixture", str(ROOT / FIXTURE),
        "--capability", IDENTITY, "--language", language,
        "--rust-executable", str(runner_path)])
    runner.main()
    result = json.loads(capsys.readouterr().out)
    ids = [v["id"] for v in vectors]
    assert checked == closed == invoked == ids
    fixture_hash = hashlib.sha256(raw).hexdigest()
    gate.validate_result(result, IDENTITY, language, fixture_hash, set(ids))
    for bad_hash in (None, "0" * 64):
        bad_result = {**result, "fixtureSha256": bad_hash}
        with pytest.raises(ValueError, match="fixtureSha256"):
            gate.validate_result(bad_result, IDENTITY, language, fixture_hash, set(ids))
