import test from "node:test";
import assert from "node:assert/strict";
import { ProjectFilePrivacy } from "../../ui/src/services/projectFilePrivacy.js";
import { loadProjectFilePrivacy } from "../../ui/src/services/projectFilePrivacyStorage.js";
import { createProjectFileJobExecutor, type ProjectFileJob } from "../../ui/src/services/projectFileJobExecutor.js";
import { encryptWithAesGcmCombined, decryptWithAesGcmCombined } from "../src/crypto.js";
import { detectPII } from "../../ui/src/components/enter_message/services/piiDetectionService.js";
import { SecretScanner } from "../../secret-scanner/src/scanner.ts";

const key = new Uint8Array(32).fill(12);
const uuid = "6d0a8c71-be37-4a1e-b601-8ab667997311";
const email = "owner@example.invalid";
const hash = "dd12580563031768101662865969133201763236529561637234101760832864";

// contract-test: supporting surface=cli assertions=projects.files.no-server-decryption-authority,projects.files.exact-patch
test("both detectors preserve coding identifiers while still detecting real phone numbers", () => {
  const text = `${uuid} ${hash} [PHONE_1_159] +49 151 23456789`;
  assert.equal(detectPII(text).filter((match) => match.type === "PHONE").length, 1);
  const result = new SecretScanner().redact(text);
  assert.ok(result.redacted.includes(uuid));
  assert.ok(result.redacted.includes(hash));
  assert.ok(result.redacted.includes("[PHONE_1_159]"));
  assert.ok(!result.redacted.includes("+49 151 23456789"));
});

// contract-test: supporting surface=cli assertions=projects.files.no-server-decryption-authority,projects.files.exact-patch
test("read and search redact exact spans, preserve line boundaries and commitments, and survive encrypted reload", async () => {
  let ciphertext: string | null = null;
  const options = {
    chatId: "chat-a", projectId: "project-a", key, mappings: [],
    read: async () => ciphertext, write: async (value: string) => { ciphertext = value; },
    encrypt: encryptWithAesGcmCombined, decrypt: decryptWithAesGcmCombined,
    detection: { personalDataEntries: [{ id: "custom", textToHide: "Private Person", replaceWith: "[NAME]" }] },
  };
  const privacy = await loadProjectFilePrivacy(options);
  const original = `const owner = "${email}";\r\n// Private Person ${uuid}\r\n`;
  const safe = await privacy.redactResult({ content: original, expected_base: hash, matches: [{ text: `owner: ${email}` }] }) as { content: string; expected_base: string; matches: Array<{ text: string }> };
  assert.ok(!JSON.stringify(safe).includes(email));
  assert.ok(!JSON.stringify(safe).includes("Private Person"));
  assert.equal(safe.expected_base, hash);
  assert.ok(safe.content.includes(uuid));
  assert.equal(safe.content.split("\r\n").length, original.split("\r\n").length);
  assert.ok(ciphertext && !ciphertext.includes(email) && !ciphertext.includes("Private Person"));
  const reloaded = await loadProjectFilePrivacy(options);
  assert.equal(reloaded.restoreText(safe.content), original);
  const foreign = new ProjectFilePrivacy({ save: async () => {} });
  assert.throws(() => foreign.restoreText(safe.content), { code: "pii_mapping_unavailable" });
  await assert.rejects(loadProjectFilePrivacy({ ...options, projectId: "other-project" }), { code: "pii_mapping_unavailable" });
});

// contract-test: supporting surface=cli assertions=projects.files.write-policy-enforcement,projects.files.exact-patch,projects.files.expected-base
test("write approval commits to restored bytes, sends a redacted proposal, and executes only on a fresh lease", async () => {
  const privacy = new ProjectFilePrivacy({ mappings: [{ placeholder: "[EMAIL_1_lid]", original: email }], save: async () => {} });
  const events: Array<Record<string, unknown>> = [];
  let digest: string | undefined;
  let written: unknown;
  const executor = createProjectFileJobExecutor({
    isActiveChat: () => true,
    send: (_event, payload) => { events.push(payload); },
    resolve: async () => ({ projectKey: key, writeMode: "always_ask", privacy, execute: async (_job, mutation) => { written = mutation; return { expected_base: hash }; } }),
    requestApproval: async (request) => {
      assert.equal(request.mutation.content, `${email}\n`);
      assert.ok(!JSON.stringify(events).includes(email));
      assert.equal(written, undefined);
      return true;
    },
    approve: async (_request, value) => { digest = value; },
  });
  const job: ProjectFileJob = { protocol_version: 1, operation_id: "write-a", chat_id: "chat-a", project_id: "project-a", operation: "create_file",
    arguments: { path: "README.md", expected_base: null, content: "[EMAIL_1_lid]\n" }, lease_token: "long-enough-lease-token", lease_generation: 1, lease_expires_at: Date.now() / 1000 + 60 };
  await executor.request(job);
  await executor.request({ ...job, lease_generation: 2 });
  assert.equal((written as { content: string }).content, `${email}\n`);
  assert.equal(((events.at(-1)!.result as Record<string, unknown>).proposal_commitment), digest);
  assert.ok(!JSON.stringify(events).includes(email));
});

// contract-test: supporting surface=cli assertions=projects.files.exact-patch,projects.files.expected-base
test("ambiguous legacy tokens, unavailable mappings and persistence failures never release raw content", async () => {
  const privacy = new ProjectFilePrivacy({ mappings: [{ placeholder: "[NAME]", original: "Alice" }, { placeholder: "[NAME]", original: "Bob" }], save: async () => { throw new Error("disk full"); } });
  assert.throws(() => privacy.restoreText("[NAME]"), { code: "pii_mapping_ambiguous" });
  await assert.rejects(privacy.redactResult({ content: email }), /disk full/);
  const patchPrivacy = new ProjectFilePrivacy({ save: async () => {} });
  const old = `contact=${email}\nflag=false\n`;
  const safe = patchPrivacy.redactText(old);
  const patch = `--- a/config.txt\n+++ b/config.txt\n@@ -1,2 +1,2 @@\n ${safe.split("\n")[0]}\n-flag=false\n+flag=true\n`;
  const restored = patchPrivacy.restoreMutation({ operation: "update_file", operation_id: "patch-a", path: "config.txt", expected_base: hash, patch });
  assert.equal(restored.expected_base, hash);
  assert.ok(restored.patch?.includes(` contact=${email}\n`));
  const literalPrivacy = new ProjectFilePrivacy({ mappings: [{ placeholder: "[NAME]", original: "Alice" }], save: async () => {} });
  const literalCode = 'const template = "[NAME]";';
  assert.equal(literalPrivacy.restoreText(literalPrivacy.redactText(literalCode)), literalCode);
});
