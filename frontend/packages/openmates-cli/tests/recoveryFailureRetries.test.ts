import { describe, it, mock } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { OpenMatesClient } from "../src/client.ts";
import { RecoveryFailureRetry, MAX_RECOVERY_OPERATION_FAILURES, RECOVERY_FAILURE_RETRY_DELAY_MS } from "../src/recoveryFailureRetry.ts";
import { WebSocketProtocolError, type AvailableRecoveryOutputFrame } from "../src/ws.ts";

const output = (id: string): AvailableRecoveryOutputFrame => ({
  record_id: id, root_chat_id: "root", target_chat_id: "child", turn_id: "turn",
  subject_id: id, output_kind: "embed", output_version: 1, chat_key_version: 1,
});

type Failure = "stale404" | "denied" | "unavailable-wrapper";
function fixture(failure: Failure = "stale404", relatedParent = false) {
  const client = Object.create(OpenMatesClient.prototype) as Record<string, unknown>;
  let passes = 0, ready = false, version = 1, owner = "owner", team: string | null = null;
  let metadataReady: "head" | "key" | null = null;
  let wrappers: Record<string, unknown>[] = [];
  let wrapperOnPass = 0;
  const reads: string[] = [];
  client.apiUrl = "https://api.example.test";
  client.resolveTeamContext = () => team;
  client.getMasterKeyBytes = () => new Uint8Array(32);
  client.hasSession = () => true;
  client.openWsClient = async () => {
    const pass = ++passes;
    if (pass === wrapperOnPass) { ready = true; wrappers = [{
      hashed_chat_id: createHash("sha256").update("root").digest("hex"),
      key_type: "master", encrypted_chat_key: "corrected-wrapper", chat_key_version: 1,
    }]; }
    return { ownerId: owner, ws: {
      collectMessages: async () => [{ type: "phase_2_last_20_chats_ready", payload: {
        chats: [{ chat_details: { id: "root", messages_v: pass } }], total_chat_count: 1,
      } }, { type: "phase_1b_chat_content_ready", payload: {
        embeds: metadataReady === "head" ? [{ embed_id: "unavailable", status: "finished",
          encrypted_content: "ciphertext", encrypted_type: "ciphertext-type", version_number: 1 }] : [],
        chat_key_wrappers: wrappers,
        embed_keys: metadataReady === "key" ? [{ hashed_embed_id: createHash("sha256").update("unavailable").digest("hex"),
          key_type: "chat", encrypted_embed_key: "wrapped-ciphertext-key" }] : [],
      } }], send: () => {}, drainPassiveTaskUpdateJobs: () => [],
      waitForRecoveryOutputDiscovery: async () => {},
      drainAvailableRecoveryOutputPages: () => [[{ ...output("unavailable"), output_version: version },
        { ...output("ready-1"), target_chat_id: relatedParent ? "child" : "unrelated-1" },
        ...(pass >= 2 ? [{ ...output("ready-2"), target_chat_id: "unrelated-2" }] : [])]],
      close: () => {},
    } };
  };
  client.persistPendingAIResponsesFromSync = async () => {};
  client.persistPendingWorkflowChatDeliveries = async () => 0;
  client.persistPendingTaskUpdateJobs = async () => new Set();
  // All recursive retry/cache logic is real. Only canonical leaf outcomes
  // are controlled; no server status or ownership semantics are substituted.
  client.replayAvailableRecoveryOutputs = async (_ws: unknown, _owner: unknown,
    outputs: AvailableRecoveryOutputFrame[]) => {
    const record = outputs[0]; reads.push(`${record.record_id}:v${record.output_version}`);
    if (record.record_id === "unavailable" && !ready) {
      if (failure === "denied") throw new WebSocketProtocolError("embed_write_denied", "Not authorized to store embed");
      if (failure === "unavailable-wrapper") throw new Error("Canonical recovery parent embed key scope was unavailable.");
      throw new Error("Canonical recovery embed read failed (HTTP404); output remains pending.");
    }
    if (relatedParent && record.record_id === "ready-1") ready = true;
    return 1;
  };
  return { client: client as unknown as OpenMatesClient, reads,
    get passes() { return passes; },
    setWrappers: (rows: Record<string, unknown>[]) => { wrappers = rows; },
    wrapperOnNextPass: () => { wrapperOnPass = passes + 2; }, setReady: () => { ready = true; },
    changeIdentity: () => { version += 1; }, changeAccount: () => { owner = "other-owner"; },
    changeTeam: () => { team = "other-team"; },
    signalReadiness: (kind: "head" | "key") => { ready = true; metadataReady = kind; } };
}

async function isolated(run: (clock: { advance: (ms: number) => void }, directory: string) => Promise<void>) {
  const previous = process.env.OPENMATES_STATE_DIR;
  const directory = mkdtempSync(join(tmpdir(), "recovery-failure-retries-"));
  process.env.OPENMATES_STATE_DIR = directory;
  let now = 100_000;
  const clock = mock.method(Date, "now", () => now);
  try { await run({ advance: ms => { now += ms; } }, directory); }
  finally {
    clock.mock.restore();
    if (previous === undefined) delete process.env.OPENMATES_STATE_DIR;
    else process.env.OPENMATES_STATE_DIR = previous;
    rmSync(directory, { recursive: true, force: true });
  }
}

const failureReads = (state: ReturnType<typeof fixture>) => state.reads.filter(r => r.startsWith("unavailable:")).length;

describe("bounded failed recovery retries", () => {
  for (const failure of ["stale404", "denied", "unavailable-wrapper"] as const) {
    // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.sync.key-gated-recovery
    it(`keeps ${failure} pending with one attempt across recursive and immediate independent syncs`, async () => {
      await isolated(async (clock, directory) => {
        const state = fixture(failure), cache = await state.client.ensureSynced(true);
        assert.equal(state.passes, 3);
        assert.equal(cache.pendingRecoveryOutputs, 1);
        assert.equal(failureReads(state), 1, "unrelated successes do not wake the failed source chat");
        assert.equal(state.reads.filter(r => r === "ready-1:v1").length, 1);
        assert.equal(state.reads.filter(r => r === "ready-2:v1").length, 1);
        await state.client.ensureSynced(true);
        assert.equal(failureReads(state), 1);
        assert.equal(JSON.parse(readFileSync(join(directory, "sync_cache.json"), "utf8")).pendingRecoveryOutputs, 1);
        state.setReady();
        assert.equal((await state.client.ensureSynced(true)).pendingRecoveryOutputs, 1,
          "an unchanged remote-ready leaf is deferred only until the finite deadline");
        clock.advance(RECOVERY_FAILURE_RETRY_DELAY_MS + 1);
        assert.equal((await state.client.ensureSynced(true)).pendingRecoveryOutputs, 0);
        assert.equal(failureReads(state), 2, "unchanged canonical readiness is retried after expiry");
      });
    });
  }

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.sync.key-gated-recovery
  it("retries a failed leaf immediately after verified related parent/key persistence", async () => {
    await isolated(async () => {
      const state = fixture("unavailable-wrapper", true);
      const recovered = await state.client.ensureSynced(true);
      assert.equal(recovered.pendingRecoveryOutputs, 0);
      assert.equal(failureReads(state), 2);
      assert.equal(state.reads.filter(r => r === "ready-1:v1").length, 1);
    });
  });

  for (const kind of ["head", "key"] as const) {
    // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.sync.key-gated-recovery
    it(`retries unchanged output immediately when local ciphertext ${kind} readiness changes`, async () => {
      await isolated(async () => {
        const state = fixture(); await state.client.ensureSynced(true);
        state.signalReadiness(kind);
        assert.equal((await state.client.ensureSynced(true)).pendingRecoveryOutputs, 0);
        assert.equal(failureReads(state), 2);
      });
    });
  }

  for (const kind of ["identity", "account", "Team"] as const) {
    // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.sync.key-gated-recovery
    it(`does not share negative retry state after ${kind} changes`, async () => {
      await isolated(async () => {
        const state = fixture(); await state.client.ensureSynced(true);
        if (kind === "identity") state.changeIdentity();
        if (kind === "account") state.changeAccount();
        if (kind === "Team") state.changeTeam();
        state.setReady();
        assert.equal((await state.client.ensureSynced(true)).pendingRecoveryOutputs, 0);
        assert.equal(failureReads(state), 2);
        if (kind === "identity") assert.ok(state.reads.includes("unavailable:v2"));
      });
    });
  }

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.sync.key-gated-recovery
  it("retries within the same operation when a corrected root wrapper arrives on a later pass", async () => {
    await isolated(async () => {
      const state = fixture("unavailable-wrapper"); state.wrapperOnNextPass();
      assert.equal((await state.client.ensureSynced(true)).pendingRecoveryOutputs, 0);
      assert.equal(failureReads(state), 2);
    });
  });

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.sync.key-gated-recovery
  it("retries immediately for related wrapper arrival/change but not an unrelated wrapper", async () => {
    await isolated(async () => {
      const state = fixture("unavailable-wrapper"); await state.client.ensureSynced(true);
      state.setWrappers([{ hashed_chat_id: createHash("sha256").update("unrelated").digest("hex"),
        key_type: "master", encrypted_chat_key: "unrelated-cipher" }]);
      await state.client.ensureSynced(true); assert.equal(failureReads(state), 1);
      const related = { hashed_chat_id: createHash("sha256").update("child").digest("hex"),
        hashed_user_id: "owner-hash", key_type: "master", chat_key_version: 1,
        encrypted_chat_key: "first-cipher" };
      state.setWrappers([related]); await state.client.ensureSynced(true);
      assert.equal(failureReads(state), 2, "arrival retries even before the deadline");
      state.setWrappers([{ ...related, encrypted_chat_key: "corrected-cipher" }]); state.setReady();
      assert.equal((await state.client.ensureSynced(true)).pendingRecoveryOutputs, 0);
      assert.equal(failureReads(state), 3, "changed ciphertext retries unchanged output immediately");
    });
  });

  // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.sync.key-gated-recovery
  it("caps operation memory without evicting failures and retries overflow in a fresh operation", () => {
    const retry = new RecoveryFailureRetry(), operation = retry.beginOperation();
    for (let i = 0; i < MAX_RECOVERY_OPERATION_FAILURES; i++) retry.failed("scope", output(`failure-${i}`), "old", operation);
    assert.equal(operation.failed.size, MAX_RECOVERY_OPERATION_FAILURES);
    assert.equal(retry.shouldDefer("scope", output("overflow"), "old", operation), true);
    assert.equal(retry.shouldDefer("scope", output("failure-0"), "old", operation), true,
      "global LRU eviction must not lose same-operation suppression");
    assert.equal(retry.shouldDefer("scope", output("failure-0"), "ready", operation), false,
      "known ready identities can retry even at capacity");
    assert.equal(retry.shouldDefer("scope", output("overflow"), "old", retry.beginOperation()), false);
  });

  // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.sync.key-gated-recovery
  it("preserves a stale pending-cache sync and retries after its existing60second freshness window", async () => {
    await isolated(async (clock, directory) => {
      const state = fixture(); await state.client.ensureSynced(true);
      const current = JSON.parse(readFileSync(join(directory, "sync_cache.json"), "utf8"));
      writeFileSync(join(directory, "sync_cache.json"), JSON.stringify({ ...current, pendingRecoveryOutputs: 1 }));
      clock.advance(60_001); state.setReady();
      const priorPasses = state.passes;
      assert.equal((await state.client.ensureSynced(false)).pendingRecoveryOutputs, 0);
      assert.ok(state.passes > priorPasses);
      assert.equal(failureReads(state), 2);
    });
  });
});
