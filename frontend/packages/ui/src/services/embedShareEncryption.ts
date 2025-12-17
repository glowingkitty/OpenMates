/**
 * Embed Share Encryption Service
 *
 * Provides encrypted sharing functionality for embeds, similar to chat sharing.
 * Uses the same patterns as shareEncryption.ts but adapted for embed IDs and embed keys.
 */

import {
  encryptWithMasterKey,
  decryptWithMasterKey,
  generateEmbedKey
} from './cryptoService';
import { embedStore } from './embedStore';

// Re-export ShareDuration type from shareEncryption for consistency
export type { ShareDuration } from './shareEncryption';

/**
 * Structure of the embed share key blob (before encryption)
 * This contains everything needed to decrypt and access the shared embed
 */
interface EmbedShareKeyData {
  /** The embed ID being shared */
  embed_id: string;
  /** The embed's encryption key (unwrapped) */
  embed_key: string; // Base64-encoded for JSON serialization
  /** Timestamp when the blob was generated (server time) */
  generated_at: number;
  /** Share duration in seconds (0 = no expiration) */
  duration_seconds: number;
  /** Whether the share is password-protected */
  password_protected: boolean;
}

/**
 * Generate an encrypted embed share key blob
 *
 * Similar to generateShareKeyBlob but for embeds:
 * 1. Gets the embed's encryption key from embedStore
 * 2. Creates a data blob with embed_id, embed_key, and sharing settings
 * 3. Optionally encrypts with password
 * 4. Encrypts the final blob with a random key
 * 5. Returns the encrypted blob as base64 string for URL fragment
 *
 * @param embedId - The embed ID to share
 * @param duration - Share duration in seconds (0 = no expiration)
 * @param password - Optional password for additional protection
 * @returns Encrypted blob for URL fragment
 */
export async function generateEmbedShareKeyBlob(
  embedId: string,
  duration: number = 0,
  password?: string
): Promise<string> {
  try {
    console.debug('[EmbedShareEncryption] Generating embed share key blob for:', embedId);

    // Get the embed's encryption key from embedStore
    const embedKey = await embedStore.getEmbedKey(embedId);
    if (!embedKey) {
      throw new Error(`Embed key not found for embed ID: ${embedId}`);
    }

    // Convert embed key to base64 for JSON serialization
    const embedKeyBase64 = btoa(String.fromCharCode(...embedKey));

    // Create the share key data
    const shareKeyData: EmbedShareKeyData = {
      embed_id: embedId,
      embed_key: embedKeyBase64,
      generated_at: Date.now(), // Client timestamp - server will validate with its own time
      duration_seconds: duration,
      password_protected: !!password
    };

    // Serialize to JSON
    let jsonData = JSON.stringify(shareKeyData);

    // If password protected, encrypt the JSON data with password-derived key
    if (password) {
      console.debug('[EmbedShareEncryption] Applying password protection');

      // Import password-based encryption from shareEncryption
      const { encryptWithPassword } = await import('./shareEncryption');
      jsonData = await encryptWithPassword(jsonData, password);
    }

    // Generate a random key for final encryption
    const randomKey = generateEmbedKey();

    // Encrypt the data with the random key
    const encryptedData = await encryptWithMasterKey(
      new TextEncoder().encode(jsonData),
      randomKey
    );

    // Create final blob structure: {key: randomKey, data: encryptedData}
    const finalBlob = {
      key: btoa(String.fromCharCode(...randomKey)),
      data: btoa(String.fromCharCode(...encryptedData))
    };

    // Encode as base64 for URL fragment
    const blobString = JSON.stringify(finalBlob);
    const encodedBlob = btoa(blobString);

    console.debug('[EmbedShareEncryption] Embed share key blob generated successfully');
    return encodedBlob;

  } catch (error) {
    console.error('[EmbedShareEncryption] Error generating embed share key blob:', error);
    throw error;
  }
}

/**
 * Decrypt an embed share key blob
 *
 * Reverses the process of generateEmbedShareKeyBlob:
 * 1. Decodes the base64 blob
 * 2. Extracts the random key and encrypted data
 * 3. Decrypts with the random key
 * 4. Optionally decrypts with password if protected
 * 5. Validates expiration
 * 6. Returns embed_id and embed_key for accessing the embed
 *
 * @param encryptedBlob - Base64-encoded encrypted blob from URL
 * @param embedId - Expected embed ID (for validation)
 * @param password - Password if the share is password-protected
 * @returns Decrypted embed data or null if invalid/expired
 */
export async function decryptEmbedShareKeyBlob(
  encryptedBlob: string,
  embedId: string,
  password?: string
): Promise<{
  embedKey: Uint8Array;
  isExpired: boolean;
  embedId: string;
} | null> {
  try {
    console.debug('[EmbedShareEncryption] Decrypting embed share key blob for:', embedId);

    // Decode the base64 blob
    const blobString = atob(encryptedBlob);
    const finalBlob = JSON.parse(blobString);

    // Extract random key and encrypted data
    const randomKey = new Uint8Array(
      atob(finalBlob.key).split('').map(c => c.charCodeAt(0))
    );
    const encryptedData = new Uint8Array(
      atob(finalBlob.data).split('').map(c => c.charCodeAt(0))
    );

    // Decrypt with random key
    const decryptedData = await decryptWithMasterKey(encryptedData, randomKey);
    let jsonData = new TextDecoder().decode(decryptedData);

    // If password protected, decrypt with password
    if (password) {
      console.debug('[EmbedShareEncryption] Decrypting password-protected embed share');

      const { decryptWithPassword } = await import('./shareEncryption');
      jsonData = await decryptWithPassword(jsonData, password);
    }

    // Parse the share key data
    const shareKeyData: EmbedShareKeyData = JSON.parse(jsonData);

    // Validate embed ID matches
    if (shareKeyData.embed_id !== embedId) {
      console.warn('[EmbedShareEncryption] Embed ID mismatch in share blob');
      return null;
    }

    // Check expiration
    let isExpired = false;
    if (shareKeyData.duration_seconds > 0) {
      const expirationTime = shareKeyData.generated_at + (shareKeyData.duration_seconds * 1000);
      isExpired = Date.now() > expirationTime;

      if (isExpired) {
        console.warn('[EmbedShareEncryption] Embed share link has expired');
      }
    }

    // Convert embed key back from base64
    const embedKey = new Uint8Array(
      atob(shareKeyData.embed_key).split('').map(c => c.charCodeAt(0))
    );

    console.debug('[EmbedShareEncryption] Embed share key blob decrypted successfully');

    return {
      embedKey,
      isExpired,
      embedId: shareKeyData.embed_id
    };

  } catch (error) {
    console.error('[EmbedShareEncryption] Error decrypting embed share key blob:', error);
    return null;
  }
}

/**
 * Get an embed's encryption key for sharing
 *
 * Helper function that wraps embedStore.getEmbedKey with proper error handling
 *
 * @param embedId - The embed ID
 * @returns The embed's encryption key or null if not found
 */
export async function getEmbedKeyForSharing(embedId: string): Promise<Uint8Array | null> {
  try {
    const embedKey = await embedStore.getEmbedKey(embedId);
    if (!embedKey) {
      console.warn('[EmbedShareEncryption] Embed key not found for sharing:', embedId);
      return null;
    }
    return embedKey;
  } catch (error) {
    console.error('[EmbedShareEncryption] Error getting embed key for sharing:', error);
    return null;
  }
}