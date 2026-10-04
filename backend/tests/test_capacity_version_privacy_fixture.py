"""Offline Project capacity fixture contract through actual client PII code."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from backend.apps.ai.testing.capacity_fixtures import generate_fixture


ROOT = Path(__file__).resolve().parents[2]
MODEL = "gemini-3.5-flash-lite"
BRIDGE = r"""
const fs = require('node:fs');
const { stripTypeScriptTypes } = require('node:module');
const root = process.cwd();
function moduleUrl(path, rewrite) {
  let source = stripTypeScriptTypes(fs.readFileSync(root + path, 'utf8'));
  if (rewrite) source = rewrite(source);
  return 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
}
async function run() {
  const identifier = moduleUrl('/frontend/packages/secret-scanner/src/identifierRanges.ts');
  const pii = moduleUrl('/frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts',
    source => source.replace(/import \{ codingIdentifierRanges \} from "[^"]+";/,
      'import { codingIdentifierRanges } from "' + identifier + '";'));
  const protocol = moduleUrl('/frontend/packages/ui/src/utils/projectFileMutationProtocol.ts');
  const privacy = moduleUrl('/frontend/packages/ui/src/services/projectFilePrivacy.ts',
    source => source.replace(/from "[^"]*piiDetectionService";/, 'from "' + pii + '";')
      .replace(/from "[^"]*projectFileMutationProtocol";/, 'from "' + protocol + '";'));
  const { ProjectFilePrivacy } = await import(privacy);
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  let mappings = input.mappings || [];
  const instance = new ProjectFilePrivacy({ mappings, preserveMappedTokens: true,
    save: async value => { mappings = value; } });
  if (input.action === 'redact') {
    const text = await instance.redactResult(input.text);
    process.stdout.write(JSON.stringify({ text, mappings }));
  } else if (input.action === 'restore') {
    process.stdout.write(JSON.stringify(instance.restoreMutation(input.mutation)));
  } else throw new Error('Unknown offline privacy action');
}
run().catch(error => { process.stderr.write(error.name + '\n'); process.exit(1); });
"""


def _client_privacy(value: dict) -> dict:
    result = subprocess.run(
        ["node", "--no-warnings", "-e", BRIDGE],
        cwd=ROOT, input=json.dumps(value), text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)


def _payload(user: int, number: int) -> str:
    # Independent ledger generator, matching the capacity runner's stated seed.
    label = f"storage-capacity-v1:{user}:version:{number}".encode()
    return "".join(hashlib.sha256(label + index.to_bytes(4, "big")).hexdigest()
                   for index in range(64))


def _fixture(messages: list[dict], tools: tuple[str, ...]) -> dict | None:
    return generate_fixture(f"llm/{MODEL}", {
        "model": MODEL, "messages": messages,
        "tools": [{"function": {"name": name}} for name in tools],
    })


def _arguments(fixture: dict) -> tuple[str, dict]:
    call = fixture["response"]["chunks"][0]["value"]
    return call["function_name"], call["function_arguments_parsed"]


# contract-test: supporting surface=cli assertions=storage.validation.synthetic-capacity
def test_redacted_create_fixture_restores_exact_independent_ledger_content() -> None:
    original = _payload(0, 0)
    prompt = ("STORAGE_CAPACITY_SCENARIO:version_create\n"
              f"CAPACITY_VERSION_NEW:{original}\n"
              "Use the Project file tool on capacity.txt and confirm the result.")
    prepared = _client_privacy({"action": "redact", "text": prompt})
    assert "[OM_PII_" in prepared["text"]  # This fixture must exercise the previous truncation.
    fixture = _fixture([{"role": "user", "content": prepared["text"]}], ("project_create_file",))
    assert fixture is not None
    name, arguments = _arguments(fixture)
    assert name == "project_create_file"
    assert "[OM_PII_" in arguments["content"]
    restored = _client_privacy({
        "action": "restore", "mappings": prepared["mappings"],
        "mutation": {"operation": "create_file", "operation_id": "capacity-test",
                     **arguments},
    })
    assert restored["content"] == original
    completed = {"status": "completed", "tool_name": "project_create_file",
                 "arguments": {"path": "capacity.txt"},
                 "results": [{"status": "completed", "path": "capacity.txt"}]}
    event = {"role": "user", "content": (
        "[async_tool_result]: Automatic tool-completion event, not a new request. "
        "Completed tool result (TOON):\n" + json.dumps(completed)
    )}
    assert _fixture([{"role": "user", "content": prepared["text"]}, event],
                    ("project_create_file",))["response"]["type"] == "stream"


# contract-test: supporting surface=cli assertions=storage.validation.synthetic-capacity
def test_redacted_update_uses_authoritative_project_read_base() -> None:
    old, new = _payload(0, 0), _payload(0, 1)
    prompt = ("STORAGE_CAPACITY_SCENARIO:version_update\n"
              f"CAPACITY_VERSION_NEW:{new}\nCAPACITY_VERSION_OLD:{old}\n"
              "Use the Project file tool on capacity.txt and confirm the result.")
    prepared = _client_privacy({"action": "redact", "text": prompt})
    messages = [{"role": "user", "content": prepared["text"]}]
    names = ("project_read_text", "project_update_file")
    initial = _fixture(messages, names)
    assert initial is not None
    assert _arguments(initial) == ("project_read_text", {"path": "capacity.txt"})
    base = hashlib.sha256(old.encode()).hexdigest()
    completion = {"status": "completed", "tool_name": "project_read_text",
                  "arguments": {"path": "capacity.txt"}, "results": [{
                      "operation": "read_text", "status": "completed", "path": "capacity.txt",
                      "content": old, "expected_base": base, "truncated": False,
                  }]}
    messages.append({"role": "user", "content": (
        "[async_tool_result]: Automatic tool-completion event, not a new request. "
        "Completed tool result (TOON):\n" + json.dumps(completion)
    )})
    proposed = _fixture(messages, names)
    assert proposed is not None
    name, arguments = _arguments(proposed)
    assert name == "project_update_file"
    assert arguments["expected_base"] == base
    restored = _client_privacy({
        "action": "restore", "mappings": prepared["mappings"],
        "mutation": {"operation": "update_file", "operation_id": "capacity-test",
                     **arguments},
    })
    assert restored["expected_base"] == base
    assert f"-{old}\n" in restored["patch"]
    assert f"+{new}\n" in restored["patch"]
    completed_write = {"status": "completed", "tool_name": "project_update_file",
                       "arguments": {"path": "capacity.txt"},
                       "results": [{"status": "completed", "path": "capacity.txt"}]}
    messages.append({"role": "user", "content": (
        "[async_tool_result]: Automatic tool-completion event, not a new request. "
        "Completed tool result (TOON):\n" + json.dumps(completed_write)
    )})
    assert _fixture(messages, names)["response"]["type"] == "stream"


# contract-test: supporting surface=cli assertions=storage.validation.synthetic-capacity
def test_partial_marker_or_unauthorized_read_fails_before_write() -> None:
    for bad in ("a3[OM_PII_BROKEN]f0", "a3?f0", "", "a3\nCAPACITY_VERSION_NEW:f0"):
        prompt = f"STORAGE_CAPACITY_SCENARIO:version_create\nCAPACITY_VERSION_NEW:{bad}\n"
        assert _fixture([{"role": "user", "content": prompt}], ("project_create_file",)) is None
    original = _payload(0, 1)
    prompt = ("STORAGE_CAPACITY_SCENARIO:version_update\n"
              f"CAPACITY_VERSION_NEW:{original}\nCAPACITY_VERSION_OLD:{original}\n")
    messages = [{"role": "user", "content": prompt}]
    stale = {"role": "user", "sender_name": "async_tool_result",
             "content": "Completed tool result (TOON):\n" + json.dumps({
                 "status": "completed", "tool_name": "project_create_file",
                 "results": [{"status": "completed"}],
             })}
    assert _arguments(_fixture([stale, *messages], ("project_read_text", "project_update_file"))) == (
        "project_read_text", {"path": "capacity.txt"})
    for completion in (
        {"status": "failed", "tool_name": "project_read_text", "arguments": {"path": "capacity.txt"}, "results": []},
        {"status": "completed", "tool_name": "project_read_text", "arguments": {"path": "capacity.txt"},
         "results": [{"operation": "read_text", "status": "completed", "path": "capacity.txt",
                      "expected_base": "0" * 64, "truncated": True}]},
    ):
        candidate = [*messages, {"role": "user", "sender_name": "async_tool_result",
                                  "content": "Completed tool result (TOON):\n" + json.dumps(completion)}]
        assert _fixture(candidate, ("project_read_text", "project_update_file")) is None


# contract-test: supporting surface=cli assertions=storage.validation.synthetic-capacity
def test_oversized_or_wrong_write_completion_cannot_acknowledge_version() -> None:
    prompt = ("STORAGE_CAPACITY_SCENARIO:version_create\n"
              f"CAPACITY_VERSION_NEW:{_payload(0, 0)}\n")
    messages = [{"role": "user", "content": prompt}]
    for completion in (
        {"status": "completed", "tool_name": "project_update_file",
         "arguments": {"path": "capacity.txt"},
         "results": [{"status": "completed", "path": "capacity.txt"}]},
        {"status": "completed", "tool_name": "project_create_file",
         "arguments": {"path": "other.txt"},
         "results": [{"status": "completed", "path": "other.txt"}]},
    ):
        event = {"role": "user", "content": (
            "[async_tool_result]: Automatic tool-completion event, not a new request. "
            "Completed tool result (TOON):\n" + json.dumps(completion)
        )}
        assert _fixture([*messages, event], ("project_create_file",)) is None
    oversized = {"role": "user", "content": (
        "[async_tool_result]: Automatic tool-completion event, not a new request. "
        "Completed tool result (TOON):\n" + "x" * (512 * 1024)
    )}
    assert _fixture([*messages, oversized], ("project_create_file",)) is None
