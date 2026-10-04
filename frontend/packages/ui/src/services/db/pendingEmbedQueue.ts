/** Wait for the IndexedDB transaction commit before sending the queued ciphertext. */
export function putPendingEmbedOperation(
  transaction: IDBTransaction,
  storeName: string,
  operation: unknown,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = transaction.objectStore(storeName).put(operation);
    request.onerror = () => reject(request.error);
    transaction.oncomplete = () => resolve();
    transaction.onabort = () => reject(transaction.error ?? new Error("Pending embed queue transaction aborted"));
    transaction.onerror = () => reject(transaction.error ?? new Error("Pending embed queue transaction failed"));
  });
}
