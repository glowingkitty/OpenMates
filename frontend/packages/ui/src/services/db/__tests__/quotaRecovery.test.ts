import { describe, expect, it, vi } from "vitest";
import { writeWithQuotaRetry } from "../quotaRecovery";

const quotaError = () => new DOMException("Browser storage full", "QuotaExceededError");

describe("bounded quota recovery", () => {
  // contract-test: supporting surface=gui.web assertions=teams.cache.bounded-isolated
  it("trims eligible cache once and acknowledges only a committed retry", async () => {
    const write = vi.fn().mockRejectedValueOnce(quotaError()).mockResolvedValueOnce("committed");
    const trim = vi.fn().mockResolvedValue(1);
    const notify = vi.fn();
    await expect(writeWithQuotaRetry(write, trim, notify)).resolves.toBe("committed");
    expect(write).toHaveBeenCalledTimes(2);
    expect(trim).toHaveBeenCalledOnce();
    expect(notify).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=teams.cache.bounded-isolated
  it("reports unavailable offline saving after one failed retry", async () => {
    const write = vi.fn().mockRejectedValue(quotaError());
    const trim = vi.fn().mockResolvedValue(0);
    const notify = vi.fn();
    await expect(writeWithQuotaRetry(write, trim, notify)).rejects.toMatchObject({ name: "QuotaExceededError" });
    expect(write).toHaveBeenCalledTimes(2);
    expect(trim).toHaveBeenCalledOnce();
    expect(notify).toHaveBeenCalledOnce();
  });

  // contract-test: supporting surface=gui.web assertions=teams.cache.bounded-isolated
  it("does not retry inside an external transaction", async () => {
    const write = vi.fn().mockRejectedValue(quotaError());
    const trim = vi.fn();
    const notify = vi.fn();
    await expect(writeWithQuotaRetry(write, trim, notify, false)).rejects.toMatchObject({ name: "QuotaExceededError" });
    expect(write).toHaveBeenCalledOnce();
    expect(trim).not.toHaveBeenCalled();
    expect(notify).toHaveBeenCalledOnce();
  });
});
