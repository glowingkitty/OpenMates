/**
 * chatNavigationStore.spec.ts
 *
 * Tests that ChatHeader prev/next navigation can reach ALL available example
 * chats — static intro chats, example chats, and legal chats.
 *
 * The store maintains an internal chat list and exposes hasPrev / hasNext
 * flags. navigatePrev() / navigateNext() walk that list sequentially.
 * These tests verify that every example chat is reachable by repeated
 * navigation from any starting position.
 *
 * Covers the bug where only a single example chat (demo-capital-of-spain)
 * was navigable while the rest were silently skipped.
 *
 * @see docs/architecture/ (chat navigation)
 * @see chatNavigationStore.ts
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { get } from "svelte/store";
import type { Chat } from "../../types/chat";

// ─── Shared state for mocks ────────────────────────────────────────────────
// vi.mock factories are hoisted — they can't reference variables declared later.
// We use a shared module-scoped container that both the mock factory and tests
// can read/write.

const sharedState = {
  exampleChats: [] as Chat[],
};

// ─── Window stubs ───────────────────────────────────────────────────────────
// test-setup.ts replaces window with a minimal object. We need dispatchEvent
// and CustomEvent for selectChat() to work.

if (typeof window !== "undefined") {
  if (!window.dispatchEvent) {
    window.dispatchEvent = vi.fn(() => true);
  }
  if (typeof CustomEvent === "undefined") {
    (globalThis as any).CustomEvent = class CustomEvent extends Event {
      detail: any;
      constructor(type: string, params?: any) {
        super(type);
        this.detail = params?.detail;
      }
    };
  }
}

// ─── Mock definitions ───────────────────────────────────────────────────────

vi.mock("../../services/chatListCache", () => ({
  chatListCache: {
    getCache: vi.fn(() => null),
  },
}));

vi.mock("../activeChatStore", () => ({
  activeChatStore: {
    setActiveChat: vi.fn(),
  },
}));

vi.mock("../../services/chatSyncService", () => ({
  chatSyncService: {
    sendSetActiveChat: vi.fn(async () => {}),
  },
}));

vi.mock("../../services/db", () => ({
  chatDB: {
    getAllChats: vi.fn(async () => []),
  },
}));

vi.mock("../../demo_chats/translateDemoChat", () => ({
  translateDemoChat: vi.fn((chat: any) => chat),
}));

vi.mock("../../demo_chats/convertToChat", () => ({
  convertDemoChatToChat: vi.fn((demo: any) => ({
    chat_id: demo.chat_id,
    title: demo.title || demo.chat_id,
    encrypted_title: null,
    messages_v: 1,
    title_v: 1,
    last_edited_overall_timestamp: demo.metadata?.order
      ? Date.now() - 7 * 24 * 60 * 60 * 1000 - demo.metadata.order * 1000
      : Date.now(),
    unread_count: 0,
    created_at: Date.now(),
    updated_at: Date.now(),
  })),
}));

// Mock the barrel export for demo_chats — inline the INTRO/LEGAL data
vi.mock("../../demo_chats", () => ({
  INTRO_CHATS: [
    {
      chat_id: "demo-for-everyone",
      title: "For Everyone",
      slug: "for-everyone",
      messages: [],
      metadata: {
        category: "general_knowledge",
        icon_names: ["globe"],
        featured: true,
        order: 0,
        lastUpdated: "2026-01-01",
      },
    },
    {
      chat_id: "demo-for-developers",
      title: "For Developers",
      slug: "for-developers",
      messages: [],
      metadata: {
        category: "software_development",
        icon_names: ["code"],
        featured: true,
        order: 1,
        lastUpdated: "2026-01-01",
      },
    },
    {
      chat_id: "demo-who-develops-openmates",
      title: "Who Develops OpenMates",
      slug: "who-develops-openmates",
      messages: [],
      metadata: {
        category: "technology",
        icon_names: ["cpu"],
        featured: true,
        order: 2,
        lastUpdated: "2026-01-01",
      },
    },
  ],
  LEGAL_CHATS: [
    {
      chat_id: "legal-privacy",
      title: "Privacy Policy",
      slug: "privacy",
      messages: [],
      metadata: {
        category: "legal",
        icon_names: ["shield"],
        featured: false,
        order: 0,
        lastUpdated: "2026-01-01",
      },
    },
    {
      chat_id: "legal-terms",
      title: "Terms of Use",
      slug: "terms",
      messages: [],
      metadata: {
        category: "legal",
        icon_names: ["file-text"],
        featured: false,
        order: 1,
        lastUpdated: "2026-01-01",
      },
    },
    {
      chat_id: "legal-imprint",
      title: "Imprint",
      slug: "imprint",
      messages: [],
      metadata: {
        category: "legal",
        icon_names: ["info"],
        featured: false,
        order: 2,
        lastUpdated: "2026-01-01",
      },
    },
  ],
  getAllExampleChats: () => sharedState.exampleChats,
  translateDemoChat: vi.fn((chat: any) => chat),
}));

// ─── Import module under test AFTER mocks ───────────────────────────────────

import {
  chatNavigationStore,
  setChatNavigationList,
  resetChatNavigationList,
  releaseChatNavigationOwnership,
  updateNavFromCache,
  navigateNext,
  navigatePrev,
} from "../chatNavigationStore";

// ─── Helpers ────────────────────────────────────────────────────────────────

/** Create a minimal Chat object for testing. */
function makeChat(id: string, opts: Partial<Chat> = {}): Chat {
  return {
    chat_id: id,
    title: id,
    encrypted_title: null,
    messages_v: 1,
    title_v: 1,
    last_edited_overall_timestamp: Date.now(),
    unread_count: 0,
    created_at: Date.now(),
    updated_at: Date.now(),
    ...opts,
  };
}

/** Build example Chat objects matching the 5 example chats. */
function makeExampleChats(): Chat[] {
  return [
    makeChat("demo-capital-of-spain", {
      title: "Capital of Spain",
      category: "general_knowledge",
      icon: "globe",
      demo_chat_category: "for_everyone",
      last_edited_overall_timestamp: Date.now() - 1000,
    }),
    makeChat("demo-implement-stripe-into-web-app", {
      title: "Implement Stripe into Web App",
      category: "software_development",
      icon: "code",
      demo_chat_category: "for_developers",
      last_edited_overall_timestamp: Date.now() - 2000,
    }),
    makeChat("demo-vegetarische-rezept-ideen", {
      title: "Vegetarian Recipe Ideas",
      category: "cooking_food",
      icon: "leaf",
      demo_chat_category: "for_everyone",
      last_edited_overall_timestamp: Date.now() - 3000,
    }),
    makeChat("demo-history-of-berlin", {
      title: "History of Berlin",
      category: "history",
      icon: "globe",
      demo_chat_category: "for_everyone",
      last_edited_overall_timestamp: Date.now() - 4000,
    }),
    makeChat("demo-deutsches-elektronen-synchrotron", {
      title: "German Electron Synchrotron",
      category: "science",
      icon: "globe",
      demo_chat_category: "for_everyone",
      last_edited_overall_timestamp: Date.now() - 5000,
    }),
  ];
}

/**
 * Build the full navigable list as Chats.svelte would for an unauthenticated user.
 * Order: intro (group 0) → examples (group 1) → legal (group 2)
 */
function buildFullChatList(): Chat[] {
  const introChats = [
    makeChat("demo-for-everyone", {
      group_key: "intro",
      last_edited_overall_timestamp: Date.now(),
    }),
    makeChat("demo-for-developers", {
      group_key: "intro",
      last_edited_overall_timestamp: Date.now() - 100,
    }),
    makeChat("demo-who-develops-openmates", {
      group_key: "intro",
      last_edited_overall_timestamp: Date.now() - 200,
    }),
  ];
  const exampleChats = makeExampleChats().map((c) => ({
    ...c,
    group_key: "examples" as const,
  }));
  const legalChats = [
    makeChat("legal-privacy", {
      group_key: "legal",
      last_edited_overall_timestamp: Date.now() - 300,
    }),
    makeChat("legal-terms", {
      group_key: "legal",
      last_edited_overall_timestamp: Date.now() - 400,
    }),
    makeChat("legal-imprint", {
      group_key: "legal",
      last_edited_overall_timestamp: Date.now() - 500,
    }),
  ];
  return [...introChats, ...exampleChats, ...legalChats];
}

// ─── Tests ──────────────────────────────────────────────────────────────────

describe("chatNavigationStore — example chat navigation", () => {
  beforeEach(() => {
    resetChatNavigationList();
    sharedState.exampleChats = [];
    vi.clearAllMocks();
    // Re-ensure window.dispatchEvent is available
    if (typeof window !== "undefined" && !window.dispatchEvent) {
      window.dispatchEvent = vi.fn(() => true);
    }
  });

  describe("setChatNavigationList (sidebar-driven)", () => {
    it("all 11 chats are navigable via setChatNavigationList + store.set", () => {
      const fullList = buildFullChatList();

      // Mimic what Chats.svelte's $effect does:
      // 1. Compute hasPrev/hasNext
      // 2. Call setChatNavigationList
      const idx = fullList.findIndex((c) => c.chat_id === "demo-for-everyone");
      chatNavigationStore.set({
        hasPrev: idx > 0,
        hasNext: idx >= 0 && idx < fullList.length - 1,
      });
      setChatNavigationList(fullList, "demo-for-everyone");

      const state = get(chatNavigationStore);
      expect(state.hasPrev).toBe(false);
      expect(state.hasNext).toBe(true);
    });

    it("can navigate forward through all 11 chats", async () => {
      const fullList = buildFullChatList();
      const idx = fullList.findIndex((c) => c.chat_id === "demo-for-everyone");
      chatNavigationStore.set({
        hasPrev: idx > 0,
        hasNext: idx >= 0 && idx < fullList.length - 1,
      });
      setChatNavigationList(fullList, "demo-for-everyone");

      let count = 1; // starting chat
      let state = get(chatNavigationStore);
      let safety = 0;
      while (state.hasNext && safety < 20) {
        await navigateNext();
        count++;
        state = get(chatNavigationStore);
        safety++;
      }

      expect(count).toBe(fullList.length);
      expect(state.hasNext).toBe(false);
      expect(state.hasPrev).toBe(true);
    });

    it("can navigate backward through all 11 chats", async () => {
      const fullList = buildFullChatList();
      const lastChat = fullList[fullList.length - 1];
      const idx = fullList.length - 1;
      chatNavigationStore.set({
        hasPrev: idx > 0,
        hasNext: false,
      });
      setChatNavigationList(fullList, lastChat.chat_id);

      let count = 1;
      let state = get(chatNavigationStore);
      let safety = 0;
      while (state.hasPrev && safety < 20) {
        await navigatePrev();
        count++;
        state = get(chatNavigationStore);
        safety++;
      }

      expect(count).toBe(fullList.length);
      expect(state.hasPrev).toBe(false);
      expect(state.hasNext).toBe(true);
    });

    it("every example chat is individually reachable", async () => {
      const fullList = buildFullChatList();

      // Start at first chat, navigate to end
      chatNavigationStore.set({
        hasPrev: false,
        hasNext: fullList.length > 1,
      });
      setChatNavigationList(fullList, fullList[0].chat_id);

      let state = get(chatNavigationStore);
      let safety = 0;
      while (state.hasNext && safety < 20) {
        await navigateNext();
        state = get(chatNavigationStore);
        safety++;
      }

      // The number of navigations should equal fullList.length - 1
      // (we visited every chat including all 5 example chats)
      expect(safety).toBe(fullList.length - 1);
    });
  });

  describe("updateNavFromCache (cold boot, sidebar closed)", () => {
    it("includes all example chats when available at call time", async () => {
      const demos = makeExampleChats();
      sharedState.exampleChats = demos;

      updateNavFromCache("demo-for-everyone");

      // Give async operations a tick
      await new Promise((r) => setTimeout(r, 150));

      const state = get(chatNavigationStore);
      expect(state.hasNext).toBe(true);

      // Navigate through all chats
      let count = 1;
      let s = get(chatNavigationStore);
      let safety = 0;
      while (s.hasNext && safety < 20) {
        await navigateNext();
        count++;
        s = get(chatNavigationStore);
        safety++;
      }

      // intro(3) + example(5) + legal(3) = 11
      expect(count).toBe(11);
    });

    it("example chats added between updateNavFromCache calls become navigable", async () => {
      // Start with no example chats
      sharedState.exampleChats = [];

      updateNavFromCache("demo-for-everyone");
      await new Promise((r) => setTimeout(r, 150));

      // Now example chats become available (e.g. module loaded later)
      sharedState.exampleChats = makeExampleChats();

      // Re-trigger (as ActiveChat.loadChat would on next chat switch)
      updateNavFromCache("demo-for-everyone");

      let count = 1;
      let s = get(chatNavigationStore);
      let safety = 0;
      while (s.hasNext && safety < 20) {
        await navigateNext();
        count++;
        s = get(chatNavigationStore);
        safety++;
      }

      // All 11 should be reachable
      expect(count).toBe(11);
    });

    it("every example chat has navigable neighbors when set as active", async () => {
      const demos = makeExampleChats();
      sharedState.exampleChats = demos;

      for (const demo of demos) {
        resetChatNavigationList();
        sharedState.exampleChats = demos;

        updateNavFromCache(demo.chat_id);
        await new Promise((r) => setTimeout(r, 150));

        const state = get(chatNavigationStore);
        expect(
          state.hasPrev || state.hasNext,
          `Chat ${demo.chat_id} should have at least one navigable neighbor`,
        ).toBe(true);
      }
    });
  });

  describe("new-chat-creation self-healing (Fix #1)", () => {
    /**
     * Regression: before the fix, chatListOwnedByChatsComponent stayed true
     * forever once Chats.svelte had mounted once. After Chats.svelte unmounts
     * (sidebar closed on mobile), newly-created chats never became part of
     * the navigation list — ChatHeader prev/next arrows would compute from
     * a stale list and report findIndex=-1 → hasPrev/hasNext false.
     *
     * With releaseChatNavigationOwnership() called on sidebar destroy, the
     * store resumes self-managing and picks up new chats from cache/DB.
     */
    it("releaseChatNavigationOwnership lets subsequent updateNavFromCache rebuild from fresh sources", async () => {
      // 1. Simulate sidebar mounting and taking ownership with an initial list
      //    that only contains the 3 intro chats.
      const introOnly = [
        makeChat("demo-for-everyone", { group_key: "intro" }),
        makeChat("demo-for-developers", { group_key: "intro" }),
        makeChat("demo-who-develops-openmates", { group_key: "intro" }),
      ];
      setChatNavigationList(introOnly, "demo-for-everyone");

      // 2. User creates a new chat while sidebar is still open — sidebar's
      //    $effect would call setChatNavigationList again. We skip that step
      //    to simulate the race where the sidebar has unmounted between the
      //    DB write and the effect re-run (mobile: send message then sidebar
      //    closes in a layout change).
      releaseChatNavigationOwnership();

      // 3. DB now contains the new chat. updateNavFromCache should rebuild.
      sharedState.exampleChats = makeExampleChats();
      updateNavFromCache("demo-for-everyone");
      await new Promise((r) => setTimeout(r, 150));

      // The example chats must now be reachable from the intro chat.
      const state = get(chatNavigationStore);
      expect(state.hasNext).toBe(true);

      // Walk forward — we should reach every example chat.
      let count = 1;
      let s = get(chatNavigationStore);
      let safety = 0;
      while (s.hasNext && safety < 20) {
        await navigateNext();
        count++;
        s = get(chatNavigationStore);
        safety++;
      }
      // 3 intro + 5 example + 3 legal
      expect(count).toBe(11);
    });

    it("without releasing ownership, stale sidebar list still shadows fresh sources", async () => {
      // Negative-control test: verifies the bug reproduces when ownership
      // is NOT released (proves the fix above is doing real work).
      const introOnly = [
        makeChat("demo-for-everyone", { group_key: "intro" }),
        makeChat("demo-for-developers", { group_key: "intro" }),
      ];
      setChatNavigationList(introOnly, "demo-for-everyone");

      // No releaseChatNavigationOwnership() call — simulates the old bug.
      sharedState.exampleChats = makeExampleChats();
      updateNavFromCache("demo-for-everyone");
      await new Promise((r) => setTimeout(r, 150));

      // hasNext is true for "demo-for-developers" (the second intro chat),
      // but when we navigate forward to its end, we should be stuck there
      // instead of reaching the example chats.
      let count = 1;
      let s = get(chatNavigationStore);
      let safety = 0;
      while (s.hasNext && safety < 20) {
        await navigateNext();
        count++;
        s = get(chatNavigationStore);
        safety++;
      }
      // Still stuck on the stale 2-chat list
      expect(count).toBe(2);
    });
  });
});
