import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { enhancedScopeEnabled, readPrivacyPreferences, updatePrivacyPreferences } from "../src/privacyModel.js";
import { convertNativePrivacyRanges, prepareCliMessagePrivacy, scanEnhancedText } from "../src/privacyScan.js";
import { createInitialTuiState, renderTuiFrame } from "../src/tuiRenderer.js";
import { privacyDetectionOptions } from "../src/privacyScan.js";
import { ProjectFilePrivacy } from "../../ui/src/services/projectFilePrivacy.js";

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity,pii.message.owner-local-reveal
test("optional local scopes retain deterministic protection without starting a worker", async () => {
  const directory = await mkdtemp(join(tmpdir(), "openmates-privacy-unit-"));
  const previous = { state: process.env.OPENMATES_STATE_DIR, privacy: process.env.OPENMATES_PRIVACY_DIR };
  process.env.OPENMATES_STATE_DIR = join(directory, "state"); process.env.OPENMATES_PRIVACY_DIR = join(directory, "model");
  try {
    const p = await readPrivacyPreferences();
    assert.equal(enhancedScopeEnabled(p, { kind: "message" }), false);
    const enabled = { ...p, enabled: true, projects: ["project-a"] };
    assert.equal(enhancedScopeEnabled(enabled, { kind: "message" }), true);
    assert.equal(enhancedScopeEnabled(enabled, { kind: "document" }), false);
    assert.equal(enhancedScopeEnabled(enabled, { kind: "project", projectId: "project-b" }), false);
    assert.equal(enhancedScopeEnabled(enabled, { kind: "project", projectId: "project-a" }), true);
    await updatePrivacyPreferences((value) => ({ ...value, documents: true }));
    const text = "Email owner@example.invalid";
    const safe = await prepareCliMessagePrivacy(text, []);
    assert.ok(!safe.message.includes("owner@example.invalid"));
    const restore = new ProjectFilePrivacy({ mappings: safe.mappings, save: async () => {} });
    assert.equal(restore.restoreText(safe.message), text);
    const again = await prepareCliMessagePrivacy(safe.message, [], safe.mappings);
    assert.equal(again.message, safe.message);
    assert.equal(restore.restoreText(again.message), text);
    const knownName = { original: "Niamh O’Connell", placeholder: "[OM_PII_00000000000000000000000000008C51AB]", type: "OTHER" };
    const followup = await prepareCliMessagePrivacy("Ask Niamh O’Connell again", [], [knownName]);
    assert.equal(followup.message, "Ask " + knownName.placeholder + " again");
    await assert.rejects(readFile(join(directory, "model", "worker.sock")), { code: "ENOENT" });
    await updatePrivacyPreferences((value) => ({ ...value, enabled: true }));
    // A selected enhanced scan must fail, rather than exposing raw text when
    // the model/runtime is unavailable. No actual inference in this unit test.
    await assert.rejects(scanEnhancedText("My colleague Niamh works here.", { kind: "message" }));
  } finally {
    if (previous.state === undefined) delete process.env.OPENMATES_STATE_DIR; else process.env.OPENMATES_STATE_DIR = previous.state;
    if (previous.privacy === undefined) delete process.env.OPENMATES_PRIVACY_DIR; else process.env.OPENMATES_PRIVACY_DIR = previous.privacy;
    await rm(directory, { recursive: true, force: true });
  }
});

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity,pii.message.owner-local-reveal
test("semantic UTF-8 spans and overlapping configured values restore exact CRLF bytes", async () => {
  const text = "🙂 Contact Niamh O’Connell\r\n";
  const original = "Niamh O’Connell"; const start = text.indexOf(original);
  const ranges = convertNativePrivacyRanges(text, [{ start: Buffer.byteLength(text.slice(0, start)), end: Buffer.byteLength(text.slice(0, start + original.length)), label: "private_person" }]);
  assert.equal(ranges[0]!.start, start);
  let mappings: Array<{ placeholder: string; original: string }> = [];
  const privacy = new ProjectFilePrivacy({ detection: { personalDataEntries: [{ id: "name", textToHide: "Niamh", replaceWith: "[FIRST_NAME]" }] },
    detectEnhanced: async () => ranges, save: async (value) => { mappings = value; } });
  const safe = await privacy.redactResult(text) as string;
  assert.ok(!safe.includes("Niamh") && !safe.includes("O’Connell"));
  assert.ok(safe.endsWith("\r\n")); assert.ok(mappings.length >= 2);
  assert.equal(privacy.restoreText(safe), text);
  assert.throws(() => convertNativePrivacyRanges(text, [{ start: 1, end: 3, label: "private_person" }]), { code: "privacy_invalid_semantic_range" });
  const uuid = "6d0a8c71-be37-4a1e-b601-8ab667997311";
  assert.deepEqual(convertNativePrivacyRanges(uuid, [{ start: 0, end: uuid.length, label: "private_phone" }]), []);
  assert.deepEqual(convertNativePrivacyRanges(original, [{ start: 0, end: Buffer.byteLength(original), label: "private_person" }], new Set(["names"])), []);
});

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
test("the installation offer remains optional and preserves the composer draft", () => {
  const state = createInitialTuiState(); state.signedIn = true; state.privacyOffer = true;
  state.input = "An unsent draft";
  const offered = renderTuiFrame(state, 100, 38, { ascii: true });
  assert.ok(offered.includes("Enhanced personal data anonymization"));
  assert.ok(offered.includes("/privacy install") && offered.includes("/privacy later"));
  state.privacyOffer = false;
  assert.ok(!renderTuiFrame(state, 100, 38, { ascii: true }).includes("/privacy install"));
  assert.equal(state.input, "An unsent draft");
  assert.equal(privacyDetectionOptions([{ app_id: "privacy", item_type: "pii_detection_settings", data: { masterEnabled: false }, id: "setting" } as import("../src/client.js").DecryptedMemoryEntry]).enabled, false);
});
