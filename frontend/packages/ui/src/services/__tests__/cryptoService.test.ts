/**
 * Comprehensive unit tests for the cryptoService module.
 * 
 * Tests the zero-knowledge encryption architecture including:
 * - Master key generation and management
 * - Email encryption/decryption
 * - Chat-specific encryption/decryption
 * - Key wrapping and storage
 * - Recovery key generation
 * - Hash functions
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import * as cryptoService from '../cryptoService';
import nacl from 'tweetnacl';

// Mock browser APIs
const mockStorage = {
  sessionStorage: new Map<string, string>(),
  localStorage: new Map<string, string>(),
};

// Mock window object
Object.defineProperty(global, 'window', {
  value: {
    btoa: (str: string) => Buffer.from(str, 'binary').toString('base64'),
    atob: (str: string) => Buffer.from(str, 'base64').toString('binary'),
    sessionStorage: {
      getItem: (key: string) => mockStorage.sessionStorage.get(key) || null,
      setItem: (key: string, value: string) => mockStorage.sessionStorage.set(key, value),
      removeItem: (key: string) => mockStorage.sessionStorage.delete(key),
    },
    localStorage: {
      getItem: (key: string) => mockStorage.localStorage.get(key) || null,
      setItem: (key: string, value: string) => mockStorage.localStorage.set(key, value),
      removeItem: (key: string) => mockStorage.localStorage.delete(key),
    },
  },
  writable: true,
});

// Mock crypto.subtle
Object.defineProperty(global, 'crypto', {
  value: {
    subtle: {
      importKey: vi.fn(),
      deriveBits: vi.fn(),
    },
    randomUUID: vi.fn(() => 'test-uuid-123'),
  },
  writable: true,
});

describe('cryptoService', () => {
  beforeEach(() => {
    // Clear all storage before each test
    mockStorage.sessionStorage.clear();
    mockStorage.localStorage.clear();
    
    // Reset mocks
    vi.clearAllMocks();
  });

  afterEach(() => {
    // Clean up after each test
    mockStorage.sessionStorage.clear();
    mockStorage.localStorage.clear();
  });

  describe('Utility Functions', () => {
    describe('uint8ArrayToBase64', () => {
      it('should convert Uint8Array to base64', () => {
        const bytes = new Uint8Array([72, 101, 108, 108, 111]); // "Hello"
        const result = cryptoService.uint8ArrayToBase64(bytes);
        expect(result).toBe('SGVsbG8=');
      });

      it('should handle empty Uint8Array', () => {
        const bytes = new Uint8Array([]);
        const result = cryptoService.uint8ArrayToBase64(bytes);
        expect(result).toBe('');
      });
    });

    describe('base64ToUint8Array', () => {
      it('should convert base64 to Uint8Array', () => {
        const base64 = 'SGVsbG8='; // "Hello"
        const result = cryptoService.base64ToUint8Array(base64);
        expect(result).toEqual(new Uint8Array([72, 101, 108, 108, 111]));
      });

      it('should handle empty base64', () => {
        const result = cryptoService.base64ToUint8Array('');
        expect(result).toEqual(new Uint8Array([]));
      });
    });

    describe('generateSalt', () => {
      it('should generate salt of specified length', () => {
        const salt = cryptoService.generateSalt(16);
        expect(salt).toBeInstanceOf(Uint8Array);
        expect(salt.length).toBe(16);
      });

      it('should generate salt of default length', () => {
        const salt = cryptoService.generateSalt();
        expect(salt).toBeInstanceOf(Uint8Array);
        expect(salt.length).toBe(16);
      });

      it('should generate different salts each time', () => {
        const salt1 = cryptoService.generateSalt(16);
        const salt2 = cryptoService.generateSalt(16);
        expect(salt1).not.toEqual(salt2);
      });
    });

    describe('generateUserMasterKey', () => {
      it('should generate master key of correct length', () => {
        const key = cryptoService.generateUserMasterKey();
        expect(key).toBeInstanceOf(Uint8Array);
        expect(key.length).toBe(nacl.secretbox.keyLength);
      });

      it('should generate different keys each time', () => {
        const key1 = cryptoService.generateUserMasterKey();
        const key2 = cryptoService.generateUserMasterKey();
        expect(key1).not.toEqual(key2);
      });
    });
  });

  describe('Key Derivation', () => {
    describe('deriveKeyFromPassword', () => {
      it('should derive key from password', async () => {
        const password = 'test-password';
        const salt = new Uint8Array(16);
        
        // Mock crypto.subtle methods
        const mockKeyMaterial = {};
        const mockDerivedBits = new ArrayBuffer(32);
        
        vi.mocked(crypto.subtle.importKey).mockResolvedValue(mockKeyMaterial);
        vi.mocked(crypto.subtle.deriveBits).mockResolvedValue(mockDerivedBits);
        
        const result = await cryptoService.deriveKeyFromPassword(password, salt);
        
        expect(result).toBeInstanceOf(Uint8Array);
        expect(result.length).toBe(32);
        expect(crypto.subtle.importKey).toHaveBeenCalledWith(
          'raw',
          expect.any(Uint8Array),
          'PBKDF2',
          false,
          ['deriveKey', 'deriveBits']
        );
        expect(crypto.subtle.deriveBits).toHaveBeenCalledWith(
          expect.objectContaining({
            name: 'PBKDF2',
            salt: salt,
            iterations: 100000,
            hash: 'SHA-256'
          }),
          mockKeyMaterial,
          256
        );
      });
    });
  });

  describe('Key Wrapping', () => {
    describe('encryptKey', () => {
      it('should encrypt key with wrapping key', () => {
        const masterKey = new Uint8Array(32);
        const wrappingKey = new Uint8Array(32);
        
        const result = cryptoService.encryptKey(masterKey, wrappingKey);
        
        expect(result).toBeDefined();
        expect(typeof result).toBe('string');
        expect(result.length).toBeGreaterThan(0);
        
        // Should be base64 encoded
        expect(() => cryptoService.base64ToUint8Array(result)).not.toThrow();
      });

      it('should produce different encrypted keys for same input', () => {
        const masterKey = new Uint8Array(32);
        const wrappingKey = new Uint8Array(32);
        
        const result1 = cryptoService.encryptKey(masterKey, wrappingKey);
        const result2 = cryptoService.encryptKey(masterKey, wrappingKey);
        
        expect(result1).not.toEqual(result2); // Different nonces
      });
    });

    describe('decryptKey', () => {
      it('should decrypt key with correct wrapping key', () => {
        const masterKey = new Uint8Array(32);
        const wrappingKey = new Uint8Array(32);
        
        const encrypted = cryptoService.encryptKey(masterKey, wrappingKey);
        const decrypted = cryptoService.decryptKey(encrypted, wrappingKey);
        
        expect(decrypted).toEqual(masterKey);
      });

      it('should return null with incorrect wrapping key', () => {
        const masterKey = new Uint8Array(32);
        const wrappingKey = new Uint8Array(32);
        const wrongKey = new Uint8Array(32);
        
        const encrypted = cryptoService.encryptKey(masterKey, wrappingKey);
        const decrypted = cryptoService.decryptKey(encrypted, wrongKey);
        
        expect(decrypted).toBeNull();
      });

      it('should return null with invalid encrypted data', () => {
        const wrappingKey = new Uint8Array(32);
        const decrypted = cryptoService.decryptKey('invalid-data', wrappingKey);
        
        expect(decrypted).toBeNull();
      });
    });
  });

  describe('Key Storage Management', () => {
    describe('saveKeyToSession', () => {
      it('should save key to sessionStorage by default', () => {
        const key = new Uint8Array(32);
        cryptoService.saveKeyToSession(key);
        
        expect(mockStorage.sessionStorage.has('openmates_master_key')).toBe(true);
        expect(mockStorage.localStorage.has('openmates_master_key_persistent')).toBe(false);
      });

      it('should save key to localStorage when requested', () => {
        const key = new Uint8Array(32);
        cryptoService.saveKeyToSession(key, true);
        
        expect(mockStorage.localStorage.has('openmates_master_key_persistent')).toBe(true);
        expect(mockStorage.sessionStorage.has('openmates_master_key')).toBe(false);
      });

      it('should clear other storage when switching', () => {
        const key = new Uint8Array(32);
        
        // First save to session
        cryptoService.saveKeyToSession(key, false);
        expect(mockStorage.sessionStorage.has('openmates_master_key')).toBe(true);
        
        // Then save to local
        cryptoService.saveKeyToSession(key, true);
        expect(mockStorage.localStorage.has('openmates_master_key_persistent')).toBe(true);
        expect(mockStorage.sessionStorage.has('openmates_master_key')).toBe(false);
      });
    });

    describe('getKeyFromStorage', () => {
      it('should retrieve key from localStorage first', () => {
        const key = new Uint8Array(32);
        const keyB64 = cryptoService.uint8ArrayToBase64(key);
        
        mockStorage.localStorage.set('openmates_master_key_persistent', keyB64);
        
        const result = cryptoService.getKeyFromStorage();
        expect(result).toEqual(key);
      });

      it('should fallback to sessionStorage', () => {
        const key = new Uint8Array(32);
        const keyB64 = cryptoService.uint8ArrayToBase64(key);
        
        mockStorage.sessionStorage.set('openmates_master_key', keyB64);
        
        const result = cryptoService.getKeyFromStorage();
        expect(result).toEqual(key);
      });

      it('should return null when no key found', () => {
        const result = cryptoService.getKeyFromStorage();
        expect(result).toBeNull();
      });
    });

    describe('clearKeyFromStorage', () => {
      it('should clear key from both storage types', () => {
        const key = new Uint8Array(32);
        const keyB64 = cryptoService.uint8ArrayToBase64(key);
        
        mockStorage.localStorage.set('openmates_master_key_persistent', keyB64);
        mockStorage.sessionStorage.set('openmates_master_key', keyB64);
        
        cryptoService.clearKeyFromStorage();
        
        expect(mockStorage.localStorage.has('openmates_master_key_persistent')).toBe(false);
        expect(mockStorage.sessionStorage.has('openmates_master_key')).toBe(false);
      });
    });
  });

  describe('Email Encryption', () => {
    describe('generateEmailSalt', () => {
      it('should generate email salt of correct length', () => {
        const salt = cryptoService.generateEmailSalt();
        expect(salt).toBeInstanceOf(Uint8Array);
        expect(salt.length).toBe(16);
      });
    });

    describe('deriveEmailEncryptionKey', () => {
      it('should derive email encryption key', async () => {
        const email = 'test@example.com';
        const salt = new Uint8Array(16);
        
        // Mock crypto.subtle.digest
        const mockDigest = vi.fn().mockResolvedValue(new ArrayBuffer(32));
        Object.defineProperty(crypto.subtle, 'digest', {
          value: mockDigest,
          writable: true,
        });
        
        const result = await cryptoService.deriveEmailEncryptionKey(email, salt);
        
        expect(result).toBeInstanceOf(Uint8Array);
        expect(result.length).toBe(32);
        expect(mockDigest).toHaveBeenCalledWith('SHA-256', expect.any(Uint8Array));
      });
    });

    describe('encryptEmail', () => {
      it('should encrypt email with key', () => {
        const email = 'test@example.com';
        const key = new Uint8Array(32);
        
        const result = cryptoService.encryptEmail(email, key);
        
        expect(result).toBeDefined();
        expect(typeof result).toBe('string');
        expect(result.length).toBeGreaterThan(0);
        
        // Should be base64 encoded
        expect(() => cryptoService.base64ToUint8Array(result)).not.toThrow();
      });

      it('should produce different encrypted emails for same input', () => {
        const email = 'test@example.com';
        const key = new Uint8Array(32);
        
        const result1 = cryptoService.encryptEmail(email, key);
        const result2 = cryptoService.encryptEmail(email, key);
        
        expect(result1).not.toEqual(result2); // Different nonces
      });
    });

    describe('decryptEmail', () => {
      it('should decrypt email with correct key', () => {
        const email = 'test@example.com';
        const key = new Uint8Array(32);
        
        const encrypted = cryptoService.encryptEmail(email, key);
        const decrypted = cryptoService.decryptEmail(encrypted, key);
        
        expect(decrypted).toBe(email);
      });

      it('should return null with incorrect key', () => {
        const email = 'test@example.com';
        const key = new Uint8Array(32);
        const wrongKey = new Uint8Array(32);
        
        const encrypted = cryptoService.encryptEmail(email, key);
        const decrypted = cryptoService.decryptEmail(encrypted, wrongKey);
        
        expect(decrypted).toBeNull();
      });

      it('should return null with invalid encrypted data', () => {
        const key = new Uint8Array(32);
        const decrypted = cryptoService.decryptEmail('invalid-data', key);
        
        expect(decrypted).toBeNull();
      });
    });

    describe('hashEmail', () => {
      it('should hash email', async () => {
        const email = 'test@example.com';
        
        // Mock crypto.subtle.digest
        const mockDigest = vi.fn().mockResolvedValue(new ArrayBuffer(32));
        Object.defineProperty(crypto.subtle, 'digest', {
          value: mockDigest,
          writable: true,
        });
        
        const result = await cryptoService.hashEmail(email);
        
        expect(result).toBeDefined();
        expect(typeof result).toBe('string');
        expect(mockDigest).toHaveBeenCalledWith('SHA-256', expect.any(Uint8Array));
      });
    });
  });

  describe('Master Key Encryption', () => {
    describe('encryptWithMasterKey', () => {
      it('should encrypt data with master key from storage', () => {
        const masterKey = new Uint8Array(32);
        const keyB64 = cryptoService.uint8ArrayToBase64(masterKey);
        mockStorage.localStorage.set('openmates_master_key_persistent', keyB64);
        
        const data = 'test data';
        const result = cryptoService.encryptWithMasterKey(data);
        
        expect(result).toBeDefined();
        expect(typeof result).toBe('string');
        expect(result.length).toBeGreaterThan(0);
      });

      it('should return null when master key not found', () => {
        const data = 'test data';
        const result = cryptoService.encryptWithMasterKey(data);
        
        expect(result).toBeNull();
      });
    });

    describe('decryptWithMasterKey', () => {
      it('should decrypt data with master key from storage', () => {
        const masterKey = new Uint8Array(32);
        const keyB64 = cryptoService.uint8ArrayToBase64(masterKey);
        mockStorage.localStorage.set('openmates_master_key_persistent', keyB64);
        
        const data = 'test data';
        const encrypted = cryptoService.encryptWithMasterKey(data);
        expect(encrypted).not.toBeNull();
        
        const decrypted = cryptoService.decryptWithMasterKey(encrypted!);
        expect(decrypted).toBe(data);
      });

      it('should return null when master key not found', () => {
        const encrypted = 'some-encrypted-data';
        const result = cryptoService.decryptWithMasterKey(encrypted);
        
        expect(result).toBeNull();
      });

      it('should return null with invalid encrypted data', () => {
        const masterKey = new Uint8Array(32);
        const keyB64 = cryptoService.uint8ArrayToBase64(masterKey);
        mockStorage.localStorage.set('openmates_master_key_persistent', keyB64);
        
        const result = cryptoService.decryptWithMasterKey('invalid-data');
        expect(result).toBeNull();
      });
    });
  });

  describe('Email Encryption Key Management', () => {
    describe('saveEmailEncryptionKey', () => {
      it('should save email encryption key to sessionStorage by default', () => {
        const key = new Uint8Array(32);
        cryptoService.saveEmailEncryptionKey(key);
        
        expect(mockStorage.sessionStorage.has('openmates_email_encryption_key')).toBe(true);
        expect(mockStorage.localStorage.has('openmates_email_encryption_key')).toBe(false);
      });

      it('should save email encryption key to localStorage when requested', () => {
        const key = new Uint8Array(32);
        cryptoService.saveEmailEncryptionKey(key, true);
        
        expect(mockStorage.localStorage.has('openmates_email_encryption_key')).toBe(true);
        expect(mockStorage.sessionStorage.has('openmates_email_encryption_key')).toBe(false);
      });
    });

    describe('getEmailEncryptionKey', () => {
      it('should retrieve email encryption key from localStorage first', () => {
        const key = new Uint8Array(32);
        const keyB64 = cryptoService.uint8ArrayToBase64(key);
        
        mockStorage.localStorage.set('openmates_email_encryption_key', keyB64);
        
        const result = cryptoService.getEmailEncryptionKey();
        expect(result).toEqual(key);
      });

      it('should fallback to sessionStorage', () => {
        const key = new Uint8Array(32);
        const keyB64 = cryptoService.uint8ArrayToBase64(key);
        
        mockStorage.sessionStorage.set('openmates_email_encryption_key', keyB64);
        
        const result = cryptoService.getEmailEncryptionKey();
        expect(result).toEqual(key);
      });

      it('should return null when no key found', () => {
        const result = cryptoService.getEmailEncryptionKey();
        expect(result).toBeNull();
      });
    });

    describe('getEmailEncryptionKeyForApi', () => {
      it('should return base64 encoded key for API use', () => {
        const key = new Uint8Array(32);
        const keyB64 = cryptoService.uint8ArrayToBase64(key);
        
        mockStorage.localStorage.set('openmates_email_encryption_key', keyB64);
        
        const result = cryptoService.getEmailEncryptionKeyForApi();
        expect(result).toBe(keyB64);
      });

      it('should return null when no key found', () => {
        const result = cryptoService.getEmailEncryptionKeyForApi();
        expect(result).toBeNull();
      });
    });

    describe('clearEmailEncryptionKey', () => {
      it('should clear email encryption key from both storage types', () => {
        const key = new Uint8Array(32);
        const keyB64 = cryptoService.uint8ArrayToBase64(key);
        
        mockStorage.localStorage.set('openmates_email_encryption_key', keyB64);
        mockStorage.sessionStorage.set('openmates_email_encryption_key', keyB64);
        
        cryptoService.clearEmailEncryptionKey();
        
        expect(mockStorage.localStorage.has('openmates_email_encryption_key')).toBe(false);
        expect(mockStorage.sessionStorage.has('openmates_email_encryption_key')).toBe(false);
      });
    });
  });

  describe('Email Storage Management', () => {
    describe('saveEmailEncryptedWithMasterKey', () => {
      it('should save encrypted email with master key', () => {
        const masterKey = new Uint8Array(32);
        const keyB64 = cryptoService.uint8ArrayToBase64(masterKey);
        mockStorage.localStorage.set('openmates_master_key_persistent', keyB64);
        
        const email = 'test@example.com';
        const result = cryptoService.saveEmailEncryptedWithMasterKey(email);
        
        expect(result).toBe(true);
        expect(mockStorage.localStorage.has('openmates_email_encrypted_master')).toBe(true);
      });

      it('should return false when master key not available', () => {
        const email = 'test@example.com';
        const result = cryptoService.saveEmailEncryptedWithMasterKey(email);
        
        expect(result).toBe(false);
      });
    });

    describe('getEmailDecryptedWithMasterKey', () => {
      it('should retrieve and decrypt email with master key', () => {
        const masterKey = new Uint8Array(32);
        const keyB64 = cryptoService.uint8ArrayToBase64(masterKey);
        mockStorage.localStorage.set('openmates_master_key_persistent', keyB64);
        
        const email = 'test@example.com';
        cryptoService.saveEmailEncryptedWithMasterKey(email);
        
        const result = cryptoService.getEmailDecryptedWithMasterKey();
        expect(result).toBe(email);
      });

      it('should return null when no encrypted email found', () => {
        const result = cryptoService.getEmailDecryptedWithMasterKey();
        expect(result).toBeNull();
      });
    });

    describe('clearEmailEncryptedWithMasterKey', () => {
      it('should clear encrypted email from both storage types', () => {
        const masterKey = new Uint8Array(32);
        const keyB64 = cryptoService.uint8ArrayToBase64(masterKey);
        mockStorage.localStorage.set('openmates_master_key_persistent', keyB64);
        
        const email = 'test@example.com';
        cryptoService.saveEmailEncryptedWithMasterKey(email);
        
        cryptoService.clearEmailEncryptedWithMasterKey();
        
        expect(mockStorage.localStorage.has('openmates_email_encrypted_master')).toBe(false);
        expect(mockStorage.sessionStorage.has('openmates_email_encrypted_master')).toBe(false);
      });
    });

    describe('clearAllEmailData', () => {
      it('should clear all email-related data', () => {
        // Set up some email data
        const key = new Uint8Array(32);
        const keyB64 = cryptoService.uint8ArrayToBase64(key);
        
        mockStorage.localStorage.set('openmates_email_encryption_key', keyB64);
        mockStorage.localStorage.set('openmates_email_encrypted_master', 'encrypted-email');
        mockStorage.localStorage.set('openmates_email_salt', 'salt-data');
        
        cryptoService.clearAllEmailData();
        
        expect(mockStorage.localStorage.has('openmates_email_encryption_key')).toBe(false);
        expect(mockStorage.localStorage.has('openmates_email_encrypted_master')).toBe(false);
        expect(mockStorage.localStorage.has('openmates_email_salt')).toBe(false);
      });
    });
  });

  describe('Email Salt Management', () => {
    describe('saveEmailSalt', () => {
      it('should save email salt to sessionStorage by default', () => {
        const salt = new Uint8Array(16);
        cryptoService.saveEmailSalt(salt);
        
        expect(mockStorage.sessionStorage.has('openmates_email_salt')).toBe(true);
        expect(mockStorage.localStorage.has('openmates_email_salt')).toBe(false);
      });

      it('should save email salt to localStorage when requested', () => {
        const salt = new Uint8Array(16);
        cryptoService.saveEmailSalt(salt, true);
        
        expect(mockStorage.localStorage.has('openmates_email_salt')).toBe(true);
        expect(mockStorage.sessionStorage.has('openmates_email_salt')).toBe(false);
      });
    });

    describe('getEmailSalt', () => {
      it('should retrieve email salt from localStorage first', () => {
        const salt = new Uint8Array(16);
        const saltB64 = cryptoService.uint8ArrayToBase64(salt);
        
        mockStorage.localStorage.set('openmates_email_salt', saltB64);
        
        const result = cryptoService.getEmailSalt();
        expect(result).toEqual(salt);
      });

      it('should fallback to sessionStorage', () => {
        const salt = new Uint8Array(16);
        const saltB64 = cryptoService.uint8ArrayToBase64(salt);
        
        mockStorage.sessionStorage.set('openmates_email_salt', saltB64);
        
        const result = cryptoService.getEmailSalt();
        expect(result).toEqual(salt);
      });

      it('should return null when no salt found', () => {
        const result = cryptoService.getEmailSalt();
        expect(result).toBeNull();
      });
    });

    describe('clearEmailSalt', () => {
      it('should clear email salt from both storage types', () => {
        const salt = new Uint8Array(16);
        const saltB64 = cryptoService.uint8ArrayToBase64(salt);
        
        mockStorage.localStorage.set('openmates_email_salt', saltB64);
        mockStorage.sessionStorage.set('openmates_email_salt', saltB64);
        
        cryptoService.clearEmailSalt();
        
        expect(mockStorage.localStorage.has('openmates_email_salt')).toBe(false);
        expect(mockStorage.sessionStorage.has('openmates_email_salt')).toBe(false);
      });
    });
  });

  describe('Chat-Specific Encryption', () => {
    describe('generateChatKey', () => {
      it('should generate chat key of correct length', () => {
        const key = cryptoService.generateChatKey();
        expect(key).toBeInstanceOf(Uint8Array);
        expect(key.length).toBe(32); // 256-bit key
      });

      it('should generate different keys each time', () => {
        const key1 = cryptoService.generateChatKey();
        const key2 = cryptoService.generateChatKey();
        expect(key1).not.toEqual(key2);
      });
    });

    describe('encryptWithChatKey', () => {
      it('should encrypt data with chat key', () => {
        const data = 'test data';
        const chatKey = new Uint8Array(32);
        
        const result = cryptoService.encryptWithChatKey(data, chatKey);
        
        expect(result).toBeDefined();
        expect(typeof result).toBe('string');
        expect(result.length).toBeGreaterThan(0);
      });

      it('should produce different encrypted data for same input', () => {
        const data = 'test data';
        const chatKey = new Uint8Array(32);
        
        const result1 = cryptoService.encryptWithChatKey(data, chatKey);
        const result2 = cryptoService.encryptWithChatKey(data, chatKey);
        
        expect(result1).not.toEqual(result2); // Different nonces
      });
    });

    describe('decryptWithChatKey', () => {
      it('should decrypt data with correct chat key', () => {
        const data = 'test data';
        const chatKey = new Uint8Array(32);
        
        const encrypted = cryptoService.encryptWithChatKey(data, chatKey);
        const decrypted = cryptoService.decryptWithChatKey(encrypted, chatKey);
        
        expect(decrypted).toBe(data);
      });

      it('should return null with incorrect chat key', () => {
        const data = 'test data';
        const chatKey = new Uint8Array(32);
        const wrongKey = new Uint8Array(32);
        
        const encrypted = cryptoService.encryptWithChatKey(data, chatKey);
        const decrypted = cryptoService.decryptWithChatKey(encrypted, wrongKey);
        
        expect(decrypted).toBeNull();
      });

      it('should return null with invalid encrypted data', () => {
        const chatKey = new Uint8Array(32);
        const decrypted = cryptoService.decryptWithChatKey('invalid-data', chatKey);
        
        expect(decrypted).toBeNull();
      });
    });

    describe('encryptChatKeyWithMasterKey', () => {
      it('should encrypt chat key with master key from storage', () => {
        const masterKey = new Uint8Array(32);
        const keyB64 = cryptoService.uint8ArrayToBase64(masterKey);
        mockStorage.localStorage.set('openmates_master_key_persistent', keyB64);
        
        const chatKey = new Uint8Array(32);
        const result = cryptoService.encryptChatKeyWithMasterKey(chatKey);
        
        expect(result).toBeDefined();
        expect(typeof result).toBe('string');
        expect(result.length).toBeGreaterThan(0);
      });

      it('should return null when master key not found', () => {
        const chatKey = new Uint8Array(32);
        const result = cryptoService.encryptChatKeyWithMasterKey(chatKey);
        
        expect(result).toBeNull();
      });
    });

    describe('decryptChatKeyWithMasterKey', () => {
      it('should decrypt chat key with master key from storage', () => {
        const masterKey = new Uint8Array(32);
        const keyB64 = cryptoService.uint8ArrayToBase64(masterKey);
        mockStorage.localStorage.set('openmates_master_key_persistent', keyB64);
        
        const chatKey = new Uint8Array(32);
        const encrypted = cryptoService.encryptChatKeyWithMasterKey(chatKey);
        expect(encrypted).not.toBeNull();
        
        const decrypted = cryptoService.decryptChatKeyWithMasterKey(encrypted!);
        expect(decrypted).toEqual(chatKey);
      });

      it('should return null when master key not found', () => {
        const encrypted = 'some-encrypted-chat-key';
        const result = cryptoService.decryptChatKeyWithMasterKey(encrypted);
        
        expect(result).toBeNull();
      });

      it('should return null with invalid encrypted data', () => {
        const masterKey = new Uint8Array(32);
        const keyB64 = cryptoService.uint8ArrayToBase64(masterKey);
        mockStorage.localStorage.set('openmates_master_key_persistent', keyB64);
        
        const result = cryptoService.decryptChatKeyWithMasterKey('invalid-data');
        expect(result).toBeNull();
      });
    });

    describe('encryptArrayWithChatKey', () => {
      it('should encrypt array with chat key', () => {
        const array = ['item1', 'item2', 'item3'];
        const chatKey = new Uint8Array(32);
        
        const result = cryptoService.encryptArrayWithChatKey(array, chatKey);
        
        expect(result).toBeDefined();
        expect(typeof result).toBe('string');
        expect(result.length).toBeGreaterThan(0);
      });
    });

    describe('decryptArrayWithChatKey', () => {
      it('should decrypt array with correct chat key', () => {
        const array = ['item1', 'item2', 'item3'];
        const chatKey = new Uint8Array(32);
        
        const encrypted = cryptoService.encryptArrayWithChatKey(array, chatKey);
        const decrypted = cryptoService.decryptArrayWithChatKey(encrypted, chatKey);
        
        expect(decrypted).toEqual(array);
      });

      it('should return null with incorrect chat key', () => {
        const array = ['item1', 'item2', 'item3'];
        const chatKey = new Uint8Array(32);
        const wrongKey = new Uint8Array(32);
        
        const encrypted = cryptoService.encryptArrayWithChatKey(array, chatKey);
        const decrypted = cryptoService.decryptArrayWithChatKey(encrypted, wrongKey);
        
        expect(decrypted).toBeNull();
      });

      it('should return null with invalid encrypted data', () => {
        const chatKey = new Uint8Array(32);
        const decrypted = cryptoService.decryptArrayWithChatKey('invalid-data', chatKey);
        
        expect(decrypted).toBeNull();
      });

      it('should return null with invalid JSON', () => {
        const chatKey = new Uint8Array(32);
        const invalidJson = 'invalid-json';
        
        // Encrypt some data first
        const encrypted = cryptoService.encryptWithChatKey(invalidJson, chatKey);
        
        // Try to decrypt as array (should fail JSON parsing)
        const decrypted = cryptoService.decryptArrayWithChatKey(encrypted, chatKey);
        
        expect(decrypted).toBeNull();
      });
    });
  });

  describe('Recovery Key Management', () => {
    describe('generateSecureRecoveryKey', () => {
      it('should generate recovery key of specified length', () => {
        const key = cryptoService.generateSecureRecoveryKey(24);
        expect(typeof key).toBe('string');
        expect(key.length).toBe(24);
      });

      it('should generate recovery key of default length', () => {
        const key = cryptoService.generateSecureRecoveryKey();
        expect(typeof key).toBe('string');
        expect(key.length).toBe(24);
      });

      it('should generate different keys each time', () => {
        const key1 = cryptoService.generateSecureRecoveryKey(24);
        const key2 = cryptoService.generateSecureRecoveryKey(24);
        expect(key1).not.toEqual(key2);
      });

      it('should contain characters from all character sets', () => {
        const key = cryptoService.generateSecureRecoveryKey(24);
        
        // Check for uppercase (excluding I and O)
        expect(key).toMatch(/[ABCDEFGHJKLMNPQRSTUVWXYZ]/);
        
        // Check for lowercase (excluding l)
        expect(key).toMatch(/[abcdefghijkmnopqrstuvwxyz]/);
        
        // Check for numbers (excluding 0 and 1)
        expect(key).toMatch(/[23456789]/);
        
        // Check for special characters
        expect(key).toMatch(/[#-=+_&%$]/);
      });
    });

    describe('hashKey', () => {
      it('should hash key without salt', async () => {
        const key = 'test-key';
        
        // Mock crypto.subtle.digest
        const mockDigest = vi.fn().mockResolvedValue(new ArrayBuffer(32));
        Object.defineProperty(crypto.subtle, 'digest', {
          value: mockDigest,
          writable: true,
        });
        
        const result = await cryptoService.hashKey(key);
        
        expect(result).toBeDefined();
        expect(typeof result).toBe('string');
        expect(mockDigest).toHaveBeenCalledWith('SHA-256', expect.any(Uint8Array));
      });

      it('should hash key with salt', async () => {
        const key = 'test-key';
        const salt = new Uint8Array(16);
        
        // Mock crypto.subtle.digest
        const mockDigest = vi.fn().mockResolvedValue(new ArrayBuffer(32));
        Object.defineProperty(crypto.subtle, 'digest', {
          value: mockDigest,
          writable: true,
        });
        
        const result = await cryptoService.hashKey(key, salt);
        
        expect(result).toBeDefined();
        expect(typeof result).toBe('string');
        expect(mockDigest).toHaveBeenCalledWith('SHA-256', expect.any(Uint8Array));
      });

      it('should produce different hashes for different keys', async () => {
        // Mock crypto.subtle.digest
        const mockDigest = vi.fn()
          .mockResolvedValueOnce(new ArrayBuffer(32))
          .mockResolvedValueOnce(new ArrayBuffer(32));
        Object.defineProperty(crypto.subtle, 'digest', {
          value: mockDigest,
          writable: true,
        });
        
        const hash1 = await cryptoService.hashKey('key1');
        const hash2 = await cryptoService.hashKey('key2');
        
        expect(hash1).not.toEqual(hash2);
      });
    });
  });

  describe('Edge Cases and Error Handling', () => {
    it('should handle empty strings gracefully', () => {
      const masterKey = new Uint8Array(32);
      const keyB64 = cryptoService.uint8ArrayToBase64(masterKey);
      mockStorage.localStorage.set('openmates_master_key_persistent', keyB64);
      
      const encrypted = cryptoService.encryptWithMasterKey('');
      expect(encrypted).toBeDefined();
      
      const decrypted = cryptoService.decryptWithMasterKey(encrypted!);
      expect(decrypted).toBe('');
    });

    it('should handle special characters in data', () => {
      const masterKey = new Uint8Array(32);
      const keyB64 = cryptoService.uint8ArrayToBase64(masterKey);
      mockStorage.localStorage.set('openmates_master_key_persistent', keyB64);
      
      const specialData = 'Special chars: !@#$%^&*()_+-=[]{}|;:,.<>?';
      const encrypted = cryptoService.encryptWithMasterKey(specialData);
      expect(encrypted).toBeDefined();
      
      const decrypted = cryptoService.decryptWithMasterKey(encrypted!);
      expect(decrypted).toBe(specialData);
    });

    it('should handle unicode characters', () => {
      const masterKey = new Uint8Array(32);
      const keyB64 = cryptoService.uint8ArrayToBase64(masterKey);
      mockStorage.localStorage.set('openmates_master_key_persistent', keyB64);
      
      const unicodeData = 'Unicode: 🚀 🌟 💫 🎉';
      const encrypted = cryptoService.encryptWithMasterKey(unicodeData);
      expect(encrypted).toBeDefined();
      
      const decrypted = cryptoService.decryptWithMasterKey(encrypted!);
      expect(decrypted).toBe(unicodeData);
    });

    it('should handle large data', () => {
      const masterKey = new Uint8Array(32);
      const keyB64 = cryptoService.uint8ArrayToBase64(masterKey);
      mockStorage.localStorage.set('openmates_master_key_persistent', keyB64);
      
      const largeData = 'x'.repeat(10000); // 10KB of data
      const encrypted = cryptoService.encryptWithMasterKey(largeData);
      expect(encrypted).toBeDefined();
      
      const decrypted = cryptoService.decryptWithMasterKey(encrypted!);
      expect(decrypted).toBe(largeData);
    });

    it('should handle null and undefined gracefully', () => {
      const masterKey = new Uint8Array(32);
      const keyB64 = cryptoService.uint8ArrayToBase64(masterKey);
      mockStorage.localStorage.set('openmates_master_key_persistent', keyB64);
      
      // These should not throw errors
      expect(() => cryptoService.encryptWithMasterKey(null as any)).not.toThrow();
      expect(() => cryptoService.encryptWithMasterKey(undefined as any)).not.toThrow();
    });
  });

  describe('Integration Tests', () => {
    it('should perform complete encryption/decryption cycle', () => {
      // Generate master key
      const masterKey = cryptoService.generateUserMasterKey();
      cryptoService.saveKeyToSession(masterKey, true);
      
      // Generate email salt and encryption key
      const emailSalt = cryptoService.generateEmailSalt();
      cryptoService.saveEmailSalt(emailSalt, true);
      
      // Encrypt email
      const email = 'test@example.com';
      cryptoService.saveEmailEncryptedWithMasterKey(email);
      
      // Generate chat key
      const chatKey = cryptoService.generateChatKey();
      const encryptedChatKey = cryptoService.encryptChatKeyWithMasterKey(chatKey);
      expect(encryptedChatKey).not.toBeNull();
      
      // Encrypt some chat data
      const chatData = 'chat message';
      const encryptedChatData = cryptoService.encryptWithChatKey(chatData, chatKey);
      
      // Decrypt everything back
      const decryptedEmail = cryptoService.getEmailDecryptedWithMasterKey();
      expect(decryptedEmail).toBe(email);
      
      const decryptedChatKey = cryptoService.decryptChatKeyWithMasterKey(encryptedChatKey!);
      expect(decryptedChatKey).toEqual(chatKey);
      
      const decryptedChatData = cryptoService.decryptWithChatKey(encryptedChatData, decryptedChatKey!);
      expect(decryptedChatData).toBe(chatData);
    });

    it('should handle multiple chat keys independently', () => {
      const masterKey = cryptoService.generateUserMasterKey();
      cryptoService.saveKeyToSession(masterKey, true);
      
      // Generate multiple chat keys
      const chatKey1 = cryptoService.generateChatKey();
      const chatKey2 = cryptoService.generateChatKey();
      
      // Encrypt different data with different keys
      const data1 = 'chat 1 message';
      const data2 = 'chat 2 message';
      
      const encrypted1 = cryptoService.encryptWithChatKey(data1, chatKey1);
      const encrypted2 = cryptoService.encryptWithChatKey(data2, chatKey2);
      
      // Verify keys are independent
      const decrypted1 = cryptoService.decryptWithChatKey(encrypted1, chatKey1);
      const decrypted2 = cryptoService.decryptWithChatKey(encrypted2, chatKey2);
      
      expect(decrypted1).toBe(data1);
      expect(decrypted2).toBe(data2);
      
      // Verify cross-decryption fails
      const crossDecrypt1 = cryptoService.decryptWithChatKey(encrypted1, chatKey2);
      const crossDecrypt2 = cryptoService.decryptWithChatKey(encrypted2, chatKey1);
      
      expect(crossDecrypt1).toBeNull();
      expect(crossDecrypt2).toBeNull();
    });
  });
});