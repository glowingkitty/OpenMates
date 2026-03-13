/**
 * chatNavigationStore.spec.ts
 *
 * Tests that ChatHeader prev/next navigation can reach ALL available example
 * chats — static intro chats, community demo chats, and legal chats.
 *
 * The store maintains an internal chat list and exposes hasPrev / hasNext
 * flags. navigatePrev() / navigateNext() walk that list sequentially.
 * These tests verify that every example chat is reachable by repeated
 * navigation from any starting position.
 *
 * Covers the bug where only a single community demo (demo-capital-of-spain)
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
  communityDemoChats: [] as Chat[],
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
vi.mock("../../demo_chats", async () => {
  const svelteStore = await import("svelte/store");
  const store = svelteStore.writable({ loaded: false, loading: false });
  return {
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
    getUiVisibleCommunityDemoChats: () => sharedState.communityDemoChats,
    communityDemoStore: {
      subscribe: store.subscribe,
      isLoaded: () => svelteStore.get(store).loaded,
      isLoading: () => svelteStore.get(store).loading,
    },
    __communityDemoStoreForTests: store,
    loadCommunityDemos: vi.fn(async () => {}),
    translateDemoChat: vi.fn((chat: any) => chat),
  };
});

// ─── Import module under test AFTER mocks ───────────────────────────────────

import {
  chatNavigationStore,
  setChatNavigationList,
  resetChatNavigationList,
  updateNavFromCache,
  navigateNext,
  navigatePrev,
} from "../chatNavigationStore";
import { __communityDemoStoreForTests } from "../../demo_chats";

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

/** Build community demo Chat objects matching the 5 server demos. */
function makeCommunityDemos(): Chat[] {
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
  const communityChats = makeCommunityDemos().map((c) => ({
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
  return [...introChats, ...communityChats, ...legalChats];
}

// ─── Tests ──────────────────────────────────────────────────────────────────

describe("chatNavigationStore — example chat navigation", () => {
  beforeEach(() => {
    resetChatNavigationList();
    sharedState.communityDemoChats = [];
    __communityDemoStoreForTests.set({ loaded: false, loading: false });
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

    it("every community demo is individually reachable", async () => {
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
      // (we visited every chat including all 5 community demos)
      expect(safety).toBe(fullList.length - 1);
    });
  });

  describe("updateNavFromCache (cold boot, sidebar closed)", () => {
    it("includes all community demos when already loaded at call time", async () => {
      const demos = makeCommunityDemos();
      sharedState.communityDemoChats = demos;
      __communityDemoStoreForTests.set({ loaded: true, loading: false });

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

      // intro(3) + community(5) + legal(3) = 11
      expect(count).toBe(11);
    });

    it("community demos that stream in after initial call become navigable", async () => {
      // Start with no community demos (cold boot, empty cache)
      sharedState.communityDemoChats = [];
      __communityDemoStoreForTests.set({ loaded: false, loading: true });

      updateNavFromCache("demo-for-everyone");
      await new Promise((r) => setTimeout(r, 150));

      // Now community demos "arrive"
      sharedState.communityDemoChats = makeCommunityDemos();
      __communityDemoStoreForTests.set({ loaded: true, loading: false });
      await new Promise((r) => setTimeout(r, 150));

      // Re-trigger (as ActiveChat.loadChat would)
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

    it("every community demo has navigable neighbors when set as active", async () => {
      const demos = makeCommunityDemos();
      sharedState.communityDemoChats = demos;
      __communityDemoStoreForTests.set({ loaded: true, loading: false });

      for (const demo of demos) {
        resetChatNavigationList();
        sharedState.communityDemoChats = demos;
        __communityDemoStoreForTests.set({ loaded: true, loading: false });

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
});
