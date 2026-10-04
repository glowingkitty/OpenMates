/** Locate and time a first read of a real archived chat page via CLI decryption. */
const observedPages = new Set();

export async function readArchivedPage({ client, chatId }) {
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
    for (const id of validIds) observedPages.add(id);
    if ((page.storageTier === 'archive' || page.storageTier === 'mixed') && firstRead) {
      return { archived: true, authorized: true, decrypted: page.messages.every(
        message => typeof message.content === 'string' && message.content.length > 0),
        cache: page.archivePayloadCache === 'disabled' ? 'cold' : 'warm', readyMs, archivePageIds: validIds };
    }
    if (!page.hasMoreBefore || !page.startCursor) return { archived: false };
    cursor = page.startCursor;
  }
  throw new Error('Archived page lookup exceeded the bounded 100-page search');
}
