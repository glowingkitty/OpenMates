// frontend/packages/ui/src/stores/__tests__/topicPreferencesStore.test.ts
// Regression coverage for topic preference persistence boundaries. Guest
// selections must remain session-only until signup promotion encrypts them into
// synced account data in a later slice.

import { describe, expect, it } from "vitest";

import {
  GUEST_TOPIC_PREFERENCES_STORAGE_KEY,
  clearGuestTopicPreferences,
  createTopicPreferencesPayload,
  loadGuestTopicPreferences,
  saveGuestTopicPreferences,
} from "../topicPreferencesStore";

function createStorageMock(): Storage {
  const data = new Map<string, string>();

  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key: string) => data.get(key) ?? null,
    key: (index: number) => Array.from(data.keys())[index] ?? null,
    removeItem: (key: string) => data.delete(key),
    setItem: (key: string, value: string) => data.set(key, value),
  };
}

describe("topicPreferencesStore guest storage", () => {
  it("creates normalized v1 payloads with stable tag IDs", () => {
    expect(
      createTopicPreferencesPayload(
        ["software_development", "unknown", "protect_my_privacy", "software_development"],
        () => new Date("2026-06-20T22:00:00Z"),
      ),
    ).toEqual({
      version: 1,
      selectedTagIds: ["software_development", "protect_my_privacy"],
      updatedAt: "2026-06-20T22:00:00.000Z",
    });
  });

  it("writes logged-out selections only to sessionStorage", () => {
    const sessionStorage = createStorageMock();
    const localStorage = createStorageMock();

    const payload = saveGuestTopicPreferences(
      ["find_apartments", "local_life"],
      {
        storage: sessionStorage,
        now: () => new Date("2026-06-20T23:00:00Z"),
      },
    );

    expect(payload.selectedTagIds).toEqual(["find_apartments", "local_life"]);
    expect(sessionStorage.getItem(GUEST_TOPIC_PREFERENCES_STORAGE_KEY)).toContain(
      "find_apartments",
    );
    expect(localStorage.getItem(GUEST_TOPIC_PREFERENCES_STORAGE_KEY)).toBeNull();
  });

  it("restores same-session selections and clears them for a new session", () => {
    const sessionStorage = createStorageMock();

    saveGuestTopicPreferences(["software_development"], {
      storage: sessionStorage,
      now: () => new Date("2026-06-20T23:30:00Z"),
    });

    expect(loadGuestTopicPreferences(sessionStorage)?.selectedTagIds).toEqual([
      "software_development",
    ]);

    expect(loadGuestTopicPreferences(createStorageMock())).toBeNull();
  });

  it("clears malformed or explicit guest selections from sessionStorage", () => {
    const sessionStorage = createStorageMock();
    sessionStorage.setItem(GUEST_TOPIC_PREFERENCES_STORAGE_KEY, "not-json");

    expect(loadGuestTopicPreferences(sessionStorage)).toBeNull();
    expect(sessionStorage.getItem(GUEST_TOPIC_PREFERENCES_STORAGE_KEY)).toBeNull();

    saveGuestTopicPreferences(["protect_my_privacy"], {
      storage: sessionStorage,
      now: () => new Date("2026-06-20T23:45:00Z"),
    });
    clearGuestTopicPreferences(sessionStorage);

    expect(sessionStorage.getItem(GUEST_TOPIC_PREFERENCES_STORAGE_KEY)).toBeNull();
  });
});
