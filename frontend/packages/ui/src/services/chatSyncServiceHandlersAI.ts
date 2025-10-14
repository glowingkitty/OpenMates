// frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts
import type { ChatSynchronizationService } from './chatSyncService';
import { aiTypingStore } from '../stores/aiTypingStore';
import { chatDB } from './db'; // Import chatDB
import * as LucideIcons from '@lucide/svelte';

/**
 * Check if a string is a valid Lucide icon name
 */
function isValidLucideIcon(iconName: string): boolean {
    // Convert kebab-case to PascalCase (e.g., 'help-circle' -> 'HelpCircle')
    const pascalCaseName = iconName
        .split('-')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join('');
    
    return pascalCaseName in LucideIcons;
}

/**
 * Get fallback icon for a category when no icon names are provided
 */
function getFallbackIconForCategory(category: string): string {
    const categoryIcons: Record<string, string> = {
        'software_development': 'code',
        'business_development': 'briefcase',
        'medical_health': 'heart',
        'legal_law': 'gavel',
        'maker_prototyping': 'wrench',
        'marketing_sales': 'megaphone',
        'finance': 'dollar-sign',
        'design': 'palette',
        'electrical_engineering': 'zap',
        'movies_tv': 'tv',
        'history': 'clock',
        'science': 'microscope',
        'life_coach_psychology': 'users',
        'cooking_food': 'utensils',
        'activism': 'trending-up',
        'general_knowledge': 'help-circle'
    };
    
    return categoryIcons[category] || 'help-circle';
}

import type {
    Chat, // Import Chat type
    Message,
    AITaskInitiatedPayload,
    AIMessageUpdatePayload,
    AIBackgroundResponseCompletedPayload,
    AITypingStartedPayload,
    AIMessageReadyPayload,
    AITaskCancelRequestedPayload
} from '../types/chat'; // Assuming these types might be moved or are already in a shared types file

// --- AI Task and Stream Event Handler Implementations ---

export function handleAITaskInitiatedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: AITaskInitiatedPayload
): void {
    console.info("[ChatSyncService:AI] Received 'ai_task_initiated':", payload);
    // Accessing private member, ensure 'this' context is correct or pass necessary state/methods
    (serviceInstance as any).activeAITasks.set(payload.chat_id, { taskId: payload.ai_task_id, userMessageId: payload.user_message_id });
    serviceInstance.dispatchEvent(new CustomEvent('aiTaskInitiated', { detail: payload }));
}

export function handleAIMessageUpdateImpl(
    serviceInstance: ChatSynchronizationService,
    payload: AIMessageUpdatePayload
): void {
    console.debug("[ChatSyncService:AI] Received 'ai_message_update':", payload);
    serviceInstance.dispatchEvent(new CustomEvent('aiMessageChunk', { detail: payload }));
    if (payload.is_final_chunk) {
        const taskInfo = (serviceInstance as any).activeAITasks.get(payload.chat_id);
        if (taskInfo && taskInfo.taskId === payload.task_id) {
            (serviceInstance as any).activeAITasks.delete(payload.chat_id);
            // Clear typing status for this specific AI task
            aiTypingStore.clearTyping(payload.chat_id, payload.task_id); 
            serviceInstance.dispatchEvent(new CustomEvent('aiTaskEnded', { detail: { chatId: payload.chat_id, taskId: payload.task_id, status: payload.interrupted_by_revocation ? 'cancelled' : (payload.interrupted_by_soft_limit ? 'timed_out' : 'completed') } }));
            console.info(`[ChatSyncService:AI] AI Task ${payload.task_id} for chat ${payload.chat_id} considered ended due to final chunk marker. Typing status cleared.`);
        }
    }
}

/**
 * Handles background AI response completion for inactive chats.
 * This allows AI processing to continue when user switches chats,
 * storing the completed response in IndexedDB for later retrieval.
 */
export async function handleAIBackgroundResponseCompletedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: AIBackgroundResponseCompletedPayload
): Promise<void> {
    console.info("[ChatSyncService:AI] Received 'ai_background_response_completed' for inactive chat:", payload);
    
    try {
        // Get chat from DB to update messages_v
        const chat = await chatDB.getChat(payload.chat_id);
        if (!chat) {
            console.error(`[ChatSyncService:AI] Chat ${payload.chat_id} not found in DB for background response`);
            return;
        }
        
        // Get the category from typing store if available
        // If not in typing store (chat was switched), try to get from chat metadata
        const { get } = await import('svelte/store');
        const typingStatus = get(aiTypingStore);
        let category = (typingStatus?.chatId === payload.chat_id) ? typingStatus.category : undefined;
        
        // CRITICAL FIX for Issue 2: If category not in typing store (because user switched chats),
        // decrypt the category from the chat's encrypted_category field
        if (!category && chat.encrypted_category) {
            try {
                const { decryptWithChatKey } = await import('./cryptoService');
                const chatKey = chatDB.getOrGenerateChatKey(payload.chat_id);
                category = decryptWithChatKey(chat.encrypted_category, chatKey);
                console.info(`[ChatSyncService:AI] Retrieved category from chat metadata for background response: ${category}`);
            } catch (error) {
                console.error(`[ChatSyncService:AI] Failed to decrypt category from chat metadata:`, error);
            }
        }
        
        // Create the completed AI message
        // CRITICAL: Store AI response as markdown string, not Tiptap JSON
        // Tiptap JSON is only for UI rendering, never stored in database
        const aiMessage: Message = {
            message_id: payload.message_id,
            chat_id: payload.chat_id,
            user_message_id: payload.user_message_id,
            role: 'assistant',
            category: category || undefined,
            content: payload.full_content, // Store as markdown string, not Tiptap JSON
            status: 'synced',
            created_at: Math.floor(Date.now() / 1000),
            // Note: encrypted fields will be populated by encryptMessageFields in chatDB.saveMessage()
            // Do NOT set encrypted_* fields here as they should only exist after encryption
            encrypted_content: '', // Will be set by encryption
        };
        
        // Save message to IndexedDB (encryption handled by chatDB)
        // This will encrypt all fields including encrypted_category
        await chatDB.saveMessage(aiMessage);
        console.info(`[ChatSyncService:AI] Saved background AI response to DB for chat ${payload.chat_id} with category: ${category || 'none'}`);
        
        // Update chat metadata with new messages_v
        const newMessagesV = (chat.messages_v || 0) + 1;
        const newLastEdited = Math.floor(Date.now() / 1000);
        const updatedChat: Chat = {
            ...chat,
            messages_v: newMessagesV,
            last_edited_overall_timestamp: newLastEdited
        };
        await chatDB.updateChat(updatedChat);
        console.info(`[ChatSyncService:AI] Updated chat ${payload.chat_id} metadata: messages_v=${newMessagesV}`);
        
        // Clear AI task tracking
        const taskInfo = (serviceInstance as any).activeAITasks.get(payload.chat_id);
        if (taskInfo && taskInfo.taskId === payload.task_id) {
            (serviceInstance as any).activeAITasks.delete(payload.chat_id);
            console.info(`[ChatSyncService:AI] Cleared active AI task for chat ${payload.chat_id}`);
        }
        
        // Clear typing status for this specific AI task
        aiTypingStore.clearTyping(payload.chat_id, payload.task_id);
        
        // Dispatch chatUpdated event to notify UI (e.g., update chat list)
        // This will NOT update ActiveChat if the chat is not currently open
        serviceInstance.dispatchEvent(new CustomEvent('chatUpdated', {
            detail: {
                chat_id: payload.chat_id,
                chat: updatedChat,
                newMessage: aiMessage,
                type: 'background_ai_completion'
            }
        }));
        
        // Dispatch aiTaskEnded event for cleanup
        serviceInstance.dispatchEvent(new CustomEvent('aiTaskEnded', {
            detail: {
                chatId: payload.chat_id,
                taskId: payload.task_id,
                status: payload.interrupted_by_revocation ? 'cancelled' : (payload.interrupted_by_soft_limit ? 'timed_out' : 'completed')
            }
        }));
        
        console.info(`[ChatSyncService:AI] Background AI response processing completed for chat ${payload.chat_id}`);
        
        // CRITICAL: Send encrypted AI response back to server for Directus storage (zero-knowledge architecture)
        // This uses the existing sendCompletedAIResponse method
        try {
            console.debug('[ChatSyncService:AI] Sending completed background AI response to server for encrypted Directus storage:', {
                messageId: aiMessage.message_id,
                chatId: aiMessage.chat_id,
                contentLength: aiMessage.content?.length || 0
            });
            await (serviceInstance as any).sendCompletedAIResponse(aiMessage);
        } catch (error) {
            console.error('[ChatSyncService:AI] Error sending completed background AI response to server:', error);
        }
        
    } catch (error) {
        console.error(`[ChatSyncService:AI] Error handling background AI response for chat ${payload.chat_id}:`, error);
    }
}

export async function handleAITypingStartedImpl( // Changed to async
    serviceInstance: ChatSynchronizationService,
    payload: AITypingStartedPayload
): Promise<void> { // Added Promise<void>
    console.debug("[ChatSyncService:AI] Received 'ai_typing_started':", payload);
    
    // Update aiTypingStore first
    aiTypingStore.setTyping(payload.chat_id, payload.user_message_id, payload.message_id, payload.category, payload.model_name);

    // DUAL-PHASE ARCHITECTURE: Handle metadata encryption ONLY for new chats (when icon_names is present)
    // Backend only sends icon_names for the first message in a chat
    if (payload.icon_names && payload.icon_names.length > 0) {
        console.info(`[ChatSyncService:AI] DUAL-PHASE: Processing metadata encryption for NEW CHAT ${payload.chat_id}:`, {
            hasTitle: !!payload.title,
            category: payload.category,
            hasIconNames: !!payload.icon_names,
            iconNames: payload.icon_names
        });
        
        try {
            // FIRST: Update local chat with encrypted title immediately
            // Get the current chat
            const chat = await chatDB.getChat(payload.chat_id);
            if (!chat) {
                console.error(`[ChatSyncService:AI] Chat ${payload.chat_id} not found for metadata encryption`);
                return;
            }
            
            // Encrypt title, icon, and category with chat-specific key for local storage
            let encryptedTitle: string | null = null;
            let encryptedIcon: string | null = null;
            let encryptedCategory: string | null = null;
            
            // Get or generate chat key for encryption
            const chatKey = chatDB.getOrGenerateChatKey(payload.chat_id);
            const { encryptWithChatKey } = await import('./cryptoService');
            
            // Encrypt title if payload has one (only for new chats on first message)
            if (payload.title) {
                encryptedTitle = encryptWithChatKey(payload.title, chatKey);
                if (!encryptedTitle) {
                    console.error(`[ChatSyncService:AI] Failed to encrypt title for chat ${payload.chat_id}`);
                    return;
                }
            }
            
            // Encrypt icon and category ONLY if payload has icon_names (only for new chats on first message)
            // Server only sends icon_names when chat doesn't have a title yet
            // CRITICAL: Only update icon and category when icon_names is present to avoid overwriting on follow-ups
            if (payload.icon_names && payload.icon_names.length > 0) {
                console.info(`[ChatSyncService:AI] Validating ${payload.icon_names.length} icon names for NEW CHAT: ${payload.icon_names.join(', ')}`);
                
                // Find the first valid Lucide icon name from the list
                let validIconName: string | null = null;
                for (const iconName of payload.icon_names) {
                    if (isValidLucideIcon(iconName)) {
                        validIconName = iconName;
                        console.info(`[ChatSyncService:AI] ✅ Found valid icon: ${iconName}`);
                        break;
                    } else {
                        console.warn(`[ChatSyncService:AI] ❌ Invalid icon name: ${iconName}, trying next...`);
                    }
                }
                
                // If no valid icon found, use category fallback
                if (!validIconName) {
                    validIconName = getFallbackIconForCategory(payload.category || 'general_knowledge');
                    console.info(`[ChatSyncService:AI] 🔄 No valid icons found, using category fallback: ${validIconName}`);
                }
                
                encryptedIcon = encryptWithChatKey(validIconName, chatKey);
                if (!encryptedIcon) {
                    console.error(`[ChatSyncService:AI] Failed to encrypt icon for chat ${payload.chat_id}`);
                    return;
                }
                
                // CRITICAL: Only encrypt and update category when icon_names is present (NEW CHAT ONLY)
                // This prevents overwriting category on follow-up messages
                if (payload.category) {
                    encryptedCategory = encryptWithChatKey(payload.category, chatKey);
                    if (!encryptedCategory) {
                        console.error(`[ChatSyncService:AI] Failed to encrypt category for chat ${payload.chat_id}`);
                        return;
                    }
                    console.info(`[ChatSyncService:AI] ✅ Encrypted category for NEW CHAT: ${payload.category}`);
                } else {
                    console.warn(`[ChatSyncService:AI] ⚠️ icon_names present but no category - using general_knowledge`);
                    encryptedCategory = encryptWithChatKey('general_knowledge', chatKey);
                }
            } else {
                console.debug(`[ChatSyncService:AI] No icon_names in payload - chat already has icon/category (follow-up message). NOT updating icon or category.`);
            }
            
            // Update local chat with encrypted metadata
            try {
                const chatToUpdate = await chatDB.getChat(payload.chat_id);
                if (chatToUpdate) {
                    console.info(`[ChatSyncService:AI] ✅ Chat loaded for update:`, {
                        chatId: payload.chat_id,
                        currentTitleV: chatToUpdate.title_v,
                        hasEncryptedIcon: !!chatToUpdate.encrypted_icon,
                        hasEncryptedCategory: !!chatToUpdate.encrypted_category
                    });
                    
                    // Update chat with encrypted title
                    if (encryptedTitle) {
                        chatToUpdate.encrypted_title = encryptedTitle;
                        chatToUpdate.title_v = (chatToUpdate.title_v || 0) + 1; // Frontend increments title_v
                        console.info(`[ChatSyncService:AI] ✅ SET encrypted_title, version: ${chatToUpdate.title_v}`);
                    }
                    
                    // Update chat with encrypted icon (ONLY if encryptedIcon is set - i.e., new chat)
                    if (encryptedIcon) {
                        chatToUpdate.encrypted_icon = encryptedIcon;
                        console.info(`[ChatSyncService:AI] ✅ SET encrypted_icon (NEW CHAT):`, encryptedIcon.substring(0, 30) + '...');
                    } else {
                        console.debug(`[ChatSyncService:AI] No encrypted_icon to set (follow-up message - preserving existing icon)`);
                    }
                    
                    // Update chat with encrypted category (ONLY if encryptedCategory is set - i.e., new chat)
                    if (encryptedCategory) {
                        chatToUpdate.encrypted_category = encryptedCategory;
                        console.info(`[ChatSyncService:AI] ✅ SET encrypted_category (NEW CHAT):`, encryptedCategory.substring(0, 30) + '...');
                    } else {
                        console.debug(`[ChatSyncService:AI] No encrypted_category to set (follow-up message - preserving existing category)`);
                    }
                    
                    // Ensure chat key is stored for decryption
                    const chatKey = chatDB.getOrGenerateChatKey(payload.chat_id);
                    const encryptedChatKey = await import('./cryptoService').then(m => m.encryptChatKeyWithMasterKey(chatKey));
                    if (encryptedChatKey) {
                        chatToUpdate.encrypted_chat_key = encryptedChatKey;
                        console.info(`[ChatSyncService:AI] Stored encrypted chat key for chat ${payload.chat_id}`);
                    }
                    
                    // Update timestamps
                    chatToUpdate.updated_at = Math.floor(Date.now() / 1000);
                    
                    console.info(`[ChatSyncService:AI] 🔵 BEFORE updateChat - Chat object has:`, {
                        chatId: chatToUpdate.chat_id,
                        hasEncryptedTitle: !!chatToUpdate.encrypted_title,
                        hasEncryptedIcon: !!chatToUpdate.encrypted_icon,
                        hasEncryptedCategory: !!chatToUpdate.encrypted_category,
                        encryptedIconPreview: chatToUpdate.encrypted_icon?.substring(0, 20) || 'null',
                        encryptedCategoryPreview: chatToUpdate.encrypted_category?.substring(0, 20) || 'null'
                    });
                    
                    await chatDB.updateChat(chatToUpdate);
                    
                    console.info(`[ChatSyncService:AI] ✅ Local chat ${payload.chat_id} updated with encrypted title, icon, category and chat key`);
                    
                    // Verify the save by reading back
                    const verifyChat = await chatDB.getChat(payload.chat_id);
                    console.info(`[ChatSyncService:AI] 🔍 VERIFICATION - Chat after save:`, {
                        chatId: payload.chat_id,
                        hasEncryptedTitle: !!verifyChat?.encrypted_title,
                        hasEncryptedIcon: !!verifyChat?.encrypted_icon,
                        hasEncryptedCategory: !!verifyChat?.encrypted_category,
                        encryptedIconPreview: verifyChat?.encrypted_icon?.substring(0, 20) || 'null',
                        encryptedCategoryPreview: verifyChat?.encrypted_category?.substring(0, 20) || 'null'
                    });
                    
                    serviceInstance.dispatchEvent(new CustomEvent('chatUpdated', { 
                        detail: { chat_id: payload.chat_id, type: 'title_updated', chat: chatToUpdate } 
                    }));
                } else {
                    console.error(`[ChatSyncService:AI] Chat ${payload.chat_id} not found for title update`);
                    return;
                }
            } catch (error) {
                console.error(`[ChatSyncService:AI] Error updating local chat ${payload.chat_id}:`, error);
                return;
            }
            
            // SECOND: Send encrypted storage package to server
            const { sendEncryptedStoragePackage } = await import('./chatSyncServiceSenders');
            
            // Get the user's pending message (the one being processed)
            const messages = await chatDB.getMessagesForChat(payload.chat_id);
            const userMessage = messages
                .filter(m => m.role === 'user')
                .sort((a, b) => b.created_at - a.created_at)[0];
                
            if (!userMessage) {
                console.error(`[ChatSyncService:AI] No user message found for chat ${payload.chat_id} to encrypt`);
                return;
            }
            
            // Get the updated chat object (chatToUpdate has the incremented title_v)
            const updatedChat = await chatDB.getChat(payload.chat_id);
            if (!updatedChat) {
                console.error(`[ChatSyncService:AI] Updated chat ${payload.chat_id} not found for sending to server`);
                return;
            }
            
            // CRITICAL: Only send icon/category to server if icon_names is present (NEW CHAT ONLY)
            // This prevents sending metadata updates for follow-up messages
            let validIconName: string | undefined = undefined;
            let categoryForServer: string | undefined = undefined;
            let titleForServer: string | undefined = undefined;
            
            if (payload.icon_names && payload.icon_names.length > 0) {
                // NEW CHAT ONLY - validate and prepare icon, category, and title for server
                console.info(`[ChatSyncService:AI] Server sync - Validating ${payload.icon_names.length} icon names for NEW CHAT: ${payload.icon_names.join(', ')}`);
                
                for (const iconName of payload.icon_names) {
                    if (isValidLucideIcon(iconName)) {
                        validIconName = iconName;
                        console.info(`[ChatSyncService:AI] Server sync - ✅ Found valid icon: ${iconName}`);
                        break;
                    } else {
                        console.warn(`[ChatSyncService:AI] Server sync - ❌ Invalid icon name: ${iconName}, trying next...`);
                    }
                }
                // If no valid icon found, use category fallback
                if (!validIconName) {
                    validIconName = getFallbackIconForCategory(payload.category || 'general_knowledge');
                    console.info(`[ChatSyncService:AI] Server sync - 🔄 No valid icons found, using category fallback: ${validIconName}`);
                }
                
                // Only include category and title for new chats
                categoryForServer = payload.category;
                titleForServer = payload.title;
                console.info(`[ChatSyncService:AI] Server sync - Preparing metadata for NEW CHAT: title=${!!titleForServer}, category=${categoryForServer}, icon=${validIconName}`);
            } else {
                console.debug(`[ChatSyncService:AI] Server sync - NO icon_names in payload (follow-up message). NOT sending icon/category/title to server.`);
            }
            
            // Send encrypted storage package with metadata (ONLY for new chats when icon_names present)
            await sendEncryptedStoragePackage(serviceInstance, {
                chat_id: payload.chat_id,
                plaintext_title: titleForServer, // Only set for new chats
                plaintext_category: categoryForServer, // Only set for new chats
                plaintext_icon: validIconName, // Only set for new chats
                user_message: userMessage,
                task_id: payload.task_id,
                updated_chat: updatedChat  // Pass the updated chat object with incremented title_v
            });
            
            console.info(`[ChatSyncService:AI] DUAL-PHASE: Sent encrypted storage package for chat ${payload.chat_id}`);
            
        } catch (error) {
            console.error(`[ChatSyncService:AI] DUAL-PHASE: Error processing metadata encryption for chat ${payload.chat_id}:`, error);
        }
    } else {
        console.debug(`[ChatSyncService:AI] 'ai_typing_started' for chat ${payload.chat_id}. No icon_names present - this is a follow-up message, NOT updating metadata.`);
    }
    
    serviceInstance.dispatchEvent(new CustomEvent('aiTypingStarted', { detail: payload }));
}

export function handleAITypingEndedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: { chat_id: string, message_id: string }
): void {
    console.debug("[ChatSyncService:AI] Received 'ai_typing_ended':", payload);
    aiTypingStore.clearTyping(payload.chat_id, payload.message_id);
    serviceInstance.dispatchEvent(new CustomEvent('aiTypingEnded', { detail: payload }));
}

export function handleAIMessageReadyImpl(
    serviceInstance: ChatSynchronizationService,
    payload: AIMessageReadyPayload
): void {
    console.debug("[ChatSyncService:AI] Received 'ai_message_ready':", payload);
    serviceInstance.dispatchEvent(new CustomEvent('aiMessageCompletedOnServer', { detail: payload }));
    const taskInfo = (serviceInstance as any).activeAITasks.get(payload.chat_id);
    if (taskInfo && taskInfo.taskId === payload.message_id) {
        (serviceInstance as any).activeAITasks.delete(payload.chat_id);
        serviceInstance.dispatchEvent(new CustomEvent('aiTaskEnded', { detail: { chatId: payload.chat_id, taskId: payload.message_id, status: 'completed' } }));
        console.info(`[ChatSyncService:AI] AI Task ${payload.message_id} for chat ${payload.chat_id} considered ended due to 'ai_message_ready'.`);
    }
}

export function handleAITaskCancelRequestedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: AITaskCancelRequestedPayload
): void {
    console.info("[ChatSyncService:AI] Received 'ai_task_cancel_requested' acknowledgement:", payload);
    serviceInstance.dispatchEvent(new CustomEvent('aiTaskCancellationAcknowledged', { detail: payload }));
    
    if (payload.status === 'already_completed' || payload.status === 'not_found') {
        const chatIdsToClear: string[] = [];
        (serviceInstance as any).activeAITasks.forEach((value: { taskId: string; }, key: string) => {
            if (value.taskId === payload.task_id) {
                chatIdsToClear.push(key);
            }
        });
        chatIdsToClear.forEach(chatId => {
            (serviceInstance as any).activeAITasks.delete(chatId);
            serviceInstance.dispatchEvent(new CustomEvent('aiTaskEnded', { detail: { chatId: chatId, taskId: payload.task_id, status: payload.status } }));
            console.info(`[ChatSyncService:AI] AI Task ${payload.task_id} for chat ${chatId} cleared due to cancel ack status: ${payload.status}.`);
        });
    }
}

/**
 * Handle AI response storage confirmation from server
 * This confirms that the encrypted AI response has been stored in Directus
 */
export function handleAIResponseStorageConfirmedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: { chat_id: string; message_id: string; task_id?: string }
): void {
    console.info("[ChatSyncService:AI] Received 'ai_response_storage_confirmed':", payload);
    
    // Dispatch event to notify components that AI response storage is confirmed
    serviceInstance.dispatchEvent(new CustomEvent('aiResponseStorageConfirmed', { 
        detail: { 
            chatId: payload.chat_id, 
            messageId: payload.message_id,
            taskId: payload.task_id 
        } 
    }));
    
    console.debug(`[ChatSyncService:AI] AI response storage confirmed for message ${payload.message_id} in chat ${payload.chat_id}`);
}

/**
 * Handles the 'encrypted_metadata_stored' event from the server.
 * This confirms that encrypted chat metadata has been successfully stored on the server.
 */
export function handleEncryptedMetadataStoredImpl(
    serviceInstance: ChatSynchronizationService,
    payload: { chat_id: string; message_id: string; task_id?: string }
): void {
    console.debug(`[ChatSyncService:AI] Received 'encrypted_metadata_stored':`, payload);
    console.debug(`[ChatSyncService:AI] Encrypted metadata storage confirmed for chat ${payload.chat_id}`);
}

/**
 * Handle server request for chat history when cache is stale or missing
 * Server sends this when it cannot decrypt cached messages
 */
export async function handleRequestChatHistoryImpl(
    serviceInstance: ChatSynchronizationService,
    payload: { chat_id: string; reason: string; message?: string }
): Promise<void> {
    console.warn(`[ChatSyncService:AI] Server requested chat history for chat ${payload.chat_id}. Reason: ${payload.reason}`);
    
    try {
        // Get all messages for this chat from IndexedDB
        const allMessages = await chatDB.getMessagesForChat(payload.chat_id);
        
        if (allMessages.length === 0) {
            console.error(`[ChatSyncService:AI] No messages found for chat ${payload.chat_id} to send to server`);
            return;
        }
        
        // Convert to format expected by server (plaintext for AI processing)
        const messageHistory = allMessages.map(msg => ({
            message_id: msg.message_id,
            role: msg.role,
            content: msg.content, // Plaintext content
            sender_name: msg.sender_name,
            category: msg.category,
            created_at: msg.created_at
        }));
        
        console.info(`[ChatSyncService:AI] Sending ${messageHistory.length} messages to server for cache refresh`);
        
        // Get the most recent user message (the one that triggered the request)
        const latestUserMessage = allMessages
            .filter(m => m.role === 'user')
            .sort((a, b) => b.created_at - a.created_at)[0];
        
        if (!latestUserMessage) {
            console.error(`[ChatSyncService:AI] No user message found to resend with history`);
            return;
        }
        
        // Get chat metadata
        const chat = await chatDB.getChat(payload.chat_id);
        const chatHasMessages = (chat?.messages_v ?? 0) > 1;
        
        // Resend the message with full history
        const resendPayload = {
            chat_id: payload.chat_id,
            message: {
                message_id: latestUserMessage.message_id,
                role: latestUserMessage.role,
                content: latestUserMessage.content,
                created_at: latestUserMessage.created_at,
                sender_name: latestUserMessage.sender_name,
                chat_has_title: chatHasMessages,
                message_history: messageHistory // Include full history
            }
        };
        
        console.info(`[ChatSyncService:AI] Resending message with ${messageHistory.length} historical messages`);
        
        // Import webSocketService
        const { webSocketService } = await import('./websocketService');
        await webSocketService.sendMessage('chat_message_added', resendPayload);
        
    } catch (error) {
        console.error(`[ChatSyncService:AI] Error handling chat history request for chat ${payload.chat_id}:`, error);
    }
}
