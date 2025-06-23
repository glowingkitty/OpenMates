import nacl from 'tweetnacl';
import { Buffer } from 'buffer';

const SESSION_STORAGE_KEY = 'openmates_master_key';

export function generateSalt(length = 16): Uint8Array {
  return nacl.randomBytes(length);
}

export function generateUserMasterKey(): Uint8Array {
  return nacl.randomBytes(nacl.secretbox.keyLength);
}

export async function deriveKeyFromPassword(password: string, salt: Uint8Array): Promise<Uint8Array> {
  if (typeof window !== 'undefined') {
    const encoder = new TextEncoder();
    const keyMaterial = await crypto.subtle.importKey(
      'raw',
      encoder.encode(password),
      'PBKDF2',
      false,
      ['deriveKey', 'deriveBits']
    );
    
    const derivedBits = await crypto.subtle.deriveBits(
      {
        name: 'PBKDF2',
        salt: salt,
        iterations: 100000,
        hash: 'SHA-256'
      },
      keyMaterial,
      256
    );
    
    return new Uint8Array(derivedBits);
  }
  return new Uint8Array(32);
}

export function encryptKey(masterKey: Uint8Array, wrappingKey: Uint8Array): string {
  const nonce = nacl.randomBytes(nacl.secretbox.nonceLength);
  const encryptedKey = nacl.secretbox(masterKey, nonce, wrappingKey);

  const combined = new Uint8Array(nonce.length + encryptedKey.length);
  combined.set(nonce);
  combined.set(encryptedKey, nonce.length);

  return Buffer.from(combined).toString('base64');
}

export function decryptKey(encryptedKeyWithNonce: string, wrappingKey: Uint8Array): Uint8Array | null {
  const combined = Buffer.from(encryptedKeyWithNonce, 'base64');
  const nonce = combined.slice(0, nacl.secretbox.nonceLength);
  const encryptedKey = combined.slice(nacl.secretbox.nonceLength);

  const decryptedKey = nacl.secretbox.open(encryptedKey, nonce, wrappingKey);

  return decryptedKey;
}

export function saveKeyToSession(key: Uint8Array): void {
  if (typeof window !== 'undefined') {
    sessionStorage.setItem(SESSION_STORAGE_KEY, Buffer.from(key).toString('base64'));
  }
}

export function getKeyFromSession(): Uint8Array | null {
  if (typeof window !== 'undefined') {
    const keyB64 = sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (!keyB64) {
      return null;
    }
    return Buffer.from(keyB64, 'base64');
  }
  return null;
}

export function clearKeyFromSession(): void {
  if (typeof window !== 'undefined') {
    sessionStorage.removeItem(SESSION_STORAGE_KEY);
  }
}
