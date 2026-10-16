import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { OpenMatesClient } from "../src/client.ts";
import type { AvailableRecoveryOutputFrame } from "../src/ws.ts";

const output = (recordId: string): AvailableRecoveryOutputFrame => ({
  record_id: recordId,
  root_chat_id: "root-chat",
  target_chat_id: "child-chat",
  turn_id: "turn-1",
  subject_id: "embed-1",
  output_kind: "embed",
  output_version: 1,
  chat_key_version: 1,
});

function recoveryClient(discovered: (pass: number) => AvailableRecoveryOutputFrame[][]) {
  const client = Object.create(OpenMatesClient.prototype) as Record<string, unknown>;
  let syncPasses = 0;
  const replayed: string[] = [];
  client.resolveTeamContext = () => null;
  client.getMasterKeyBytes = () => new Uint8Array(32);
  client.hasSession = () => true;
  client.openWsClient = async () => {
    const pass = ++syncPasses;
    return { ownerId: "owner", ws: {
      collectMessages: async () => [{ type: "phase_2_last_20_chats_ready", payload: {
        chats: [{ chat_details: { id: "root-chat", messages_v: pass } }], total_chat_count: 1,
      } }],
      send: () => {},
      drainPassiveTaskUpdateJobs: () => [],
      waitForRecoveryOutputDiscovery: async () => {},
      drainAvailableRecoveryOutputPages: () => discovered(pass),
      close: () => {},
    } };
  };
  client.persistPendingAIResponsesFromSync = async () => {};
  client.persistPendingWorkflowChatDeliveries = async () => 0;
  client.persistPendingTaskUpdateJobs = async () => new Set();
  client.replayAvailableRecoveryOutputs = async (_ws: unknown, _owner: string,
    outputs: AvailableRecoveryOutputFrame[]) => {
    replayed.push(outputs[0].record_id);
    return 1;
  };
  return { client: client as unknown as OpenMatesClient,
    get syncPasses() { return syncPasses; }, replayed };
}

describe("CLI recovery resync bound", () => {
  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.sync.key-gated-recovery
  it("reads fresh metadata once after an ACK without replaying a rediscovered record", async () => {
    const previous = process.env.OPENMATES_STATE_DIR;
    const directory = mkdtempSync(join(tmpdir(), "cli-recovery-resync-"));
    process.env.OPENMATES_STATE_DIR = directory;
    try {
      const fixture = recoveryClient(() => [[output("record-1")]]);
      const cache = await fixture.client.ensureSynced(true);
      assert.equal(fixture.syncPasses, 2);
      assert.deepEqual(fixture.replayed, ["record-1"]);
      assert.equal(cache.chats[0].details.messages_v, 2, "the returned snapshot is post-ACK");
      assert.equal(JSON.parse(readFileSync(join(directory, "sync_cache.json"), "utf8"))
        .chats[0].details.messages_v, 2);
    } finally {
      if (previous === undefined) delete process.env.OPENMATES_STATE_DIR;
      else process.env.OPENMATES_STATE_DIR = previous;
      rmSync(directory, { recursive: true, force: true });
    }
  });

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.sync.key-gated-recovery
  it("rejects a reused record ID whose recovery identity changes", async () => {
    const previous = process.env.OPENMATES_STATE_DIR;
    const directory = mkdtempSync(join(tmpdir(), "cli-recovery-resync-"));
    process.env.OPENMATES_STATE_DIR = directory;
    try {
      const fixture = recoveryClient(pass => [[pass === 1 ? output("record-1")
        : { ...output("record-1"), subject_id: "different-embed" }]]);
      await assert.rejects(fixture.client.ensureSynced(true), /changed identity during sync/);
      assert.equal(fixture.syncPasses, 2);
      assert.deepEqual(fixture.replayed, ["record-1"]);
    } finally {
      if (previous === undefined) delete process.env.OPENMATES_STATE_DIR;
      else process.env.OPENMATES_STATE_DIR = previous;
      rmSync(directory, { recursive: true, force: true });
    }
  });

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("fails closed when genuinely new outputs keep arriving beyond the refresh bound", async () => {
    const previous = process.env.OPENMATES_STATE_DIR;
    const directory = mkdtempSync(join(tmpdir(), "cli-recovery-resync-"));
    process.env.OPENMATES_STATE_DIR = directory;
    try {
      writeFileSync(join(directory, "sync_cache.json"), JSON.stringify({
        syncedAt: Date.now(), totalChatCount: 0, loadedChatCount: 0,
        chats: [], embeds: [], embedKeys: [], chatKeyWrappers: [],
      }));
      const fixture = recoveryClient(pass => [[output(`record-${pass}`)]]);
      await assert.rejects(fixture.client.ensureSynced(true), /Recovery outputs kept arriving/);
      assert.equal(fixture.syncPasses, 4);
      assert.deepEqual(fixture.replayed, ["record-1", "record-2", "record-3", "record-4"]);
      assert.equal(JSON.parse(readFileSync(join(directory, "sync_cache.json"), "utf8")).syncedAt, 0,
        "a cached snapshot must be invalidated rather than published as current history");
    } finally {
      if (previous === undefined) delete process.env.OPENMATES_STATE_DIR;
      else process.env.OPENMATES_STATE_DIR = previous;
      rmSync(directory, { recursive: true, force: true });
    }
  });
});
