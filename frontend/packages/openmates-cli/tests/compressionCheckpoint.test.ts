// contract-test-file: supporting surface=cli assertions=storage.compression.incremental-archive
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { persistCompressionCheckpoints } from "../src/client.ts";
import type { OpenMatesWsClient } from "../src/ws.ts";

describe("CLI compression checkpoint persistence", () => {
  const checkpoint = {
    chatId: "chat-1", taskId: "task-1", checkpointId: "11111111-1111-4111-8111-111111111111",
    summaryContent: "Encrypted client summary", compressedUpToTimestamp: 1780000010,
    compressedUpToMessageId: "33333333-3333-4333-8333-333333333333",
    coveredMessageIds: ["22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"],
    compressedMessageCount: 2, summaryTokenEstimate: 42,
  };

  // contract-test: supporting surface=cli assertions=storage.compression.incremental-archive
  it("sends the server source boundary and accepts only a matching canonical receipt", async () => {
    const sent: Array<Record<string, unknown>> = [];
    let resolveReceipt: ((value: { payload: Record<string, unknown> }) => void) | undefined;
    const socket = {
      waitForMessage: () => new Promise((resolve) => { resolveReceipt = resolve; }),
      sendAsync: async (_type: string, payload: Record<string, unknown>) => {
        sent.push(payload);
        resolveReceipt?.({ payload: { chat_id: checkpoint.chatId, checkpoint: {
          id: checkpoint.checkpointId,
          compressed_up_to_message_id: payload.compressed_up_to_message_id,
          covered_message_ids: payload.covered_message_ids,
        } } });
      },
    } as unknown as OpenMatesWsClient;
    await persistCompressionCheckpoints(socket, new Uint8Array(32), [checkpoint]);
    assert.equal(sent.length, 1);
    assert.equal(sent[0].compressed_up_to_message_id, checkpoint.compressedUpToMessageId);
    assert.deepEqual(sent[0].covered_message_ids, checkpoint.coveredMessageIds);

    const canonical = {
      chat_id: checkpoint.chatId,
      checkpoint: { id: checkpoint.checkpointId,
        compressed_up_to_message_id: checkpoint.compressedUpToMessageId,
        covered_message_ids: checkpoint.coveredMessageIds },
    };
    for (const changed of [
      { ...canonical, chat_id: "other-chat" },
      { ...canonical, checkpoint: { ...canonical.checkpoint, id: "other-checkpoint" } },
      { ...canonical, checkpoint: { ...canonical.checkpoint, compressed_up_to_message_id: "other-boundary" } },
      { ...canonical, checkpoint: { ...canonical.checkpoint, covered_message_ids: [checkpoint.coveredMessageIds[0]] } },
    ]) {
      const mismatch = {
        waitForMessage: async () => ({ payload: changed }),
        sendAsync: async () => {},
      } as unknown as OpenMatesWsClient;
      await assert.rejects(
        persistCompressionCheckpoints(mismatch, new Uint8Array(32), [checkpoint]),
        /canonical compression checkpoint receipt/i,
      );
    }
  });
});
