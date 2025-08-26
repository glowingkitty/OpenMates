// Client ContentStore for the unified message parsing architecture
// Integrates with existing IndexedDB structure from db.ts and uses cryptoService for encryption

import { ContentStoreEntry, EmbedType } from '../message_parsing/types';
import { computeSHA256, createContentId } from '../message_parsing/utils';
import { chatDB } from './db';
import { encryptWithMasterKey, decryptWithMasterKey } from './cryptoService';

// Content store name for IndexedDB
const CONTENTS_STORE_NAME = 'contents';

// In-memory cache for content (decrypted)
const contentCache = new Map<string, ContentStoreEntry>();

export class ContentStore {
  /**
   * Put content into the store (encrypted)
   * @param contentRef - The content reference key
   * @param data - The content data to store
   * @param type - The type of embed content
   */
  async put(contentRef: string, data: any, type: EmbedType): Promise<void> {
    // Encrypt the data using the master key
    const dataString = JSON.stringify(data);
    const encryptedData = encryptWithMasterKey(dataString);
    
    if (!encryptedData) {
      console.warn('[ContentStore] Master key not available, storing unencrypted data');
    }
    
    const entry: ContentStoreEntry = {
      contentRef,
      data: encryptedData || dataString, // Fallback to unencrypted if master key not available
      type,
      createdAt: Date.now(),
      updatedAt: Date.now()
    };
    
    // Store in memory cache
    contentCache.set(contentRef, entry);
    
    try {
      // Store in IndexedDB
      const transaction = await chatDB.getTransaction([CONTENTS_STORE_NAME], 'readwrite');
      const store = transaction.objectStore(CONTENTS_STORE_NAME);
      
      await new Promise<void>((resolve, reject) => {
        const request = store.put(entry);
        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error);
      });
      
      console.debug('[ContentStore] Put content in IndexedDB:', contentRef, type);
    } catch (error) {
      console.warn('[ContentStore] Failed to store in IndexedDB, using memory cache only:', error);
    }
  }
  
  /**
   * Get content from the store (decrypted)
   * @param contentRef - The content reference key to retrieve
   * @returns The stored content or undefined if not found
   */
  async get(contentRef: string): Promise<any> {
    // Check memory cache first
    let entry = contentCache.get(contentRef);
    
    // If not in cache, try to load from IndexedDB
    if (!entry) {
      try {
        const transaction = await chatDB.getTransaction([CONTENTS_STORE_NAME], 'readonly');
        const store = transaction.objectStore(CONTENTS_STORE_NAME);
        
        entry = await new Promise<ContentStoreEntry | undefined>((resolve, reject) => {
          const request = store.get(contentRef);
          request.onsuccess = () => resolve(request.result);
          request.onerror = () => reject(request.error);
        });
        
        if (entry) {
          // Cache in memory for future access
          contentCache.set(contentRef, entry);
          console.debug('[ContentStore] Loaded content from IndexedDB:', contentRef);
        }
      } catch (error) {
        console.warn('[ContentStore] Failed to load from IndexedDB:', error);
        return undefined;
      }
    }
    
    if (!entry) {
      return undefined;
    }
    
    // Decrypt the data using the master key
    const encryptedData = entry.data as string;
    const decryptedData = decryptWithMasterKey(encryptedData);
    
    if (!decryptedData) {
      console.warn('[ContentStore] Failed to decrypt content, returning encrypted data');
      return entry.data;
    }
    
    try {
      return JSON.parse(decryptedData);
    } catch (error) {
      console.error('[ContentStore] Error parsing decrypted data:', error);
      return decryptedData;
    }
  }
  
  /**
   * Ensure content exists in the store
   * @param contentRef - The content reference key
   * @param inlineContent - Optional inline content to store if missing
   */
  async ensure(contentRef: string, inlineContent?: any): Promise<void> {
    // TODO: Implement content existence checking and storage
    // This will call get() first, then put() if content is missing
    
    const existingContent = await this.get(contentRef);
    if (existingContent === undefined && inlineContent !== undefined) {
      // Store the inline content with a default type
      // The actual type should be determined during implementation
      await this.put(contentRef, inlineContent, 'text');
    }
    
    console.debug('[ContentStore] Ensure content:', contentRef);
  }
  
  /**
   * Subscribe to content changes
   * @param contentRef - The content reference key to monitor
   * @param callback - Function to call when content changes
   */
  subscribe(contentRef: string, callback: (data: any) => void): () => void {
    // TODO: Implement subscription mechanism
    // This will be filled in during later phases
    console.debug('[ContentStore] Subscribe to content:', contentRef);
    
    // Return unsubscribe function
    return () => {
      // TODO: Remove subscription
      console.debug('[ContentStore] Unsubscribe from content:', contentRef);
    };
  }
  
  /**
   * Rekey stream content to CID format
   * Finalizes content, computes SHA256 hash, and updates storage
   * @param streamKey - The stream key to rekey
   * @returns The new CID-based content reference
   */
  async rekeyStreamToCid(streamKey: string): Promise<string> {
    // TODO: Implement rekeying logic
    // Get content from stream key, compute hash, store under CID
    
    const entry = contentCache.get(streamKey);
    if (!entry) {
      throw new Error(`Content not found for stream key: ${streamKey}`);
    }
    
    // Get the decrypted content
    const content = await this.get(streamKey);
    if (content === undefined) {
      throw new Error(`Content not found for stream key: ${streamKey}`);
    }
    
    // Compute SHA256 hash of the content
    const contentString = typeof content === 'string' ? content : JSON.stringify(content);
    const hash = await computeSHA256(contentString);
    const cid = createContentId(hash);
    
    // Store content under new CID key
    await this.put(cid, content, entry.type);
    
    // Remove old stream key (optional, depending on requirements)
    contentCache.delete(streamKey);
    
    console.debug('[ContentStore] Rekeyed stream to CID:', streamKey, '->', cid);
    return cid;
  }
}

// Export singleton instance
export const contentStore = new ContentStore();
