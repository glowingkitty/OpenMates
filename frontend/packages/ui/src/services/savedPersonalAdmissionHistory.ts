import type { Message } from '../types/chat';

/** Same full saved-history envelope as legacy sends, prepared before sealing.
 * A read/decryption/scope failure cannot become an empty-history admission. */
export async function prepareSavedPersonalAdmissionHistory(input: {
  chatId: string; messageId: string; currentContent: string;
  read: () => Promise<Message[]>;
  category: (message: Message) => Promise<string | undefined>;
  assertCurrent: () => void;
}): Promise<Message[]> {
  input.assertCurrent();
  const messages = await input.read();
  input.assertCurrent();
  if (!messages.some(message => message.message_id !== input.messageId)) {
    throw new Error('Saved phased admission requires previous history.');
  }
  const ids = new Set<string>();
  const projected = await Promise.all(messages.map(async message => {
    if (message.chat_id !== input.chatId || !message.message_id || ids.has(message.message_id)) {
      throw new Error('Saved phased admission history identity mismatch.');
    }
    ids.add(message.message_id);
    if (typeof message.content !== 'string') throw new Error('Saved phased admission history was not decrypted.');
    return {
      message_id: message.message_id, chat_id: input.chatId, role: message.role,
      content: message.message_id === input.messageId ? input.currentContent : message.content,
      encrypted_content: message.encrypted_content,
      encrypted_sender_name: message.encrypted_sender_name,
      encrypted_category: message.encrypted_category,
      encrypted_model_name: message.encrypted_model_name,
      encrypted_pii_mappings: message.encrypted_pii_mappings,
      created_at: message.created_at, sender_name: message.sender_name,
      category: await input.category(message),
    } as Message;
  }));
  input.assertCurrent();
  return projected;
}

/** A committed retry journal owns its original transport and context identity. */
export function selectPersonalPhasedAdmission(eligible: boolean, retainedJournal: boolean, retainedPhased: boolean): boolean {
  return retainedJournal ? retainedPhased : eligible;
}
