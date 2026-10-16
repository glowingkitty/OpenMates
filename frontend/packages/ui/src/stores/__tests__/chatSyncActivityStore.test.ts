import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { chatSyncActivity } from "../chatSyncActivityStore";

describe("chatSyncActivity", () => {
  beforeEach(() => chatSyncActivity.clear());
  afterEach(() => {
    chatSyncActivity.clear();
    vi.useRealTimers();
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
  it("tracks the active request until its matching real full completion", () => {
    chatSyncActivity.begin({ teamId: null, epoch: 4 });
    expect(get(chatSyncActivity)).toEqual({ active: true, teamId: null, contextEpoch: 4 });

    chatSyncActivity.complete({ phase: "phase1", team_id: null, context_epoch: 4 });
    chatSyncActivity.complete({ phase: "all", team_id: null, context_epoch: 3 });
    chatSyncActivity.complete({ phase: "all", team_id: "another-team", context_epoch: 4 });
    expect(get(chatSyncActivity).active).toBe(true);

    chatSyncActivity.complete({ phase: "all", team_id: null, context_epoch: 4 });
    expect(get(chatSyncActivity).active).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
  it("does not let an older failed send clear a newer attempt", () => {
    const oldAttempt = chatSyncActivity.begin({ teamId: null, epoch: 4 });
    const currentAttempt = chatSyncActivity.begin({ teamId: "team-1", epoch: 5 });

    chatSyncActivity.clearAttempt(oldAttempt);
    expect(get(chatSyncActivity)).toEqual({ active: true, teamId: "team-1", contextEpoch: 5 });

    chatSyncActivity.clearAttempt(currentAttempt);
    expect(get(chatSyncActivity).active).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
  it("keeps the icon active while either phased or offline sync is pending", () => {
    chatSyncActivity.begin({ teamId: null, epoch: 4 });
    chatSyncActivity.beginOffline();
    chatSyncActivity.complete({ phase: "all", team_id: null, context_epoch: 4 });
    expect(get(chatSyncActivity).active).toBe(true);

    chatSyncActivity.begin({ teamId: null, epoch: 4 });
    chatSyncActivity.completeOffline();
    expect(get(chatSyncActivity).active).toBe(true);

    chatSyncActivity.complete({ phase: "all", team_id: null, context_epoch: 4 });
    expect(get(chatSyncActivity).active).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
  it("bounds offline activity and ignores a failed older send", () => {
    vi.useFakeTimers();
    const older = chatSyncActivity.beginOffline();
    vi.advanceTimersByTime(20_000);
    chatSyncActivity.beginOffline();
    chatSyncActivity.clearOfflineAttempt(older);
    expect(get(chatSyncActivity).active).toBe(true);

    vi.advanceTimersByTime(10_000);
    expect(get(chatSyncActivity).active).toBe(true);
    vi.advanceTimersByTime(20_000);
    expect(get(chatSyncActivity).active).toBe(false);
  });
});
