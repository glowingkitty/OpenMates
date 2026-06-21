// frontend/packages/ui/src/services/topicPreferencesSync.ts
// Encrypted account topic-preference sync for guest smart selection.
// Guest selections remain in sessionStorage until a user is authenticated.
// Authenticated preferences are merged into the existing encrypted_settings
// ciphertext so the server never receives cleartext interest tags.

import { get } from "svelte/store";

import { apiEndpoints, getApiEndpoint } from "../config/api";
import { normalizeInterestTagIds } from "../demo_chats/interestTags";
import {
  decryptWithMasterKey,
  encryptWithMasterKey,
} from "./encryption/MetadataEncryptor";
import { updateProfile } from "../stores/userProfile";
import {
  clearGuestTopicPreferences,
  createTopicPreferencesPayload,
  loadGuestTopicPreferences,
  topicPreferencesStore,
  type TopicPreferencesPayload,
} from "../stores/topicPreferencesStore";
import { userProfile } from "../stores/userProfile";

const TOPIC_PREFERENCES_SETTINGS_KEY = "topic_preferences";

type EncryptedSettingsRecord = Record<string, unknown>;

function parseEncryptedSettingsJson(
  raw: string | null,
  options: { strict?: boolean } = {},
): EncryptedSettingsRecord {
  if (!raw) {
    return {};
  }

  try {
    const parsed = JSON.parse(raw) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as EncryptedSettingsRecord)
      : {};
  } catch (error) {
    if (options.strict) {
      throw new Error(
        `Encrypted settings JSON is invalid: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
    console.warn("[TopicPreferencesSync] Failed to parse encrypted settings JSON", error);
    return {};
  }
}

export function normalizeTopicPreferencesPayload(
  value: unknown,
): TopicPreferencesPayload | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }

  const candidate = value as Partial<TopicPreferencesPayload>;
  if (candidate.version !== 1 || !Array.isArray(candidate.selectedTagIds)) {
    return null;
  }

  return {
    version: 1,
    selectedTagIds: normalizeInterestTagIds(candidate.selectedTagIds),
    updatedAt:
      typeof candidate.updatedAt === "string"
        ? candidate.updatedAt
        : new Date(0).toISOString(),
  };
}

export async function decryptTopicPreferencesFromSettings(
  encryptedSettings: string | null | undefined,
): Promise<TopicPreferencesPayload | null> {
  if (!encryptedSettings) {
    return null;
  }

  const decrypted = await decryptWithMasterKey(encryptedSettings);
  if (!decrypted) {
    console.warn(
      "[TopicPreferencesSync] Could not decrypt encrypted settings for topic preferences",
    );
    return null;
  }

  const settings = parseEncryptedSettingsJson(decrypted);
  return normalizeTopicPreferencesPayload(settings[TOPIC_PREFERENCES_SETTINGS_KEY]);
}

async function persistEncryptedSettings(encryptedSettings: string): Promise<void> {
  const response = await fetch(getApiEndpoint(apiEndpoints.settings.topicPreferences), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ encrypted_settings: encryptedSettings }),
  });

  if (!response.ok) {
    throw new Error(`Topic preferences sync failed with ${response.status}`);
  }
}

export async function saveAccountTopicPreferences(
  selectedTagIds: readonly string[],
  options: { now?: () => Date } = {},
): Promise<TopicPreferencesPayload> {
  const profile = get(userProfile);
  const existingEncryptedSettings = profile.encrypted_settings ?? null;
  const existingPlainSettings = existingEncryptedSettings
    ? await decryptWithMasterKey(existingEncryptedSettings)
    : null;

  if (existingEncryptedSettings && !existingPlainSettings) {
    throw new Error("Unable to decrypt existing account settings");
  }

  const settings = parseEncryptedSettingsJson(existingPlainSettings, { strict: true });
  const payload = createTopicPreferencesPayload(selectedTagIds, options.now);
  settings[TOPIC_PREFERENCES_SETTINGS_KEY] = payload;

  const encryptedSettings = await encryptWithMasterKey(JSON.stringify(settings));
  if (!encryptedSettings) {
    throw new Error("Unable to encrypt topic preferences");
  }

  await persistEncryptedSettings(encryptedSettings);
  updateProfile({
    encrypted_settings: encryptedSettings,
    topic_preferences: payload,
  });

  return payload;
}

export async function hydrateAccountTopicPreferences(
  encryptedSettings: string | null | undefined,
): Promise<TopicPreferencesPayload | null> {
  const payload = await decryptTopicPreferencesFromSettings(encryptedSettings);
  updateProfile({
    encrypted_settings: encryptedSettings ?? null,
    topic_preferences: payload ?? undefined,
  });
  return payload;
}

export async function promoteGuestTopicPreferencesIfNeeded(): Promise<
  TopicPreferencesPayload | null
> {
  const guestPayload = loadGuestTopicPreferences();
  if (!guestPayload || guestPayload.selectedTagIds.length === 0) {
    const profile = get(userProfile);
    return await hydrateAccountTopicPreferences(profile.encrypted_settings);
  }

  const savedPayload = await saveAccountTopicPreferences(
    guestPayload.selectedTagIds,
  );
  clearGuestTopicPreferences();
  topicPreferencesStore.clearGuest();
  return savedPayload;
}
