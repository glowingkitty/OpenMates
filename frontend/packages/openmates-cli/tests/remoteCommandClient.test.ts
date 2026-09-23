import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { decryptWithAesGcmCombined, encryptWithAesGcmCombined } from "../src/crypto.ts";
import {
  decryptRemoteCommandEvent,
  disableRemoteCommandPreset,
  enableRemoteCommandPreset,
  listRemoteCommandPresetGrants,
  prepareRemoteCommandApproval,
  registerRemoteCommandOriginClient,
  RemoteCommandOutputAccumulator,
  renderRemoteCommandReview,
  type RemoteCommandReview,
} from "../src/remoteCommandClient.ts";

const review: RemoteCommandReview = {
  protocol_version: 1,
  execution_id: "execution-1",
  chat_id: "chat-1",
  project_id: "project-1",
  source_id: "source-1",
  state: "REVIEW_REQUIRED",
  created_at: 1,
  review_expires_at: 100,
  review_token: "r".repeat(32),
  approval_requirement: "one_run_or_preset",
  command: {
    argv: ["npm", "test"], cwd: ".", mode: "foreground", source_access: "read_only",
    deadline_ms: 60_000, writable_profiles: ["cache"], network_profile: null, credential_profiles: [],
  },
  explanation: {
    summary: "Runs tests\u001b[2J", effects: ["Reads the Project"], risks: ["Runs repository code"], uncertainty: [],
  },
};

describe("remote command origin client", () => {
  // contract-test: direct surface=cli assertions=code-run.remote.explicit-approval,code-run.remote.command-lists
  it("defers an unmatched noninteractive review but prepares a matching preset", async () => {
    const handlers = new Map<string, (payload: unknown) => void>();
    const sent: Array<{ type: string; payload: unknown }> = [];
    const deferred: Array<Record<string, unknown>> = [];
    const ws = {
      onMessageType(type: string, handler: (payload: unknown) => void) { handlers.set(type, handler); return () => handlers.delete(type); },
      onClose() { return () => {}; },
      async sendAsync(type: string, payload: unknown) { sent.push({ type, payload }); },
      notifyRemoteCommandReviewDeferred(payload: Record<string, unknown>) { deferred.push(payload); },
    };
    const client = {
      async getActiveProjectFocus() { return { project_id: review.project_id, team_id: null }; },
      async getProject() { return { project: {} }; },
      async decryptProjectKey() { return new Uint8Array(32).fill(5); },
    };
    const payload = { ...review, message_id: "message-1" };

    const stopDeferred = registerRemoteCommandOriginClient({
      ws: ws as never,
      client: client as never,
      chatId: review.chat_id,
      onReview: async () => undefined,
    });
    handlers.get("remote_command_review_required")?.(payload);
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(deferred, [{ chat_id: review.chat_id, execution_id: review.execution_id, message_id: "message-1" }]);
    assert.equal(sent.length, 0);
    stopDeferred();

    deferred.length = 0;
    const stopPreset = registerRemoteCommandOriginClient({
      ws: ws as never,
      client: client as never,
      chatId: review.chat_id,
      onReview: async () => ({ kind: "preset", preset_id: "checks", definition_digest: "a".repeat(64) }),
    });
    handlers.get("remote_command_review_required")?.(payload);
    for (let attempt = 0; attempt < 20 && sent.length === 0; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
    assert.equal(deferred.length, 0);
    assert.equal(sent.at(-1)?.type, "remote_command_prepare");
    stopPreset();
  });

  // contract-test: direct surface=cli assertions=code-run.remote.explicit-approval,code-run.remote.resource-profiles
  it("renders exact review facts without terminal controls", () => {
    const output = renderRemoteCommandReview(review);
    assert.match(output, /Command argv: \["npm","test"\]/);
    assert.match(output, /Working directory: \./);
    assert.match(output, /Writable profiles: cache/);
    assert.match(output, /Approval: one-run or enabled preset/);
    // eslint-disable-next-line no-control-regex -- Raw escape bytes must be escaped in review text.
    assert.doesNotMatch(output, /\u001b/);
    assert.match(output, /\\u001b\[2J/);
  });

  // contract-test: supporting surface=cli assertions=code-run.remote.explicit-approval,code-run.remote.managed-jobs
  it("encrypts the exact portable request and includes approval in its Project-bound identity", async () => {
    const key = new Uint8Array(32).fill(7);
    const prepared = await prepareRemoteCommandApproval(review, key, { kind: "one_run" });
    assert.equal(typeof prepared.encrypted_request, "string");
    assert.match(String(prepared.request_digest), /^[A-Za-z0-9_-]{43}$/);
    const plaintext = await decryptWithAesGcmCombined(String(prepared.encrypted_request), key);
    assert.deepEqual(JSON.parse(plaintext ?? "null"), {
      protocol_version: 1,
      execution_id: review.execution_id,
      chat_id: review.chat_id,
      project_id: review.project_id,
      source_id: review.source_id,
      policy: review.command,
      approval: { kind: "one_run" },
    });
    await assert.rejects(
      prepareRemoteCommandApproval(
        { ...review, approval_requirement: "one_run" },
        key,
        { kind: "preset", preset_id: "checks", definition_digest: "a".repeat(64) },
      ),
      /requires explicit one-run approval/,
    );
  });

  // contract-test: supporting surface=cli assertions=code-run.remote.explicit-approval,code-run.remote.managed-jobs
  it("decrypts only events whose clear and encrypted identities agree", async () => {
    const key = new Uint8Array(32).fill(9);
    const payload = { execution_id: "execution-1", sequence: 2, event_kind: "output", status: "running", stream: "stdout", text: "ok" };
    const encrypted_event = await encryptWithAesGcmCombined(JSON.stringify(payload), key);
    const result = await decryptRemoteCommandEvent({ ...payload, encrypted_event }, key);
    assert.equal(result.payload.text, "ok");
    await assert.rejects(
      decryptRemoteCommandEvent({ ...payload, sequence: 3, encrypted_event }, key),
      /identity mismatch/,
    );
  });

  // contract-test: supporting surface=cli assertions=code-run.remote.managed-jobs,code-run.remote.resource-profiles
  it("deduplicates ordered events and marks bounded head-tail output incomplete on sequence gaps", () => {
    const output = new RemoteCommandOutputAccumulator();
    assert.equal(output.add({ execution_id: "execution-1", sequence: 0, event_kind: "output", status: "running", payload: { text: `head\u001b[2J${"x".repeat(30_000)}` } }), "accepted");
    assert.equal(output.add({ execution_id: "execution-1", sequence: 0, event_kind: "output", status: "running", payload: { text: "duplicate" } }), "duplicate");
    output.add({ execution_id: "execution-1", sequence: 2, event_kind: "output", status: "running", payload: { text: `${"y".repeat(30_000)}tail` } });
    const selected = output.selection();
    assert.equal(selected.coverage, "selected_excerpt");
    assert.equal(selected.sequence_gap, true);
    assert.equal(selected.upstream_truncated, true);
    assert.ok(selected.omitted_chars > 0);
    assert.ok(selected.text.length <= 24_000);
    assert.match(selected.text, /^head/);
    assert.match(selected.text, /tail$/);
    // eslint-disable-next-line no-control-regex -- Selected terminal output must contain no raw escape bytes.
    assert.doesNotMatch(selected.text, /\u001b/);

    const runtimeTruncated = new RemoteCommandOutputAccumulator();
    runtimeTruncated.add({ execution_id: "execution-2", sequence: 0, event_kind: "output", status: "running", payload: { text: "partial" } });
    runtimeTruncated.add({ execution_id: "execution-2", sequence: 1, event_kind: "output_truncated", status: "running", payload: { retained_bytes: 7 } });
    assert.deepEqual(runtimeTruncated.selection(), {
      text: "partial",
      coverage: "selected_excerpt",
      sequence_gap: false,
      upstream_truncated: true,
      omitted_chars: 0,
    });
  });

  // contract-test: direct surface=cli assertions=code-run.remote.command-lists,code-run.remote.explicit-approval
  it("stores explicit preset activation outside the command-writable Project", () => {
    const base = mkdtempSync(join(tmpdir(), "openmates-command-grants-"));
    const project = join(base, "project");
    const state = join(base, "state");
    mkdirSync(join(project, ".openmates"), { recursive: true });
    writeFileSync(join(project, ".openmates", "permissions.yml"), `schema_version: 1
presets:
  - id: checks
    label: Checks
    commands:
      - argv: [npm, test]
        cwd: .
        mode: foreground
        source_access: read_only
        deadline_ms: 60000
        writable_profiles: []
        network_profile: null
        credential_profiles: []
resource_profiles:
  writable: []
  network: []
  credentials: []
`);
    const previous = process.env.OPENMATES_STATE_DIR;
    process.env.OPENMATES_STATE_DIR = state;
    try {
      const grant = enableRemoteCommandPreset("project-1", project, "checks");
      assert.match(grant.definition_digest, /^[a-f0-9]{64}$/);
      assert.deepEqual(listRemoteCommandPresetGrants(), [grant]);
      disableRemoteCommandPreset("project-1", "checks");
      assert.deepEqual(listRemoteCommandPresetGrants(), []);
    } finally {
      if (previous === undefined) delete process.env.OPENMATES_STATE_DIR;
      else process.env.OPENMATES_STATE_DIR = previous;
      rmSync(base, { recursive: true, force: true });
    }
  });
});
