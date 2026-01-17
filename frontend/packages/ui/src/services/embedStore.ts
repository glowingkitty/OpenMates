// Client EmbedStore for the unified message parsing architecture
// Integrates with existing IndexedDB structure from db.ts and uses cryptoService for encryption
//
// Wrapped Key Architecture:
// Each embed has a unique embed_key that encrypts its content. The embed_key is stored
// in multiple wrapped forms in the embed_keys collection (similar to master key for login methods):
// - key_type="master": AES(embed_key, master_key) - for owner's cross-chat access
// - key_type="chat": AES(embed_key, chat_key) - one per chat for shared chat access
//
// This enables offline-first chat sharing: all wrapped keys are pre-stored on server

import { EmbedStoreEntry, EmbedType } from '../message_parsing/types';
import { computeSHA256, createContentId } from '../message_parsing/utils';
import { chatDB } from './db';
import {
  encryptWithMasterKey,
  decryptWithMasterKey,
  generateEmbedKey,
  wrapEmbedKeyWithMasterKey,
  wrapEmbedKeyWithChatKey,
  unwrapEmbedKeyWithMasterKey,
  unwrapEmbedKeyWithChatKey,
  encryptWithEmbedKey,
  decryptWithEmbedKey
} from './cryptoService';

// Embed store name for IndexedDB
const EMBEDS_STORE_NAME = 'embeds';

// Embed keys store name for IndexedDB (stores wrapped embed keys)
const EMBED_KEYS_STORE_NAME = 'embed_keys';

// In-memory cache for embeds (decrypted)
const embedCache = new Map<string, EmbedStoreEntry>();

// In-memory cache for unwrapped embed keys (for performance)
const embedKeyCache = new Map<string, Uint8Array>();

// TOON decoder (lazy-loaded to avoid circular dependencies)
let toonDecode: ((toonString: string) => any) | null = null;

/**
 * Initialize TOON decoder (lazy-loaded)
 */
async function initToonDecoder() {
  if (!toonDecode) {
    try {
      const toonModule = await import('@toon-format/toon');
      toonDecode = toonModule.decode;
      console.debug('[EmbedStore] TOON decoder initialized');
    } catch (error) {
      console.warn('[EmbedStore] TOON decoder not available, will use JSON fallback:', error);
    }
  }
}

/**
 * Decode TOON content to JavaScript object
 * This is a local implementation to avoid circular dependencies with embedResolver
 */
async function decodeToonContentLocal(toonContent: string | null | undefined): Promise<any> {
  if (!toonContent) {
    return null;
  }
  
  if (typeof toonContent !== 'string') {
    if (typeof toonContent === 'object') {
      return toonContent;
    }
    return null;
  }
  
  await initToonDecoder();
  
  if (toonDecode) {
    try {
      return toonDecode(toonContent);
    } catch (error) {
      console.debug('[EmbedStore] TOON decode failed, trying JSON fallback:', error);
      try {
        return JSON.parse(toonContent);
      } catch (jsonError) {
        console.error('[EmbedStore] JSON fallback also failed:', jsonError);
        return null;
      }
    }
  } else {
    // Fallback to JSON parsing if TOON decoder not available
    try {
      return JSON.parse(toonContent);
    } catch (error) {
      console.error('[EmbedStore] Error parsing content as JSON:', error);
      return null;
    }
  }
}

/**
 * Interface for embed key entries stored in embed_keys collection
 */
export interface EmbedKeyEntry {
  hashed_embed_id: string;
  key_type: 'master' | 'chat';
  hashed_chat_id: string | null;
  encrypted_embed_key: string;
  hashed_user_id: string;
  created_at: number;
}

export class EmbedStore {
  private normalizeEmbedType(type: string): EmbedType {
    // Normalize server embed types to the UI embed types used throughout the frontend.
    // This prevents mismatches like "app_skill_use" vs "app-skill-use" and "code" vs "code-code".
    switch (type) {
      case 'app_skill_use':
        return 'app-skill-use' as EmbedType;
      case 'website':
        return 'web-website' as EmbedType;
      case 'video':
        return 'videos-video' as EmbedType;
      case 'code':
        return 'code-code' as EmbedType;
      default:
        return type as EmbedType;
    }
  }
  
  /**
   * Extract app_id and skill_id from embed content (for app_skill_use embeds)
   * This extracts metadata from TOON content to enable efficient filtering in IndexedDB
   * @param content - The TOON-encoded content string or already-decoded object
   * @param type - The embed type
   * @returns Object with app_id and skill_id if found, undefined otherwise
   */
  private async extractAppMetadata(content: any, type: EmbedType): Promise<{ app_id?: string; skill_id?: string }> {
    // Only extract for app_skill_use embeds (handle both hyphen and underscore)
    const isAppSkillUse = type === 'app-skill-use' || type === 'app_skill_use';
    if (!isAppSkillUse) {
      return {};
    }

    try {
      let decodedContent: any = null;
      
      // If content is a string, try to decode it as TOON
      if (typeof content === 'string') {
        decodedContent = await decodeToonContentLocal(content);
      } else if (typeof content === 'object' && content !== null) {
        // If content is an object, check if it has a 'content' field that's a TOON string
        if (content.content && typeof content.content === 'string') {
          decodedContent = await decodeToonContentLocal(content.content);
        } else {
          // Content might already be decoded
          decodedContent = content;
        }
      }

      // Extract app_id and skill_id from decoded content
      if (decodedContent && typeof decodedContent === 'object') {
        const app_id = decodedContent.app_id;
        const skill_id = decodedContent.skill_id;
        
        if (app_id || skill_id) {
          return {
            app_id: typeof app_id === 'string' ? app_id : undefined,
            skill_id: typeof skill_id === 'string' ? skill_id : undefined
          };
        }
      }
    } catch (error) {
      // If extraction fails, that's okay - we'll just not have the metadata
      // This can happen if content is encrypted or in an unexpected format
      console.debug('[EmbedStore] Could not extract app metadata from content:', error);
    }

    return {};
  }

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

    // Extract app_id and skill_id from content (for app_skill_use embeds)
    // This metadata is stored unencrypted in IndexedDB only, not sent to server
    // This enables efficient filtering without decrypting all embeds
    const appMetadata = await this.extractAppMetadata(dataToStore, type);

    // Store fields separately instead of JSON string in data field
    // CRITICAL FIX: DO NOT set encrypted_content here - that field is reserved for embed-key encryption
    // used by putEncrypted(). The put() method uses master-key encryption stored in the `data` field.
    // If encrypted_content is set, getFromSeparateFields() will try to decrypt with embed key and fail!
    const entry: EmbedStoreEntry = {
      contentRef,
      // Master-key encrypted data stored in `data` field
      // The get() method's old format path handles decryption with master key
      data: encryptedData || dataString,
      
      type,
      createdAt: Date.now(), // For put(), we don't have server timestamps
      updatedAt: Date.now(),
      
      // Store app metadata unencrypted in IndexedDB only (for efficient querying)
      app_id: appMetadata.app_id,
      skill_id: appMetadata.skill_id
      
      // NOTE: encrypted_content is intentionally NOT set here
      // encrypted_content is only for embed-key encryption (used by putEncrypted)
      
      // Hybrid Encryption Mode
      encryption_mode: data.encryption_mode || 'client',
      vault_key_id: data.vault_key_id
    };

    // Store in memory cache
    embedCache.set(contentRef, entry);
    console.debug('[EmbedStore] ✅ Stored embed in memory cache:', contentRef, { 
      type, 
      dataLength: entry.data?.length || 0,
      wasEncrypted: !!encryptedData 
    });

    try {
      // Store in IndexedDB
      const transaction = await chatDB.getTransaction([EMBEDS_STORE_NAME], 'readwrite');
      const store = transaction.objectStore(EMBEDS_STORE_NAME);

      await new Promise<void>((resolve, reject) => {
        const request = store.put(entry);
        request.onsuccess = () => {
          console.info('[EmbedStore] ✅ Successfully stored embed in IndexedDB:', contentRef, type);
          resolve();
        };
        request.onerror = () => {
          console.error('[EmbedStore] ❌ IndexedDB store.put failed:', contentRef, request.error);
          reject(request.error);
        };
      });
    } catch (error) {
      console.error('[EmbedStore] ❌ Failed to store in IndexedDB:', contentRef, error);
      console.warn('[EmbedStore] Using memory cache only for:', contentRef);
    }
  }
  
  /**
   * Put embed into the store WITHOUT encryption (for synced embeds already client-encrypted)
   * Use this for embeds from sync that are already encrypted (same pattern as messages)
   * 
   * NEW: Stores fields separately in IndexedDB instead of JSON string in data field
   * This enables better querying, indexing, and preserves server timestamps
   * 
   * @param contentRef - The embed reference key (e.g., embed:{embed_id})
   * @param encryptedData - The already-encrypted embed data object
   * @param type - The type of embed content
   * @param plaintextContent - Optional plaintext TOON content for extracting app_id/skill_id metadata
   *                          This should be provided when available to avoid needing to decrypt
   */
  async putEncrypted(
    contentRef: string,
    encryptedData: any,
    type: EmbedType,
    plaintextContent?: string,
    preExtractedMetadata?: { app_id?: string; skill_id?: string }
  ): Promise<void> {
    const normalizedType = this.normalizeEmbedType(type as unknown as string);
    
    // Extract app_id and skill_id from plaintext content if provided, otherwise try to decrypt
    // For app_skill_use embeds, we extract metadata to enable efficient filtering in IndexedDB
    let appMetadata: { app_id?: string; skill_id?: string } = {};
    
    if (normalizedType === 'app-skill-use' || normalizedType === 'app_skill_use') {
      try {
        // If metadata was already extracted upstream, trust it
        if (preExtractedMetadata?.app_id || preExtractedMetadata?.skill_id) {
          appMetadata = {
            app_id: preExtractedMetadata.app_id,
            skill_id: preExtractedMetadata.skill_id
          };
          console.debug('[EmbedStore] Using pre-extracted app metadata:', appMetadata);
        } else if (plaintextContent) {
          // Extract from plaintext content (preferred - no decryption needed)
          const decodedContent = await decodeToonContentLocal(plaintextContent);
          if (decodedContent && typeof decodedContent === 'object') {
            appMetadata = {
              app_id: typeof decodedContent.app_id === 'string' ? decodedContent.app_id : undefined,
              skill_id: typeof decodedContent.skill_id === 'string' ? decodedContent.skill_id : undefined
            };
            console.debug('[EmbedStore] Extracted app metadata from plaintext content:', appMetadata);
          }
        } else if (encryptedData.encrypted_content) {
          // Fallback: Try to decrypt content temporarily to extract app_id/skill_id
          // This is safe because we're only extracting metadata, not storing decrypted content
          const embedId = encryptedData.embed_id || contentRef.replace('embed:', '');
          const embedKey = await this.getEmbedKey(embedId, encryptedData.hashed_chat_id);
          
          if (embedKey) {
            const decryptedContent = await decryptWithEmbedKey(encryptedData.encrypted_content, embedKey);
            if (decryptedContent) {
              // Decode TOON content to extract app_id and skill_id
              const decodedContent = await decodeToonContentLocal(decryptedContent);
              if (decodedContent && typeof decodedContent === 'object') {
                appMetadata = {
                  app_id: typeof decodedContent.app_id === 'string' ? decodedContent.app_id : undefined,
                  skill_id: typeof decodedContent.skill_id === 'string' ? decodedContent.skill_id : undefined
                };
                console.debug('[EmbedStore] Extracted app metadata from decrypted content:', appMetadata);
              }
            }
          } else {
            console.debug('[EmbedStore] Embed key not available yet, will extract metadata later');
          }
        }
      } catch (error) {
        // If extraction fails, that's okay - we'll just not have the metadata
        // This can happen if content is in unexpected format
        console.debug('[EmbedStore] Could not extract app metadata:', error);
      }
    }
    
    // Extract server-provided timestamps if available, otherwise use current time
    // CRITICAL: Preserve server timestamps instead of overwriting with Date.now()
    const createdAt = encryptedData.createdAt ?? encryptedData.created_at ?? Date.now();
    const updatedAt = encryptedData.updatedAt ?? encryptedData.updated_at ?? Date.now();
    
    // Store fields separately instead of JSON string in data field
    // This enables better querying, indexing, and preserves server timestamps
    const entry: EmbedStoreEntry = {
      contentRef,
      // DEPRECATED: data field kept for backward compatibility during migration
      // New embeds should use separate fields below
      // data: undefined, // Don't store JSON string anymore
      
      type: normalizedType,
      createdAt, // Server-provided timestamp (preserved!)
      updatedAt, // Server-provided timestamp (preserved!)
      
      // Store app metadata unencrypted in IndexedDB only (for efficient querying)
      app_id: appMetadata.app_id,
      skill_id: appMetadata.skill_id,
      
      // Store all embed fields separately for clean data model
      embed_id: encryptedData.embed_id,
      encrypted_content: encryptedData.encrypted_content,
      encrypted_type: encryptedData.encrypted_type,
      encrypted_text_preview: encryptedData.encrypted_text_preview,
      status: encryptedData.status,
      hashed_chat_id: encryptedData.hashed_chat_id,
      hashed_message_id: encryptedData.hashed_message_id,
      hashed_task_id: encryptedData.hashed_task_id,
      hashed_user_id: encryptedData.hashed_user_id,
      embed_ids: encryptedData.embed_ids,
      parent_embed_id: encryptedData.parent_embed_id,
      version_number: encryptedData.version_number,
      file_path: encryptedData.file_path,
      content_hash: encryptedData.content_hash,
      text_length_chars: encryptedData.text_length_chars,
      is_private: encryptedData.is_private ?? false,
      is_shared: encryptedData.is_shared ?? false,
      
      // Hybrid Encryption Mode
      encryption_mode: (preExtractedMetadata as any)?.encryption_mode || 'client',
      vault_key_id: (preExtractedMetadata as any)?.vault_key_id
    };

    // Store in memory cache
    embedCache.set(contentRef, entry);

    try {
      // Store in IndexedDB
      const transaction = await chatDB.getTransaction([EMBEDS_STORE_NAME], 'readwrite');
      const store = transaction.objectStore(EMBEDS_STORE_NAME);

      await new Promise<void>((resolve, reject) => {
        const request = store.put(entry);
        request.onsuccess = () => {
          console.info('[EmbedStore] ✅ Successfully stored encrypted embed in IndexedDB:', contentRef, { type: normalizedType, hasEmbedId: !!encryptedData.embed_id });
          resolve();
        };
        request.onerror = () => reject(request.error);
      });
    } catch (error) {
      console.warn('[EmbedStore] Failed to store encrypted embed in IndexedDB, using memory cache only:', error);
    }
  }

  /**
   * Reconstruct embed object from separate fields (new format)
   * @param entry - The EmbedStoreEntry with separate fields
   * @param contentRef - The embed reference key
   * @returns The reconstructed embed object with decrypted content
   */
  private async getFromSeparateFields(entry: EmbedStoreEntry, contentRef: string): Promise<any> {
    // Reconstruct embed object from separate fields
    const embed: any = {
      embed_id: entry.embed_id,
      status: entry.status,
      hashed_chat_id: entry.hashed_chat_id,
      hashed_message_id: entry.hashed_message_id,
      hashed_task_id: entry.hashed_task_id,
      hashed_user_id: entry.hashed_user_id,
      embed_ids: entry.embed_ids,
      parent_embed_id: entry.parent_embed_id,
      version_number: entry.version_number,
      file_path: entry.file_path,
      content_hash: entry.content_hash,
      text_length_chars: entry.text_length_chars,
      is_private: entry.is_private ?? false,
      is_shared: entry.is_shared ?? false,
      createdAt: entry.createdAt,
      updatedAt: entry.updatedAt
    };

    // Decrypt encrypted_content if present (embed_key encryption)
    if (entry.encrypted_content) {
      try {
        const embedId = entry.embed_id || contentRef.replace('embed:', '');
        console.debug('[EmbedStore] Attempting to decrypt encrypted_content for:', embedId, {
          hasHashedChatId: !!entry.hashed_chat_id,
          encryptedContentLength: entry.encrypted_content?.length || 0,
          encryptedContentPreview: entry.encrypted_content?.substring(0, 50) + '...'
        });
        
        const embedKey = await this.getEmbedKey(embedId, entry.hashed_chat_id);
        
        if (embedKey) {
          console.debug('[EmbedStore] Found embed key, attempting decryption:', {
            embedId,
            keyLength: embedKey.length,
            encryptedContentLength: entry.encrypted_content.length
          });
          
          // Clean the base64 string before decryption (remove whitespace, URL decode if needed)
          let cleanedContent = entry.encrypted_content.trim();
          try {
            cleanedContent = decodeURIComponent(cleanedContent);
          } catch {
            // Not URL-encoded, use as-is
          }
          
          const decryptedContent = await decryptWithEmbedKey(cleanedContent, embedKey);
          if (decryptedContent) {
            embed.content = decryptedContent;
            console.debug('[EmbedStore] ✅ Successfully decrypted embed content from separate fields:', embedId);
          } else {
            console.warn('[EmbedStore] ❌ Failed to decrypt encrypted_content from separate fields - decryptWithEmbedKey returned null');
            embed._decryptionFailed = true;
            embed.status = 'error';
            embed.content = null;
          }
        } else {
          console.warn('[EmbedStore] No embed key found for separate fields format:', embedId, {
            hashedChatId: entry.hashed_chat_id?.substring(0, 16) + '...'
          });
          embed._decryptionFailed = true;
          embed.status = 'error';
          embed.content = null;
        }
      } catch (error) {
        console.warn('[EmbedStore] Error decrypting encrypted_content from separate fields:', error);
        embed._decryptionFailed = true;
        embed.status = 'error';
        embed.content = null;
      }
    } else if (entry.data) {
      // Fallback: If encrypted_content not set but data is, try old format decryption
      // This handles embeds stored via put() (master-key encrypted)
      try {
        const decryptedData = await decryptWithMasterKey(entry.data);
        if (decryptedData) {
          const parsed = JSON.parse(decryptedData);
          embed.content = parsed.content || parsed;
        }
      } catch (error) {
        console.debug('[EmbedStore] Could not decrypt data field as master-key encrypted:', error);
      }
    }

    // Decrypt encrypted_type if present
    if (entry.encrypted_type) {
      try {
        const embedId = entry.embed_id || contentRef.replace('embed:', '');
        const embedKey = await this.getEmbedKey(embedId, entry.hashed_chat_id);
        
        if (embedKey) {
          const decryptedType = await decryptWithEmbedKey(entry.encrypted_type, embedKey);
          if (decryptedType) {
            embed.type = decryptedType;
            embed.embed_type = decryptedType;
          }
        }
      } catch (error) {
        console.debug('[EmbedStore] Error decrypting encrypted_type from separate fields:', error);
      }
    }

    // Decrypt encrypted_text_preview if present
    if (entry.encrypted_text_preview) {
      try {
        const embedId = entry.embed_id || contentRef.replace('embed:', '');
        const embedKey = await this.getEmbedKey(embedId, entry.hashed_chat_id);
        
        if (embedKey) {
          const decryptedPreview = await decryptWithEmbedKey(entry.encrypted_text_preview, embedKey);
          if (decryptedPreview) {
            embed.text_preview = decryptedPreview;
          }
        }
      } catch (error) {
        console.debug('[EmbedStore] Error decrypting encrypted_text_preview from separate fields:', error);
      }
    }

    // Set type from entry if not decrypted
    if (!embed.type && !embed.embed_type) {
      embed.type = entry.type;
      embed.embed_type = entry.type;
    }

    return embed;
  }

  /**
   * Get embed from the store (decrypted)
   * @param contentRef - The embed reference key to retrieve
   * @returns The stored embed data or undefined if not found
   */
  async get(contentRef: string): Promise<any> {
    console.debug('[EmbedStore] get() called for:', contentRef);
    
    // Check memory cache first
    let entry = embedCache.get(contentRef);
    if (entry) {
      console.debug('[EmbedStore] Found in memory cache:', contentRef);
    }
    
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
        } else {
          // DEBUG: Log when embed is not found to help diagnose sync issues
          console.warn('[EmbedStore] Embed not found in IndexedDB:', contentRef);
          // Try to list all embeds to see what's actually stored
          try {
            const allEntries = await new Promise<EmbedStoreEntry[]>((resolve, reject) => {
              const request = store.getAll();
              request.onsuccess = () => resolve(request.result || []);
              request.onerror = () => reject(request.error);
            });
            console.debug('[EmbedStore] Total embeds in IndexedDB:', allEntries.length);
            if (allEntries.length > 0) {
              console.debug('[EmbedStore] Sample embed keys:', allEntries.slice(0, 5).map(e => e.contentRef));
            }
          } catch (listError) {
            console.warn('[EmbedStore] Failed to list embeds:', listError);
          }
        }
      } catch (error) {
        console.warn('[EmbedStore] Failed to load from IndexedDB:', error);
        return undefined;
      }
    }
    
    if (!entry) {
      return undefined;
    }
    
    // NEW FORMAT: Check if entry has separate fields (new clean data model)
    // If entry has encrypted_content as separate field, reconstruct from separate fields
    if (entry.encrypted_content !== undefined || (entry.embed_id && !entry.data)) {
      console.debug('[EmbedStore] Loading embed from new format (separate fields):', contentRef);
      return await this.getFromSeparateFields(entry, contentRef);
    }
    
    // OLD FORMAT: Fall back to legacy JSON string in data field (backward compatibility)
    // Handle two legacy storage formats:
    // 1. put(): Stores encrypted JSON string (encrypted by embedStore with master key)
    // 2. putEncrypted(): Stores plain JSON string with encrypted_content field (already encrypted from sync)
    let storedData = entry.data;

    // CRITICAL: Ensure storedData is not a Promise
    if (storedData instanceof Promise) {
      console.warn('[EmbedStore] Stored data is a Promise, awaiting resolution');
      storedData = await storedData;
    }

    if (!storedData) {
      console.warn('[EmbedStore] Entry has no data field and no separate fields');
      return undefined;
    }

    if (typeof storedData !== 'string') {
      // Memory-only entries (from setInMemoryOnly) store data as objects directly
      // This is expected behavior for "processing" embeds that need immediate rendering
      console.debug('[EmbedStore] ✅ Returning memory-only embed data (not encrypted):', contentRef, {
        type: storedData?.type,
        skill_id: storedData?.skill_id,
        status: storedData?.status
      });
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
      
      // If parsed object has encrypted_content, decrypt using embed key
      // The embed key is obtained from embed_keys collection (wrapped with master key or chat key)
      if (parsed && parsed.encrypted_content && typeof parsed.encrypted_content === 'string') {
        // Validate encrypted_content is not empty
        if (parsed.encrypted_content.trim().length === 0) {
          console.warn('[EmbedStore] encrypted_content is empty, cannot decrypt');
          parsed._decryptionFailed = true;
          parsed.status = 'error';
          parsed.content = null;
        } else {
          let decryptionFailed = false;
          try {
            // Get the embed_id to look up embed key
            const embedId = parsed.embed_id || contentRef.replace('embed:', '');
            
            // Try to get the unwrapped embed key
            let embedKey = await this.getEmbedKey(embedId, parsed.hashed_chat_id);
            
            if (embedKey) {
              // Decrypt content with embed key
              console.debug('[EmbedStore] Attempting decrypt with embed key:', {
                embedId,
                keyLength: embedKey.length,
                contentLength: parsed.encrypted_content?.length || 0,
                contentPreview: parsed.encrypted_content.substring(0, 50) + '...'
              });
              const decryptedContent = await decryptWithEmbedKey(parsed.encrypted_content, embedKey);
              if (decryptedContent) {
                parsed.content = decryptedContent;
                console.debug('[EmbedStore] ✅ Successfully decrypted embed content with embed key:', embedId);
              } else {
                console.warn('[EmbedStore] ❌ Failed to decrypt encrypted_content with embed key - decrypt returned null');
                decryptionFailed = true;
              }
            } else {
              console.warn('[EmbedStore] No embed key found for:', embedId);
              decryptionFailed = true;
            }
          } catch (error) {
            console.warn('[EmbedStore] Error decrypting encrypted_content field:', error);
            decryptionFailed = true;
          }
          
          // CRITICAL: If decryption failed, set a flag so UI can show error state instead of crashing
          // This prevents crashes when embed keys are missing (e.g., not synced yet)
          if (decryptionFailed && !parsed.content) {
            parsed._decryptionFailed = true;
            parsed.status = 'error';
            // Provide minimal content to prevent crashes in TOON decoder
            parsed.content = null;
            console.warn('[EmbedStore] Embed decryption failed, setting error status for:', contentRef);
          }
        }
      }
      
      // If parsed object has encrypted_type, decrypt using embed key
      if (parsed && parsed.encrypted_type && typeof parsed.encrypted_type === 'string') {
        try {
          const embedId = parsed.embed_id || contentRef.replace('embed:', '');
          let embedKey = await this.getEmbedKey(embedId, parsed.hashed_chat_id);
          
          if (embedKey) {
            const decryptedType = await decryptWithEmbedKey(parsed.encrypted_type, embedKey);
            if (decryptedType) {
              parsed.type = decryptedType;
              parsed.embed_type = decryptedType;
              console.debug('[EmbedStore] Successfully decrypted embed type with embed key:', embedId);
            }
          }
          // If type decryption fails, use a default type to prevent crashes
          if (!parsed.type && !parsed.embed_type) {
            parsed.type = 'unknown';
            parsed.embed_type = 'unknown';
          }
        } catch (error) {
          console.warn('[EmbedStore] Error decrypting encrypted_type field:', error);
          // Set default type to prevent crashes
          if (!parsed.type && !parsed.embed_type) {
            parsed.type = 'unknown';
            parsed.embed_type = 'unknown';
          }
        }
      }
    }

    // If this is embed data with TOON content, return as-is
    // Content will be decoded when needed (by embedResolver)
    if (parsed && typeof parsed.content === 'string') {
      // This is embed data with TOON content - return as-is
      // The TOON string will be decoded by embedResolver when needed
      console.debug('[EmbedStore] Returning embed with TOON content:', contentRef, { hasContent: true, hasEmbedId: !!parsed.embed_id });
      return parsed;
    }

    // CRITICAL: Even if decryption failed, return the parsed object with error flag
    // This allows the UI to show an error state instead of crashing
    if (parsed) {
      console.debug('[EmbedStore] Returning embed (may have decryption errors):', contentRef, { 
        hasEmbedId: !!parsed.embed_id, 
        hasContent: !!parsed.content,
        decryptionFailed: !!parsed._decryptionFailed,
        status: parsed.status 
      });
      return parsed;
    }

    // If we get here, something went wrong - log it
    console.warn('[EmbedStore] Failed to parse embed data, returning undefined:', contentRef);
    return undefined;
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
   * Store embed data in memory cache ONLY (not persisted to IndexedDB)
   * Used for "processing" embeds that need to be rendered before finalization
   * This allows `resolveEmbed()` to find the embed data during streaming
   * @param contentRef - The embed reference key (e.g., embed:{embed_id})
   * @param embedData - The embed data object (plaintext)
   */
  setInMemoryOnly(contentRef: string, embedData: any): void {
    // CRITICAL FIX: Store the embed data as an OBJECT (not JSON string) so that
    // get() can detect it's not encrypted and return it directly.
    // When get() sees typeof storedData !== 'string', it returns the data as-is.
    // This is essential for "processing" embeds that need immediate rendering.
    const entry: EmbedStoreEntry = {
      contentRef,
      type: this.normalizeEmbedType(embedData.type || 'unknown') as EmbedType,
      data: embedData, // Store as object directly - NOT stringified!
      createdAt: embedData.createdAt || Date.now(),
      updatedAt: embedData.updatedAt || Date.now(),
      // Copy additional fields that might be present (for getRawEntry)
      embed_id: embedData.embed_id,
      status: embedData.status,
      parent_embed_id: embedData.parent_embed_id,
      embed_ids: embedData.embed_ids,
    };
    
    embedCache.set(contentRef, entry);
    console.info('[EmbedStore] 🔄 Set embed in memory cache only (not persisted):', contentRef, {
      type: entry.type,
      status: embedData.status,
      skill_id: embedData.skill_id,
      app_id: embedData.app_id,
      query: embedData.query?.substring(0, 30),
      hasContent: !!embedData.content
    });
  }
  
  /**
   * Get raw embed entry from IndexedDB/cache WITHOUT decryption
   * This is used internally to check for parent_embed_id and embed_ids without triggering decryption
   * (which would call getEmbedKey and cause infinite recursion)
   * @param contentRef - The embed reference key
   * @returns The raw stored data (may be encrypted) with parent_embed_id and embed_ids if present
   */
  async getRawEntry(contentRef: string): Promise<{ parent_embed_id?: string; embed_ids?: string[] } | null> {
    // Check memory cache first
    let entry = embedCache.get(contentRef);
    
    // If not in cache, try IndexedDB
    if (!entry) {
      try {
        const transaction = await chatDB.getTransaction([EMBEDS_STORE_NAME], 'readonly');
        const store = transaction.objectStore(EMBEDS_STORE_NAME);
        
        entry = await new Promise<EmbedStoreEntry | undefined>((resolve, reject) => {
          const request = store.get(contentRef);
          request.onsuccess = () => resolve(request.result);
          request.onerror = () => reject(request.error);
        });
      } catch (error) {
        console.debug('[EmbedStore] getRawEntry failed to load from IndexedDB:', error);
        return null;
      }
    }
    
    if (!entry) {
      return null;
    }
    
    // For new format (separate fields), check parent_embed_id and embed_ids directly from entry
    // Always check parent_embed_id first (for child embeds), then embed_ids (for parent embeds)
    if (entry.parent_embed_id !== undefined || entry.embed_ids !== undefined) {
      return {
        parent_embed_id: entry.parent_embed_id,
        embed_ids: Array.isArray(entry.embed_ids) ? entry.embed_ids : undefined
      };
    }
    
    // For old format (data field), try to parse
    if (!entry.data) {
      return null;
    }
    
    // Try to parse the stored data to extract parent_embed_id and embed_ids
    // This doesn't decrypt, just parses the JSON structure
    try {
      const storedData = entry.data;
      if (typeof storedData === 'string') {
        // Could be JSON or encrypted base64
        if (storedData.trim().startsWith('{')) {
          const parsed = JSON.parse(storedData);
          return {
            parent_embed_id: parsed.parent_embed_id,
            embed_ids: Array.isArray(parsed.embed_ids) ? parsed.embed_ids : undefined
          };
        }
      } else if (typeof storedData === 'object') {
        return {
          parent_embed_id: (storedData as any).parent_embed_id,
          embed_ids: Array.isArray((storedData as any).embed_ids) ? (storedData as any).embed_ids : undefined
        };
      }
    } catch {
      // Parsing failed, data might be encrypted
    }
    
    return null;
  }
  
  /**
   * Get the unwrapped embed key for an embed
   * Tries master key first (for owner), then chat key (for shared chat access)
   * For child embeds with parent_embed_id, falls back to parent's key (nested embed support)
   * @param embedId - The embed ID
   * @param hashedChatId - Optional hashed chat ID to try chat key unwrapping
   * @returns Promise<Uint8Array | null> - The unwrapped embed key or null
   */
  async getEmbedKey(embedId: string, hashedChatId?: string, visited: Set<string> = new Set()): Promise<Uint8Array | null> {
    const normalizedEmbedId = embedId.startsWith('embed:') ? embedId.slice('embed:'.length) : embedId;
    const contentRef = `embed:${normalizedEmbedId}`;

    if (visited.has(normalizedEmbedId)) {
      console.warn('[EmbedStore] Detected embed key lookup cycle, aborting:', embedId);
      return null;
    }
    visited.add(normalizedEmbedId);

    // Check cache first
    const cacheKey = `${normalizedEmbedId}:${hashedChatId || 'master'}`;
    if (embedKeyCache.has(cacheKey)) {
      const cachedKey = embedKeyCache.get(cacheKey)!;
      console.debug('[EmbedStore] ✅ Found embed key in cache:', normalizedEmbedId, 'cacheKey:', cacheKey);
      return cachedKey;
    }
    
    // Fallback: If hashedChatId was provided but cache lookup failed, try 'master' cache key
    if (hashedChatId) {
      const masterCacheKey = `${normalizedEmbedId}:master`;
      if (embedKeyCache.has(masterCacheKey)) {
        const masterKey = embedKeyCache.get(masterCacheKey)!;
        // Also cache it with the hashedChatId for future lookups
        embedKeyCache.set(cacheKey, masterKey);
        console.debug('[EmbedStore] Found embed key in master cache, also cached with hashedChatId:', normalizedEmbedId);
        return masterKey;
      }
    }
    
    // Debug: Log all cache keys to help diagnose cache misses
    console.debug('[EmbedStore] Cache miss for:', normalizedEmbedId, 'cacheKey:', cacheKey, 'hashedChatId:', hashedChatId);
    console.debug('[EmbedStore] Current cache keys:', Array.from(embedKeyCache.keys()).filter(k => k.startsWith(normalizedEmbedId + ':')));

    // Child embed support: child embeds inherit the parent's embed_key.
    // In shared chats, only the parent's wrapped key exists in embed_keys, so for child embeds
    // we must resolve the parent key and reuse it.
    try {
      const rawEntry = await this.getRawEntry(contentRef);
      const parentEmbedId = rawEntry?.parent_embed_id;
      if (parentEmbedId && parentEmbedId !== normalizedEmbedId) {
        const normalizedParentEmbedId = parentEmbedId.startsWith('embed:') ? parentEmbedId.slice('embed:'.length) : parentEmbedId;
        const parentKey = await this.getEmbedKey(normalizedParentEmbedId, hashedChatId, visited);
        if (parentKey) {
          embedKeyCache.set(cacheKey, parentKey);
          embedKeyCache.set(`${normalizedEmbedId}:master`, parentKey);
          console.debug('[EmbedStore] ✅ Reused parent embed key for child embed:', normalizedEmbedId, 'parent:', normalizedParentEmbedId);
          return parentKey;
        }
      }
    } catch (error) {
      console.debug('[EmbedStore] Child embed key fallback failed (will try direct keys):', error);
    }

    try {
      // Compute hashed_embed_id for lookup
      const hashedEmbedId = await computeSHA256(normalizedEmbedId);
      console.debug('[EmbedStore] Looking up embed keys with hashedEmbedId:', 
        hashedEmbedId.substring(0, 16) + '...', 'for embedId:', normalizedEmbedId);

      // Try to load embed keys from IndexedDB (ONLY for parent embeds)
      const keys = await this.getEmbedKeyEntries(hashedEmbedId);

      if (keys && keys.length > 0) {
        console.debug('[EmbedStore] Found', keys.length, 'embed key entries for:', embedId, 
          'types:', keys.map(k => k.key_type));
        
        // Try master key first (for owner access)
        const masterKeyEntry = keys.find(k => k.key_type === 'master');
        if (masterKeyEntry) {
          console.debug('[EmbedStore] Attempting master key unwrap for:', embedId);
          const embedKey = await unwrapEmbedKeyWithMasterKey(masterKeyEntry.encrypted_embed_key);
          if (embedKey) {
            embedKeyCache.set(cacheKey, embedKey);
            console.debug('[EmbedStore] ✅ Unwrapped embed key with master key:', embedId);
            return embedKey;
          } else {
            console.warn('[EmbedStore] ❌ Master key unwrap failed (returned null) for:', embedId);
          }
        } else {
          console.debug('[EmbedStore] No master key entry found for:', embedId);
        }

        // If master key failed and we have a hashed_chat_id, try chat key
        if (hashedChatId) {
          console.debug('[EmbedStore] Trying chat key unwrap with provided hashedChatId for:', embedId);
          const chatKeyEntry = keys.find(k => k.key_type === 'chat' && k.hashed_chat_id === hashedChatId);
          if (chatKeyEntry) {
            const embedKey = await this.unwrapChatKeyEntry(chatKeyEntry, hashedChatId);
            if (embedKey) {
              embedKeyCache.set(cacheKey, embedKey);
              console.debug('[EmbedStore] ✅ Unwrapped embed key with chat key (matched hashedChatId):', embedId);
              return embedKey;
            } else {
              console.warn('[EmbedStore] ❌ Chat key unwrap failed for:', embedId);
            }
          } else {
            console.debug('[EmbedStore] No matching chat key entry for hashedChatId:', hashedChatId?.substring(0, 16) + '...');
          }
        }

        // Try any available chat key entries as fallback
        const chatKeyEntries = keys.filter(k => k.key_type === 'chat');
        console.debug('[EmbedStore] Trying', chatKeyEntries.length, 'chat key entries as fallback for:', embedId);
        for (const entry of chatKeyEntries) {
          const embedKey = await this.unwrapChatKeyEntry(entry, entry.hashed_chat_id);
          if (embedKey) {
            embedKeyCache.set(cacheKey, embedKey);
            console.debug('[EmbedStore] ✅ Unwrapped embed key with fallback chat key:', embedId, 
              'keyLength:', embedKey.length);
            return embedKey;
          }
        }
        console.warn('[EmbedStore] ❌ All chat key fallback attempts failed for:', embedId);
      }

      // No direct key found - this should not happen for child embeds (they're handled at the start)
      // This path is only for parent embeds that couldn't unwrap their keys

      console.warn('[EmbedStore] Could not unwrap embed key (no valid key wrapper found and no parent key available):', embedId);
      return null;
    } catch (error) {
      console.error('[EmbedStore] Error getting embed key:', error);
      return null;
    }
  }

  /**
   * Helper method to unwrap a chat key entry
   * @param entry - The embed key entry to unwrap
   * @param hashedChatId - Optional hashed chat ID
   * @returns Promise<Uint8Array | null> - The unwrapped embed key or null
   */
  private async unwrapChatKeyEntry(entry: EmbedKeyEntry, hashedChatId?: string): Promise<Uint8Array | null> {
    if (!entry.hashed_chat_id) {
      return null;
    }

    try {
      const allChats = await chatDB.getAllChats();
      for (const chat of allChats) {
        const chatIdHash = await computeSHA256(chat.chat_id);
        if (chatIdHash === entry.hashed_chat_id) {
          const chatKey = chatDB.getChatKey(chat.chat_id);
          if (chatKey) {
            const embedKey = await unwrapEmbedKeyWithChatKey(entry.encrypted_embed_key, chatKey);
            if (embedKey) {
              return embedKey;
            }
          }
        }
      }
    } catch (error) {
      console.error('[EmbedStore] Error unwrapping chat key entry:', error);
    }

    return null;
  }

  /**
   * Get embed key entries from IndexedDB
   * @param hashedEmbedId - The hashed embed ID to look up
   * @returns Promise<EmbedKeyEntry[]> - Array of embed key entries
   */
  async getEmbedKeyEntries(hashedEmbedId: string): Promise<EmbedKeyEntry[]> {
    try {
      const transaction = await chatDB.getTransaction([EMBED_KEYS_STORE_NAME], 'readonly');
      const store = transaction.objectStore(EMBED_KEYS_STORE_NAME);
      const index = store.index('hashed_embed_id');
      
      const result = await new Promise<EmbedKeyEntry[]>((resolve, reject) => {
        const request = index.getAll(hashedEmbedId);
        request.onsuccess = () => resolve(request.result || []);
        request.onerror = () => reject(request.error);
      });
      
      // Debug: Log what we found
      if (result.length === 0) {
        console.warn('[EmbedStore] No embed key entries found for hashedEmbedId:', hashedEmbedId.substring(0, 16) + '...');
        // Debug: List all stored keys to see what's there
        try {
          const allKeys = await new Promise<EmbedKeyEntry[]>((resolve, reject) => {
            const allRequest = store.getAll();
            allRequest.onsuccess = () => resolve(allRequest.result || []);
            allRequest.onerror = () => reject(allRequest.error);
          });
          console.debug('[EmbedStore] Total embed_keys in IndexedDB:', allKeys.length);
          if (allKeys.length > 0) {
            // Show the hashed_embed_ids we have
            const uniqueIds = Array.from(new Set(allKeys.map(k => k.hashed_embed_id?.substring(0, 16) || 'null')));
            console.debug('[EmbedStore] Available hashed_embed_ids (first 16 chars):', uniqueIds.slice(0, 10));
          }
        } catch (listError) {
          console.debug('[EmbedStore] Could not list all keys:', listError);
        }
      } else {
        console.debug('[EmbedStore] Found', result.length, 'embed key entries for hashedEmbedId:', hashedEmbedId.substring(0, 16) + '...');
      }
      
      return result;
    } catch (error) {
      console.warn('[EmbedStore] Failed to get embed key entries:', error);
      return [];
    }
  }

  /**
   * Store embed key entries in IndexedDB
   * @param entries - Array of embed key entries to store
   */
  async storeEmbedKeys(entries: EmbedKeyEntry[]): Promise<void> {
    if (entries.length === 0) return;
    
    // Count key types for logging
    const masterKeys = entries.filter(e => e.key_type === 'master').length;
    const chatKeys = entries.filter(e => e.key_type === 'chat').length;
    console.debug(`[EmbedStore] Storing ${entries.length} embed key entries (${masterKeys} master, ${chatKeys} chat)`);
    
    try {
      const transaction = await chatDB.getTransaction([EMBED_KEYS_STORE_NAME], 'readwrite');
      const store = transaction.objectStore(EMBED_KEYS_STORE_NAME);
      
      for (const entry of entries) {
        // Use composite key for storage
        const storageKey = `${entry.hashed_embed_id}:${entry.key_type}:${entry.hashed_chat_id || 'null'}`;
        await new Promise<void>((resolve, reject) => {
          const request = store.put({ ...entry, id: storageKey });
          request.onsuccess = () => resolve();
          request.onerror = () => reject(request.error);
        });
      }
      
      console.info(`[EmbedStore] ✅ Successfully stored ${entries.length} embed key entries (${masterKeys} master, ${chatKeys} chat)`);
    } catch (error) {
      console.error('[EmbedStore] Failed to store embed keys:', error);
      throw error;
    }
  }

  /**
   * Set an embed key directly in the cache (for shared chat loading)
   * @param embedId - The embed ID
   * @param embedKey - The unwrapped embed key
   * @param hashedChatId - Optional hashed chat ID
   */
  setEmbedKeyInCache(embedId: string, embedKey: Uint8Array, hashedChatId?: string): void {
    const cacheKey = `${embedId}:${hashedChatId || 'master'}`;
    embedKeyCache.set(cacheKey, embedKey);
    console.debug('[EmbedStore] Set embed key in cache:', embedId, 'cacheKey:', cacheKey, 'hashedChatId:', hashedChatId || 'master');
  }

  /**
   * Clear embed key cache (e.g., on logout)
   */
  clearEmbedKeyCache(): void {
    embedKeyCache.clear();
    console.debug('[EmbedStore] Cleared embed key cache');
  }

  /**
   * Get all embeds for a specific app
   * Uses IndexedDB index on app_id for efficient querying
   * @param appId - The app ID to filter by
   * @returns Array of embed entries (with encrypted content, needs decryption for use)
   */
  async getEmbedsByAppId(appId: string): Promise<EmbedStoreEntry[]> {
    try {
      const transaction = await chatDB.getTransaction([EMBEDS_STORE_NAME], 'readonly');
      const store = transaction.objectStore(EMBEDS_STORE_NAME);
      const index = store.index('app_id');
      
      const result = await new Promise<EmbedStoreEntry[]>((resolve, reject) => {
        const request = index.getAll(appId);
        request.onsuccess = () => resolve(request.result || []);
        request.onerror = () => reject(request.error);
      });
      
      console.debug(`[EmbedStore] Found ${result.length} embeds for app_id: ${appId}`);
      return result;
    } catch (error) {
      console.error('[EmbedStore] Error querying embeds by app_id:', error);
      return [];
    }
  }

  /**
   * Get all embeds for a specific app and skill
   * Uses IndexedDB indexes for efficient querying
   * @param appId - The app ID to filter by
   * @param skillId - The skill ID to filter by (optional)
   * @returns Array of embed entries (with encrypted content, needs decryption for use)
   */
  async getEmbedsByAppAndSkill(appId: string, skillId?: string): Promise<EmbedStoreEntry[]> {
    try {
      // First get all embeds for the app
      const appEmbeds = await this.getEmbedsByAppId(appId);
      
      // If skillId is provided, filter by skill_id
      if (skillId) {
        return appEmbeds.filter(embed => embed.skill_id === skillId);
      }
      
      return appEmbeds;
    } catch (error) {
      console.error('[EmbedStore] Error querying embeds by app and skill:', error);
      return [];
    }
  }

  /**
   * Get all embeds of a specific type (fallback for when app_id is not set)
   * @param type - The embed type to filter by (e.g., 'app-skill-use')
   * @returns Array of embed entries
   */
  async getAllEmbedsByType(type: EmbedType): Promise<EmbedStoreEntry[]> {
    try {
      const transaction = await chatDB.getTransaction([EMBEDS_STORE_NAME], 'readonly');
      const store = transaction.objectStore(EMBEDS_STORE_NAME);
      const index = store.index('type');
      
      const result = await new Promise<EmbedStoreEntry[]>((resolve, reject) => {
        const request = index.getAll(type);
        request.onsuccess = () => resolve(request.result || []);
        request.onerror = () => reject(request.error);
      });
      
      console.debug(`[EmbedStore] Found ${result.length} embeds for type: ${type}`);
      return result;
    } catch (error) {
      console.error('[EmbedStore] Error querying embeds by type:', error);
      return [];
    }
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

  /**
   * Get all embeds for a specific chat (by hashed_chat_id)
   * Used for embed cleanup when deleting a chat
   * @param hashedChatId - SHA256 hash of the chat_id
   * @returns Array of embed entries for the chat
   */
  async getEmbedsByHashedChatId(hashedChatId: string): Promise<EmbedStoreEntry[]> {
    try {
      const transaction = await chatDB.getTransaction([EMBEDS_STORE_NAME], 'readonly');
      const store = transaction.objectStore(EMBEDS_STORE_NAME);
      const index = store.index('hashed_chat_id');
      
      const result = await new Promise<EmbedStoreEntry[]>((resolve, reject) => {
        const request = index.getAll(hashedChatId);
        request.onsuccess = () => resolve(request.result || []);
        request.onerror = () => reject(request.error);
      });
      
      console.debug(`[EmbedStore] Found ${result.length} embeds for hashed_chat_id: ${hashedChatId.substring(0, 16)}...`);
      return result;
    } catch (error) {
      console.error('[EmbedStore] Error querying embeds by hashed_chat_id:', error);
      return [];
    }
  }

  /**
   * Get all embed keys for a specific chat (by hashed_chat_id)
   * Used to check if embeds are shared with other chats
   * @param hashedChatId - SHA256 hash of the chat_id
   * @returns Array of embed key entries for the chat
   */
  async getEmbedKeysByHashedChatId(hashedChatId: string): Promise<EmbedKeyEntry[]> {
    try {
      const transaction = await chatDB.getTransaction([EMBED_KEYS_STORE_NAME], 'readonly');
      const store = transaction.objectStore(EMBED_KEYS_STORE_NAME);
      const index = store.index('hashed_chat_id');
      
      const result = await new Promise<EmbedKeyEntry[]>((resolve, reject) => {
        const request = index.getAll(hashedChatId);
        request.onsuccess = () => resolve(request.result || []);
        request.onerror = () => reject(request.error);
      });
      
      console.debug(`[EmbedStore] Found ${result.length} embed keys for hashed_chat_id: ${hashedChatId.substring(0, 16)}...`);
      return result;
    } catch (error) {
      console.error('[EmbedStore] Error querying embed keys by hashed_chat_id:', error);
      return [];
    }
  }

  /**
   * Check if an embed is used by any chat other than the specified one
   * An embed is "shared" if it has key entries for multiple chats
   * @param hashedEmbedId - SHA256 hash of the embed_id
   * @param excludeHashedChatId - hashed_chat_id to exclude from the check
   * @returns true if the embed is used by other chats
   */
  async isEmbedUsedByOtherChats(hashedEmbedId: string, excludeHashedChatId: string): Promise<boolean> {
    try {
      const transaction = await chatDB.getTransaction([EMBED_KEYS_STORE_NAME], 'readonly');
      const store = transaction.objectStore(EMBED_KEYS_STORE_NAME);
      const index = store.index('hashed_embed_id');
      
      const allKeys = await new Promise<EmbedKeyEntry[]>((resolve, reject) => {
        const request = index.getAll(hashedEmbedId);
        request.onsuccess = () => resolve(request.result || []);
        request.onerror = () => reject(request.error);
      });
      
      // Check if any key entry is for a different chat (has a hashed_chat_id different from excludeHashedChatId)
      // Also check for 'master' key type which indicates the owner's cross-chat access
      const hasOtherChatKeys = allKeys.some(key => 
        key.key_type === 'chat' && 
        key.hashed_chat_id && 
        key.hashed_chat_id !== excludeHashedChatId
      );
      
      console.debug(`[EmbedStore] Embed ${hashedEmbedId.substring(0, 16)}... used by other chats: ${hasOtherChatKeys}`);
      return hasOtherChatKeys;
    } catch (error) {
      console.error('[EmbedStore] Error checking if embed is used by other chats:', error);
      return false; // Default to not shared to be safe
    }
  }

  /**
   * Delete embed and its keys from IndexedDB
   * @param embedId - The embed_id to delete
   * @param hashedEmbedId - SHA256 hash of the embed_id (optional, will be computed if not provided)
   */
  async deleteEmbed(embedId: string, hashedEmbedId?: string): Promise<void> {
    try {
      const contentRef = `embed:${embedId}`;
      const hashedId = hashedEmbedId || await computeSHA256(embedId);
      
      // Delete from embeds store
      const embedTransaction = await chatDB.getTransaction([EMBEDS_STORE_NAME], 'readwrite');
      const embedStore = embedTransaction.objectStore(EMBEDS_STORE_NAME);
      await new Promise<void>((resolve, reject) => {
        const request = embedStore.delete(contentRef);
        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error);
      });
      
      // Delete from in-memory cache
      embedCache.delete(contentRef);
      
      // Delete all keys for this embed from embed_keys store
      const keysTransaction = await chatDB.getTransaction([EMBED_KEYS_STORE_NAME], 'readwrite');
      const keysStore = keysTransaction.objectStore(EMBED_KEYS_STORE_NAME);
      const keysIndex = keysStore.index('hashed_embed_id');
      
      const keysToDelete = await new Promise<EmbedKeyEntry[]>((resolve, reject) => {
        const request = keysIndex.getAll(hashedId);
        request.onsuccess = () => resolve(request.result || []);
        request.onerror = () => reject(request.error);
      });
      
      // Delete each key entry
      for (const keyEntry of keysToDelete) {
        const keyId = `${keyEntry.hashed_embed_id}:${keyEntry.key_type}:${keyEntry.hashed_chat_id || 'null'}`;
        await new Promise<void>((resolve, reject) => {
          const request = keysStore.delete(keyId);
          request.onsuccess = () => resolve();
          request.onerror = () => reject(request.error);
        });
        
        // Also clear from key cache
        embedKeyCache.delete(`${embedId}:${keyEntry.hashed_chat_id || 'master'}`);
      }
      
      console.debug(`[EmbedStore] Deleted embed ${embedId} and ${keysToDelete.length} associated keys`);
    } catch (error) {
      console.error(`[EmbedStore] Error deleting embed ${embedId}:`, error);
      throw error;
    }
  }

  /**
   * Delete all embeds for a chat that are not shared with other chats
   * Also deletes associated embed keys
   * @param chatId - The chat_id being deleted
   * @returns Array of embed_ids that were deleted (for server notification)
   */
  async deleteEmbedsForChat(chatId: string): Promise<string[]> {
    const deletedEmbedIds: string[] = [];
    
    try {
      const hashedChatId = await computeSHA256(chatId);
      
      // Get all embeds for this chat
      const chatEmbeds = await this.getEmbedsByHashedChatId(hashedChatId);
      console.debug(`[EmbedStore] Found ${chatEmbeds.length} embeds for chat ${chatId}`);
      
      // Check each embed and delete if not shared with other chats
      for (const embed of chatEmbeds) {
        if (!embed.embed_id) {
          console.warn('[EmbedStore] Embed has no embed_id, skipping:', embed.contentRef);
          continue;
        }
        
        const hashedEmbedId = await computeSHA256(embed.embed_id);
        
        // Check if this embed is used by other chats
        const isShared = await this.isEmbedUsedByOtherChats(hashedEmbedId, hashedChatId);
        
        if (isShared) {
          console.debug(`[EmbedStore] Embed ${embed.embed_id} is shared with other chats, only removing chat key`);
          // Only remove the chat-specific key, not the embed itself
          await this.deleteEmbedKeyForChat(hashedEmbedId, hashedChatId);
        } else {
          console.debug(`[EmbedStore] Embed ${embed.embed_id} is not shared, deleting completely`);
          await this.deleteEmbed(embed.embed_id, hashedEmbedId);
          deletedEmbedIds.push(embed.embed_id);
        }
      }
      
      console.info(`[EmbedStore] Deleted ${deletedEmbedIds.length} embeds for chat ${chatId}`);
      return deletedEmbedIds;
    } catch (error) {
      console.error(`[EmbedStore] Error deleting embeds for chat ${chatId}:`, error);
      return deletedEmbedIds;
    }
  }

  /**
   * DEBUG: Get fully decrypted embed content with all fields decoded
   * This function is intended for debugging purposes - call from browser console:
   *   await window.debugGetDecryptedEmbed('your-embed-id')
   * 
   * @param embedId - The embed_id to retrieve and decrypt
   * @returns Object with all embed fields decrypted and TOON content decoded
   */
  async debugGetDecryptedEmbed(embedId: string): Promise<{
    raw: Record<string, unknown>;
    decrypted: Record<string, unknown> | null;
    toonDecoded: Record<string, unknown> | null;
    metadata: {
      embedId: string;
      contentRef: string;
      type: string | undefined;
      status: string | undefined;
      hasEncryptedContent: boolean;
      hasContent: boolean;
      decryptionSuccess: boolean;
      toonDecodeSuccess: boolean;
    };
  } | null> {
    console.log('[EmbedStore DEBUG] Getting decrypted embed for:', embedId);
    
    const normalizedEmbedId = embedId.startsWith('embed:') ? embedId : embedId;
    const contentRef = embedId.startsWith('embed:') ? embedId : `embed:${embedId}`;
    
    try {
      // Step 1: Get raw entry from IndexedDB/cache (without decryption)
      let rawEntry: EmbedStoreEntry | undefined;
      
      // Check memory cache first
      rawEntry = embedCache.get(contentRef);
      
      // If not in cache, try IndexedDB
      if (!rawEntry) {
        try {
          const transaction = await chatDB.getTransaction([EMBEDS_STORE_NAME], 'readonly');
          const store = transaction.objectStore(EMBEDS_STORE_NAME);
          
          rawEntry = await new Promise<EmbedStoreEntry | undefined>((resolve, reject) => {
            const request = store.get(contentRef);
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
          });
        } catch (error) {
          console.error('[EmbedStore DEBUG] Error loading from IndexedDB:', error);
        }
      }
      
      if (!rawEntry) {
        console.error('[EmbedStore DEBUG] Embed not found:', contentRef);
        return null;
      }
      
      console.log('[EmbedStore DEBUG] Raw entry:', rawEntry);
      
      // Step 2: Get decrypted embed using standard get() method
      const decryptedEmbed = await this.get(contentRef);
      console.log('[EmbedStore DEBUG] Decrypted embed:', decryptedEmbed);
      
      // Step 3: Decode TOON content if present
      let toonDecoded: Record<string, unknown> | null = null;
      let toonDecodeSuccess = false;
      
      if (decryptedEmbed?.content) {
        try {
          toonDecoded = await decodeToonContentLocal(decryptedEmbed.content);
          toonDecodeSuccess = toonDecoded !== null;
          console.log('[EmbedStore DEBUG] TOON decoded content:', toonDecoded);
        } catch (error) {
          console.error('[EmbedStore DEBUG] TOON decode failed:', error);
        }
      }
      
      // Step 4: Build result object with all information
      const result = {
        raw: {
          contentRef: rawEntry.contentRef,
          type: rawEntry.type,
          embed_id: rawEntry.embed_id,
          status: rawEntry.status,
          hashed_chat_id: rawEntry.hashed_chat_id,
          hashed_message_id: rawEntry.hashed_message_id,
          hashed_task_id: rawEntry.hashed_task_id,
          hashed_user_id: rawEntry.hashed_user_id,
          parent_embed_id: rawEntry.parent_embed_id,
          embed_ids: rawEntry.embed_ids,
          app_id: rawEntry.app_id,
          skill_id: rawEntry.skill_id,
          createdAt: rawEntry.createdAt,
          updatedAt: rawEntry.updatedAt,
          hasEncryptedContent: !!rawEntry.encrypted_content,
          hasEncryptedType: !!rawEntry.encrypted_type,
          hasData: !!rawEntry.data,
          encryptedContentLength: rawEntry.encrypted_content?.length || 0,
          dataLength: typeof rawEntry.data === 'string' ? rawEntry.data.length : 0,
        },
        decrypted: decryptedEmbed,
        toonDecoded: toonDecoded,
        metadata: {
          embedId: normalizedEmbedId,
          contentRef: contentRef,
          type: rawEntry.type || decryptedEmbed?.type || decryptedEmbed?.embed_type,
          status: rawEntry.status || decryptedEmbed?.status,
          hasEncryptedContent: !!rawEntry.encrypted_content,
          hasContent: !!decryptedEmbed?.content,
          decryptionSuccess: !!decryptedEmbed?.content && !decryptedEmbed?._decryptionFailed,
          toonDecodeSuccess: toonDecodeSuccess,
        }
      };
      
      // Pretty print the result for console viewing
      console.log('[EmbedStore DEBUG] ====== FULL EMBED DEBUG OUTPUT ======');
      console.log('[EmbedStore DEBUG] Metadata:', result.metadata);
      console.log('[EmbedStore DEBUG] Raw entry info:', result.raw);
      console.log('[EmbedStore DEBUG] Decrypted embed:', result.decrypted);
      console.log('[EmbedStore DEBUG] TOON decoded (full content):', result.toonDecoded);
      console.log('[EmbedStore DEBUG] =====================================');
      
      return result;
    } catch (error) {
      console.error('[EmbedStore DEBUG] Error in debugGetDecryptedEmbed:', error);
      return null;
    }
  }

  /**
   * Delete a specific chat's key for an embed (without deleting the embed itself)
   * Used when an embed is shared with multiple chats
   * @param hashedEmbedId - SHA256 hash of the embed_id
   * @param hashedChatId - SHA256 hash of the chat_id
   */
  private async deleteEmbedKeyForChat(hashedEmbedId: string, hashedChatId: string): Promise<void> {
    try {
      const keyId = `${hashedEmbedId}:chat:${hashedChatId}`;
      
      const transaction = await chatDB.getTransaction([EMBED_KEYS_STORE_NAME], 'readwrite');
      const store = transaction.objectStore(EMBED_KEYS_STORE_NAME);
      
      await new Promise<void>((resolve, reject) => {
        const request = store.delete(keyId);
        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error);
      });
      
      // Clear from cache
      const cacheKey = `${hashedEmbedId}:${hashedChatId}`;
      embedKeyCache.delete(cacheKey);
      
      console.debug(`[EmbedStore] Deleted chat key for embed ${hashedEmbedId.substring(0, 16)}... in chat ${hashedChatId.substring(0, 16)}...`);
    } catch (error) {
      console.error(`[EmbedStore] Error deleting embed key for chat:`, error);
    }
  }
}

// Export singleton instance
export const embedStore = new EmbedStore();

// ============================================
// DEBUG: Expose debug function on window for console access
// Usage: await window.debugGetDecryptedEmbed('your-embed-id')
// ============================================
if (typeof window !== 'undefined') {
  (window as unknown as Record<string, unknown>).debugGetDecryptedEmbed = async (embedId: string) => {
    return embedStore.debugGetDecryptedEmbed(embedId);
  };
  console.debug('[EmbedStore] Debug function exposed: window.debugGetDecryptedEmbed(embedId)');
}
