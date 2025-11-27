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
   * Use this for NEW embeds that need encryption (e.g., from send_embed_data with plaintext TOON)
   * @param contentRef - The embed reference key (e.g., embed:{embed_id})
   * @param data - The embed data to store (can be TOON string or object)
   * @param type - The type of embed content
   */
  async put(contentRef: string, data: any, type: EmbedType): Promise<void> {
    // DEBUG: Check if data itself is a Promise
    if (data instanceof Promise) {
      console.error('[EmbedStore] ERROR: data parameter is a Promise!', {
        contentRef,
        type,
        dataType: typeof data
      });
      throw new Error('EmbedStore.put() received a Promise as data parameter');
    }

    // DEBUG: Check if data is an object and inspect its fields for Promises
    if (typeof data === 'object' && data !== null) {
      for (const [key, value] of Object.entries(data)) {
        if (value instanceof Promise) {
          console.error(`[EmbedStore] ERROR: data.${key} is a Promise!`, {
            contentRef,
            key,
            value
          });
          throw new Error(`EmbedStore.put() received data with Promise in field: ${key}`);
        }
      }
    }

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

    // CRITICAL: Verify dataString is actually a string before encrypting
    if (typeof dataString !== 'string') {
      console.error('[EmbedStore] JSON.stringify did not return a string!', {
        type: typeof dataString,
        value: dataString
      });
      throw new Error(`JSON.stringify returned ${typeof dataString} instead of string`);
    }

    const encryptedData = await encryptWithMasterKey(dataString);

    // CRITICAL: Verify encryptedData is either a string or null (not a Promise or other type)
    if (encryptedData !== null && typeof encryptedData !== 'string') {
      console.error('[EmbedStore] encryptWithMasterKey returned unexpected type!', {
        type: typeof encryptedData,
        isPromise: (encryptedData as any) instanceof Promise,
        value: encryptedData
      });
      throw new Error(`encryptWithMasterKey returned ${typeof encryptedData} instead of string or null`);
    }

    if (!encryptedData) {
      console.warn('[EmbedStore] Master key not available, storing unencrypted data');
    }

    const entry: EmbedStoreEntry = {
      contentRef,
      // Always store a plain string (either encrypted or plaintext) to avoid IndexedDB cloning errors
      data: encryptedData || dataString,
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
   * Put embed into the store WITHOUT encryption (for synced embeds already client-encrypted)
   * Use this for embeds from sync that are already encrypted (same pattern as messages)
   * @param contentRef - The embed reference key (e.g., embed:{embed_id})
   * @param encryptedData - The already-encrypted embed data object
   * @param type - The type of embed content
   */
  async putEncrypted(contentRef: string, encryptedData: any, type: EmbedType): Promise<void> {
    // Store the encrypted data directly without re-encrypting
    // This matches the pattern used for messages during sync
    const dataString = JSON.stringify(encryptedData);
    
    const entry: EmbedStoreEntry = {
      contentRef,
      // Store encrypted data as-is (already client-encrypted from Directus)
      data: dataString,
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

      console.debug('[EmbedStore] Put encrypted embed in IndexedDB (no re-encryption):', contentRef, type);
    } catch (error) {
      console.warn('[EmbedStore] Failed to store encrypted embed in IndexedDB, using memory cache only:', error);
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
    
    // Handle two storage formats:
    // 1. put(): Stores encrypted JSON string (encrypted by embedStore)
    // 2. putEncrypted(): Stores plain JSON string with encrypted_content field (already encrypted from sync)
    let storedData = entry.data;

    // CRITICAL: Ensure storedData is not a Promise
    if (storedData instanceof Promise) {
      console.warn('[EmbedStore] Stored data is a Promise, awaiting resolution');
      storedData = await storedData;
    }

    if (typeof storedData !== 'string') {
      console.warn('[EmbedStore] Stored embed is not a string; returning as-is');
      return storedData as any;
    }

    // Helper function to check if a string is valid base64
    const isValidBase64 = (str: string): boolean => {
      try {
        // Base64 strings should only contain A-Z, a-z, 0-9, +, /, and = for padding
        // They should also have a length that's a multiple of 4 (after padding)
        const base64Regex = /^[A-Za-z0-9+/]*={0,2}$/;
        if (!base64Regex.test(str)) {
          return false;
        }
        // Try to decode it - if it fails, it's not valid base64
        window.atob(str);
        return true;
      } catch {
        return false;
      }
    };

    // Try to decrypt first (for embeds stored via put())
    // But only if the stored data looks like base64 (encrypted data)
    // If it's plain JSON (from putEncrypted), skip decryption attempt
    let decryptedData: string | null = null;
    let parsed: any;
    
    // Check if storedData looks like encrypted base64 or plain JSON
    const looksLikeBase64 = isValidBase64(storedData);
    const looksLikeJSON = storedData.trim().startsWith('{') || storedData.trim().startsWith('[');
    
    if (looksLikeBase64 && !looksLikeJSON) {
      // Looks like encrypted data - try to decrypt
      try {
        decryptedData = await decryptWithMasterKey(storedData);
      } catch (error) {
        // Decryption failed - might be invalid base64 or wrong key
        console.debug('[EmbedStore] Decryption attempt failed (might be plain JSON):', error);
        decryptedData = null;
      }
    }
    
    if (decryptedData) {
      // Successfully decrypted - this was stored via put() (encrypted by embedStore)
      try {
        parsed = JSON.parse(decryptedData);
      } catch (error) {
        console.error('[EmbedStore] Error parsing decrypted data:', error);
        return decryptedData;
      }
    } else {
      // Decryption failed or skipped - this might be stored via putEncrypted() (plain JSON with encrypted fields)
      try {
        parsed = JSON.parse(storedData);
      } catch (error) {
        console.error('[EmbedStore] Error parsing stored data as JSON:', error);
        return storedData;
      }
      
      // If parsed object has encrypted_content, decrypt it now
      if (parsed && parsed.encrypted_content && typeof parsed.encrypted_content === 'string') {
        try {
          const decryptedContent = await decryptWithMasterKey(parsed.encrypted_content);
          if (decryptedContent) {
            parsed.content = decryptedContent;
            // Keep encrypted_content for reference but content is now decrypted
          } else {
            console.warn('[EmbedStore] Failed to decrypt encrypted_content field');
          }
        } catch (error) {
          console.warn('[EmbedStore] Error decrypting encrypted_content field:', error);
        }
      }
      
      // If parsed object has encrypted_type, decrypt it
      if (parsed && parsed.encrypted_type && typeof parsed.encrypted_type === 'string') {
        const decryptedType = await decryptWithMasterKey(parsed.encrypted_type);
        if (decryptedType) {
          parsed.type = decryptedType;
          parsed.embed_type = decryptedType;
        }
      }
    }

    // If this is embed data with TOON content, return as-is
    // Content will be decoded when needed (by embedResolver)
    if (parsed && typeof parsed.content === 'string') {
      // This is embed data with TOON content - return as-is
      // The TOON string will be decoded by embedResolver when needed
      return parsed;
    }

    return parsed;
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
