/**
 * Covers the timestamp handoff between authenticated final stream and recovery.
 * Discovery may arrive before the marker, and unrelated markers must not match.
 * A timeout or session reset releases waiting recovery without losing the reply.
 * No provider output or plaintext response is needed for these identity checks.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearRecoveryFinalTimestamps, recordRecoveryFinalTimestamp, waitForRecoveryFinalTimestamp,
} from "../recoveryAssistantTimestamp";

const finalMarker = {
  chat_id: "chat-1", message_id: "assistant-1", user_message_id: "user-1",
  recovery_job_id: "job-1", recovery_turn_id: "turn-1", recovery_protocol_version: 1,
  created_at: 1_700_000_001, is_final_chunk: true,
};

beforeEach(() => { vi.useFakeTimers(); clearRecoveryFinalTimestamps(); });
afterEach(() => { clearRecoveryFinalTimestamps(); vi.useRealTimers(); });

describe("recovery final timestamp handoff", () => {
  // contract-test: direct surface=gui.web assertions=chats.completion.lease-fenced
  it("waits for a matched final marker when recovery discovery arrives first", async () => {
    const timestamp = waitForRecoveryFinalTimestamp("chat-1", "assistant-1", "job-1", "turn-1");
    recordRecoveryFinalTimestamp({ ...finalMarker, recovery_job_id: "foreign-job" });
    recordRecoveryFinalTimestamp({ ...finalMarker, recovery_turn_id: "foreign-turn" });
    recordRecoveryFinalTimestamp({ ...finalMarker, is_final_chunk: false });
    let resolved = false;
    void timestamp.then(() => { resolved = true; });
    await Promise.resolve();
    expect(resolved).toBe(false);
    recordRecoveryFinalTimestamp(finalMarker);
    await expect(timestamp).resolves.toBe(1_700_000_001);
  });

  // contract-test: direct surface=gui.web assertions=chats.completion.lease-fenced
  it("releases missing metadata on timeout or lifecycle reset", async () => {
    const timedOut = waitForRecoveryFinalTimestamp("chat-1", "assistant-1", "job-1", "turn-1");
    await vi.advanceTimersByTimeAsync(2_000);
    await expect(timedOut).resolves.toBeNull();
    const disconnected = waitForRecoveryFinalTimestamp("chat-1", "assistant-2", "job-2", "turn-2");
    clearRecoveryFinalTimestamps();
    await expect(disconnected).resolves.toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });
});
