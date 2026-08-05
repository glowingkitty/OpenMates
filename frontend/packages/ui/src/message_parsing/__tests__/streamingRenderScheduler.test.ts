// frontend/packages/ui/src/message_parsing/__tests__/streamingRenderScheduler.test.ts
// Defines the bounded leading/trailing scheduler used by streamed chat messages.
// Continuous chunks must not starve rendering or trigger token-level compilation.
// Completion applies only a newer final revision and always clears pending work.
// Spec: docs/specs/streaming-message-render-convergence/spec.yml

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StreamingRenderScheduler } from "../streamingRenderScheduler";

describe("StreamingRenderScheduler", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("flushes continuous 30ms updates without exceeding the 80ms cadence", () => {
    const flushes: Array<{ value: string; revision: number; reason: string; at: number }> = [];
    const scheduler = new StreamingRenderScheduler<string>({
      intervalMs: 80,
      onFlush: (value, revision, reason) => {
        flushes.push({ value, revision, reason, at: Date.now() });
      },
    });

    for (let revision = 1; revision <= 34; revision += 1) {
      scheduler.update(`snapshot-${revision}`, revision);
      vi.advanceTimersByTime(30);
    }

    expect(flushes[0]).toMatchObject({ value: "snapshot-1", revision: 1, reason: "stream" });
    expect(flushes.length).toBeGreaterThan(10);
    expect(flushes.length).toBeLessThanOrEqual(14);
    expect(Math.max(...flushes.slice(1).map((entry, index) => entry.at - flushes[index].at))).toBeLessThanOrEqual(80);
    expect(flushes.at(-1)?.revision).toBeGreaterThanOrEqual(32);
  });

  it("coalesces pending updates and applies a newer final revision at most once", () => {
    const onFlush = vi.fn();
    const scheduler = new StreamingRenderScheduler<string>({ intervalMs: 80, onFlush });

    scheduler.update("one", 1);
    scheduler.update("two", 2);
    scheduler.update("three", 3);
    expect(onFlush).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(80);
    expect(onFlush).toHaveBeenLastCalledWith("three", 3, "stream");

    scheduler.complete("three", 3);
    scheduler.complete("three", 3);
    expect(onFlush).toHaveBeenCalledTimes(2);

    scheduler.complete("four", 4);
    scheduler.complete("four", 4);
    expect(onFlush).toHaveBeenCalledTimes(3);
    expect(onFlush).toHaveBeenLastCalledWith("four", 4, "complete");
    expect(vi.getTimerCount()).toBe(0);
  });
});
