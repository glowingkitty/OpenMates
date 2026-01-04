/**
 * Debug Utilities for Chat Data Inspection
 * 
 * These utilities are exposed to the global window object for debugging via the browser console.
 * They allow inspecting IndexedDB chat data, messages, and sync status.
 * 
 * Usage in browser console (all read-only):
 *   await window.debugChat('chat-id')      - Inspect a specific chat
 *   await window.debugAllChats()           - List all chats with consistency check
 *   await window.debugGetMessage('msg-id') - Get raw message data
 * 
 * IMPORTANT: These utilities are for development/debugging only.
 * They should not be used in production code paths.
 */

// Database constants (must match db.ts)
const DB_NAME = 'chats_db';
const CHATS_STORE = 'chats';
const MESSAGES_STORE = 'messages';
const EMBEDS_STORE = 'embeds';

/**
 * Open the IndexedDB database
 */
async function openDB(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result);
    });
}

/**
 * Get a value from an object store by key
 */
async function getFromStore<T>(db: IDBDatabase, storeName: string, key: string): Promise<T | undefined> {
    return new Promise((resolve, reject) => {
        const tx = db.transaction(storeName, 'readonly');
        const store = tx.objectStore(storeName);
        const request = store.get(key);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result);
    });
}

/**
 * Get all values from an object store using an index
 */
async function getAllFromIndex<T>(db: IDBDatabase, storeName: string, indexName: string, key: IDBValidKey): Promise<T[]> {
    return new Promise((resolve, reject) => {
        const tx = db.transaction(storeName, 'readonly');
        const store = tx.objectStore(storeName);
        const index = store.index(indexName);
        const request = index.getAll(key);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result || []);
    });
}

/**
 * Get all items from an object store
 */
async function getAllFromStore<T>(db: IDBDatabase, storeName: string): Promise<T[]> {
    return new Promise((resolve, reject) => {
        const tx = db.transaction(storeName, 'readonly');
        const store = tx.objectStore(storeName);
        const request = store.getAll();
        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result || []);
    });
}

// ============================================================================
// DEBUG FUNCTIONS EXPOSED TO WINDOW
// ============================================================================

interface ChatDebugInfo {
    chat_id: string;
    messages_v: number;
    title_v: number;
    draft_v: number;
    last_message_timestamp?: number;
    last_edited_overall_timestamp?: number;
    created_at?: number;
    updated_at?: number;
    has_encrypted_title: boolean;
    has_encrypted_chat_key: boolean;
    raw_metadata: Record<string, unknown>;
}

interface MessageDebugInfo {
    message_id: string;
    chat_id: string;
    role: string;
    created_at: number;
    created_at_formatted: string;
    has_content: boolean;
    has_encrypted_content: boolean;
    status?: string;
}

interface DebugChatResult {
    chat_id: string;
    found: boolean;
    chat_metadata: ChatDebugInfo | null;
    messages: {
        total_count: number;
        role_distribution: Record<string, number>;
        items: MessageDebugInfo[];
    };
    embeds: {
        total_count: number;
    };
    version_analysis: {
        messages_v: number;
        actual_message_count: number;
        is_consistent: boolean;
        discrepancy: string;
    };
}

/**
 * Debug a specific chat - inspect metadata, messages, and consistency
 * 
 * Usage in console:
 *   await window.debugChat('your-chat-id-here')
 */
export async function debugChat(chatId: string): Promise<DebugChatResult> {
    console.log('🔍 Opening IndexedDB...');
    const db = await openDB();
    
    console.log('✅ Database opened:', db.name, 'version:', db.version);
    console.log('📦 Object stores:', Array.from(db.objectStoreNames));
    
    // Get chat metadata
    const chatMeta = await getFromStore<Record<string, unknown>>(db, CHATS_STORE, chatId);
    
    console.log('\n📋 CHAT METADATA:');
    let chatDebugInfo: ChatDebugInfo | null = null;
    
    if (chatMeta) {
        chatDebugInfo = {
            chat_id: chatMeta.chat_id as string,
            messages_v: (chatMeta.messages_v as number) || 0,
            title_v: (chatMeta.title_v as number) || 0,
            draft_v: (chatMeta.draft_v as number) || 0,
            last_message_timestamp: chatMeta.last_message_timestamp as number | undefined,
            last_edited_overall_timestamp: chatMeta.last_edited_overall_timestamp as number | undefined,
            created_at: chatMeta.created_at as number | undefined,
            updated_at: chatMeta.updated_at as number | undefined,
            has_encrypted_title: !!chatMeta.encrypted_title,
            has_encrypted_chat_key: !!chatMeta.encrypted_chat_key,
            raw_metadata: chatMeta
        };
        
        console.log('  - chat_id:', chatDebugInfo.chat_id);
        console.log('  - messages_v:', chatDebugInfo.messages_v);
        console.log('  - title_v:', chatDebugInfo.title_v);
        console.log('  - draft_v:', chatDebugInfo.draft_v);
        console.log('  - last_message_timestamp:', chatDebugInfo.last_message_timestamp);
        console.log('  - last_edited_overall_timestamp:', chatDebugInfo.last_edited_overall_timestamp);
        console.log('  - has_encrypted_title:', chatDebugInfo.has_encrypted_title);
        console.log('  - has_encrypted_chat_key:', chatDebugInfo.has_encrypted_chat_key);
        console.log('  Full metadata:', chatMeta);
    } else {
        console.log('  ❌ Chat NOT FOUND in IndexedDB');
    }
    
    // Get all messages for the chat
    const messages = await getAllFromIndex<Record<string, unknown>>(db, MESSAGES_STORE, 'chat_id', chatId);
    
    console.log('\n💬 MESSAGES:');
    console.log('  Total count:', messages.length);
    
    const roleCount: Record<string, number> = {};
    const messageItems: MessageDebugInfo[] = [];
    
    if (messages.length > 0) {
        // Sort by created_at for display
        messages.sort((a, b) => (a.created_at as number) - (b.created_at as number));
        
        messages.forEach((msg, i) => {
            const role = (msg.role as string) || 'unknown';
            roleCount[role] = (roleCount[role] || 0) + 1;
            
            const created_at = msg.created_at as number;
            const messageInfo: MessageDebugInfo = {
                message_id: msg.message_id as string,
                chat_id: msg.chat_id as string,
                role,
                created_at,
                created_at_formatted: new Date(created_at * 1000).toISOString(),
                has_content: !!msg.content,
                has_encrypted_content: !!msg.encrypted_content,
                status: msg.status as string | undefined
            };
            messageItems.push(messageInfo);
            
            console.log(`  ${i + 1}. [${role}] message_id: ${messageInfo.message_id}`);
            console.log(`     created_at: ${messageInfo.created_at_formatted}`);
            console.log(`     has content: ${messageInfo.has_content}`);
            console.log(`     has encrypted_content: ${messageInfo.has_encrypted_content}`);
        });
        
        console.log('\n  Role distribution:', roleCount);
        console.log('\n  Raw messages array:', messages);
    } else {
        console.log('  ❌ No messages found for this chat');
    }
    
    // Get embed count for this chat (by hashed_chat_id)
    // Note: We can't easily get embed count without knowing the hashed_chat_id
    // For now just count all embeds
    const allEmbeds = await getAllFromStore<Record<string, unknown>>(db, EMBEDS_STORE);
    
    db.close();
    
    // Analyze version consistency
    const messagesV = chatDebugInfo?.messages_v || 0;
    const actualMessageCount = messages.length;
    // Note: messages_v increments for each message, but can have gaps
    // A consistent state would have messages_v >= message count
    // An inconsistent state is when messages_v is much higher than message count
    const isConsistent = messagesV <= actualMessageCount + 1; // Allow 1 buffer for in-progress
    const discrepancy = isConsistent 
        ? '✅ Versions appear consistent' 
        : `⚠️ VERSION MISMATCH: messages_v=${messagesV} but only ${actualMessageCount} messages in IndexedDB!`;
    
    console.log('\n📊 VERSION ANALYSIS:');
    console.log('  messages_v:', messagesV);
    console.log('  actual_message_count:', actualMessageCount);
    console.log('  Status:', discrepancy);
    
    const result: DebugChatResult = {
        chat_id: chatId,
        found: !!chatMeta,
        chat_metadata: chatDebugInfo,
        messages: {
            total_count: messages.length,
            role_distribution: roleCount,
            items: messageItems
        },
        embeds: {
            total_count: allEmbeds.length
        },
        version_analysis: {
            messages_v: messagesV,
            actual_message_count: actualMessageCount,
            is_consistent: isConsistent,
            discrepancy
        }
    };
    
    console.log('\n📦 Full result object:', result);
    return result;
}

/**
 * Debug all chats - get overview of all chats in IndexedDB
 * 
 * Usage in console:
 *   await window.debugAllChats()
 */
export async function debugAllChats(): Promise<{
    total_chats: number;
    total_messages: number;
    chats: Array<{
        chat_id: string;
        messages_v: number;
        actual_messages: number;
        is_consistent: boolean;
    }>;
}> {
    console.log('🔍 Loading all chats from IndexedDB...');
    const db = await openDB();
    
    const allChats = await getAllFromStore<Record<string, unknown>>(db, CHATS_STORE);
    const allMessages = await getAllFromStore<Record<string, unknown>>(db, MESSAGES_STORE);
    
    console.log(`\n📋 Found ${allChats.length} chats and ${allMessages.length} messages total`);
    
    // Group messages by chat_id
    const messagesByChatId: Record<string, number> = {};
    for (const msg of allMessages) {
        const chatId = msg.chat_id as string;
        messagesByChatId[chatId] = (messagesByChatId[chatId] || 0) + 1;
    }
    
    const chatSummaries = allChats.map(chat => {
        const chatId = chat.chat_id as string;
        const messagesV = (chat.messages_v as number) || 0;
        const actualMessages = messagesByChatId[chatId] || 0;
        const isConsistent = messagesV <= actualMessages + 1;
        
        return {
            chat_id: chatId,
            messages_v: messagesV,
            actual_messages: actualMessages,
            is_consistent: isConsistent
        };
    });
    
    // Log inconsistent chats
    const inconsistentChats = chatSummaries.filter(c => !c.is_consistent);
    if (inconsistentChats.length > 0) {
        console.log('\n⚠️ INCONSISTENT CHATS:');
        inconsistentChats.forEach(c => {
            console.log(`  - ${c.chat_id}: messages_v=${c.messages_v}, actual=${c.actual_messages}`);
        });
    } else {
        console.log('\n✅ All chats have consistent message counts');
    }
    
    db.close();
    
    const result = {
        total_chats: allChats.length,
        total_messages: allMessages.length,
        chats: chatSummaries
    };
    
    console.log('\n📦 Full result:', result);
    return result;
}

/**
 * Get raw message data for a specific message ID
 * 
 * Usage in console:
 *   await window.debugGetMessage('message-id-here')
 */
export async function debugGetMessage(messageId: string): Promise<Record<string, unknown> | null> {
    const db = await openDB();
    const message = await getFromStore<Record<string, unknown>>(db, MESSAGES_STORE, messageId);
    db.close();
    
    if (message) {
        console.log('📧 Message found:', message);
    } else {
        console.log('❌ Message not found');
    }
    
    return message || null;
}

// ============================================================================
// INITIALIZATION - Expose to window object
// ============================================================================

/**
 * Initialize debug utilities and expose to window object
 * Called once when the module is imported
 */
export function initDebugUtils(): void {
    if (typeof window !== 'undefined') {
        // Expose read-only debug functions to window for console access
        (window as unknown as Record<string, unknown>).debugChat = debugChat;
        (window as unknown as Record<string, unknown>).debugAllChats = debugAllChats;
        (window as unknown as Record<string, unknown>).debugGetMessage = debugGetMessage;
        
        console.info(
            '%c🔧 Debug utilities loaded!%c\n' +
            'Available commands (read-only):\n' +
            '  • await window.debugChat("chat-id") - Inspect a specific chat\n' +
            '  • await window.debugAllChats() - List all chats with consistency check\n' +
            '  • await window.debugGetMessage("message-id") - Get raw message data',
            'color: #4CAF50; font-weight: bold; font-size: 14px;',
            'color: #888; font-size: 12px;'
        );
    }
}

