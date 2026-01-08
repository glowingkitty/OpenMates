import type { Editor } from '@tiptap/core';
import { get } from 'svelte/store'; // Import get
import { isDesktop } from '../../../utils/platform';
import { hasActualContent, vibrateMessageField } from '../utils';
import { Extension } from '@tiptap/core';
import { chatDB } from '../../../services/db';
import { chatSyncService } from '../../../services/chatSyncService'; // Import chatSyncService
import type { Message } from '../../../types/chat'; // Import Message type
import { draftEditorUIState } from '../../../services/drafts/draftState';
import { clearCurrentDraft } from '../../../services/drafts/draftSave'; // Import clearCurrentDraft
import { tipTapToCanonicalMarkdown } from '../../../message_parsing/serializers'; // Import TipTap to markdown converter
import { isPublicChat } from '../../../demo_chats/convertToChat';
import { websocketStatus } from '../../../stores/websocketStatusStore'; // Import WebSocket status store
import { chatListCache } from '../../../services/chatListCache';
import { createEmbedFromUrl } from '../services/urlMetadataService'; // Import URL-to-embed creation
import { authStore } from '../../../stores/authStore'; // Import authStore for authentication check

// Removed sendMessageToAPI as it will be handled by chatSyncService

// =============================================================================
// URL Detection and Processing
// =============================================================================

/**
 * Regular expression to detect URLs in text content.
 * Matches http and https URLs.
 */
const URL_REGEX = /https?:\/\/[^\s\])"'<>]+/g;

/**
 * Detects all URLs in the given text content.
 * Returns array of URL matches with their positions.
 * Excludes URLs that are already inside JSON code blocks (embed references).
 * 
 * @param text The text content to search
 * @returns Array of {url, startPos, endPos} objects
 */
function detectUrlsInText(text: string): Array<{url: string, startPos: number, endPos: number}> {
    const urls: Array<{url: string, startPos: number, endPos: number}> = [];
    
    // Find all code block ranges to exclude URLs within them
    const codeBlockRanges: Array<{start: number, end: number}> = [];
    const codeBlockPattern = /```[\s\S]*?```/g;
    let blockMatch;
    while ((blockMatch = codeBlockPattern.exec(text)) !== null) {
        codeBlockRanges.push({
            start: blockMatch.index,
            end: blockMatch.index + blockMatch[0].length
        });
    }
    
    // Find all URLs
    let match;
    URL_REGEX.lastIndex = 0; // Reset regex state
    
    while ((match = URL_REGEX.exec(text)) !== null) {
        const url = match[0];
        const startPos = match.index;
        const endPos = startPos + url.length;
        
        // Check if URL is inside a code block - skip if so
        const isInsideCodeBlock = codeBlockRanges.some(range => 
            startPos >= range.start && endPos <= range.end
        );
        
        if (!isInsideCodeBlock) {
            urls.push({ url, startPos, endPos });
        }
    }
    
    return urls;
}

/**
 * Process all URLs in the message content and convert them to embeds.
 * This is called BEFORE sending a message to ensure URL metadata is fetched
 * and embeds are created with proper embed_ids.
 * 
 * @param markdown The markdown content to process
 * @returns Updated markdown with URLs replaced by embed references
 */
async function processUrlsBeforeSend(markdown: string): Promise<string> {
    const urls = detectUrlsInText(markdown);
    
    if (urls.length === 0) {
        console.debug('[sendHandlers] No URLs to process in message');
        return markdown;
    }
    
    console.info('[sendHandlers] Processing', urls.length, 'URL(s) before send');
    
    // Process URLs in parallel for better performance
    const embedPromises = urls.map(async (urlInfo) => {
        try {
            console.debug('[sendHandlers] Creating embed for URL:', urlInfo.url);
            const embedResult = await createEmbedFromUrl(urlInfo.url);
            return { urlInfo, embedResult };
        } catch (error) {
            console.error('[sendHandlers] Error creating embed for URL:', urlInfo.url, error);
            return { urlInfo, embedResult: null };
        }
    });
    
    const embedResults = await Promise.all(embedPromises);
    
    // Replace URLs with embed references from end to beginning to maintain positions
    const sortedResults = [...embedResults].sort((a, b) => b.urlInfo.startPos - a.urlInfo.startPos);
    let processedMarkdown = markdown;
    
    for (const { urlInfo, embedResult } of sortedResults) {
        if (!embedResult) {
            console.warn('[sendHandlers] Skipping URL - embed creation failed:', urlInfo.url);
            continue;
        }
        
        console.info('[sendHandlers] Replacing URL with embed reference:', {
            url: urlInfo.url,
            embed_id: embedResult.embed_id,
            type: embedResult.type
        });
        
        // Replace URL with embed reference block
        const beforeUrl = processedMarkdown.substring(0, urlInfo.startPos);
        const afterUrl = processedMarkdown.substring(urlInfo.endPos);
        
        // Ensure proper spacing around the embed reference block
        let processedBeforeUrl = beforeUrl;
        let processedAfterUrl = afterUrl;
        
        // Add newline before if there's content and it doesn't end with newline
        if (processedBeforeUrl.length > 0 && !processedBeforeUrl.endsWith('\n')) {
            processedBeforeUrl += '\n';
        }
        
        // Add newline after if there's content
        if (processedAfterUrl.length > 0 && !processedAfterUrl.startsWith('\n')) {
            processedAfterUrl = '\n' + processedAfterUrl;
        }
        
        processedMarkdown = processedBeforeUrl + embedResult.embedReference + processedAfterUrl;
    }
    
    console.debug('[sendHandlers] URL processing complete. Processed', embedResults.filter(r => r.embedResult).length, 'URL(s)');
    
    return processedMarkdown;
}

// =============================================================================
// Message Creation
// =============================================================================

/**
 * Creates a message payload from markdown content
 * @param markdown The processed markdown content (with URLs already converted to embeds)
 * @param chatId The ID of the current chat
 * @returns Message payload object with markdown content
 */
function createMessagePayload(markdown: string, chatId: string): Message {
    // Validate markdown content
    if (!markdown || typeof markdown !== 'string') {
        console.error('Invalid markdown content:', markdown);
        throw new Error('Invalid markdown content');
    }

    const message_id = `${chatId.slice(-10)}-${crypto.randomUUID()}`;

    // Check WebSocket connection status to determine initial message status
    // If offline, set status to 'waiting_for_internet' instead of 'sending'
    const wsStatus = get(websocketStatus);
    const isConnected = wsStatus.status === 'connected';
    const initialStatus: Message['status'] = isConnected ? 'sending' : 'waiting_for_internet';

    const message: Message = {
        message_id,
        chat_id: chatId,
        role: "user", // Changed from sender to role
        content: markdown, // Send markdown string directly to server (never Tiptap JSON!)
        status: initialStatus, // Initial status based on connection state
        created_at: Math.floor(Date.now() / 1000), // Unix timestamp in seconds
        sender_name: "user", // Set default sender name for Phase 2 encryption
        encrypted_content: null // Will be set during Phase 2 encryption
        // category will be set by server during preprocessing and sent back via chat_metadata_for_encryption
    };

    // current_chat_title removed - not needed for dual-phase architecture

    return message;
}

/**
 * Resets the editor content
 * @param editor The TipTap editor instance
 * @param shouldKeepFocus Whether to maintain focus after clearing (default: true on desktop, false on touch)
 */
function resetEditorContent(editor: Editor, shouldKeepFocus?: boolean) {
    // Clear the content. The `false` argument prevents triggering an 'update' event from this specific command.
    // Tiptap's Placeholder extension should handle showing placeholder text if the editor is empty.
    editor.commands.clearContent(false);
    
    // Determine if we should keep focus based on device type
    // On desktop: keep focus so user can continue typing
    // On touch devices: blur to make input compact and show assistant response better
    const keepFocus = shouldKeepFocus !== undefined ? shouldKeepFocus : isDesktop();
    
    if (keepFocus) {
        editor.commands.focus('end');
        console.debug('[resetEditorContent] Keeping focus on editor (desktop behavior)');
    } else {
        // Blur the editor on touch devices to make it compact
        editor.commands.blur();
        console.debug('[resetEditorContent] Blurring editor (touch device behavior)');
    }
}


/**
 * Handles sending a message via the message input
 */
export async function handleSend(
    editor: Editor | null,
    dispatch: (type: string, detail?: Record<string, unknown>) => void,
    setHasContent: (value: boolean) => void,
    currentChatId?: string
) {
    if (!editor || !hasActualContent(editor)) {
        vibrateMessageField();
        return;
    }
    
    // Get the TipTap editor content as JSON
    const editorContent = editor.getJSON();
    if (!editorContent || !editorContent.content || editorContent.content.length === 0) {
        console.warn('[handleSend] No editor content available');
        vibrateMessageField();
        return;
    }
    
    // Convert to markdown
    let markdown = tipTapToCanonicalMarkdown(editorContent);
    
    // CRITICAL: Process URLs before sending to convert them to proper embeds
    // This ensures that when user types "summarize https://example.com" and presses Enter,
    // the URL is converted to an embed with metadata fetched from the preview server.
    // The embed will be:
    // 1. Stored in EmbedStore for client-side access
    // 2. Sent with the message to the server
    // 3. Cached server-side for LLM inference (so LLM gets the URL metadata)
    try {
        markdown = await processUrlsBeforeSend(markdown);
    } catch (error) {
        console.error('[handleSend] Error processing URLs before send:', error);
        // Continue with original markdown if URL processing fails
    }
    
    // Debug logging: Show the markdown that will be sent to server
    console.log('[handleSend] 📤 Sending markdown to server:', {
        length: markdown.length,
        content: markdown,
        editorContent: editorContent
    });

    // Check if a new chat suggestion was clicked - if so, track it for deletion
    const { consumeClickedSuggestion } = await import('../../../stores/suggestionTracker');
    const encryptedSuggestionToDelete = consumeClickedSuggestion();
    console.log('[handleSend] SUGGESTION DEBUG 1: consumeClickedSuggestion result:', {
        hasValue: !!encryptedSuggestionToDelete,
        value: encryptedSuggestionToDelete ? `${encryptedSuggestionToDelete.substring(0, 20)}...` : null
    });
    
    if (encryptedSuggestionToDelete) {
        console.debug('[handleSend] New chat suggestion was used, will delete from client and server:', encryptedSuggestionToDelete);
        // Delete from local IndexedDB immediately
        try {
            const { chatDB } = await import('../../../services/db');
            
            // We need to find the suggestion by encrypted match and delete it by ID
            console.log('[handleSend] SUGGESTION DEBUG 2: Getting all suggestions from DB...');
            const allSuggestions = await chatDB.getAllNewChatSuggestions();
            console.log('[handleSend] SUGGESTION DEBUG 3: Found total suggestions in DB:', {
                count: allSuggestions.length,
                suggestions: allSuggestions.map(s => ({
                    id: s.id,
                    encrypted: `${s.encrypted_suggestion.substring(0, 20)}...`,
                    created_at: s.created_at
                }))
            });
            
            const suggestionToDelete = allSuggestions.find(s => s.encrypted_suggestion === encryptedSuggestionToDelete);
            console.log('[handleSend] SUGGESTION DEBUG 4: Search result for encrypted match:', {
                found: !!suggestionToDelete,
                suggestionId: suggestionToDelete?.id,
                matchedEncrypted: suggestionToDelete ? `${suggestionToDelete.encrypted_suggestion.substring(0, 20)}...` : null
            });
            
            if (suggestionToDelete) {
                console.log('[handleSend] SUGGESTION DEBUG 5: Found suggestion to delete, will delete by ID...');
                
                // Delete directly by ID instead of re-encrypting text
                // This avoids encryption mismatch issues
                const deleteResult = await chatDB.deleteNewChatSuggestionById(suggestionToDelete.id);
                console.log('[handleSend] SUGGESTION DEBUG 8: Deletion result:', {
                    success: deleteResult,
                    message: deleteResult ? '✅ Deleted' : '❌ Failed to delete'
                });
                
                if (deleteResult) {
                    // Verify deletion by checking DB again
                    const suggestionAfterDelete = await chatDB.getAllNewChatSuggestions();
                    console.log('[handleSend] SUGGESTION DEBUG 9: Verification after deletion:', {
                        totalAfterDelete: suggestionAfterDelete.length,
                        stillExists: suggestionAfterDelete.some(s => s.id === suggestionToDelete.id)
                    });
                }
            } else {
                console.warn('[handleSend] SUGGESTION DEBUG 4B: Suggestion NOT found in DB!', {
                    searchedFor: `${encryptedSuggestionToDelete.substring(0, 20)}...`,
                    dbHas: allSuggestions.map(s => s.encrypted_suggestion.substring(0, 20))
                });
            }
        } catch (error) {
            console.error('[handleSend] SUGGESTION DEBUG ERROR: Failed to delete new chat suggestion from local IndexedDB:', {
                error: error instanceof Error ? error.message : String(error),
                stack: error instanceof Error ? error.stack : undefined
            });
            // Continue with message send even if deletion fails
        }
    } else {
        console.log('[handleSend] SUGGESTION DEBUG 1B: No suggestion was tracked for deletion (encryptedSuggestionToDelete is null/undefined)');
    }

    let chatIdToUse = currentChatId;
    let chatToUpdate: import('../../../types/chat').Chat | null = null;
    let isNewChatCreation = false;
    let messagePayload: Message; // Defined here to be accessible for sendNewMessage

    try {
        // Check if there's already a chat with a draft (created during typing)
        const draftState = get(draftEditorUIState);
        if (!chatIdToUse && draftState.currentChatId) {
            // Use the existing chat that was created for the draft
            chatIdToUse = draftState.currentChatId;
            console.info(`[handleSend] Using existing draft chat ${chatIdToUse} for message`);
        } else if (!chatIdToUse) {
            // Only create a new chat if there's no current chat and no draft chat
            chatIdToUse = crypto.randomUUID();
            isNewChatCreation = true;
            console.info(`[handleSend] Creating new chat ${chatIdToUse} for message`);
        }

        // CRITICAL: Check if we're sending a message to a demo/legal chat (public chat)
        // If so, we MUST generate a new UUID for the chat so it becomes a regular chat
        // This ensures:
        // 1. The chat can't be identified as demo/legal later
        // 2. Message IDs use proper format {last_10_chars_of_UUID}-{uuid_v4} instead of {last_10_chars_of_demo-welcome}-{uuid_v4}
        if (chatIdToUse && isPublicChat(chatIdToUse)) {
            const oldChatId = chatIdToUse;
            chatIdToUse = crypto.randomUUID();
            isNewChatCreation = true;
            console.info(`[handleSend] 🔄 Converting public chat ${oldChatId} to regular chat ${chatIdToUse} - user sent message to demo/legal chat`);
        }

        // Check if we're using an existing draft chat
        const isUsingDraftChat = !currentChatId && draftState.currentChatId && chatIdToUse === draftState.currentChatId;
        
        // Check if we're dealing with a temporary chat ID (not a real chat in the database)
        // This happens when a temporaryChatId was set in ActiveChat but the chat doesn't actually exist in DB
        // We need to check the database to determine if this is a real chat or temporary
        const existingChatCheck = await chatDB.getChat(chatIdToUse);
        const isTemporaryChat = !existingChatCheck && !isNewChatCreation;
        if (isTemporaryChat) {
            // For temporary chats, we need to create a new chat
            isNewChatCreation = true;
            console.info(`[handleSend] Detected temporary chat ID ${chatIdToUse} (not in DB), treating as new chat creation`);
        }
        
        // No need to fetch current title - server will send metadata after preprocessing

        // Create new message payload using the processed markdown and determined chatIdToUse
        // The markdown has already been processed to convert URLs to embed references
        messagePayload = createMessagePayload(markdown, chatIdToUse);

        // Optimistically cache the last message so the chat list can show "Sending..." immediately
        // (prevents a brief empty chat row while active chat selection/metadata settles)
        chatListCache.setLastMessage(chatIdToUse, messagePayload);
        
        // Debug logging to understand the flow
        console.debug(`[handleSend] Chat creation logic:`, {
            currentChatId,
            draftChatId: draftState.currentChatId,
            chatIdToUse,
            isNewChatCreation,
            isUsingDraftChat,
            isTemporaryChat
        });
        
        // Check if incognito mode is enabled
        const { incognitoMode } = await import('../../../stores/incognitoModeStore');
        const isIncognitoEnabled = incognitoMode.get();
        
        if (isNewChatCreation) {
            const now = Math.floor(Date.now() / 1000);
            const newChatData: import('../../../types/chat').Chat = {
                chat_id: chatIdToUse,
                encrypted_title: null,
                messages_v: 1, // A new chat with its first message starts at version 1
                title_v: 0, // Will be incremented to 1 when first title is set
                draft_v: 0,
                encrypted_draft_md: null,
                encrypted_draft_preview: null,
                last_edited_overall_timestamp: messagePayload.created_at, // Use message timestamp
                unread_count: 0,
                created_at: now,
                updated_at: now,
                processing_metadata: false, // Show chat immediately in sidebar (no longer hidden)
                waiting_for_metadata: !isIncognitoEnabled, // Incognito chats don't get metadata from server
                is_incognito: isIncognitoEnabled
            };
            console.debug(`[handleSend] Creating new ${isIncognitoEnabled ? 'incognito' : 'regular'} chat with waiting_for_metadata=${newChatData.waiting_for_metadata}:`, {
                chatId: chatIdToUse,
                waiting_for_metadata: newChatData.waiting_for_metadata
            });
            
            if (isIncognitoEnabled) {
                // Create incognito chat in sessionStorage
                const { incognitoChatService } = await import('../../../services/incognitoChatService');
                await incognitoChatService.storeChat(newChatData);
                await incognitoChatService.addMessage(chatIdToUse, messagePayload);
                chatToUpdate = newChatData;
                console.info(`[handleSend] Created new incognito chat ${chatIdToUse} and saved its first message.`);
            } else {
                // Create regular chat in IndexedDB
                await chatDB.addChat(newChatData); // Save new chat metadata
                await chatDB.saveMessage(messagePayload); // Save the first message separately
                
                // Fetch the chat again to ensure we have the consistent DB version for chatToUpdate
                // This also ensures chatToUpdate has the correct messages_v (which is 1)
                chatToUpdate = await chatDB.getChat(chatIdToUse); 
                if (!chatToUpdate) {
                     console.error(`[handleSend] CRITICAL: Newly created chat ${chatIdToUse} not found in DB immediately after addChat and saveMessage.`);
                     vibrateMessageField();
                     return;
                }
                console.info(`[handleSend] Created new local chat ${chatIdToUse} and saved its first message (messages_v should be 1).`);
            }
            
            // Dispatch event to update chat list immediately
            window.dispatchEvent(new CustomEvent('localChatListChanged', { 
                detail: { chat_id: chatIdToUse } 
            }));
        } else {
            // Existing chat: Save the new message and update chat metadata
            // Check if it's an incognito chat
            const { incognitoChatService } = await import('../../../services/incognitoChatService');
            let isIncognitoChat = false;
            let existingChat: import('../../../types/chat').Chat | null = null;
            
            try {
                existingChat = await incognitoChatService.getChat(chatIdToUse);
                if (existingChat) {
                    isIncognitoChat = true;
                }
            } catch {
                // Not an incognito chat, continue to check IndexedDB
            }
            
            if (isIncognitoChat && existingChat) {
                // Update incognito chat
                await incognitoChatService.addMessage(chatIdToUse, messagePayload);
                existingChat.messages_v = (existingChat.messages_v || 0) + 1;
                existingChat.last_edited_overall_timestamp = messagePayload.created_at;
                existingChat.updated_at = Math.floor(Date.now() / 1000);
                await incognitoChatService.updateChat(chatIdToUse, {
                    messages_v: existingChat.messages_v,
                    last_edited_overall_timestamp: existingChat.last_edited_overall_timestamp,
                    updated_at: existingChat.updated_at
                });
                chatToUpdate = existingChat;
                console.info(`[handleSend] Updated incognito chat ${chatIdToUse} with new message.`);
            } else {
                // Update regular chat in IndexedDB
                await chatDB.saveMessage(messagePayload);
                existingChat = await chatDB.getChat(chatIdToUse);
                if (existingChat) {
                    existingChat.messages_v = (existingChat.messages_v || 0) + 1;
                    existingChat.last_edited_overall_timestamp = messagePayload.created_at;
                    existingChat.updated_at = Math.floor(Date.now() / 1000);
                    
                    // Clear draft fields after message is sent (especially important for draft chats)
                    existingChat.encrypted_draft_md = null;
                    existingChat.encrypted_draft_preview = null;
                    existingChat.draft_v = 0;
                    
                    await chatDB.updateChat(existingChat);
                    chatToUpdate = existingChat;
                    
                    if (isUsingDraftChat) {
                        console.info(`[handleSend] Updated existing draft chat ${chatIdToUse} with first message and cleared draft fields`);
                    } else {
                        console.info(`[handleSend] Updated existing chat ${chatIdToUse} with new message and cleared draft fields`);
                    }
                } else {
                    console.error(`[handleSend] Existing chat ${chatIdToUse} not found when trying to add a message.`);
                    vibrateMessageField();
                    return; // Early exit if chat doesn't exist
                }
            }
        }

        // If chatToUpdate is null at this point, the local DB operation failed.
        if (!chatToUpdate) {
            console.error(`[handleSend] Failed to update local chat ${chatIdToUse} with new message. Aborting send.`);
            vibrateMessageField();
            return;
        }
        
        // Check if there's an active AI task for this chat
        // If so, the new message will be queued on the server
        // We don't cancel the existing task - it will complete and then process the queued message
        if (chatIdToUse && chatSyncService) {
            const existingTaskId = chatSyncService.getActiveAITaskIdForChat(chatIdToUse);
            if (existingTaskId) {
                console.info(`[handleSend] Active AI task ${existingTaskId} exists for chat ${chatIdToUse}. New message will be queued.`);
                // TODO: Show UI message "Press enter again to stop previous response" or similar
                // This will be handled by the frontend when it receives a queue notification
            }
        }
        
        // Set hasContent to false first to prevent race conditions with editor updates
        setHasContent(false);
        // Reset editor and force blur to show stop button and reduce height
        // Always blur after sending to make input compact and show assistant response
        resetEditorContent(editor, false); // Force blur (false = don't keep focus)

        // Dispatch for UI update (ActiveChat will pick this up)
        // The messagePayload is already defined and includes the correct chat_id
        // If it's a new chat (isNewChatCreation is true) OR we're using an existing draft chat, 
        // chatToUpdate will hold the Chat object.
        dispatch("sendMessage", { 
            message: messagePayload, 
            newChat: (isNewChatCreation || isUsingDraftChat) ? chatToUpdate : undefined 
        });

        // chatToUpdate should be the definitive version of the chat from the DB
        // The 'chatUpdated' event is still useful for other components like the chat list.
        if (chatToUpdate) {
            // Dispatch chatUpdated so other parts of the UI (like chat list) can update if needed
            // This local dispatch is for MessageInput's parent (ActiveChat)
            dispatch("chatUpdated", { chat: chatToUpdate }); 

            // If a new chat was created, signal it through draftEditorUIState
            // This is what Chats.svelte listens to for selecting new chats.
            if (isNewChatCreation) {
                draftEditorUIState.update(state => ({ ...state, newlyCreatedChatIdToSelect: chatIdToUse }));
                console.info(`[handleSend] Signaled new chat ${chatIdToUse} for selection via draftEditorUIState.`);
            } else {
                // For existing chats, ensure chatSyncService knows about the local update
                // so it can propagate to Chats.svelte if necessary, or handle consistency.
                // A more direct way for Chats.svelte to react to local DB changes might be needed
                // if chatSyncService events are strictly for server-originated changes.
                // For now, we rely on draftEditorUIState for new chats, and existing chat updates
                // should be picked up by Chats.svelte if it re-queries DB on 'chatUpdated' from ActiveChat.
                 window.dispatchEvent(new CustomEvent('chatUpdated', { // This helps Chats.svelte if it listens globally or via ActiveChat relay
                    detail: { chat_id: chatToUpdate.chat_id, chat: chatToUpdate }, // Ensure chat_id is at top level for some handlers
                    bubbles: true,
                    composed: true
                }));
            }
        }


        // CRITICAL: Notify backend about the active chat BEFORE sending the message
        // This prevents race conditions where the backend starts processing the message
        // and tries to stream chunks before knowing which chat is active, causing chunks to be dropped
        // This is especially important for new chats where the active_chat might be null or the old chat ID
        await chatSyncService.sendSetActiveChat(chatIdToUse);
        console.debug('[handleSend] Notified backend about active chat before sending message:', chatIdToUse);

        // Send message to backend via chatSyncService
        // Include encrypted suggestion for deletion if one was clicked
        await chatSyncService.sendNewMessage(messagePayload, encryptedSuggestionToDelete);
        console.debug('[handleSend] Message sent to chatSyncService:', messagePayload, encryptedSuggestionToDelete ? '(with suggestion to delete)' : '');

        // After successfully sending the message, clear the draft for this chat
        // Ensure we only clear if the message was for the chat currently in the draft editor's context
        const currentDraftState = get(draftEditorUIState);
        if (chatIdToUse && currentDraftState.currentChatId === chatIdToUse) {
            console.info(`[handleSend] Message sent for chat ${chatIdToUse}, clearing its draft.`);
            await clearCurrentDraft();
        } else {
            // This case might happen if a message is sent for a chat that isn't the one
            // currently active in the MessageInput's draft context (e.g., programmatic send).
            // Or if a new chat was just created, the draft context might not be set yet,
            // but clearCurrentDraft relies on draftEditorUIState.currentChatId.
            // If it's a new chat, there shouldn't be a draft to clear anyway.
            // If it's an existing chat but not the one in draft context, we might not want to clear its draft.
            // The current logic of clearCurrentDraft uses draftEditorUIState.currentChatId,
            // so if chatIdToUse is different, it won't clear the draft of chatIdToUse unless
            // draftEditorUIState.currentChatId happens to be chatIdToUse.
            // This seems fine for now, as sending a message typically implies the chat is active.
            console.debug(`[handleSend] Message sent for chat ${chatIdToUse}, but draft context is ${currentDraftState.currentChatId}. Draft clear skipped or handled by clearCurrentDraft's internal logic.`);
        }

    } catch (error) {
        console.error('Failed to handle message send:', error);
        vibrateMessageField();
    }
}

/**
 * Clears the message field and resets it to initial state
 * @param editor The TipTap editor instance
 * @param shouldKeepFocus Whether to maintain focus after clearing (default: true on desktop, false on touch)
 */
export function clearMessageField(editor: Editor | null, shouldKeepFocus?: boolean) {
    if (!editor) return;
    resetEditorContent(editor, shouldKeepFocus);
}



/**
 * Creates a custom keyboard extension for handling Enter key events in the editor
 * @returns TipTap extension for custom keyboard handling
 */
export function createKeyboardHandlingExtension() {
    return Extension.create({
        name: 'customKeyboardHandling',
        priority: 1000,

        addKeyboardShortcuts() {
            return {
                // Handle regular Enter press
                Enter: ({ editor }) => {
                    const desktop = isDesktop();

                    // On mobile, Enter should create a new line. Returning false lets TipTap handle it.
                    if (!desktop) {
                        return false;
                    }

                    // On desktop, Enter sends the message.
                    // But we don't handle Enter if Shift is pressed (that's for newlines).
                    // The 'Shift-Enter' shortcut below handles that case by returning false.
                    
                    // Don't do anything if there's a text selection, let the user replace it.
                    if (this.editor.view.state.selection.$anchor.pos !== this.editor.view.state.selection.$head.pos) {
                        return false;
                    }

                    if (hasActualContent(editor)) {
                        // CRITICAL: Check authentication status before sending
                        // Unauthenticated users should be prompted to sign in, not have their message sent
                        // (which would fail because WebSocket requires authentication)
                        const isAuthenticated = get(authStore).isAuthenticated;
                        
                        if (!isAuthenticated) {
                            // Dispatch sign-in event instead of send event for unauthenticated users
                            // This triggers the sign-in flow which saves the draft and opens login interface
                            const signInEvent = new Event('custom-sign-in-click', {
                                bubbles: true,
                                cancelable: true
                            });
                            editor.view.dom.dispatchEvent(signInEvent);
                            console.debug('[KeyboardShortcuts] User not authenticated, triggering sign-in flow instead of send');
                            return true; // We've handled the event.
                        }
                        
                        // Dispatch our custom event to send the message.
                        const sendEvent = new Event('custom-send-message', {
                            bubbles: true,
                            cancelable: true
                        });
                        editor.view.dom.dispatchEvent(sendEvent);
                        return true; // We've handled the event.
                    } else {
                        vibrateMessageField();
                        return true; // We've handled the event, even if we did nothing.
                    }
                },

                // Handle Shift+Enter for line breaks
                'Shift-Enter': () => {
                    // Return false to let TipTap handle the default line break behavior
                    return false;
                },
            };
        },
    });
}
