// Client EmbedStore for the unified message parsing architecture
// Integrates with existing IndexedDB structure from db.ts and uses cryptoService for encryption

import { EmbedStoreEntry, EmbedType } from '../message_parsing/types';
import { computeSHA256, createContentId } from '../message_parsing/utils';
import { chatDB } from './db';
import { encryptWithMasterKey, decryptWithMasterKey } from './cryptoService';

// Embed store name for IndexedDB
const EMBEDS_STORE_NAME = 'embeds';

// In-memory cache for embeds (decrypted)
const embedCache = new Map<string, EmbedStoreEntry>();

export class EmbedStore {
  /**
   * Put embed into the store (encrypted)
   * @param contentRef - The embed reference key (e.g., embed:{embed_id})
   * @param data - The embed data to store (can be TOON string or object)
   * @param type - The type of embed content
   */
  async put(contentRef: string, data: any, type: EmbedType): Promise<void> {
    // For embeds, data.content might be a TOON string (store as-is for efficiency)
    // If data is an object with a 'content' field that's a string, preserve it as TOON
    let dataToStore = data;
    
    // If data has a 'content' field that's a string (TOON), keep it as string
    // Otherwise, stringify the entire object
    if (typeof data === 'object' && data !== null && typeof data.content === 'string') {
      // This is embed data with TOON content - store as-is (content stays as TOON string)
      dataToStore = data;
    } else if (typeof data === 'string') {
      // Already a string (TOON content) - wrap it for storage
      dataToStore = { content: data };
    }
    
    // Encrypt the data using the master key
    const dataString = JSON.stringify(dataToStore);
    const encryptedData = encryptWithMasterKey(dataString);
    
    if (!encryptedData) {
      console.warn('[EmbedStore] Master key not available, storing unencrypted data');
    }
    
    const entry: EmbedStoreEntry = {
      contentRef,
      data: encryptedData || dataString, // Fallback to unencrypted if master key not available
      type,
      createdAt: Date.now(),
      updatedAt: Date.now()
    };
    
    // Store in memory cache
    embedCache.set(contentRef, entry);
    
    try {
      // Store in IndexedDB
      const transaction = await chatDB.getTransaction([EMBEDS_STORE_NAME], 'readwrite');
      const store = transaction.objectStore(EMBEDS_STORE_NAME);
      
      await new Promise<void>((resolve, reject) => {
        const request = store.put(entry);
        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error);
      });
      
      console.debug('[EmbedStore] Put embed in IndexedDB:', contentRef, type);
    } catch (error) {
      console.warn('[EmbedStore] Failed to store in IndexedDB, using memory cache only:', error);
    }
  }
  
  /**
   * Get embed from the store (decrypted)
   * @param contentRef - The embed reference key to retrieve
   * @returns The stored embed data or undefined if not found
   */
  async get(contentRef: string): Promise<any> {
    // Check memory cache first
    let entry = embedCache.get(contentRef);
    
    // If not in cache, try to load from IndexedDB
    if (!entry) {
      try {
        const transaction = await chatDB.getTransaction([EMBEDS_STORE_NAME], 'readonly');
        const store = transaction.objectStore(EMBEDS_STORE_NAME);
        
        entry = await new Promise<EmbedStoreEntry | undefined>((resolve, reject) => {
          const request = store.get(contentRef);
          request.onsuccess = () => resolve(request.result);
          request.onerror = () => reject(request.error);
        });
        
        if (entry) {
          // Cache in memory for future access
          embedCache.set(contentRef, entry);
          console.debug('[EmbedStore] Loaded embed from IndexedDB:', contentRef);
        }
      } catch (error) {
        console.warn('[EmbedStore] Failed to load from IndexedDB:', error);
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
      console.warn('[EmbedStore] Failed to decrypt embed, returning encrypted data');
      return entry.data;
    }
    
    try {
      const parsed = JSON.parse(decryptedData);
      
      // If this is embed data with TOON content, return as-is
      // Content will be decoded when needed (by embedResolver)
      if (parsed && typeof parsed.content === 'string') {
        // This is embed data with TOON content - return as-is
        // The TOON string will be decoded by embedResolver when needed
        return parsed;
      }
      
      return parsed;
    } catch (error) {
      console.error('[EmbedStore] Error parsing decrypted data:', error);
      return decryptedData;
    }
  }
  
  /**
   * Ensure embed exists in the store
   * @param contentRef - The embed reference key
   * @param inlineContent - Optional inline content to store if missing
   */
  async ensure(contentRef: string, inlineContent?: any): Promise<void> {
    // TODO: Implement embed existence checking and storage
    // This will call get() first, then put() if embed is missing
    
    const existingEmbed = await this.get(contentRef);
    if (existingEmbed === undefined && inlineContent !== undefined) {
      // Store the inline content with a default type
      // The actual type should be determined during implementation
      await this.put(contentRef, inlineContent, 'text');
    }
    
    console.debug('[EmbedStore] Ensure embed:', contentRef);
  }
  
  /**
   * Subscribe to embed changes
   * @param contentRef - The embed reference key to monitor
   * @param callback - Function to call when embed changes
   */
  subscribe(contentRef: string, callback: (data: any) => void): () => void {
    // TODO: Implement subscription mechanism
    // This will be filled in during later phases
    console.debug('[EmbedStore] Subscribe to embed:', contentRef);
    
    // Return unsubscribe function
    return () => {
      // TODO: Remove subscription
      console.debug('[EmbedStore] Unsubscribe from embed:', contentRef);
    };
  }
  
  /**
   * Rekey stream content to CID format
   * Finalizes embed content, computes SHA256 hash, and updates storage
   * @param streamKey - The stream key to rekey
   * @returns The new CID-based embed reference
   */
  async rekeyStreamToCid(streamKey: string): Promise<string> {
    // TODO: Implement rekeying logic
    // Get embed from stream key, compute hash, store under CID
    
    const entry = embedCache.get(streamKey);
    if (!entry) {
      throw new Error(`Embed not found for stream key: ${streamKey}`);
    }
    
    // Get the decrypted embed
    const embed = await this.get(streamKey);
    if (embed === undefined) {
      throw new Error(`Embed not found for stream key: ${streamKey}`);
    }
    
    // Compute SHA256 hash of the embed content
    const embedString = typeof embed === 'string' ? embed : JSON.stringify(embed);
    const hash = await computeSHA256(embedString);
    const cid = createContentId(hash);
    
    // Store embed under new CID key
    await this.put(cid, embed, entry.type);
    
    // Remove old stream key (optional, depending on requirements)
    embedCache.delete(streamKey);
    
    console.debug('[EmbedStore] Rekeyed stream to CID:', streamKey, '->', cid);
    return cid;
  }
}

// Export singleton instance
export const embedStore = new EmbedStore();

