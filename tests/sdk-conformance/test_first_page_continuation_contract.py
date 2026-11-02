"""Pure schema/dispatch/refusal checks; no listener, SDK import or native runtime."""

# contract-test-file: tooling
import ast
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import pytest
import jsonschema

ROOT = Path(__file__).resolve().parents[2]
CAP = "session.chat-first-page-continuation.v1"
FIXTURE = "tests/sdk-conformance/fixtures/session-chat-first-page-continuation.json"
SCHEMA = (
    "tests/sdk-conformance/schemas/session-chat-first-page-continuation.schema.json"
)


def docs():
    return json.loads((ROOT / FIXTURE).read_bytes()), json.loads(
        (ROOT / SCHEMA).read_bytes()
    )


def test_all16_ordered_vectors_checked_by_exact_schema():
    fixture, schema = docs()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(fixture, schema)
    vectors = fixture["capabilities"][CAP]["vectors"]
    assert len(vectors) == len({v["id"] for v in vectors}) == 16
    assert [v["message_id_mode"] for v in vectors[:3]] == [
        "uuid",
        "composite",
        "opaque",
    ]


@pytest.mark.parametrize(
    "mutation",
    ["unknown", "wrong-mode", "wrong-id-mode", "swapped", "missing", "extra", "crypto"],
)
def test_schema_refuses_unregistered_or_misbound_vectors(mutation):
    fixture, schema = docs()
    suite = fixture["capabilities"][CAP]
    vectors = suite["vectors"]
    if mutation == "unknown":
        vectors[0]["id"] = "fabricated-pass"
    elif mutation == "wrong-mode":
        vectors[0]["mode"] = "capacity-false"
    elif mutation == "wrong-id-mode":
        vectors[1]["message_id_mode"] = "uuid"
    elif mutation == "swapped":
        vectors[0], vectors[1] = vectors[1], vectors[0]
    elif mutation == "missing":
        vectors.pop()
    elif mutation == "extra":
        vectors.append(copy.deepcopy(vectors[0]))
    elif mutation == "crypto":
        suite["account"]["master_key"] = "fabricated-key"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(fixture, schema)


def test_crypto_and_protocol_are_exact_prior_fixture_without_modifying_it():
    fixture, _ = docs()
    prior = json.loads(
        (
            ROOT
            / "tests/sdk-conformance/fixtures/session-cache-preferred-settlement.json"
        ).read_bytes()
    )["capabilities"]["session.cache-preferred-settlement.v1"]
    for field in ["account", "protocol"]:
        assert fixture["capabilities"][CAP][field] == prior[field]
    assert len(prior["vectors"]) == 8
    assert fixture["capabilities"][CAP]["required_unverified"]


def gate():
    spec = importlib.util.spec_from_file_location(
        "first_page_gate_contract", ROOT / "scripts/check_sdk_conformance.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixed_three_real_library_adapters_and_schema_mapping():
    module = gate()
    fixture, _ = docs()
    module.validate_fixture_document(FIXTURE, fixture, ROOT)
    assert module.FIXTURE_SCHEMAS[FIXTURE] == SCHEMA
    assert (
        "session-chat-first-page-continuation-conformance"
        in module.ADAPTER_OVERRIDES[("rust", CAP)]
    )
    assert module.ADAPTER_OVERRIDES[("rust", CAP)][0] == "cargo"
    assert module.ADAPTER_OVERRIDES[("npm", CAP)] == [
        "node",
        "tests/sdk-conformance/runners/session-chat-first-page-continuation.mjs",
    ]
    assert (
        module.ADAPTER_OVERRIDES[("python", CAP)][1]
        == "tests/sdk-conformance/runners/session-chat-first-page-continuation.py"
    )
    assert (
        '"packages/openmates-session-bindings/examples/session-chat-first-page-continuation-conformance.rs",'
        in (ROOT / "scripts/check_sdk_conformance.py").read_text()
    )


def test_actual_python_adapter_refuses_unknown_mode_before_any_peer_or_client():
    # Extract the authored function unchanged without importing native dependencies.
    # The first assertion must fire before any temporary directory/peer/client access.
    source = ast.parse(
        (
            ROOT
            / "tests/sdk-conformance/runners/session-chat-first-page-continuation.py"
        ).read_text()
    )
    nodes = [
        n
        for n in source.body
        if (
            isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "MODES" for t in n.targets)
        )
        or (isinstance(n, ast.AsyncFunctionDef) and n.name == "vector")
    ]
    namespace = {}
    exec(
        compile(
            ast.Module(body=nodes, type_ignores=[]), "<actual-adapter-refusal>", "exec"
        ),
        namespace,
    )
    with pytest.raises(AssertionError, match="unregistered mode"):
        asyncio.run(
            namespace["vector"](
                {}, {"mode": "invented", "message_id_mode": "uuid"}, None
            )
        )


def test_actual_python_logical_id_selectors_preserve_composite_and_opaque_exactly():
    source = ast.parse(
        (
            ROOT
            / "tests/sdk-conformance/runners/session-chat-first-page-continuation.py"
        ).read_text()
    )
    namespace = {}
    nodes = [
        n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "logical"
    ]
    exec(
        compile(
            ast.Module(body=nodes, type_ignores=[]), "<actual-adapter-selector>", "exec"
        ),
        namespace,
    )
    logical = namespace["logical"]
    chat = "22222222-2222-4222-8222-222222222222"
    assert (
        logical(chat, "composite", 41)
        == "2222222222-10000000-0000-4000-8000-000000000041"
    )
    assert logical(chat, "opaque", 41) == "legacy_msg_0041"
    with pytest.raises(AssertionError):
        logical(chat, "normalized-or-unbounded", 41)


def test_real_interfaces_and_failclosed_dispatch_are_authored_not_mock_substitutes():
    npm = (
        ROOT / "tests/sdk-conformance/runners/session-chat-first-page-continuation.mjs"
    ).read_text()
    python = (
        ROOT / "tests/sdk-conformance/runners/session-chat-first-page-continuation.py"
    ).read_text()
    rust = (
        ROOT
        / "packages/openmates-session-bindings/examples/session-chat-first-page-continuation-conformance.rs"
    ).read_text()
    assert "dist/sdk-entry.js" in npm and "client.readChatWithFirstPage(" in npm
    assert (
        "read_chat_with_first_page(" in python
        and "from essential_session import Store,client,refused" in python
    )
    assert (
        "use _native::" in rust
        and ".first_page_open(" in rust
        and ".first_page_receipt(" in rust
    )
    assert (
        "Unsupported first-page mode" in npm
        and "unregistered mode" in python
        and "unregistered mode" in rust
    )
    for source in [npm, python, rust]:
        assert "first_page_continuation_peer.py" in source
        assert "openmates tasks" not in source and "cli.js" not in source


def test_stale_owner_actions_precede_pending_b_ack_in_each_real_adapter():
    npm = (
        ROOT / "tests/sdk-conformance/runners/session-chat-first-page-continuation.mjs"
    ).read_text()
    python = (
        ROOT / "tests/sdk-conformance/runners/session-chat-first-page-continuation.py"
    ).read_text()
    rust = (
        ROOT
        / "packages/openmates-session-bindings/examples/session-chat-first-page-continuation-conformance.rs"
    ).read_text()
    pending = npm.index("stageB=await next(b)")
    close = npm.index("assert.throws(()=>nativeClient.firstPageClose(a)", pending)
    stale = npm.index("nativeClient.firstPageReceipt(a,stageA.id,receiptA)", close)
    ack = npm.index("nativeClient.firstPageReceipt(b,stageB.id,receiptB)", stale)
    assert pending < close < stale < ack
    pending = python.index("stage_b=await next_event(b)")
    close = python.index("conflict(lambda:native.first_page_close(a))", pending)
    stale = python.index(
        "conflict(lambda:native.first_page_receipt(a,stage_a['id'],receipt_a))", close
    )
    ack = python.index("native.first_page_receipt(b,stage_b['id'],receipt_b)", stale)
    assert pending < close < stale < ack
    assert "first_page_close(a.clone()).err().unwrap().code" in rust


def test_rust_construction_installs_owned_guard_before_child_and_awaits():
    rust = (
        ROOT
        / "packages/openmates-session-bindings/examples/session-chat-first-page-continuation-conformance.rs"
    ).read_text()
    guard = rust.index("let mut owned = PeerGuard")
    spawn = rust.index(".spawn()", guard)
    ready = rust.index("recv_timeout", spawn)
    validation = rust.index(".validate_session()", ready)
    transfer = rust.index("peer: owned", validation)
    assert guard < spawn < ready < validation < transfer
    assert (
        "if let Some(child) = &mut self.child" in rust
        and "child.kill()" in rust
        and "child.wait()" in rust
    )


def test_callback_abort_is_separate_from_vector_watchdog_ownership():
    npm = (
        ROOT / "tests/sdk-conformance/runners/session-chat-first-page-continuation.mjs"
    ).read_text()
    assert (
        "lease=createOwnership(),owner=lease.vector,controller=lease.read,check=lease.check"
        in npm
    )
    assert "lease.cancelAll();" in npm
