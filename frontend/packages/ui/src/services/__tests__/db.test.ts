/**
 * Comprehensive unit tests for the database service (db.ts).
 * 
 * Tests the zero-knowledge encryption architecture including:
 * - Chat encryption/decryption for storage
 * - Message encryption/decryption with chat-specific keys
 * - Chat key management and caching
 * - Database operations with encrypted data
 * - Data integrity and security
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { chatDB } from '../db';
import * as cryptoService from '../cryptoService';
import type { Chat, Message } from '../../types/chat';

// Mock IndexedDB
const mockIndexedDB = {
  open: vi.fn(),
  deleteDatabase: vi.fn(),
};

// Mock IDBDatabase
const mockDatabase = {
  transaction: vi.fn(),
  objectStoreNames: {
    contains: vi.fn().mockReturnValue(true),
  },
  close: vi.fn(),
};

// Mock IDBObjectStore
const mockObjectStore = {
  put: vi.fn(),
  get: vi.fn(),
  delete: vi.fn(),
  clear: vi.fn(),
  createIndex: vi.fn(),
  indexNames: {
    contains: vi.fn().mockReturnValue(true),
  },
  deleteIndex: vi.fn(),
  openCursor: vi.fn(),
  index: vi.fn().mockReturnValue({
    openCursor: vi.fn(),
    getAll: vi.fn(),
  }),
};

// Mock IDBTransaction
const mockTransaction = {
  objectStore: vi.fn().mockReturnValue(mockObjectStore),
  oncomplete: null,
  onerror: null,
  abort: vi.fn(),
};

// Mock IDBRequest
const mockRequest = {
  result: null,
  error: null,
  onsuccess: null,
  onerror: null,
};

// Mock IDBCursor
const mockCursor = {
  value: null,
  continue: vi.fn(),
  update: vi.fn(),
  delete: vi.fn(),
};

// Mock crypto.randomUUID
Object.defineProperty(global, 'crypto', {
  value: {
    randomUUID: vi.fn(() => 'test-uuid-123'),
  },
  writable: true,
});

// Mock IndexedDB globally
Object.defineProperty(global, 'indexedDB', {
  value: mockIndexedDB,
  writable: true,
});

describe('ChatDatabase', () => {
  beforeEach(() => {
    // Reset all mocks
    vi.clearAllMocks();
    
    // Setup default mock implementations
    mockIndexedDB.open.mockImplementation(() => {
      const request = { ...mockRequest };
      setTimeout(() => {
        request.result = mockDatabase;
        if (request.onsuccess) request.onsuccess({ target: request });
      }, 0);
      return request;
    });
    
    mockDatabase.transaction.mockReturnValue(mockTransaction);
    mockObjectStore.put.mockImplementation(() => {
      const request = { ...mockRequest };
      setTimeout(() => {
        request.result = 'success';
        if (request.onsuccess) request.onsuccess({ target: request });
      }, 0);
      return request;
    });
    
    mockObjectStore.get.mockImplementation(() => {
      const request = { ...mockRequest };
      setTimeout(() => {
        request.result = null;
        if (request.onsuccess) request.onsuccess({ target: request });
      }, 0);
      return request;
    });
    
    mockObjectStore.openCursor.mockImplementation(() => {
      const request = { ...mockRequest };
      setTimeout(() => {
        request.result = null; // No more cursors
        if (request.onsuccess) request.onsuccess({ target: request });
      }, 0);
      return request;
    });
    
    // Mock crypto service functions
    vi.spyOn(cryptoService, 'encryptWithMasterKey').mockReturnValue('encrypted-title');
    vi.spyOn(cryptoService, 'decryptWithMasterKey').mockReturnValue('decrypted-title');
    vi.spyOn(cryptoService, 'generateChatKey').mockReturnValue(new Uint8Array(32));
    vi.spyOn(cryptoService, 'encryptWithChatKey').mockReturnValue('encrypted-data');
    vi.spyOn(cryptoService, 'decryptWithChatKey').mockReturnValue('decrypted-data');
    vi.spyOn(cryptoService, 'encryptArrayWithChatKey').mockReturnValue('encrypted-array');
    vi.spyOn(cryptoService, 'decryptArrayWithChatKey').mockReturnValue(['mate1', 'mate2']);
    vi.spyOn(cryptoService, 'encryptChatKeyWithMasterKey').mockReturnValue('encrypted-chat-key');
    vi.spyOn(cryptoService, 'decryptChatKeyWithMasterKey').mockReturnValue(new Uint8Array(32));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('Initialization', () => {
    it('should initialize database successfully', async () => {
      await chatDB.init();
      expect(mockIndexedDB.open).toHaveBeenCalledWith('chats_db', 9);
    });

    it('should handle database initialization error', async () => {
      mockIndexedDB.open.mockImplementation(() => {
        const request = { ...mockRequest };
        setTimeout(() => {
          request.error = new Error('Database error');
          if (request.onerror) request.onerror({ target: request });
        }, 0);
        return request;
      });

      await expect(chatDB.init()).rejects.toThrow('Database error');
    });
  });

  describe('Chat Encryption/Decryption', () => {
    let testChat: Chat;

    beforeEach(() => {
      testChat = {
        chat_id: 'test-chat-123',
        title: 'Test Chat',
        encrypted_title: null,
        messages_v: 0,
        title_v: 0,
        last_edited_overall_timestamp: Date.now() / 1000,
        unread_count: 0,
        mates: ['software_development', 'medical_health'],
        created_at: Date.now() / 1000,
        updated_at: Date.now() / 1000,
      };
    });

    describe('encryptChatForStorage', () => {
      it('should encrypt chat title with master key', () => {
        const encryptedChat = (chatDB as any).encryptChatForStorage(testChat);
        
        expect(encryptedChat.title).toBeNull(); // Cleartext title should be cleared
        expect(encryptedChat.encrypted_title).toBe('encrypted-title');
        expect(cryptoService.encryptWithMasterKey).toHaveBeenCalledWith('Test Chat');
      });

      it('should generate and encrypt chat key for future use', () => {
        const encryptedChat = (chatDB as any).encryptChatForStorage(testChat);
        
        expect(encryptedChat.encrypted_chat_key).toBe('encrypted-chat-key');
        expect(cryptoService.encryptChatKeyWithMasterKey).toHaveBeenCalledWith(
          expect.any(Uint8Array)
        );
      });

      it('should handle chat without title', () => {
        const chatWithoutTitle = { ...testChat, title: null };
        const encryptedChat = (chatDB as any).encryptChatForStorage(chatWithoutTitle);
        
        expect(encryptedChat.encrypted_title).toBeUndefined();
        expect(cryptoService.encryptWithMasterKey).not.toHaveBeenCalled();
      });

      it('should handle chat without mates', () => {
        const chatWithoutMates = { ...testChat, mates: null };
        const encryptedChat = (chatDB as any).encryptChatForStorage(chatWithoutMates);
        
        // Chat key should still be generated for future encrypted fields
        expect(encryptedChat.encrypted_chat_key).toBe('encrypted-chat-key');
      });

      it('should throw error when master key not available for title encryption', () => {
        vi.spyOn(cryptoService, 'encryptWithMasterKey').mockReturnValue(null);
        
        expect(() => (chatDB as any).encryptChatForStorage(testChat)).toThrow(
          'Failed to encrypt chat title - master key not available'
        );
      });
    });

    describe('decryptChatFromStorage', () => {
      let encryptedChat: Chat;

      beforeEach(() => {
        encryptedChat = {
          chat_id: 'test-chat-123',
          title: null,
          encrypted_title: 'encrypted-title',
          messages_v: 0,
          title_v: 0,
          last_edited_overall_timestamp: Date.now() / 1000,
          unread_count: 0,
          mates: null,
          encrypted_chat_key: 'encrypted-chat-key',
          created_at: Date.now() / 1000,
          updated_at: Date.now() / 1000,
        };
      });

      it('should decrypt chat title from storage', () => {
        const decryptedChat = (chatDB as any).decryptChatFromStorage(encryptedChat);
        
        expect(decryptedChat.title).toBe('decrypted-title');
        expect(decryptedChat.encrypted_title).toBeNull(); // Encrypted field should be cleared
        expect(cryptoService.decryptWithMasterKey).toHaveBeenCalledWith('encrypted-title');
      });

      it('should decrypt chat key for future use', () => {
        const decryptedChat = (chatDB as any).decryptChatFromStorage(encryptedChat);
        
        expect(cryptoService.decryptChatKeyWithMasterKey).toHaveBeenCalledWith(
          'encrypted-chat-key'
        );
        // Chat key should be stored in memory for future encrypted field decryption
      });

      it('should handle chat without encrypted title', () => {
        const chatWithoutEncryptedTitle = { ...encryptedChat, encrypted_title: null };
        const decryptedChat = (chatDB as any).decryptChatFromStorage(chatWithoutEncryptedTitle);
        
        expect(decryptedChat.title).toBeUndefined();
        expect(cryptoService.decryptWithMasterKey).not.toHaveBeenCalled();
      });

      it('should handle chat without encrypted chat key', () => {
        const chatWithoutEncryptedKey = { ...encryptedChat, encrypted_chat_key: null };
        const decryptedChat = (chatDB as any).decryptChatFromStorage(chatWithoutEncryptedKey);
        
        expect(cryptoService.decryptChatKeyWithMasterKey).not.toHaveBeenCalled();
      });

      it('should handle decryption failure gracefully', () => {
        vi.spyOn(cryptoService, 'decryptWithMasterKey').mockReturnValue(null);
        
        const decryptedChat = (chatDB as any).decryptChatFromStorage(encryptedChat);
        
        expect(decryptedChat.title).toBeUndefined();
      });
    });
  });

  describe('Message Encryption/Decryption', () => {
    let testMessage: Message;
    let testChatId: string;

    beforeEach(() => {
      testChatId = 'test-chat-123';
      testMessage = {
        message_id: 'test-message-123',
        chat_id: testChatId,
        role: 'user',
        content: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Hello world' }] }] },
        created_at: Date.now() / 1000,
        status: 'synced',
        sender_name: 'John Doe',
        category: 'software_development',
      };
    });

    describe('encryptMessageFields', () => {
      it('should encrypt message content with chat-specific key', () => {
        const encryptedMessage = chatDB.encryptMessageFields(testMessage, testChatId);
        
        expect(encryptedMessage.content).toEqual(testMessage.content); // Plaintext content preserved for AI
        expect(encryptedMessage.encrypted_content).toBe('encrypted-data');
        expect(cryptoService.encryptWithChatKey).toHaveBeenCalledWith(
          JSON.stringify(testMessage.content),
          expect.any(Uint8Array)
        );
      });

      it('should encrypt sender name with chat-specific key', () => {
        const encryptedMessage = chatDB.encryptMessageFields(testMessage, testChatId);
        
        expect(encryptedMessage.sender_name).toBe('John Doe'); // Plaintext preserved for AI
        expect(encryptedMessage.encrypted_sender_name).toBe('encrypted-data');
        expect(cryptoService.encryptWithChatKey).toHaveBeenCalledWith(
          'John Doe',
          expect.any(Uint8Array)
        );
      });

      it('should encrypt category with chat-specific key', () => {
        const encryptedMessage = chatDB.encryptMessageFields(testMessage, testChatId);
        
        expect(encryptedMessage.category).toBe('software_development'); // Plaintext preserved for AI
        expect(encryptedMessage.encrypted_category).toBe('encrypted-data');
        expect(cryptoService.encryptWithChatKey).toHaveBeenCalledWith(
          'software_development',
          expect.any(Uint8Array)
        );
      });

      it('should handle message without optional fields', () => {
        const messageWithoutOptionalFields = {
          ...testMessage,
          sender_name: undefined,
          category: undefined,
        };
        
        const encryptedMessage = chatDB.encryptMessageFields(messageWithoutOptionalFields, testChatId);
        
        expect(encryptedMessage.encrypted_sender_name).toBeUndefined();
        expect(encryptedMessage.encrypted_category).toBeUndefined();
      });

      it('should generate chat key if not cached', () => {
        chatDB.encryptMessageFields(testMessage, testChatId);
        
        expect(cryptoService.generateChatKey).toHaveBeenCalled();
      });
    });

    describe('decryptMessageFields', () => {
      let encryptedMessage: Message;

      beforeEach(() => {
        encryptedMessage = {
          message_id: 'test-message-123',
          chat_id: testChatId,
          role: 'user',
          content: null,
          encrypted_content: 'encrypted-content',
          created_at: Date.now() / 1000,
          status: 'synced',
          sender_name: null,
          encrypted_sender_name: 'encrypted-sender-name',
          category: null,
          encrypted_category: 'encrypted-category',
        };
      });

      it('should decrypt message content with chat-specific key', () => {
        const decryptedMessage = chatDB.decryptMessageFields(encryptedMessage, testChatId);
        
        expect(decryptedMessage.content).toEqual({ type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Hello world' }] }] });
        expect(decryptedMessage.encrypted_content).toBeUndefined(); // Encrypted field should be cleared
        expect(cryptoService.decryptWithChatKey).toHaveBeenCalledWith(
          'encrypted-content',
          expect.any(Uint8Array)
        );
      });

      it('should decrypt sender name with chat-specific key', () => {
        const decryptedMessage = chatDB.decryptMessageFields(encryptedMessage, testChatId);
        
        expect(decryptedMessage.sender_name).toBe('decrypted-data');
        expect(decryptedMessage.encrypted_sender_name).toBeUndefined(); // Encrypted field should be cleared
        expect(cryptoService.decryptWithChatKey).toHaveBeenCalledWith(
          'encrypted-sender-name',
          expect.any(Uint8Array)
        );
      });

      it('should decrypt category with chat-specific key', () => {
        const decryptedMessage = chatDB.decryptMessageFields(encryptedMessage, testChatId);
        
        expect(decryptedMessage.category).toBe('decrypted-data');
        expect(decryptedMessage.encrypted_category).toBeUndefined(); // Encrypted field should be cleared
        expect(cryptoService.decryptWithChatKey).toHaveBeenCalledWith(
          'encrypted-category',
          expect.any(Uint8Array)
        );
      });

      it('should handle message without encrypted fields', () => {
        const messageWithoutEncryptedFields = {
          ...encryptedMessage,
          encrypted_content: undefined,
          encrypted_sender_name: undefined,
          encrypted_category: undefined,
        };
        
        const decryptedMessage = chatDB.decryptMessageFields(messageWithoutEncryptedFields, testChatId);
        
        expect(decryptedMessage.content).toBeUndefined();
        expect(decryptedMessage.sender_name).toBeUndefined();
        expect(decryptedMessage.category).toBeUndefined();
      });

      it('should handle missing chat key gracefully', () => {
        // Clear chat key cache
        chatDB.clearAllChatKeys();
        
        const decryptedMessage = chatDB.decryptMessageFields(encryptedMessage, testChatId);
        
        expect(decryptedMessage.content).toBeUndefined();
        expect(decryptedMessage.sender_name).toBeUndefined();
        expect(decryptedMessage.category).toBeUndefined();
      });

      it('should handle decryption failure gracefully', () => {
        vi.spyOn(cryptoService, 'decryptWithChatKey').mockReturnValue(null);
        
        const decryptedMessage = chatDB.decryptMessageFields(encryptedMessage, testChatId);
        
        expect(decryptedMessage.content).toBeUndefined();
        expect(decryptedMessage.sender_name).toBeUndefined();
        expect(decryptedMessage.category).toBeUndefined();
      });

      it('should handle JSON parsing error gracefully', () => {
        vi.spyOn(cryptoService, 'decryptWithChatKey').mockReturnValue('invalid-json');
        vi.spyOn(JSON, 'parse').mockImplementation(() => {
          throw new Error('Invalid JSON');
        });
        
        const decryptedMessage = chatDB.decryptMessageFields(encryptedMessage, testChatId);
        
        expect(decryptedMessage.content).toBeUndefined();
      });
    });
  });

  describe('Chat Key Management', () => {
    describe('getOrGenerateChatKey', () => {
      it('should generate new chat key if not cached', () => {
        const chatId = 'test-chat-123';
        const chatKey = chatDB.getOrGenerateChatKey(chatId);
        
        expect(chatKey).toBeInstanceOf(Uint8Array);
        expect(chatKey.length).toBe(32);
        expect(cryptoService.generateChatKey).toHaveBeenCalled();
      });

      it('should return cached chat key if available', () => {
        const chatId = 'test-chat-123';
        const firstKey = chatDB.getOrGenerateChatKey(chatId);
        const secondKey = chatDB.getOrGenerateChatKey(chatId);
        
        expect(firstKey).toBe(secondKey);
        expect(cryptoService.generateChatKey).toHaveBeenCalledTimes(1);
      });

      it('should return different keys for different chats', () => {
        const chatId1 = 'test-chat-123';
        const chatId2 = 'test-chat-456';
        
        const key1 = chatDB.getOrGenerateChatKey(chatId1);
        const key2 = chatDB.getOrGenerateChatKey(chatId2);
        
        expect(key1).not.toEqual(key2);
      });
    });

    describe('clearAllChatKeys', () => {
      it('should clear all cached chat keys', () => {
        const chatId1 = 'test-chat-123';
        const chatId2 = 'test-chat-456';
        
        // Generate keys for multiple chats
        chatDB.getOrGenerateChatKey(chatId1);
        chatDB.getOrGenerateChatKey(chatId2);
        
        // Clear all keys
        chatDB.clearAllChatKeys();
        
        // Generate new keys - should be different
        const newKey1 = chatDB.getOrGenerateChatKey(chatId1);
        const newKey2 = chatDB.getOrGenerateChatKey(chatId2);
        
        expect(cryptoService.generateChatKey).toHaveBeenCalledTimes(4); // 2 before clear + 2 after clear
      });
    });
  });

  describe('Database Operations', () => {
    let testChat: Chat;

    beforeEach(async () => {
      await chatDB.init();
      
      testChat = {
        chat_id: 'test-chat-123',
        title: 'Test Chat',
        encrypted_title: null,
        messages_v: 0,
        title_v: 0,
        last_edited_overall_timestamp: Date.now() / 1000,
        unread_count: 0,
        mates: ['software_development'],
        created_at: Date.now() / 1000,
        updated_at: Date.now() / 1000,
      };
    });

    describe('addChat', () => {
      it('should add chat with encrypted data', async () => {
        await chatDB.addChat(testChat);
        
        expect(mockObjectStore.put).toHaveBeenCalled();
        const putCall = mockObjectStore.put.mock.calls[0][0];
        
        // Verify encrypted data is stored
        expect(putCall.title).toBeNull(); // Cleartext title should be cleared
        expect(putCall.encrypted_title).toBe('encrypted-title');
        expect(putCall.mates).toBeUndefined(); // Plaintext mates should be cleared
        expect(putCall.encrypted_chat_key).toBe('encrypted-chat-key');
      });

      it('should handle addChat error', async () => {
        mockObjectStore.put.mockImplementation(() => {
          const request = { ...mockRequest };
          setTimeout(() => {
            request.error = new Error('Put error');
            if (request.onerror) request.onerror({ target: request });
          }, 0);
          return request;
        });

        await expect(chatDB.addChat(testChat)).rejects.toThrow('Put error');
      });
    });

    describe('getChat', () => {
      it('should retrieve and decrypt chat', async () => {
        const encryptedChat = {
          chat_id: 'test-chat-123',
          title: null,
          encrypted_title: 'encrypted-title',
          messages_v: 0,
          title_v: 0,
          last_edited_overall_timestamp: Date.now() / 1000,
          unread_count: 0,
          mates: null,
          encrypted_chat_key: 'encrypted-chat-key',
          created_at: Date.now() / 1000,
          updated_at: Date.now() / 1000,
        };

        mockObjectStore.get.mockImplementation(() => {
          const request = { ...mockRequest };
          setTimeout(() => {
            request.result = encryptedChat;
            if (request.onsuccess) request.onsuccess({ target: request });
          }, 0);
          return request;
        });

        const result = await chatDB.getChat('test-chat-123');
        
        expect(result).toBeDefined();
        expect(result!.title).toBe('decrypted-title');
        expect(result!.mates).toEqual(['mate1', 'mate2']);
      });

      it('should return null for non-existent chat', async () => {
        mockObjectStore.get.mockImplementation(() => {
          const request = { ...mockRequest };
          setTimeout(() => {
            request.result = null;
            if (request.onsuccess) request.onsuccess({ target: request });
          }, 0);
          return request;
        });

        const result = await chatDB.getChat('non-existent-chat');
        expect(result).toBeNull();
      });
    });

    describe('getAllChats', () => {
      it('should retrieve and decrypt all chats', async () => {
        const encryptedChats = [
          {
            chat_id: 'chat-1',
            encrypted_title: 'encrypted-title-1',
            encrypted_chat_key: 'encrypted-chat-key-1',
          },
          {
            chat_id: 'chat-2',
            encrypted_title: 'encrypted-title-2',
            encrypted_chat_key: 'encrypted-chat-key-2',
          },
        ];

        mockObjectStore.index.mockReturnValue({
          openCursor: vi.fn().mockImplementation(() => {
            let index = 0;
            const request = { ...mockRequest };
            setTimeout(() => {
              if (index < encryptedChats.length) {
                request.result = {
                  value: encryptedChats[index],
                  continue: vi.fn(),
                };
                index++;
              } else {
                request.result = null;
              }
              if (request.onsuccess) request.onsuccess({ target: request });
            }, 0);
            return request;
          }),
        });

        const result = await chatDB.getAllChats();
        
        expect(result).toHaveLength(2);
        expect(result[0].title).toBe('decrypted-title');
        expect(result[1].title).toBe('decrypted-title');
      });
    });

    describe('saveMessage', () => {
      let testMessage: Message;

      beforeEach(() => {
        testMessage = {
          message_id: 'test-message-123',
          chat_id: 'test-chat-123',
          role: 'user',
          content: { type: 'doc', content: [] },
          created_at: Date.now() / 1000,
          status: 'synced',
        };
      });

      it('should save message', async () => {
        await chatDB.saveMessage(testMessage);
        
        expect(mockObjectStore.put).toHaveBeenCalledWith(testMessage);
      });

      it('should handle saveMessage error', async () => {
        mockObjectStore.put.mockImplementation(() => {
          const request = { ...mockRequest };
          setTimeout(() => {
            request.error = new Error('Put error');
            if (request.onerror) request.onerror({ target: request });
          }, 0);
          return request;
        });

        await expect(chatDB.saveMessage(testMessage)).rejects.toThrow('Put error');
      });
    });

    describe('getMessagesForChat', () => {
      it('should retrieve messages for chat', async () => {
        const messages = [
          { message_id: 'msg-1', chat_id: 'test-chat-123', role: 'user' },
          { message_id: 'msg-2', chat_id: 'test-chat-123', role: 'assistant' },
        ];

        mockObjectStore.index.mockReturnValue({
          getAll: vi.fn().mockImplementation(() => {
            const request = { ...mockRequest };
            setTimeout(() => {
              request.result = messages;
              if (request.onsuccess) request.onsuccess({ target: request });
            }, 0);
            return request;
          }),
        });

        const result = await chatDB.getMessagesForChat('test-chat-123');
        
        expect(result).toEqual(messages);
      });
    });

    describe('deleteChat', () => {
      it('should delete chat and its messages', async () => {
        await chatDB.deleteChat('test-chat-123');
        
        expect(mockObjectStore.delete).toHaveBeenCalledWith('test-chat-123');
      });
    });

    describe('clearAllChatData', () => {
      it('should clear all chat data', async () => {
        await chatDB.clearAllChatData();
        
        expect(mockObjectStore.clear).toHaveBeenCalled();
      });
    });

    describe('deleteDatabase', () => {
      it('should delete database', async () => {
        mockIndexedDB.deleteDatabase.mockImplementation(() => {
          const request = { ...mockRequest };
          setTimeout(() => {
            request.result = 'success';
            if (request.onsuccess) request.onsuccess({ target: request });
          }, 0);
          return request;
        });

        await chatDB.deleteDatabase();
        
        expect(mockIndexedDB.deleteDatabase).toHaveBeenCalledWith('chats_db');
        expect(mockDatabase.close).toHaveBeenCalled();
      });
    });
  });

  describe('Draft Management', () => {
    let testChat: Chat;

    beforeEach(async () => {
      await chatDB.init();
      
      testChat = {
        chat_id: 'test-chat-123',
        title: 'Test Chat',
        encrypted_title: null,
        messages_v: 0,
        title_v: 0,
        last_edited_overall_timestamp: Date.now() / 1000,
        unread_count: 0,
        mates: [],
        created_at: Date.now() / 1000,
        updated_at: Date.now() / 1000,
      };
    });

    describe('saveCurrentUserChatDraft', () => {
      it('should save encrypted draft', async () => {
        mockObjectStore.get.mockImplementation(() => {
          const request = { ...mockRequest };
          setTimeout(() => {
            request.result = testChat;
            if (request.onsuccess) request.onsuccess({ target: request });
          }, 0);
          return request;
        });

        await chatDB.saveCurrentUserChatDraft('test-chat-123', 'encrypted-draft-md', 'encrypted-draft-preview');
        
        expect(mockObjectStore.put).toHaveBeenCalled();
        const putCall = mockObjectStore.put.mock.calls[0][0];
        expect(putCall.encrypted_draft_md).toBe('encrypted-draft-md');
        expect(putCall.encrypted_draft_preview).toBe('encrypted-draft-preview');
        expect(putCall.draft_v).toBe(1);
      });

      it('should increment draft version when content changes', async () => {
        const chatWithDraft = { ...testChat, encrypted_draft_md: 'old-draft', draft_v: 1 };
        
        mockObjectStore.get.mockImplementation(() => {
          const request = { ...mockRequest };
          setTimeout(() => {
            request.result = chatWithDraft;
            if (request.onsuccess) request.onsuccess({ target: request });
          }, 0);
          return request;
        });

        await chatDB.saveCurrentUserChatDraft('test-chat-123', 'new-draft', 'new-preview');
        
        const putCall = mockObjectStore.put.mock.calls[0][0];
        expect(putCall.draft_v).toBe(2);
      });

      it('should return null for non-existent chat', async () => {
        mockObjectStore.get.mockImplementation(() => {
          const request = { ...mockRequest };
          setTimeout(() => {
            request.result = null;
            if (request.onsuccess) request.onsuccess({ target: request });
          }, 0);
          return request;
        });

        const result = await chatDB.saveCurrentUserChatDraft('non-existent-chat', 'draft', 'preview');
        expect(result).toBeNull();
      });
    });

    describe('createNewChatWithCurrentUserDraft', () => {
      it('should create new chat with draft', async () => {
        const result = await chatDB.createNewChatWithCurrentUserDraft('encrypted-draft', 'encrypted-preview');
        
        expect(result).toBeDefined();
        expect(result.chat_id).toBe('test-uuid-123');
        expect(result.encrypted_draft_md).toBe('encrypted-draft');
        expect(result.encrypted_draft_preview).toBe('encrypted-preview');
        expect(result.draft_v).toBe(1);
      });
    });

    describe('clearCurrentUserChatDraft', () => {
      it('should clear draft from chat', async () => {
        const chatWithDraft = { ...testChat, encrypted_draft_md: 'draft', draft_v: 1 };
        
        mockObjectStore.get.mockImplementation(() => {
          const request = { ...mockRequest };
          setTimeout(() => {
            request.result = chatWithDraft;
            if (request.onsuccess) request.onsuccess({ target: request });
          }, 0);
          return request;
        });

        const result = await chatDB.clearCurrentUserChatDraft('test-chat-123');
        
        expect(result).toBeDefined();
        expect(result!.encrypted_draft_md).toBeNull();
        expect(result!.encrypted_draft_preview).toBeNull();
        expect(result!.draft_v).toBe(0);
      });
    });
  });

  describe('Offline Changes', () => {
    beforeEach(async () => {
      await chatDB.init();
    });

    describe('addOfflineChange', () => {
      it('should add offline change', async () => {
        const change = {
          change_id: 'change-123',
          chat_id: 'chat-123',
          type: 'title' as const,
          value: 'New Title',
          version_before_edit: 1,
        };

        await chatDB.addOfflineChange(change);
        
        expect(mockObjectStore.put).toHaveBeenCalledWith(change);
      });
    });

    describe('getOfflineChanges', () => {
      it('should retrieve offline changes', async () => {
        const changes = [
          { change_id: 'change-1', chat_id: 'chat-1', type: 'title', value: 'Title 1', version_before_edit: 1 },
          { change_id: 'change-2', chat_id: 'chat-2', type: 'draft', value: 'Draft 2', version_before_edit: 2 },
        ];

        mockObjectStore.getAll.mockImplementation(() => {
          const request = { ...mockRequest };
          setTimeout(() => {
            request.result = changes;
            if (request.onsuccess) request.onsuccess({ target: request });
          }, 0);
          return request;
        });

        const result = await chatDB.getOfflineChanges();
        
        expect(result).toEqual(changes);
      });
    });

    describe('deleteOfflineChange', () => {
      it('should delete offline change', async () => {
        await chatDB.deleteOfflineChange('change-123');
        
        expect(mockObjectStore.delete).toHaveBeenCalledWith('change-123');
      });
    });
  });

  describe('Component Version Management', () => {
    beforeEach(async () => {
      await chatDB.init();
    });

    describe('updateChatComponentVersion', () => {
      it('should update draft version', async () => {
        mockObjectStore.get.mockImplementation(() => {
          const request = { ...mockRequest };
          setTimeout(() => {
            request.result = testChat;
            if (request.onsuccess) request.onsuccess({ target: request });
          }, 0);
          return request;
        });

        await chatDB.updateChatComponentVersion('test-chat-123', 'draft_v', 5);
        
        const putCall = mockObjectStore.put.mock.calls[0][0];
        expect(putCall.draft_v).toBe(5);
      });

      it('should update messages version', async () => {
        mockObjectStore.get.mockImplementation(() => {
          const request = { ...mockRequest };
          setTimeout(() => {
            request.result = testChat;
            if (request.onsuccess) request.onsuccess({ target: request });
          }, 0);
          return request;
        });

        await chatDB.updateChatComponentVersion('test-chat-123', 'messages_v', 10);
        
        const putCall = mockObjectStore.put.mock.calls[0][0];
        expect(putCall.messages_v).toBe(10);
      });

      it('should update title version', async () => {
        mockObjectStore.get.mockImplementation(() => {
          const request = { ...mockRequest };
          setTimeout(() => {
            request.result = testChat;
            if (request.onsuccess) request.onsuccess({ target: request });
          }, 0);
          return request;
        });

        await chatDB.updateChatComponentVersion('test-chat-123', 'title_v', 3);
        
        const putCall = mockObjectStore.put.mock.calls[0][0];
        expect(putCall.title_v).toBe(3);
      });
    });

    describe('updateChatLastEditedTimestamp', () => {
      it('should update last edited timestamp', async () => {
        mockObjectStore.get.mockImplementation(() => {
          const request = { ...mockRequest };
          setTimeout(() => {
            request.result = testChat;
            if (request.onsuccess) request.onsuccess({ target: request });
          }, 0);
          return request;
        });

        const timestamp = 1234567890;
        await chatDB.updateChatLastEditedTimestamp('test-chat-123', timestamp);
        
        const putCall = mockObjectStore.put.mock.calls[0][0];
        expect(putCall.last_edited_overall_timestamp).toBe(timestamp);
      });
    });
  });

  describe('Batch Operations', () => {
    beforeEach(async () => {
      await chatDB.init();
    });

    describe('addOrUpdateChatWithFullData', () => {
      it('should add chat and messages in single transaction', async () => {
        const messages = [
          { message_id: 'msg-1', chat_id: 'test-chat-123', role: 'user' as const, content: null, created_at: Date.now() / 1000, status: 'synced' as const },
          { message_id: 'msg-2', chat_id: 'test-chat-123', role: 'assistant' as const, content: null, created_at: Date.now() / 1000, status: 'synced' as const },
        ];

        await chatDB.addOrUpdateChatWithFullData(testChat, messages);
        
        expect(mockObjectStore.put).toHaveBeenCalledTimes(3); // 1 chat + 2 messages
      });
    });

    describe('batchProcessChatData', () => {
      it('should process multiple operations in batch', async () => {
        const chatsToUpdate = [testChat];
        const messagesToSave = [
          { message_id: 'msg-1', chat_id: 'test-chat-123', role: 'user' as const, content: null, created_at: Date.now() / 1000, status: 'synced' as const },
        ];
        const chatIdsToDelete = ['chat-to-delete'];
        const messageIdsToDelete = ['msg-to-delete'];

        await chatDB.batchProcessChatData(chatsToUpdate, messagesToSave, chatIdsToDelete, messageIdsToDelete, mockTransaction);
        
        expect(mockObjectStore.put).toHaveBeenCalledTimes(2); // 1 chat update + 1 message save
        expect(mockObjectStore.delete).toHaveBeenCalledTimes(2); // 1 chat delete + 1 message delete
      });
    });
  });

  describe('Error Handling', () => {
    beforeEach(async () => {
      await chatDB.init();
    });

    it('should handle database connection errors gracefully', async () => {
      mockDatabase.transaction.mockImplementation(() => {
        throw new Error('Transaction error');
      });

      await expect(chatDB.addChat(testChat)).rejects.toThrow('Transaction error');
    });

    it('should handle encryption errors gracefully', async () => {
      vi.spyOn(cryptoService, 'encryptWithMasterKey').mockImplementation(() => {
        throw new Error('Encryption error');
      });

      await expect(chatDB.addChat(testChat)).rejects.toThrow('Encryption error');
    });

    it('should handle decryption errors gracefully', async () => {
      vi.spyOn(cryptoService, 'decryptWithMasterKey').mockImplementation(() => {
        throw new Error('Decryption error');
      });

      const encryptedChat = {
        ...testChat,
        title: null,
        encrypted_title: 'encrypted-title',
      };

      mockObjectStore.get.mockImplementation(() => {
        const request = { ...mockRequest };
        setTimeout(() => {
          request.result = encryptedChat;
          if (request.onsuccess) request.onsuccess({ target: request });
        }, 0);
        return request;
      });

      const result = await chatDB.getChat('test-chat-123');
      
      // Should not throw, but title should be undefined due to decryption error
      expect(result).toBeDefined();
      expect(result!.title).toBeUndefined();
    });
  });

  describe('Security Tests', () => {
    beforeEach(async () => {
      await chatDB.init();
    });

    it('should never store plaintext sensitive data', async () => {
      const sensitiveChat = {
        ...testChat,
        title: 'Sensitive Title',
        mates: ['confidential', 'private'],
      };

      await chatDB.addChat(sensitiveChat);
      
      const putCall = mockObjectStore.put.mock.calls[0][0];
      
      // Verify sensitive data is not stored in plaintext
      expect(putCall.title).toBeNull();
      expect(putCall.mates).toBeUndefined();
      
      // Verify encrypted versions are stored
      expect(putCall.encrypted_title).toBeDefined();
      expect(putCall.encrypted_chat_key).toBeDefined();
    });

    it('should use different chat keys for different chats', async () => {
      const chat1 = { ...testChat, chat_id: 'chat-1' };
      const chat2 = { ...testChat, chat_id: 'chat-2' };

      await chatDB.addChat(chat1);
      await chatDB.addChat(chat2);
      
      // Verify different encrypted chat keys are generated
      const putCall1 = mockObjectStore.put.mock.calls[0][0];
      const putCall2 = mockObjectStore.put.mock.calls[1][0];
      
      expect(putCall1.encrypted_chat_key).not.toEqual(putCall2.encrypted_chat_key);
    });

    it('should isolate message encryption by chat', () => {
      const message1 = {
        message_id: 'msg-1',
        chat_id: 'chat-1',
        role: 'user' as const,
        content: { type: 'doc', content: [] },
        created_at: Date.now() / 1000,
        status: 'synced' as const,
        sender_name: 'User 1',
      };

      const message2 = {
        message_id: 'msg-2',
        chat_id: 'chat-2',
        role: 'user' as const,
        content: { type: 'doc', content: [] },
        created_at: Date.now() / 1000,
        status: 'synced' as const,
        sender_name: 'User 2',
      };

      const encrypted1 = chatDB.encryptMessageFields(message1, 'chat-1');
      const encrypted2 = chatDB.encryptMessageFields(message2, 'chat-2');
      
      // Verify different encryption keys are used
      expect(encrypted1.encrypted_sender_name).not.toEqual(encrypted2.encrypted_sender_name);
    });
  });
});