/** Locate and time a first read of a real archived chat page via CLI decryption. */
const observedPages = new Set();

export async function readArchivedPage({ client, chatId, expectedUserMessages }) {
  if (!(expectedUserMessages instanceof Set) || expectedUserMessages.size === 0) {
    throw new Error('Archived read requires the plaintext message ledger');
  }
  let cursor = null;
  for (let pageNumber = 0; pageNumber < 100; pageNumber++) {
    const options = { direction: cursor ? 'before' : 'latest', limit: 20,
      respectCompressionBoundary: false, personal: true };
    if (cursor) {
      options.beforeTimestamp = cursor.created_at;
      options.beforeMessageId = cursor.message_id;
    }
    const started = performance.now();
    const page = await client.getChatMessagesWindow(chatId, options);
    const readyMs = performance.now() - started;
    if (!Array.isArray(page.messages) || !page.messages.length) return { archived: false };
    const archiveIds = Array.isArray(page.archivePageIds) ? page.archivePageIds : [];
    const validIds = archiveIds.filter(id => typeof id === 'string' && id.length > 0);
    const firstRead = validIds.length > 0 && validIds.length === archiveIds.length &&
      validIds.every(id => !observedPages.has(id));
    if (page.storageTier === 'archive' && firstRead) {
      for (const id of validIds) observedPages.add(id);
      const userMessages = page.messages.filter(message => message.role === 'user');
      const decrypted = page.messages.every(message =>
        typeof message.content === 'string' && message.content.length > 0) &&
        userMessages.length > 0 && userMessages.every(message => expectedUserMessages.has(message.content));
      return { archived: true, authorized: true, decrypted,
        cache: page.archivePayloadCache === 'disabled' ? 'cold' : 'warm', readyMs, archivePageIds: validIds };
    }
    if (!page.hasMoreBefore || !page.startCursor) return { archived: false };
    cursor = page.startCursor;
  }
  throw new Error('Archived page lookup exceeded the bounded 100-page search');
}
