// frontend/packages/ui/src/services/__tests__/unavailableModelRecovery.test.ts
// Contract tests for visible recovery from unavailable exact model selections.
// Validation must work both when a chat loads and immediately before sending.
// Recovery notifies the owner, persists Auto through the injected selection API,
// and returns Auto so normal automatic routing can resume without substitution.
// Architecture: contracts/features/ai-model-routing/contract.yml

import { describe, expect, it, vi } from "vitest";

import { recoverUnavailableModelSelection } from "../unavailableModelRecovery";

const UNAVAILABLE_MODEL = "anthropic/claude-sonnet-5";

describe("unavailable model recovery", () => {
  // contract-test: direct surface=gui.web assertions=ai-model-routing.unavailable.notify-reset-auto
  it.each(["load", "send"] as const)(
    "notifies and persists Auto when an exact model is unavailable during %s",
    async (phase) => {
      const notify = vi.fn();
      const persistSelection = vi.fn(async () => undefined);

      await expect(
        recoverUnavailableModelSelection({
          phase,
          selection: UNAVAILABLE_MODEL,
          isUsable: () => false,
          notify,
          persistSelection,
        }),
      ).resolves.toBe("auto");

      expect(notify).toHaveBeenCalledWith({ phase, unavailableModel: UNAVAILABLE_MODEL });
      expect(persistSelection).toHaveBeenCalledWith("auto");
      expect(notify.mock.invocationCallOrder[0]).toBeLessThan(
        persistSelection.mock.invocationCallOrder[0],
      );
    },
  );

  // contract-test: direct surface=gui.web assertions=ai-model-routing.unavailable.notify-reset-auto
  it("keeps an available exact selection without a notification or persistence reset", async () => {
    const notify = vi.fn();
    const persistSelection = vi.fn(async () => undefined);

    await expect(
      recoverUnavailableModelSelection({
        phase: "send",
        selection: UNAVAILABLE_MODEL,
        isUsable: (model) => model === UNAVAILABLE_MODEL,
        notify,
        persistSelection,
      }),
    ).resolves.toBe(UNAVAILABLE_MODEL);

    expect(notify).not.toHaveBeenCalled();
    expect(persistSelection).not.toHaveBeenCalled();
  });
});
