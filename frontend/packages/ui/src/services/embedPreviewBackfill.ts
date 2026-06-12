// frontend/packages/ui/src/services/embedPreviewBackfill.ts
// Pure guardrails for parent embed preview metadata backfill.
// Fullscreen components may derive lightweight preview metadata after explicit
// child loading, but only owner/write copies with complete encrypted routing
// metadata may persist that backfill through store_embed.
// Covered by embedPreviewBackfill.test.ts.

export interface PreviewBackfillPersistEntry {
  is_shared?: boolean;
  encrypted_content?: string;
  encrypted_type?: string;
  hashed_chat_id?: string;
  hashed_message_id?: string;
  hashed_user_id?: string;
}

export function canPersistPreviewBackfill(
  entry: PreviewBackfillPersistEntry | null | undefined,
): entry is PreviewBackfillPersistEntry & {
  encrypted_content: string;
  encrypted_type: string;
  hashed_chat_id: string;
  hashed_message_id: string;
  hashed_user_id: string;
} {
  return Boolean(
    entry &&
      !entry.is_shared &&
      entry.encrypted_content &&
      entry.encrypted_type &&
      entry.hashed_chat_id &&
      entry.hashed_message_id &&
      entry.hashed_user_id,
  );
}
