import nacl from 'tweetnacl';

const SESSION_STORAGE_KEY = 'openmates_master_key';

// Helper function to convert Uint8Array to Base64
function uint8ArrayToBase64(bytes: Uint8Array): string {
  let binary = '';
  const len = bytes.byteLength;
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return window.btoa(binary);
}

// Helper function to convert Base64 to Uint8Array
function base64ToUint8Array(base64: string): Uint8Array {
  const binary_string = window.atob(base64);
  const len = binary_string.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    bytes[i] = binary_string.charCodeAt(i);
  }
  return bytes;
}

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

  return uint8ArrayToBase64(combined);
}

export function decryptKey(encryptedKeyWithNonce: string, wrappingKey: Uint8Array): Uint8Array | null {
  const combined = base64ToUint8Array(encryptedKeyWithNonce);
  const nonce = combined.slice(0, nacl.secretbox.nonceLength);
  const encryptedKey = combined.slice(nacl.secretbox.nonceLength);

  const decryptedKey = nacl.secretbox.open(encryptedKey, nonce, wrappingKey);

  return decryptedKey;
}

export function saveKeyToSession(key: Uint8Array): void {
  if (typeof window !== 'undefined') {
    sessionStorage.setItem(SESSION_STORAGE_KEY, uint8ArrayToBase64(key));
  }
}

export function getKeyFromSession(): Uint8Array | null {
  if (typeof window !== 'undefined') {
    const keyB64 = sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (!keyB64) {
      return null;
    }
    return base64ToUint8Array(keyB64);
  }
  return null;
}

export function clearKeyFromSession(): void {
  if (typeof window !== 'undefined') {
    sessionStorage.removeItem(SESSION_STORAGE_KEY);
  }
}
