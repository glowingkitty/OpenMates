/*
 * OpenMates CLI encrypted object slug helpers.
 *
 * Purpose: keep private object handles encrypted while making CLI/SDK output readable.
 * Architecture: callers provide the object encryption key and owner/team lookup key.
 * Security: plaintext slugs are normalized locally, never sent to the API.
 * Spec: docs/specs/cli-encrypted-slugs/spec.yml.
 * Tests: existing workflow/project/plan/task/chat CLI and SDK suites.
 */

import { createHmac, hkdfSync } from "node:crypto";

import { decryptWithAesGcmCombined, encryptWithAesGcmCombined } from "./crypto.js";

const SLUG_LOOKUP_HASH_INFO = "openmates-object-slug-index-v1";
const MAX_SLUG_LENGTH = 80;

export interface EncryptedObjectSlugMetadata {
  slug: string;
  encrypted_slug: string;
  slug_lookup_hash: string;
}

export function normalizeObjectSlug(value: string): string {
  const normalized = value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim()
    .replace(/'/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .replace(/-{2,}/g, "-");
  const slug = normalized.slice(0, MAX_SLUG_LENGTH).replace(/-+$/g, "");
  if (!slug) throw new Error("Object slug must contain at least one letter or number.");
  return slug;
}

export async function buildEncryptedObjectSlugMetadata(input: {
  value: string;
  encryptionKey: Uint8Array;
  lookupKey: Uint8Array;
}): Promise<EncryptedObjectSlugMetadata> {
  const slug = normalizeObjectSlug(input.value);
  return {
    slug,
    encrypted_slug: await encryptWithAesGcmCombined(slug, input.encryptionKey),
    slug_lookup_hash: objectSlugLookupHash(slug, input.lookupKey),
  };
}

export async function decryptObjectSlug(
  encryptedSlug: string | null | undefined,
  encryptionKey: Uint8Array,
): Promise<string> {
  if (!encryptedSlug) return "";
  return (await decryptWithAesGcmCombined(encryptedSlug, encryptionKey)) ?? "";
}

export function objectSlugMatches(slug: string | null | undefined, query: string): boolean {
  if (!slug) return false;
  try {
    return normalizeObjectSlug(slug) === normalizeObjectSlug(query);
  } catch {
    return false;
  }
}

function objectSlugLookupHash(slug: string, lookupKey: Uint8Array): string {
  const indexKey = Buffer.from(
    hkdfSync("sha256", Buffer.from(lookupKey), Buffer.alloc(0), SLUG_LOOKUP_HASH_INFO, 32),
  );
  return createHmac("sha256", indexKey).update(slug).digest("hex");
}
