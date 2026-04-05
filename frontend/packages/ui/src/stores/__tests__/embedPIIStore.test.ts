// frontend/packages/ui/src/stores/__tests__/embedPIIStore.test.ts
// Unit tests for embed PII store — two-layer PII mapping architecture
// that merges message-level and embed-level mappings for embed components.
//
// Architecture: frontend/packages/ui/src/stores/embedPIIStore.ts

import { describe, it, expect, beforeEach } from "vitest";
import { get } from "svelte/store";
import {
  embedPIIStore,
  setEmbedPIIState,
  addEmbedPIIMappings,
  removeEmbedPIIMappings,
  getEmbedPIIState,
  resetEmbedPIIState,
} from "../embedPIIStore";
import type { PIIMapping } from "../../types/chat";

const emailMapping: PIIMapping = {
  placeholder: "[EMAIL_1_com]",
  original: "user@example.com",
  type: "email",
};

const phoneMapping: PIIMapping = {
  placeholder: "[PHONE_1_100]",
  original: "+1-555-0100",
  type: "phone",
};

const addressMapping: PIIMapping = {
  placeholder: "[ADDRESS_1]",
  original: "123 Main St",
  type: "address",
};

describe("embedPIIStore", () => {
  beforeEach(() => {
    resetEmbedPIIState();
  });

  // ──────────────────────────────────────────────────────────────────
  // Initial state
  // ──────────────────────────────────────────────────────────────────

  describe("initial state", () => {
    it("starts with empty mappings and revealed=false", () => {
      const state = get(embedPIIStore);
      expect(state.mappings).toEqual([]);
      expect(state.revealed).toBe(false);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // setEmbedPIIState (message-level mappings)
  // ──────────────────────────────────────────────────────────────────

  describe("setEmbedPIIState", () => {
    it("sets message-level mappings", () => {
      setEmbedPIIState([emailMapping], false);
      const state = get(embedPIIStore);
      expect(state.mappings).toEqual([emailMapping]);
      expect(state.revealed).toBe(false);
    });

    it("sets revealed state", () => {
      setEmbedPIIState([emailMapping], true);
      expect(get(embedPIIStore).revealed).toBe(true);
    });

    it("clears embed-level mappings on update (chat switch)", () => {
      // Register embed-level mappings first
      setEmbedPIIState([emailMapping], false);
      addEmbedPIIMappings("embed-1", [phoneMapping]);
      expect(get(embedPIIStore).mappings).toHaveLength(2);

      // Switching chat clears embed mappings, keeps new message mappings
      setEmbedPIIState([addressMapping], false);
      const state = get(embedPIIStore);
      expect(state.mappings).toEqual([addressMapping]);
    });

    it("replaces previous message mappings", () => {
      setEmbedPIIState([emailMapping], false);
      setEmbedPIIState([phoneMapping], true);

      const state = get(embedPIIStore);
      expect(state.mappings).toEqual([phoneMapping]);
      expect(state.revealed).toBe(true);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // addEmbedPIIMappings (embed-level mappings)
  // ──────────────────────────────────────────────────────────────────

  describe("addEmbedPIIMappings", () => {
    it("merges embed mappings with message mappings", () => {
      setEmbedPIIState([emailMapping], false);
      addEmbedPIIMappings("embed-1", [phoneMapping]);

      const state = get(embedPIIStore);
      // Message-level first, embed-level second
      expect(state.mappings).toEqual([emailMapping, phoneMapping]);
    });

    it("supports multiple embeds with separate mappings", () => {
      addEmbedPIIMappings("embed-1", [emailMapping]);
      addEmbedPIIMappings("embed-2", [phoneMapping]);

      const state = get(embedPIIStore);
      expect(state.mappings).toHaveLength(2);
      expect(state.mappings).toContainEqual(emailMapping);
      expect(state.mappings).toContainEqual(phoneMapping);
    });

    it("is idempotent — same embedId replaces previous mappings", () => {
      addEmbedPIIMappings("embed-1", [emailMapping]);
      addEmbedPIIMappings("embed-1", [phoneMapping]);

      const state = get(embedPIIStore);
      expect(state.mappings).toEqual([phoneMapping]);
    });

    it("ignores empty mappings array", () => {
      addEmbedPIIMappings("embed-1", []);
      expect(get(embedPIIStore).mappings).toEqual([]);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // removeEmbedPIIMappings
  // ──────────────────────────────────────────────────────────────────

  describe("removeEmbedPIIMappings", () => {
    it("removes mappings for a specific embed", () => {
      addEmbedPIIMappings("embed-1", [emailMapping]);
      addEmbedPIIMappings("embed-2", [phoneMapping]);

      removeEmbedPIIMappings("embed-1");

      const state = get(embedPIIStore);
      expect(state.mappings).toEqual([phoneMapping]);
    });

    it("is safe to call with non-existent embedId", () => {
      addEmbedPIIMappings("embed-1", [emailMapping]);
      removeEmbedPIIMappings("non-existent");

      expect(get(embedPIIStore).mappings).toEqual([emailMapping]);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // getEmbedPIIState (synchronous read)
  // ──────────────────────────────────────────────────────────────────

  describe("getEmbedPIIState", () => {
    it("returns current merged state synchronously", () => {
      setEmbedPIIState([emailMapping], true);
      addEmbedPIIMappings("embed-1", [phoneMapping]);

      const state = getEmbedPIIState();
      expect(state.mappings).toEqual([emailMapping, phoneMapping]);
      expect(state.revealed).toBe(true);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // resetEmbedPIIState
  // ──────────────────────────────────────────────────────────────────

  describe("resetEmbedPIIState", () => {
    it("clears all mappings and resets revealed to false", () => {
      setEmbedPIIState([emailMapping], true);
      addEmbedPIIMappings("embed-1", [phoneMapping]);

      resetEmbedPIIState();

      const state = get(embedPIIStore);
      expect(state.mappings).toEqual([]);
      expect(state.revealed).toBe(false);
    });
  });
});
