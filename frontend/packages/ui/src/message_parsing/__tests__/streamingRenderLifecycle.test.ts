// frontend/packages/ui/src/message_parsing/__tests__/streamingRenderLifecycle.test.ts
// Covers cancellation and monotonic revision guards for streamed render work.
// Stale callbacks must never mutate a removed, superseded, or destroyed message.
// A valid later revision must recover after an incomplete or malformed suffix.
// Spec: docs/specs/streaming-message-render-convergence/spec.yml

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StreamingRenderScheduler } from "../streamingRenderScheduler";

describe("StreamingRenderScheduler lifecycle", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  // contract-test: supporting surface=gui.web assertions=chats.streaming.ordered-final,chats.rendering.assistant-document-convergence
  it("ignores stale revisions and cancels pending callbacks", () => {
    const onFlush = vi.fn();
    const scheduler = new StreamingRenderScheduler<string>({ intervalMs: 80, onFlush });

    scheduler.update("revision-2", 2);
    scheduler.update("stale-revision-1", 1);
    scheduler.update("revision-3", 3);
    scheduler.cancel();
    vi.runAllTimers();

    expect(onFlush).toHaveBeenCalledTimes(1);
    expect(onFlush).toHaveBeenCalledWith("revision-2", 2, "stream");
    expect(vi.getTimerCount()).toBe(0);

    scheduler.update("post-cancel", 4);
    expect(onFlush).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it("destroy prevents a pending callback and a fresh scheduler can recover", () => {
    const staleFlush = vi.fn();
    const staleScheduler = new StreamingRenderScheduler<string>({ intervalMs: 80, onFlush: staleFlush });
    staleScheduler.update("valid prefix plus malformed suffix {", 1);
    staleScheduler.update("superseded", 2);
    staleScheduler.destroy();
    vi.runAllTimers();
    expect(staleFlush).toHaveBeenCalledTimes(1);

    const recoveredFlush = vi.fn();
    const recoveredScheduler = new StreamingRenderScheduler<string>({ intervalMs: 80, onFlush: recoveredFlush });
    recoveredScheduler.update("valid recovered snapshot", 3);
    expect(recoveredFlush).toHaveBeenCalledWith("valid recovered snapshot", 3, "stream");
  });
});
