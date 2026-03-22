// frontend/packages/ui/src/stores/__tests__/searchStore.test.ts
// Unit tests for search store — state management for the chat search bar.
//
// Architecture: frontend/packages/ui/src/stores/searchStore.ts

import { describe, it, expect, beforeEach } from "vitest";
import { get } from "svelte/store";
import {
  searchStore,
  openSearch,
  closeSearch,
  setSearchQuery,
  setSearching,
} from "../searchStore";

describe("searchStore", () => {
  beforeEach(() => {
    closeSearch(); // resets to initialState
  });

  // ──────────────────────────────────────────────────────────────────
  // Initial state
  // ──────────────────────────────────────────────────────────────────

  describe("initial state", () => {
    it("starts inactive with empty query", () => {
      const state = get(searchStore);
      expect(state.query).toBe("");
      expect(state.isActive).toBe(false);
      expect(state.isSearching).toBe(false);
      expect(state.activeMessageId).toBeNull();
      expect(state.activeSearchChatId).toBeNull();
      expect(state.closeChatsOnEscape).toBe(false);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // openSearch
  // ──────────────────────────────────────────────────────────────────

  describe("openSearch", () => {
    it("sets isActive to true", () => {
      openSearch();
      expect(get(searchStore).isActive).toBe(true);
    });

    it("defaults closeChatsOnEscape to false", () => {
      openSearch();
      expect(get(searchStore).closeChatsOnEscape).toBe(false);
    });

    it("accepts closeChatsOnEscape option", () => {
      openSearch({ closeChatsOnEscape: true });
      expect(get(searchStore).closeChatsOnEscape).toBe(true);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // closeSearch
  // ──────────────────────────────────────────────────────────────────

  describe("closeSearch", () => {
    it("resets all state to initial values", () => {
      openSearch({ closeChatsOnEscape: true });
      setSearchQuery("test query");
      closeSearch();

      const state = get(searchStore);
      expect(state.query).toBe("");
      expect(state.isActive).toBe(false);
      expect(state.isSearching).toBe(false);
      expect(state.activeMessageId).toBeNull();
      expect(state.activeSearchChatId).toBeNull();
      expect(state.closeChatsOnEscape).toBe(false);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // setSearchQuery
  // ──────────────────────────────────────────────────────────────────

  describe("setSearchQuery", () => {
    it("updates the query string", () => {
      setSearchQuery("hello");
      expect(get(searchStore).query).toBe("hello");
    });

    it("sets isSearching=true for non-empty query", () => {
      setSearchQuery("hello");
      expect(get(searchStore).isSearching).toBe(true);
    });

    it("sets isSearching=false for empty query", () => {
      setSearchQuery("hello");
      setSearchQuery("");
      expect(get(searchStore).isSearching).toBe(false);
    });

    it("sets isSearching=false for whitespace-only query", () => {
      setSearchQuery("   ");
      expect(get(searchStore).isSearching).toBe(false);
    });

    it("clears activeMessageId when query changes", () => {
      // Simulate having an active message from previous search
      searchStore.update((s) => ({
        ...s,
        activeMessageId: "msg-1",
        activeSearchChatId: "chat-1",
      }));

      setSearchQuery("new query");
      expect(get(searchStore).activeMessageId).toBeNull();
    });

    it("preserves isActive state", () => {
      openSearch();
      setSearchQuery("test");
      expect(get(searchStore).isActive).toBe(true);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // setSearching
  // ──────────────────────────────────────────────────────────────────

  describe("setSearching", () => {
    it("sets isSearching to true", () => {
      setSearching(true);
      expect(get(searchStore).isSearching).toBe(true);
    });

    it("sets isSearching to false", () => {
      setSearching(true);
      setSearching(false);
      expect(get(searchStore).isSearching).toBe(false);
    });

    it("does not affect other state", () => {
      openSearch();
      setSearchQuery("test");
      setSearching(false);

      const state = get(searchStore);
      expect(state.isActive).toBe(true);
      expect(state.query).toBe("test");
    });
  });
});
