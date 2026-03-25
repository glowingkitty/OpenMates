// frontend/packages/ui/src/stores/__tests__/authState.test.ts
// Unit tests for auth state stores — the core contract for authentication status.
//
// Bug history:
//  - 780b871e7: isAuthenticated not flipped to false fast enough → stale chat data
//  - 775a8db00: spurious WS 1006 → auth check → offline-first set isAuthenticated
//  - e7cd73d88: pair login triggering destructive forced logout
//  - 7cb9cd11b: logout notification shown when local profile is empty
//
// Architecture: frontend/packages/ui/src/stores/authState.ts

import { describe, it, expect, beforeEach } from "vitest";
import { get } from "svelte/store";
import {
  authStore,
  isCheckingAuth,
  needsDeviceVerification,
  deviceVerificationType,
  deviceVerificationReason,
  authInitialState,
} from "../authState";

describe("authState stores", () => {
  beforeEach(() => {
    authStore.set({ ...authInitialState });
    isCheckingAuth.set(false);
    needsDeviceVerification.set(false);
    deviceVerificationType.set(null);
    deviceVerificationReason.set(null);
  });

  // ──────────────────────────────────────────────────────────────────
  // Initial state contract
  // ──────────────────────────────────────────────────────────────────

  describe("initial state", () => {
    it("isAuthenticated defaults to false", () => {
      expect(get(authStore).isAuthenticated).toBe(false);
    });

    it("isInitialized defaults to false", () => {
      expect(get(authStore).isInitialized).toBe(false);
    });

    it("isCheckingAuth defaults to false", () => {
      expect(get(isCheckingAuth)).toBe(false);
    });

    it("needsDeviceVerification defaults to false", () => {
      expect(get(needsDeviceVerification)).toBe(false);
    });

    it("deviceVerificationType defaults to null", () => {
      expect(get(deviceVerificationType)).toBeNull();
    });

    it("deviceVerificationReason defaults to null", () => {
      expect(get(deviceVerificationReason)).toBeNull();
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // authStore transitions
  // ──────────────────────────────────────────────────────────────────

  describe("authStore transitions", () => {
    it("can transition to authenticated + initialized", () => {
      authStore.update((state) => ({
        ...state,
        isAuthenticated: true,
        isInitialized: true,
      }));
      const state = get(authStore);
      expect(state.isAuthenticated).toBe(true);
      expect(state.isInitialized).toBe(true);
    });

    it("logout sets isAuthenticated=false but keeps isInitialized=true", () => {
      // Login
      authStore.set({ isAuthenticated: true, isInitialized: true });
      // Logout
      authStore.set({ ...authInitialState, isInitialized: true });

      const state = get(authStore);
      expect(state.isAuthenticated).toBe(false);
      expect(state.isInitialized).toBe(true);
    });

    it("notifies subscribers on state change", () => {
      const values: boolean[] = [];
      const unsubscribe = authStore.subscribe((state) => {
        values.push(state.isAuthenticated);
      });

      authStore.set({ isAuthenticated: true, isInitialized: true });
      authStore.set({ isAuthenticated: false, isInitialized: true });

      unsubscribe();
      // Initial false + set to true + set to false = 3 values
      expect(values).toEqual([false, true, false]);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // Device verification stores (independent of authStore)
  // ──────────────────────────────────────────────────────────────────

  describe("device verification stores", () => {
    it("needsDeviceVerification is independent of authStore", () => {
      needsDeviceVerification.set(true);
      expect(get(needsDeviceVerification)).toBe(true);
      expect(get(authStore).isAuthenticated).toBe(false);
    });

    it("deviceVerificationType tracks 2fa type", () => {
      deviceVerificationType.set("2fa");
      expect(get(deviceVerificationType)).toBe("2fa");
    });

    it("deviceVerificationType tracks passkey type", () => {
      deviceVerificationType.set("passkey");
      expect(get(deviceVerificationType)).toBe("passkey");
    });

    it("deviceVerificationReason tracks new_device", () => {
      deviceVerificationReason.set("new_device");
      expect(get(deviceVerificationReason)).toBe("new_device");
    });

    it("deviceVerificationReason tracks location_change", () => {
      deviceVerificationReason.set("location_change");
      expect(get(deviceVerificationReason)).toBe("location_change");
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // isCheckingAuth flag
  // ──────────────────────────────────────────────────────────────────

  describe("isCheckingAuth", () => {
    it("can be set to true and back to false", () => {
      isCheckingAuth.set(true);
      expect(get(isCheckingAuth)).toBe(true);
      isCheckingAuth.set(false);
      expect(get(isCheckingAuth)).toBe(false);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // authInitialState export
  // ──────────────────────────────────────────────────────────────────

  describe("authInitialState", () => {
    it("matches expected shape", () => {
      expect(authInitialState).toEqual({
        isAuthenticated: false,
        isInitialized: false,
      });
    });

    it("is not mutated by authStore.set", () => {
      authStore.set({ isAuthenticated: true, isInitialized: true });
      expect(authInitialState.isAuthenticated).toBe(false);
      expect(authInitialState.isInitialized).toBe(false);
    });
  });
});
