// frontend/packages/ui/src/services/__tests__/websocketService.test.ts
// Regression coverage for low-level WebSocket message routing.
// Some server events can arrive during cold boot before ChatSync registers its
// handlers. These tests guard the tiny replay buffer used for recovery jobs so
// encrypted completion recovery does not lose an availability announcement.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { webSocketService } from "../websocketService";

describe("webSocketService early message replay", () => {
  beforeEach(() => {
    webSocketService.clearHandlers("recovery_jobs_available");
    (webSocketService as unknown as { earlyMessagesByType: Map<string, unknown[]> })
      .earlyMessagesByType
      .clear();
  });

  it("replays buffered recovery availability once when the handler registers", async () => {
    const payload = { jobs: [{ job_id: "job-1" }] };
    (webSocketService as unknown as {
      bufferEarlyMessage: (messageType: string, payload: unknown) => void;
    }).bufferEarlyMessage("recovery_jobs_available", payload);

    const handler = vi.fn();
    webSocketService.on("recovery_jobs_available", handler);

    await vi.waitFor(() => {
      expect(handler).toHaveBeenCalledWith(payload);
    });
    expect(handler).toHaveBeenCalledTimes(1);

    const laterHandler = vi.fn();
    webSocketService.on("recovery_jobs_available", laterHandler);
    await Promise.resolve();

    expect(laterHandler).not.toHaveBeenCalled();
    webSocketService.off("recovery_jobs_available", handler);
    webSocketService.off("recovery_jobs_available", laterHandler);
  });
});
