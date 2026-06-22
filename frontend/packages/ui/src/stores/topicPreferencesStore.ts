// frontend/packages/ui/src/stores/topicPreferencesStore.ts
// Topic preference state shared by guest smart selection and future encrypted
// account sync. Guest selections are intentionally sessionStorage-only; do not
// read from or write to localStorage here. Account promotion/encryption belongs
// to the authenticated sync layer added in a later slice.

import { writable } from "svelte/store";

import {
  normalizeInterestTagIds,
  type InterestTagId,
} from "../demo_chats/interestTags";

export const GUEST_TOPIC_PREFERENCES_STORAGE_KEY =
  "openmates.guest_interest_tags.v1";

export interface TopicPreferencesPayload {
  version: 1;
  selectedTagIds: InterestTagId[];
  updatedAt: string;
}

interface TopicPreferencesState {
  guestSelectedTagIds: InterestTagId[];
}

const initialState: TopicPreferencesState = {
  guestSelectedTagIds: [],
};

function getDefaultSessionStorage(): Storage | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function createTopicPreferencesPayload(
  selectedTagIds: readonly string[],
  now: () => Date = () => new Date(),
): TopicPreferencesPayload {
  return {
    version: 1,
    selectedTagIds: normalizeInterestTagIds(selectedTagIds),
    updatedAt: now().toISOString(),
  };
}

export function loadGuestTopicPreferences(
  storage: Storage | null = getDefaultSessionStorage(),
): TopicPreferencesPayload | null {
  if (!storage) {
    return null;
  }

  const raw = storage.getItem(GUEST_TOPIC_PREFERENCES_STORAGE_KEY);
  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as Partial<TopicPreferencesPayload>;
    if (parsed.version !== 1 || !Array.isArray(parsed.selectedTagIds)) {
      storage.removeItem(GUEST_TOPIC_PREFERENCES_STORAGE_KEY);
      return null;
    }

    return {
      version: 1,
      selectedTagIds: normalizeInterestTagIds(parsed.selectedTagIds),
      updatedAt:
        typeof parsed.updatedAt === "string"
          ? parsed.updatedAt
          : new Date(0).toISOString(),
    };
  } catch {
    storage.removeItem(GUEST_TOPIC_PREFERENCES_STORAGE_KEY);
    return null;
  }
}

export function saveGuestTopicPreferences(
  selectedTagIds: readonly string[],
  options: {
    storage?: Storage | null;
    now?: () => Date;
  } = {},
): TopicPreferencesPayload {
  const payload = createTopicPreferencesPayload(selectedTagIds, options.now);
  const storage = options.storage ?? getDefaultSessionStorage();

  storage?.setItem(GUEST_TOPIC_PREFERENCES_STORAGE_KEY, JSON.stringify(payload));

  return payload;
}

export function clearGuestTopicPreferences(
  storage: Storage | null = getDefaultSessionStorage(),
): void {
  storage?.removeItem(GUEST_TOPIC_PREFERENCES_STORAGE_KEY);
}

function createTopicPreferencesStore() {
  const store = writable<TopicPreferencesState>(initialState);

  return {
    subscribe: store.subscribe,
    loadGuest(storage: Storage | null = getDefaultSessionStorage()) {
      const payload = loadGuestTopicPreferences(storage);
      store.set({
        guestSelectedTagIds: payload?.selectedTagIds ?? [],
      });
      return payload;
    },
    setGuestSelectedTagIds(
      selectedTagIds: readonly string[],
      options: { storage?: Storage | null; now?: () => Date } = {},
    ) {
      const payload = saveGuestTopicPreferences(selectedTagIds, options);
      store.set({ guestSelectedTagIds: payload.selectedTagIds });
      return payload;
    },
    clearGuest(storage: Storage | null = getDefaultSessionStorage()) {
      clearGuestTopicPreferences(storage);
      store.set(initialState);
    },
  };
}

export const topicPreferencesStore = createTopicPreferencesStore();
