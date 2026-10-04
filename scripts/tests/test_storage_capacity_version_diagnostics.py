# contract-test-file: infrastructure
"""The disposable Project adapter reports only bounded own-script failure stages."""

import json
from pathlib import Path
import re
import subprocess


def test_project_version_adapter_labels_send_callback_and_readback_failures():
    adapter = Path(__file__).resolve().parents[1] / "storage_capacity_version_adapter.mjs"
    source = r"""
import { pathToFileURL } from 'node:url';
const { writeVersion } = await import(pathToFileURL(process.argv[1]).href);
const project = () => ({ projectId: 'disposable-project', revision: 0, currentContent: null, embedId: null });
const cases = [
  { expected: 'version_send', client: { sendMessage: async () => { throw new TypeError('private-ciphertext'); } } },
  { expected: 'version_callback_count', client: { sendMessage: async () => ({ status: 'completed' }) } },
  { expected: 'version_readback', client: {
    sendMessage: async ({ onHostedVersionCommitted }) => {
      onHostedVersionCommitted({ embed_id: 'disposable-embed', revision: 1 });
      return { status: 'completed' };
    },
    getEmbedVersion: async () => { throw new TypeError('private-ciphertext'); },
  } },
];
const results = [];
for (const item of cases) {
  try {
    await writeVersion({ client: item.client, chatId: 'disposable-chat', project: project(), content: 'synthetic' });
    throw new Error('Expected a stage failure');
  } catch (error) {
    results.push({ expected: item.expected, phase: error.capacityPhase,
      error_class: error.capacityErrorClass, location: error.capacitySourceLocation });
  }
}
process.stdout.write(JSON.stringify(results));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", source, str(adapter)],
        capture_output=True, text=True, check=True,
    )
    results = json.loads(completed.stdout)
    assert [row["phase"] for row in results] == [
        "version_send", "version_callback_count", "version_readback",
    ]
    assert [row["error_class"] for row in results] == ["TypeError", "Error", "TypeError"]
    assert all(re.fullmatch(r"storage_capacity_version_adapter\.mjs:[1-9]\d*", row["location"])
               for row in results)
    assert "private-ciphertext" not in completed.stdout


def test_version_readback_keeps_exact_gate_and_content_free_diagnostics() -> None:
    repo = Path(__file__).resolve().parents[2]
    script = """
        import { assertVersionReadback } from './scripts/storage_capacity_version_adapter.mjs';
        const expected = 'synthetic-secret-expected';
        const actual = 'synthetic-secret-actual';
        const cases = [
          [{ content: expected, version_number: 1 }, true],
          [{ content: actual, version_number: 1 }, false],
          [{ content: expected, version_number: 2 }, false],
          [{ content: expected, version_number: '1' }, false],
        ];
        const results = cases.map(([fetched, shouldPass]) => {
          try {
            assertVersionReadback(fetched, expected, 1);
            return { passed: true, shouldPass };
          } catch (error) {
            return {
              passed: false, shouldPass, message: error.message,
              phase: error.capacityPhase, source: error.capacitySourceLocation,
            };
          }
        });
        process.stdout.write(JSON.stringify(results));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    results = json.loads(completed.stdout)
    assert results[0] == {"passed": True, "shouldPass": True}
    assert [row["passed"] for row in results] == [True, False, False, False]
    assert all(row.get("phase") == "version_readback" for row in results[1:])
    assert all(row.get("source", "").startswith("storage_capacity_version_adapter.mjs:") for row in results[1:])
    assert "content_matches=false revision_matches=true expected_revision=1 actual_revision=1" in results[1]["message"]
    assert "content_matches=true revision_matches=false expected_revision=1 actual_revision=2" in results[2]["message"]
    assert "content_matches=true revision_matches=false expected_revision=1 actual_revision_type=string" in results[3]["message"]
    assert "synthetic-secret" not in json.dumps(results)
