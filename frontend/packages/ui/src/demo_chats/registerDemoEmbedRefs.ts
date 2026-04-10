// frontend/packages/ui/src/demo_chats/registerDemoEmbedRefs.ts
//
// Registers embed_ref → embed_id mappings from community demo chat embeds
// into the embedStore's ref index. This bridges the gap between demo embeds
// (stored cleartext in communityDemoStore) and the embed resolution pipeline
// (which uses embedStore.resolveByRef() to map embed_ref slugs to UUIDs).
//
// Without this registration, inline embed references in demo chat messages
// (e.g. [!](embed:youtube.com-naK) or [text](embed:ref)) cannot resolve
// because the embedRefToIdIndex is only populated for encrypted user embeds.
/* eslint-disable no-console */

import { embedStore } from "../services/embedStore";
import type { DemoEmbed } from "../services/demoChatsDB";

const LOG_PREFIX = "[registerDemoEmbedRefs]";

/**
 * Regex to extract embed_ref from TOON-encoded content.
 * Matches lines like:
 *   embed_ref: youtube.com-naK
 *   embed_ref: "youtube.com-naK"
 */
const EMBED_REF_RE = /^embed_ref:\s*"?([^\n"]+)"?\s*$/m;

/**
 * Regex to extract app_id from TOON-encoded content.
 * Used to set the correct badge colour on inline embed links.
 */
const APP_ID_RE = /^app_id:\s*"?([^\n"]+)"?\s*$/m;

/**
 * Extract embed_ref and app_id from a TOON-encoded content string
 * without requiring the full TOON decoder. This is a lightweight
 * extraction — the fields are simple key: value lines in TOON format.
 */
function extractRefFields(content: string): {
  embedRef: string | null;
  appId: string | null;
} {
  const refMatch = content.match(EMBED_REF_RE);
  const appIdMatch = content.match(APP_ID_RE);
  return {
    embedRef: refMatch ? refMatch[1].trim() : null,
    appId: appIdMatch ? appIdMatch[1].trim() : null,
  };
}

/**
 * Register embed_ref → embed_id mappings for an array of demo embeds.
 * Call this after demo embeds are stored in communityDemoStore.
 *
 * @param embeds - Array of DemoEmbed objects with cleartext TOON content
 */
export function registerDemoEmbedRefs(embeds: DemoEmbed[]): void {
  let registered = 0;

  for (const embed of embeds) {
    if (!embed.content || !embed.embed_id) continue;

    const { embedRef, appId } = extractRefFields(embed.content);
    if (!embedRef) continue;

    embedStore.registerEmbedRef(embedRef, embed.embed_id, appId);
    registered++;
  }

  if (registered > 0) {
    console.debug(
      `${LOG_PREFIX} Registered ${registered}/${embeds.length} embed_ref mappings for demo embeds`,
    );
  }
}
