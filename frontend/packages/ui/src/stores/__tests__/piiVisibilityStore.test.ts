// frontend/packages/ui/src/stores/__tests__/piiVisibilityStore.test.ts
// Unit tests for PII visibility store — per-chat toggle for showing/hiding
// sensitive personal information in chat messages.
//
// Architecture: frontend/packages/ui/src/stores/piiVisibilityStore.ts

import { describe, it, expect, beforeEach } from "vitest";
import { get } from "svelte/store";
import { piiVisibilityStore } from "../piiVisibilityStore";

describe("piiVisibilityStore", () => {
  beforeEach(() => {
    piiVisibilityStore.reset();
  });

  // ──────────────────────────────────────────────────────────────────
  // Initial / default state
  // ──────────────────────────────────────────────────────────────────

  describe("initial state", () => {
    it("starts with an empty map", () => {
      const map = get(piiVisibilityStore);
      expect(map.size).toBe(0);
    });

    it("isRevealed returns false for unknown chat", () => {
      expect(piiVisibilityStore.isRevealed("unknown-chat")).toBe(false);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // toggle
  // ──────────────────────────────────────────────────────────────────

  describe("toggle", () => {
    it("reveals PII on first toggle (default hidden → revealed)", () => {
      piiVisibilityStore.toggle("chat-1");
      expect(piiVisibilityStore.isRevealed("chat-1")).toBe(true);
    });

    it("hides PII on second toggle (revealed → hidden)", () => {
      piiVisibilityStore.toggle("chat-1");
      piiVisibilityStore.toggle("chat-1");
      expect(piiVisibilityStore.isRevealed("chat-1")).toBe(false);
    });

    it("toggles independently per chat", () => {
      piiVisibilityStore.toggle("chat-1");
      expect(piiVisibilityStore.isRevealed("chat-1")).toBe(true);
      expect(piiVisibilityStore.isRevealed("chat-2")).toBe(false);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // setRevealed
  // ──────────────────────────────────────────────────────────────────

  describe("setRevealed", () => {
    it("sets PII to revealed", () => {
      piiVisibilityStore.setRevealed("chat-1", true);
      expect(piiVisibilityStore.isRevealed("chat-1")).toBe(true);
    });

    it("sets PII to hidden", () => {
      piiVisibilityStore.setRevealed("chat-1", true);
      piiVisibilityStore.setRevealed("chat-1", false);
      expect(piiVisibilityStore.isRevealed("chat-1")).toBe(false);
    });

    it("does not affect other chats", () => {
      piiVisibilityStore.setRevealed("chat-1", true);
      expect(piiVisibilityStore.isRevealed("chat-2")).toBe(false);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // forChat (derived store)
  // ──────────────────────────────────────────────────────────────────

  describe("forChat", () => {
    it("returns a derived store defaulting to false", () => {
      const chatPII = piiVisibilityStore.forChat("chat-1");
      expect(get(chatPII)).toBe(false);
    });

    it("reacts to toggle changes", () => {
      const chatPII = piiVisibilityStore.forChat("chat-1");
      piiVisibilityStore.toggle("chat-1");
      expect(get(chatPII)).toBe(true);
    });

    it("does not react to other chat changes", () => {
      const chatPII = piiVisibilityStore.forChat("chat-1");
      piiVisibilityStore.toggle("chat-2");
      expect(get(chatPII)).toBe(false);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // reset
  // ──────────────────────────────────────────────────────────────────

  describe("reset", () => {
    it("clears all chat visibility state", () => {
      piiVisibilityStore.setRevealed("chat-1", true);
      piiVisibilityStore.setRevealed("chat-2", true);
      piiVisibilityStore.reset();

      expect(piiVisibilityStore.isRevealed("chat-1")).toBe(false);
      expect(piiVisibilityStore.isRevealed("chat-2")).toBe(false);
      expect(get(piiVisibilityStore).size).toBe(0);
    });
  });
});
