// frontend/packages/ui/src/services/shareState/incognitoChatPolicy.ts
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
// Forced fields, sessionStorage projection and update-accept rule of
// incognitoChatService.ts. Maps, sessionStorage and DOM events stay in the
// service; with VITE_OPENMATES_RUST_CORE=1 the shared Rust core decides.

type ChatRecord = Record<string, unknown>;

/** Chats loaded from sessionStorage always carry the incognito flags, even if stored before they existed. */
export function incognitoNormalize(input: { chats: ChatRecord[] }): ChatRecord[] {
  return input.chats.map((chat) => ({ ...chat, is_incognito: true, group_key: "incognito" }));
}

/** Essential metadata only: messages and server-generated encrypted fields are not persisted. */
export function incognitoMetadata(input: { chats: ChatRecord[] }): ChatRecord[] {
  return input.chats.map((chat) => ({
    chat_id: chat.chat_id,
    is_incognito: true,
    group_key: "incognito",
    encrypted_title: chat.encrypted_title,
    title: chat.title,
    // Plaintext category and icon come from the ai_typing_started payload so the
    // sidebar and header show the right icon after a reload within the session.
    category: chat.category,
    icon: chat.icon,
    created_at: chat.created_at,
    updated_at: chat.updated_at,
    last_edited_overall_timestamp: chat.last_edited_overall_timestamp,
    unread_count: chat.unread_count,
    messages_v: chat.messages_v,
    title_v: chat.title_v,
    draft_v: chat.draft_v,
    encrypted_draft_md: chat.encrypted_draft_md,
    encrypted_draft_preview: chat.encrypted_draft_preview,
    waiting_for_metadata: chat.waiting_for_metadata,
  }));
}

/** An update is applied only if it returned a row with the same message and chat ids. */
export function incognitoUpdateAccepted(input: {
  message_id: string; chat_id: string; next: { message_id?: string; chat_id?: string } | null;
}): boolean {
  const { next } = input;
  return !!next && next.message_id === input.message_id && next.chat_id === input.chat_id;
}

export const INCOGNITO_OPS = { incognitoNormalize, incognitoMetadata, incognitoUpdateAccepted };
