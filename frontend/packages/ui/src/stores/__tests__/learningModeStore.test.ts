// frontend/packages/ui/src/stores/__tests__/learningModeStore.test.ts
//
// Regression coverage for Learning Mode store load state.
// A failed authenticated status load must not leave the store in a state that
// lets settings effects retry forever and flood users with notifications.

import { webcrypto } from "node:crypto";
import { get } from "svelte/store";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import {
  GUEST_RECORD_STORAGE_KEY,
  LearningModeRequestError,
  getAnonymousLearningModeContext,
  learningMode,
} from "../learningModeStore";

vi.mock("../../config/api", () => ({
  getApiEndpoint: (path: string) => `https://api.test${path}`,
}));

// The shared test setup mocks crypto; guest passcode hashing needs the real WebCrypto.
beforeAll(() => {
  Object.defineProperty(globalThis, "crypto", { value: webcrypto, configurable: true });
});

describe("learningModeStore", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    learningMode.reset();
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  // contract-test: supporting surface=gui.web assertions=learning-mode.collaborative-toggle
  it("marks failed authenticated loads as terminal to prevent settings retry loops", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: "Invalid or expired token" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        })
      )
    );

    await expect(learningMode.load()).rejects.toThrow("Invalid or expired token");

    expect(get(learningMode)).toMatchObject({
      loaded: true,
      loading: false,
      source: "account",
    });
  });

  describe("account actions", () => {
    function stubStatus(body: Record<string, unknown>, status = 200) {
      const fetchMock = vi.fn(async () =>
        new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
      );
      vi.stubGlobal("fetch", fetchMock);
      return fetchMock;
    }
    const accountStatus = {
      enabled: true,
      age_group: "13_15",
      collaborative_build: true,
      failed_attempts: 0,
      deactivation_blocked_until: null,
    };

    // contract-test: supporting surface=gui.web assertions=learning-mode.collaborative-toggle
    it("activate sends collaborative_build and forces it off for under_10", async () => {
      const fetchMock = stubStatus(accountStatus);
      await learningMode.activate("1234", "13_15", true);
      await learningMode.activate("1234", "under_10", true);

      const bodies = fetchMock.mock.calls.map((call) => JSON.parse((call as unknown as [string, RequestInit])[1].body as string));
      expect(bodies[0]).toEqual({ passcode: "1234", age_group: "13_15", collaborative_build: true });
      expect(bodies[1]).toEqual({ passcode: "1234", age_group: "under_10", collaborative_build: false });
      expect(get(learningMode).collaborative_build).toBe(true);
    });

    // contract-test: supporting surface=gui.web assertions=learning-mode.anonymous-client-side
    it("setCollaborativeBuild sends the passcode only when enabling", async () => {
      const fetchMock = stubStatus(accountStatus);
      await learningMode.setCollaborativeBuild(true, "1234");
      await learningMode.setCollaborativeBuild(false, "1234");

      const calls = fetchMock.mock.calls.map((call) => call as unknown as [string, RequestInit]);
      expect(calls[0][0]).toBe("https://api.test/v1/learning-mode/collaborative");
      expect(JSON.parse(calls[0][1].body as string)).toEqual({ enabled: true, passcode: "1234" });
      expect(JSON.parse(calls[1][1].body as string)).toEqual({ enabled: false });
    });

    // contract-test: supporting surface=gui.web assertions=learning-mode.anonymous-client-side
    it("surfaces the 403 reason and syncs the lockout counters", async () => {
      stubStatus({ detail: { ...accountStatus, reason: "wrong_passcode", failed_attempts: 3 } }, 403);
      const error = await learningMode.setCollaborativeBuild(true, "nope").catch((caught) => caught);

      expect(error).toBeInstanceOf(LearningModeRequestError);
      expect((error as LearningModeRequestError).reason).toBe("wrong_passcode");
      expect(get(learningMode).failed_attempts).toBe(3);
    });
  });

  describe("guest learning mode", () => {
    // contract-test: supporting surface=gui.web assertions=learning-mode.anonymous-client-side
    it("persists a passcode-locked record in localStorage, not sessionStorage", async () => {
      await learningMode.activateGuest("1234", "10_12", true);

      const raw = window.localStorage.getItem(GUEST_RECORD_STORAGE_KEY) ?? "";
      expect(raw).not.toBe("");
      expect(raw).not.toContain("1234\"");
      expect(JSON.parse(raw).passcode).toMatchObject({ algorithm: "pbkdf2_sha256", iterations: 210000 });
      expect(window.sessionStorage.length).toBe(0);
      expect(learningMode.loadGuest()).toMatchObject({ enabled: true, age_group: "10_12", collaborative_build: true });
    });

    // contract-test: supporting surface=gui.web assertions=learning-mode.anonymous-client-side
    it("ignores the legacy sessionStorage keys", () => {
      window.sessionStorage.setItem("openmates.learningMode.enabled", "true");
      window.sessionStorage.setItem("openmates.learningMode.ageGroup", "10_12");

      expect(learningMode.loadGuest().enabled).toBe(false);
      expect(getAnonymousLearningModeContext()).toBeUndefined();
    });

    // contract-test: supporting surface=gui.web assertions=learning-mode.anonymous-client-side
    it("rejects too short passcodes", async () => {
      await expect(learningMode.activateGuest("abc", "13_15", true)).rejects.toMatchObject({ reason: "invalid_passcode" });
      expect(get(learningMode).enabled).toBe(false);
    });

    // contract-test: supporting surface=gui.web assertions=learning-mode.collaborative-toggle
    it("forces collaborative building off for under_10", async () => {
      const status = await learningMode.activateGuest("1234", "under_10", true);

      expect(status.collaborative_build).toBe(false);
      expect(getAnonymousLearningModeContext()).toEqual({
        enabled: true,
        age_group: "under_10",
        collaborative_build: false,
        source: "anonymous_session",
      });
      await expect(learningMode.setGuestCollaborativeBuild(true, "1234")).rejects.toMatchObject({ reason: "not_allowed" });
    });

    // contract-test: supporting surface=gui.web assertions=learning-mode.anonymous-client-side
    it("turns collaborative off freely but needs the passcode to turn it on", async () => {
      await learningMode.activateGuest("1234", "13_15", true);

      expect((await learningMode.setGuestCollaborativeBuild(false)).collaborative_build).toBe(false);
      await expect(learningMode.setGuestCollaborativeBuild(true)).rejects.toMatchObject({ reason: "wrong_passcode" });
      expect(get(learningMode).collaborative_build).toBe(false);
      expect((await learningMode.setGuestCollaborativeBuild(true, "1234")).collaborative_build).toBe(true);
    });

    // contract-test: supporting surface=gui.web assertions=learning-mode.anonymous-client-side
    it("requires the passcode to deactivate and blocks for 24h after 5 wrong attempts", async () => {
      await learningMode.activateGuest("1234", "13_15", true);

      for (let attempt = 1; attempt <= 4; attempt += 1) {
        await expect(learningMode.deactivateGuest("0000")).rejects.toMatchObject({ reason: "wrong_passcode" });
        expect(get(learningMode).failed_attempts).toBe(attempt);
      }
      await expect(learningMode.deactivateGuest("0000")).rejects.toMatchObject({ reason: "blocked" });

      const blockedUntil = get(learningMode).deactivation_blocked_until;
      expect(blockedUntil).not.toBeNull();
      expect((blockedUntil as number) - Math.floor(Date.now() / 1000)).toBeGreaterThan(24 * 3600 - 60);

      // Even the right passcode is refused while blocked, for deactivation and collaborative ON.
      await expect(learningMode.deactivateGuest("1234")).rejects.toMatchObject({ reason: "blocked" });
      await learningMode.setGuestCollaborativeBuild(false);
      await expect(learningMode.setGuestCollaborativeBuild(true, "1234")).rejects.toMatchObject({ reason: "blocked" });
      expect(learningMode.loadGuest().enabled).toBe(true);
    });

    // contract-test: supporting surface=gui.web assertions=learning-mode.anonymous-client-side
    it("deactivates with the right passcode and clears the lock", async () => {
      await learningMode.activateGuest("1234", "16_18", true);
      await learningMode.deactivateGuest("1234");

      expect(get(learningMode).enabled).toBe(false);
      expect(getAnonymousLearningModeContext()).toBeUndefined();
    });

    // contract-test: supporting surface=gui.web assertions=learning-mode.anonymous-client-side
    it("exposes only non-secret fields in the anonymous request context", async () => {
      await learningMode.activateGuest("1234", "13_15", true);
      await expect(learningMode.deactivateGuest("0000")).rejects.toBeInstanceOf(LearningModeRequestError);

      const context = getAnonymousLearningModeContext();
      expect(context).toEqual({
        enabled: true,
        age_group: "13_15",
        collaborative_build: true,
        source: "anonymous_session",
      });
      expect(Object.keys(context as object).sort()).toEqual(["age_group", "collaborative_build", "enabled", "source"]);
    });
  });
});
