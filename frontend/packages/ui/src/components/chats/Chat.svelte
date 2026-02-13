<script lang="ts">
  import type { Chat, TiptapJSON, Message, AITypingStartedPayload, AITaskInitiatedPayload } from '../../types/chat';
  import { onMount, onDestroy } from 'svelte';
  import { chatSyncService } from '../../services/chatSyncService';
  import { chatDB } from '../../services/db';
  import { notificationStore } from '../../stores/notificationStore';
  import { unreadMessagesStore } from '../../stores/unreadMessagesStore';
  import { text } from '@repo/ui'; // Use text store from @repo/ui
  import { aiTypingStore, type AITypingStatus } from '../../stores/aiTypingStore';
  import { decryptWithMasterKey, decryptWithChatKey } from '../../services/cryptoService';
  import { parse_message } from '../../message_parsing/parse_message';
  import { extractUrlFromJsonEmbedBlock } from '../enter_message/services/urlMetadataService';
  import { LOCAL_CHAT_LIST_CHANGED_EVENT } from '../../services/drafts/draftConstants';
  import { chatMetadataCache, type DecryptedChatMetadata } from '../../services/chatMetadataCache';
  import { chatListCache } from '../../services/chatListCache'; // Global cache for last messages
  import ChatContextMenu from './ChatContextMenu.svelte';
  import { copyChatToClipboard, type PIIExportOptions } from '../../services/chatExportService';
  import { downloadChatAsZip } from '../../services/zipExportService';
  import { piiVisibilityStore } from '../../stores/piiVisibilityStore';
  import type { DecryptedChatData } from '../../types/chat';
  import { DEMO_CHATS, LEGAL_CHATS, getDemoMessages, isPublicChat, isDemoChat, isLegalChat, getDemoChatById, getLegalChatById } from '../../demo_chats'; // Import demo chat utilities
  import { authStore } from '../../stores/authStore'; // Import authStore to check authentication
  import { getSessionStorageDraftPreview } from '../../services/drafts/sessionStorageDraftService'; // Import sessionStorage draft service
  import { userProfile } from '../../stores/userProfile'; // Import userProfile to update hidden_demo_chats
  import { websocketStatus } from '../../stores/websocketStatusStore'; // Import WebSocket status for connection checks
  import { 
    getCategoryGradientColors, 
    getFallbackIconForCategory, 
    getValidIconName, 
    getLucideIcon
  } from '../../utils/categoryUtils';
  import { modelsMetadata } from '../../data/modelsMetadata'; // For model name lookup in mentions
  import { matesMetadata } from '../../data/matesMetadata'; // For mate name lookup in mentions
  import { appSkillsStore } from '../../stores/appSkillsStore'; // For skill/focus/memory name lookup in mentions
  
  // Import Lucide icons dynamically
  import * as LucideIcons from '@lucide/svelte';

  // Props using Svelte 5 runes
  let { 
    chat,
    activeChatId = undefined,
    selectMode = false,
    selectedChatIds = new Set<string>(),
    onToggleSelection
  }: {
    chat: Chat;
    activeChatId?: string | undefined;
    selectMode?: boolean;
    selectedChatIds?: Set<string>;
    onToggleSelection?: (chatId: string) => void;
  } = $props();
  
  // Check if this chat is selected
  let isSelected = $derived(chat ? selectedChatIds.has(chat.chat_id) : false);
 
  let draftTextContent = $state(''); 
  let displayLabel = $state('');     
  let displayText = $state('');
  let hasWaitingForUser = $state(false);
  let currentTypingMateInfo: AITypingStatus | null = $state(null);
  let lastMessage: Message | null = $state(null); // Declare lastMessage here
  let typingStoreValue = $state<AITypingStatus>({ 
    isTyping: false, 
    category: null, 
    modelName: null, 
    providerName: null,
    chatId: null, 
    userMessageId: null, 
    aiMessageId: null 
  });
  
  // Category circle state
  let categoryIconNames: string[] = $state([]);
  let categoryGradientColors: { start: string; end: string } | null = $state(null);
  let chatCategory: string | null = $state(null); // Store the chat's category (null if not set by server)
  let chatIcon: string | null = $state(null); // Store the chat's icon (null if not set by server)
  
  // Context menu state
  let showContextMenu = $state(false);
  let contextMenuX = $state(0);
  let contextMenuY = $state(0);
  let isDownloading = $state(false); // Track download in progress for context menu loading state

  // Touch/long-press detection state
  let touchTimer: ReturnType<typeof setTimeout> | null = null;
  let touchStartX = 0;
  let touchStartY = 0;
  const LONG_PRESS_DURATION = 500; // milliseconds
  const TOUCH_MOVE_THRESHOLD = 10; // pixels

  // Subscribe to aiTypingStore with proper cleanup
  let unsubscribeTypingStore: (() => void) | null = null;
  
  onMount(() => {
    unsubscribeTypingStore = aiTypingStore.subscribe(value => {
      // Update the typing store value (needed for reactive updates)
      // Don't log - this fires for every chat component on every store change
      // Only log in exceptional cases if needed for debugging
      typingStoreValue = value;
    });
  });
  
  onDestroy(() => {
    if (unsubscribeTypingStore) {
      unsubscribeTypingStore();
      unsubscribeTypingStore = null;
    }
  });

  function extractTextFromTiptap(jsonContent: TiptapJSON | null | undefined): string {
    if (!jsonContent || !jsonContent.content) return '';
    // Type guard: ensure content is an array before mapping
    if (!Array.isArray(jsonContent.content)) return '';
    try {
      return jsonContent.content.map((node: any) =>
        node.content?.map((contentNode: any) =>
          contentNode.type === 'text' ? contentNode.text : ''
        ).join('')
      ).join('\n').trim() || '';
    } catch (error) {
      console.error('Error extracting text from Tiptap content:', error);
      return '';
    }
  }

  /**
   * Convert a name to hyphenated format for mention display.
   * e.g., "Claude 4.5 Opus" -> "Claude-4.5-Opus"
   */
  function toHyphenatedName(name: string): string {
    return name.replace(/\s+/g, '-');
  }

  /**
   * Capitalize first letter of each word for display.
   * e.g., "get-docs" -> "Get-Docs"
   */
  function capitalizeWords(str: string): string {
    return str.split('-').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join('-');
  }

  /**
   * Convert backend mention syntax to human-readable display names.
   * This ensures draft previews show "@Claude-4.5-Opus" instead of "@ai-model:claude-4-sonnet"
   */
  function convertMentionSyntaxToDisplayName(text: string): string {
    // Replace @ai-model:{id} with @Model-Name
    text = text.replace(/@ai-model:([^\s]+)/g, (match, modelId) => {
      const model = modelsMetadata.find(m => m.id === modelId);
      if (model) {
        return `@${toHyphenatedName(model.name)}`;
      }
      return match;
    });
    
    // Replace @mate:{id} with @MateName
    text = text.replace(/@mate:([^\s]+)/g, (match, mateId) => {
      const mate = matesMetadata.find(m => m.id === mateId);
      if (mate) {
        const displayName = capitalizeWords(mate.search_names[0] || mate.id);
        return `@${displayName}`;
      }
      return match;
    });
    
    // Replace @skill:{app_id}:{skill_id} with @App-Skill-Name
    text = text.replace(/@skill:([^:]+):([^\s]+)/g, (match, appId, skillId) => {
      const apps = appSkillsStore.apps;
      const app = apps[appId];
      if (app) {
        const skill = app.skills.find(s => s.id === skillId);
        if (skill) {
          const appDisplayName = capitalizeWords(appId);
          const skillDisplayName = capitalizeWords(skillId.replace(/_/g, '-'));
          return `@${appDisplayName}-${skillDisplayName}`;
        }
      }
      return match;
    });
    
    // Replace @focus:{app_id}:{focus_id} with @App-Focus-Name
    text = text.replace(/@focus:([^:]+):([^\s]+)/g, (match, appId, focusId) => {
      const apps = appSkillsStore.apps;
      const app = apps[appId];
      if (app) {
        const focusMode = app.focus_modes.find(f => f.id === focusId);
        if (focusMode) {
          const appDisplayName = capitalizeWords(appId);
          const focusDisplayName = capitalizeWords(focusId.replace(/_/g, '-'));
          return `@${appDisplayName}-${focusDisplayName}`;
        }
      }
      return match;
    });
    
    // Replace @memory:{app_id}:{memory_id}:{type} with @App-Memory-Name
    text = text.replace(/@memory:([^:]+):([^:]+):([^\s]+)/g, (match, appId, memoryId) => {
      const apps = appSkillsStore.apps;
      const app = apps[appId];
      if (app) {
        const memory = app.settings_and_memories.find(m => m.id === memoryId);
        if (memory) {
          const appDisplayName = capitalizeWords(appId);
          const memoryDisplayName = capitalizeWords(memoryId.replace(/_/g, '-'));
          return `@${appDisplayName}-${memoryDisplayName}`;
        }
      }
      return match;
    });
    
    return text;
  }

  /**
   * Extract text from markdown, replacing json_embed blocks with their URLs
   * and code blocks with readable placeholders for better display in chat previews
   */
  function extractDisplayTextFromMarkdown(markdown: string): string {
    if (!markdown) return '';
    
    try {
      let displayText = markdown;
      
      // Convert backend mention syntax to human-readable display names
      // e.g., "@ai-model:claude-4-sonnet" -> "@Claude-4.5-Sonnet"
      displayText = convertMentionSyntaxToDisplayName(displayText);
      
      // Replace json_embed code blocks with their URLs for display, ensuring proper spacing
      displayText = displayText.replace(/```json_embed\n([\s\S]*?)\n```/g, (match, jsonContent) => {
        const url = extractUrlFromJsonEmbedBlock(match);
        if (url) {
          // Ensure the URL has spaces around it for proper separation from surrounding text
          return ` ${url} `;
        }
        return match; // Return original if URL extraction failed
      });
      
      // Replace regular code blocks with a placeholder showing the code content
      // This handles ```python\ncode\n``` style blocks
      displayText = displayText.replace(/```(\w*)\n([\s\S]*?)\n```/g, (match, language, codeContent) => {
        // Show the actual code content, not just the language
        const trimmedCode = codeContent.trim();
        if (trimmedCode) {
          // Show first line of code or truncated version
          const firstLine = trimmedCode.split('\n')[0].trim();
          return ` [Code: ${firstLine.substring(0, 30)}${firstLine.length > 30 ? '...' : ''}] `;
        }
        return language ? ` [${language} code] ` : ' [code] ';
      });
      
      // Clean up multiple spaces and trim
      return displayText.replace(/\s+/g, ' ').trim();
    } catch (error) {
      console.error('[Chat] Error extracting display text from markdown:', error);
      return markdown;
    }
  }

  /**
   * Decrypt chat data on-demand (icon and category)
   * ARCHITECTURE: Demo chats use cleartext fields (icon, category), 
   * regular chats use encrypted fields (encrypted_icon, encrypted_category)
   */
  async function decryptChatData(chat: Chat): Promise<DecryptedChatData> {
    const result: DecryptedChatData = {};
    
    // Check for cleartext fields first (demo chats - already decrypted server-side)
    if (chat.icon) {
      result.icon = chat.icon;
    }
    if (chat.category) {
      result.category = chat.category;
    }
    
    // If we already have cleartext data, return it
    if (result.icon || result.category) {
      return result;
    }
    
    // For regular chats, decrypt from encrypted fields
    // Get chat key for decryption
    const chatKey = chatDB.getChatKey(chat.chat_id);
    if (!chatKey) {
      console.warn(`[Chat] No chat key found for chat ${chat.chat_id}, cannot decrypt icon/category`);
      return result;
    }
    
    // Decrypt icon if present
    if (chat.encrypted_icon) {
      try {
        const decryptedIcon = await decryptWithChatKey(chat.encrypted_icon, chatKey);
        if (decryptedIcon) {
          result.icon = decryptedIcon;
        }
      } catch (error) {
        console.error(`[Chat] Error decrypting icon for chat ${chat.chat_id}:`, error);
      }
    }
    
    // Decrypt category if present
    if (chat.encrypted_category) {
      try {
        const decryptedCategory = await decryptWithChatKey(chat.encrypted_category, chatKey);
        if (decryptedCategory) {
          result.category = decryptedCategory;
        }
      } catch (error) {
        console.error(`[Chat] Error decrypting category for chat ${chat.chat_id}:`, error);
      }
    }
    
    return result;
  }

  // Update typing indicator based on store value
  $effect(() => {
    if (chat && typingStoreValue && typingStoreValue.chatId === chat.chat_id && typingStoreValue.isTyping) {
      currentTypingMateInfo = typingStoreValue;
      console.debug(`[Chat] Setting typing indicator for chat ${chat.chat_id}`);
      
      // Update category circle data when typing starts
      if (typingStoreValue.category) {
        categoryGradientColors = getCategoryGradientColors(typingStoreValue.category);
        // icon_names from the typing store
        categoryIconNames = typingStoreValue.icon_names || [];
      }
    } else {
      if (currentTypingMateInfo) {
        console.debug(`[Chat] Clearing typing indicator for chat ${chat.chat_id}`);
      }
      currentTypingMateInfo = null; 
      
      // When typing ends, restore the category from chat metadata (stored in chatCategory)
      // This ensures the permanent category is displayed, not the typing indicator's category
      // Only set gradient if category exists (null = no fallback)
      if (chat && !currentTypingMateInfo) {
        categoryGradientColors = chatCategory ? getCategoryGradientColors(chatCategory) : null;
        categoryIconNames = []; // No icon names for regular chats (only shown during typing)
      }
    }
  });

  let typingIndicatorInTitleView = $derived((() => {
    if (currentTypingMateInfo?.isTyping && currentTypingMateInfo.category) {
      const mateName = $text(`mates.${currentTypingMateInfo.category}.text`);
      return $text('enter_message.is_typing.text').replace('{mate}', mateName);
    }
    return null;
  })());

  // Store cached metadata at component level
  let cachedMetadata: DecryptedChatMetadata | null = $state(null);
  
  // CRITICAL: Track if we're waiting for title (reactive variable for template)
  // This ensures we keep showing "Processing..." until title is ready
  let isWaitingForTitle = $derived(!cachedMetadata?.title && !chat.title && 
                                    (chat.waiting_for_metadata === true || 
                                     (lastMessage && (lastMessage.status === 'processing' || lastMessage.status === 'sending'))));

  async function updateDisplayInfo(currentChat: Chat) {
    if (!currentChat) {
      draftTextContent = '';
      lastMessage = null;
      displayLabel = '';
      displayText = '';
      cachedMetadata = null;
      return;
    }

    // PUBLIC CHAT HANDLING (demo + legal): Public chats have plaintext titles and categories, no encryption
    if (isPublicChat(currentChat.chat_id)) {
      // CRITICAL: For non-authenticated users, check sessionStorage for drafts
      // Authenticated users won't have drafts in demo chats (they would have converted to regular chats)
      if (!$authStore.isAuthenticated) {
        const sessionDraftPreview = getSessionStorageDraftPreview(currentChat.chat_id);
        if (sessionDraftPreview) {
          draftTextContent = sessionDraftPreview;
          console.debug(`[Chat] Found sessionStorage draft preview for demo chat ${currentChat.chat_id}:`, {
            previewLength: sessionDraftPreview.length,
            preview: sessionDraftPreview.substring(0, 50)
          });
        } else {
          draftTextContent = '';
        }
      } else {
        // Authenticated users: public chats have no drafts (they would have been converted to regular chats)
        draftTextContent = '';
      }
      
      // Load messages from static bundle instead of IndexedDB (searches both DEMO_CHATS and LEGAL_CHATS)
      const demoMessages = getDemoMessages(currentChat.chat_id, DEMO_CHATS, LEGAL_CHATS);
      lastMessage = demoMessages && demoMessages.length > 0 ? demoMessages[demoMessages.length - 1] : null;
      
      // ARCHITECTURE: Demo chats use cleartext fields (category, icon)
      // Fallback to encrypted_* fields for backwards compatibility
      chatCategory = currentChat.category || currentChat.encrypted_category || null;
      
      // Icon names stored in icon field (as comma-separated string for demos)
      // Fallback to encrypted_icon for backwards compatibility
      const iconField = currentChat.icon || currentChat.encrypted_icon;
      if (iconField) {
        const iconNames = iconField.split(',');
        chatIcon = iconNames.length > 0 ? iconNames[0] : null;
      } else {
        chatIcon = null;
      }
      
      // Public chat loaded (no log needed - this is normal operation when component mounts or updates)
      
      // No cached metadata for public chats (they don't use encryption)
      cachedMetadata = null;
      
      // Public chats show draft status if there's a sessionStorage draft
      // Otherwise show no status line (no drafts, no sending status)
      if (draftTextContent) {
        displayLabel = $text('enter_message.draft.text');
        displayText = draftTextContent;
      } else {
        displayLabel = '';
        displayText = '';
      }
      return;
    }

    // REGULAR CHAT HANDLING: Get draft content using cached metadata for performance
    // CRITICAL: For non-authenticated users, check if this is a shared chat (has chat key) or sessionStorage-only chat
    if (!$authStore.isAuthenticated) {
      // Check if this is a shared chat (has chat key in cache) or sessionStorage-only chat
      const chatKey = chatDB.getChatKey(currentChat.chat_id);
      const sessionDraftPreview = getSessionStorageDraftPreview(currentChat.chat_id);
      
      if (sessionDraftPreview) {
        // SessionStorage-only chat (new chat with draft that doesn't exist in database yet)
        draftTextContent = sessionDraftPreview;
        console.debug('[Chat] Found sessionStorage draft preview for new chat:', {
          chatId: currentChat.chat_id,
          previewLength: sessionDraftPreview.length,
          preview: sessionDraftPreview.substring(0, 50)
        });
        
        // SessionStorage-only chats have no messages and no metadata
        lastMessage = null;
        cachedMetadata = null;
        chatCategory = null;
        chatIcon = null;
      } else if (chatKey) {
        // Shared chat - has chat key, can decrypt metadata
        // Try to get decrypted metadata (for shared chats, this will decrypt title, category, icon)
        cachedMetadata = await chatMetadataCache.getDecryptedMetadata(currentChat);
        
        if (cachedMetadata?.draftPreview) {
          draftTextContent = cachedMetadata.draftPreview;
        } else {
          draftTextContent = '';
        }
        
        // Load last message from IndexedDB for shared chats
        try {
          lastMessage = await chatDB.getLastMessageForChat(currentChat.chat_id);
        } catch (error) {
          console.debug(`[Chat] Error loading last message for shared chat ${currentChat.chat_id}:`, error);
          lastMessage = null;
        }
        
        // Use decrypted metadata for category and icon
        if (cachedMetadata?.category) {
          chatCategory = cachedMetadata.category;
          chatIcon = cachedMetadata.icon || null;
          console.debug(`[Chat] Using decrypted metadata for shared chat - category: ${chatCategory || 'NULL'}, hasIcon: ${!!chatIcon}`);
        } else {
          // Fallback: Decrypt on-demand if cache miss
          const decryptedChatData = await decryptChatData(currentChat);
          chatCategory = decryptedChatData.category || null;
          chatIcon = decryptedChatData.icon || null;
          console.debug(`[Chat] Decrypted metadata on-demand for shared chat - category: ${chatCategory || 'NULL'}, hasIcon: ${!!chatIcon}`);
        }
      } else {
        // No chat key and no sessionStorage draft - this shouldn't happen for non-auth users
        // But handle gracefully
        draftTextContent = '';
        lastMessage = null;
        cachedMetadata = null;
        chatCategory = null;
        chatIcon = null;
      }
    } else {
      // Authenticated users: use IndexedDB drafts
      cachedMetadata = await chatMetadataCache.getDecryptedMetadata(currentChat);
      // console.debug('[Chat] Cache lookup result:', {
      //   chatId: currentChat.chat_id,
      //   hasCachedMetadata: !!cachedMetadata,
      //   hasDraftPreview: !!cachedMetadata?.draftPreview,
      //   hasEncryptedDraftMd: !!currentChat.encrypted_draft_md,
      //   hasEncryptedDraftPreview: !!currentChat.encrypted_draft_preview
      // });
      
      if (cachedMetadata?.draftPreview) {
        // Use the pre-computed, decrypted draft preview
        draftTextContent = cachedMetadata.draftPreview;
        console.debug('[Chat] Using cached draft preview:', {
          chatId: currentChat.chat_id,
          previewLength: draftTextContent.length,
          preview: draftTextContent.substring(0, 50)
        });
      } else if (currentChat.encrypted_draft_md) {
        // Fallback: decrypt the full draft content if no preview is available
        // This should only happen during migration or if preview generation failed
        try {
          const decryptedMarkdown = await decryptWithMasterKey(currentChat.encrypted_draft_md);
          if (decryptedMarkdown) {
            // Extract display text directly from markdown, replacing json_embed blocks with URLs
            draftTextContent = extractDisplayTextFromMarkdown(decryptedMarkdown);
            console.warn('[Chat] Using fallback full content decryption (no preview available):', {
              chatId: currentChat.chat_id,
              originalLength: decryptedMarkdown.length,
              extractedLength: draftTextContent.length,
              preview: draftTextContent.substring(0, 50)
            });
          } else {
            draftTextContent = '';
          }
        } catch (error) {
          console.error('[Chat] Error decrypting draft content:', error);
          draftTextContent = '';
        }
      } else {
        draftTextContent = '';
      }
      
      // CRITICAL OPTIMIZATION: Only fetch/decrypt last message if we actually need it
      // We only need it if there's NO draft (draft takes precedence in display)
      // For chats with drafts, we skip fetching the last message entirely
      // For chats without drafts, we check cache first, then only fetch if needed
      
      if (draftTextContent) {
        // Has draft - don't need last message (draft takes precedence)
        lastMessage = null;
      } else {
        // No draft - check cache first, only fetch if in cache or if we suspect special status
        let cachedLastMessage = chatListCache.getLastMessage(currentChat.chat_id);
        
        if (cachedLastMessage !== undefined) {
          // Cache hit - use cached message (might be null if no messages)
          lastMessage = cachedLastMessage;
        } else {
          // Cache miss - check if we might have a special status that requires fetching
          // Special statuses (sending, processing, etc.) are transient and should be rare
          // For most chats, we don't need to fetch (delivered/synced messages aren't shown anyway)
          // Only fetch if this chat is actively being used (typing, or it's the active chat)
          const mightHaveSpecialStatus = 
            typingStoreValue?.chatId === currentChat.chat_id ||
            currentChat.chat_id === activeChatId;
          
          if (mightHaveSpecialStatus) {
            // Might have special status - fetch and cache
            let lastMessageFromDB: Message | null = null;
            try {
              lastMessageFromDB = await chatDB.getLastMessageForChat(currentChat.chat_id);
              // Cache the result (even if null)
              chatListCache.setLastMessage(currentChat.chat_id, lastMessageFromDB);
            } catch (error: any) {
              // If database is being deleted or unavailable, use null
              if (error?.message?.includes('being deleted') || error?.message?.includes('cannot be initialized')) {
                console.debug(`[Chat] Database is being deleted, skipping last message load for ${currentChat.chat_id}`);
                chatListCache.setLastMessage(currentChat.chat_id, null); // Cache null to avoid retrying
              } else {
                // Re-throw other errors
                throw error;
              }
            }
            lastMessage = lastMessageFromDB;
          } else {
            // No draft, no special status likely - skip fetching
            // For delivered/synced messages, we don't show them anyway (displayLabel/displayText stay empty)
            lastMessage = null;
          }
        }
      }
      
      // CRITICAL: Use cached metadata for category/icon to avoid repeated decryption
      // The chatMetadataCache already decrypts and caches category/icon, so use it!
      // This ensures consistent behavior and avoids redundant decryption calls
      
      // CRITICAL: Category and icon are ONLY set during chat creation (when ai_typing_started is received for NEW chats)
      // They should NEVER change after that, even on followup messages
      // CRITICAL: NO FALLBACKS - we must know if the backend hasn't generated category/icon
      // Use cached metadata if available, otherwise decrypt on-demand
      if (cachedMetadata?.category) {
        // Use cached category from metadata cache (preferred path for performance)
        chatCategory = cachedMetadata.category;
        chatIcon = cachedMetadata.icon || null;
        // Using cached metadata (no log needed for normal operation)
      } else {
        // Fallback: Decrypt chat data on-demand if cache miss
        const decryptedChatData = await decryptChatData(currentChat);
        
        if (!decryptedChatData.category) {
          // NO FALLBACK - set to null to make it clear that backend hasn't set category
          // Check if this is a new chat that hasn't received category yet (title_v === 0 means server hasn't set title/category yet)
          // Or an old chat created before the category feature was added
          const isNewChat = (currentChat.title_v === 0 || currentChat.title_v === undefined);
          const hasAnyMessages = (currentChat.messages_v > 0);
          
          if (isNewChat && !hasAnyMessages) {
            // Brand new chat with no messages - category will be set when AI responds
            console.debug(`[Chat] New chat ${currentChat.chat_id} waiting for category from server (title_v: ${currentChat.title_v}, messages_v: ${currentChat.messages_v})`);
          } else if (isNewChat && hasAnyMessages) {
            // New chat with messages but no category yet - server is processing
            console.debug(`[Chat] Chat ${currentChat.chat_id} has messages but no category yet (processing) - title_v: ${currentChat.title_v}, messages_v: ${currentChat.messages_v}`);
          } else {
            // Established chat without category - this is a BUG (legacy chat or server issue)
            console.error(`[Chat] ❌ BUG: Chat ${currentChat.chat_id} is missing category (legacy chat or server failed to set it) - title_v: ${currentChat.title_v}, messages_v: ${currentChat.messages_v}`);
          }
          chatCategory = null; // NO FALLBACK - null makes it clear data is missing
        } else {
          chatCategory = decryptedChatData.category;
        }
        
        chatIcon = decryptedChatData.icon || null;
        console.debug(`[Chat] Decrypted metadata - category: ${chatCategory || 'NULL'}, hasIcon: ${!!chatIcon}`);
      }
    }

    displayLabel = '';
    displayText = '';

    // Handle sending, processing, waiting_for_internet, waiting_for_user, and failed states first as they take precedence
    // Check all messages (not just lastMessage) for waiting_for_user since the system message
    // may not be the last message in the array
    const waitingForUserMessage = chat.messages?.find(m => m.status === 'waiting_for_user');
    hasWaitingForUser = !!waitingForUserMessage;
    if (hasWaitingForUser) {
      // Show "Waiting for user" label with the system message content as preview
      // (e.g., insufficient credits message), using draft-like design in the sidebar
      displayLabel = $text('enter_message.waiting_for_user.text');
      // Extract the system message content to show as preview text
      if (waitingForUserMessage.content) {
        displayText = typeof waitingForUserMessage.content === 'string' 
          ? waitingForUserMessage.content 
          : extractTextFromTiptap(waitingForUserMessage.content);
      } else {
        displayText = '';
      }
    } else if (lastMessage?.status === 'sending') {
      displayLabel = $text('enter_message.sending.text');
      displayText = typeof lastMessage.content === 'string' ? lastMessage.content : extractTextFromTiptap(lastMessage.content);
    } else if (lastMessage?.status === 'waiting_for_internet') {
      displayLabel = $text('enter_message.waiting_for_internet.text');
      displayText = typeof lastMessage.content === 'string' ? lastMessage.content : extractTextFromTiptap(lastMessage.content);
    } else if (lastMessage?.status === 'processing') {
      // Show "Processing..." if message is processing
      // Note: isWaitingForTitle is checked separately in template to show "Processing..." as title
      displayLabel = $text('enter_message.processing.text');
      displayText = typeof lastMessage.content === 'string' ? lastMessage.content : extractTextFromTiptap(lastMessage.content);
    } else if (lastMessage?.status === 'failed') {
      displayLabel = 'Failed'; 
      displayText = typeof lastMessage.content === 'string' ? lastMessage.content : extractTextFromTiptap(lastMessage.content);
    } else if (draftTextContent) {
      // If there's a draft, display draft information
      if (cachedMetadata?.title) {
        // For titled chats with draft, use specific translation that includes the beginning
        displayLabel = $text('enter_message.draft_with_beginning.text').replace('{draft_beginning}', truncateText(draftTextContent, 30));
        displayText = ''; // The label itself contains the preview for this case
      } else {
        // For untitled chats with draft
        displayLabel = $text('enter_message.draft.text');
        displayText = draftTextContent;
      }
    } else {
      // No sending, no failed, no draft:
      // For titled chats, the status line should be empty.
      // For untitled chats without a last message, also empty.
      // If there's a lastMessage for an untitled chat (and it's not sending/failed),
      // the original logic showed its content. Per feedback, this should now be empty too
      // unless explicitly decided otherwise. For now, keep it empty.
      displayLabel = '';
      displayText = '';
    }
  }

  $effect(() => {
    if (chat) {
      // CRITICAL: Make this reactive to auth state changes
      // When auth state changes, we need to re-check sessionStorage for demo chats
      const _authState = $authStore.isAuthenticated; // Reference to trigger reactivity
      updateDisplayInfo(chat);
      
      // Set gradient colors based on chat category (only if category is set)
      // If category is null, gradient will be null too - this makes it clear when data is missing
      categoryGradientColors = chatCategory ? getCategoryGradientColors(chatCategory) : null;
    }
  });

  async function handleChatOrMessageUpdated(event: Event) {
    const customEvent = event as CustomEvent;
    const detail = customEvent.detail;

    if (chat && detail && (detail.chat_id === chat.chat_id || detail.chatId === chat.chat_id)) {
      // CRITICAL: For draft deletion and title/metadata update events, invalidate cache and fetch fresh chat data
      // This ensures the UI reflects the latest state (draft removed, or new title/category/icon)
      const eventTypesRequiringFreshData = ['draft_deleted', 'title_updated', 'metadata_updated'];
      
      if (eventTypesRequiringFreshData.includes(detail.type)) {
        console.debug(`[Chat] ${detail.type} event received, invalidating cache and fetching fresh data for chat:`, chat.chat_id);
        chatMetadataCache.invalidateChat(chat.chat_id);
        
        // Fetch fresh chat data from database to ensure we have the latest state
        try {
          const freshChat = await chatDB.getChat(chat.chat_id);
          if (freshChat) {
            // Update display info with fresh data - the parent component will update the prop
            // when it receives the event and refreshes from the database
            console.debug(`[Chat] Fetched fresh chat data after ${detail.type}:`, {
              chatId: chat.chat_id,
              hasEncryptedTitle: !!freshChat.encrypted_title,
              hasCategory: !!freshChat.category || !!freshChat.encrypted_category,
              hasIcon: !!freshChat.icon || !!freshChat.encrypted_icon,
              waitingForMetadata: freshChat.waiting_for_metadata
            });
            await updateDisplayInfo(freshChat);
            return;
          }
        } catch (error: any) {
          // If database is being deleted, skip update (component will unmount anyway)
          if (error?.message?.includes('being deleted') || error?.message?.includes('cannot be initialized')) {
            console.debug(`[Chat] Database is being deleted, skipping fresh chat fetch for ${chat.chat_id}`);
            return;
          }
          console.error(`[Chat] Error fetching fresh chat data after ${detail.type}:`, error);
          // Fallback: update display with current chat data (cache already invalidated)
        }
      }
      
      // For other update types, use the existing chat object
      await updateDisplayInfo(chat); 
    }
  }

  /**
   * Handles local draft changes for immediate UI refresh
   * This ensures individual Chat components update immediately when drafts are saved locally,
   * by fetching fresh data from the database or sessionStorage
   */
  async function handleLocalDraftChanged(event: Event) {
    const customEvent = event as CustomEvent<{ chat_id?: string; draftDeleted?: boolean }>;
    const detail = customEvent.detail;

    // Only update if this event is for our specific chat or if no specific chat is mentioned (general update)
    if (chat && detail && detail.chat_id === chat.chat_id) {
      console.debug('[Chat] Local draft changed for chat:', chat.chat_id);
      
      // CRITICAL: For non-authenticated users with demo chats, check sessionStorage directly
      // For authenticated users, fetch from database
      if (!$authStore.isAuthenticated && isPublicChat(chat.chat_id)) {
        // For demo chats, just re-run updateDisplayInfo which will check sessionStorage
        console.debug('[Chat] Re-running updateDisplayInfo for demo chat with sessionStorage draft');
        await updateDisplayInfo(chat);
        return;
      }
      
      // Note: Cache invalidation is now handled centrally in Chats.svelte to ensure it works
      // even when individual Chat components are unmounted (e.g., when panel is closed)
      
      // Fetch fresh chat data from database to get updated draft content
      try {
        const freshChat = await chatDB.getChat(chat.chat_id);
        if (freshChat) {
          // Update display info with fresh data - the parent component will update the prop
          // when it receives the event and refreshes from the database
          await updateDisplayInfo(freshChat);
        }
      } catch (error: any) {
        // If database is being deleted, skip update (component will unmount anyway)
        if (error?.message?.includes('being deleted') || error?.message?.includes('cannot be initialized')) {
          console.debug(`[Chat] Database is being deleted, skipping fresh chat fetch for ${chat.chat_id}`);
          return;
        }
        console.error('[Chat] Error fetching fresh chat data after local draft change:', error);
        // Fallback: just update display with current chat data
        await updateDisplayInfo(chat);
      }
    }
  }
  
  // Handler for hiding chat after unlock
  function handleHideChatAfterUnlock(event: Event) {
    const customEvent = event as CustomEvent<{ chatId: string }>;
    if (chat && chat.chat_id === customEvent.detail.chatId) {
      // Now that hidden chats are unlocked, proceed with hiding
      handleHideChat();
    }
  }

  onMount(() => {
    if (chat) {
        updateDisplayInfo(chat); 
    }
    
    // Listen to local draft changes for immediate UI updates
    window.addEventListener(LOCAL_CHAT_LIST_CHANGED_EVENT, handleLocalDraftChanged);
    
    // Listen to server-driven chat updates
    chatSyncService.addEventListener('chatUpdated', handleChatOrMessageUpdated);
    chatSyncService.addEventListener('messageStatusChanged', handleChatOrMessageUpdated);
    chatSyncService.addEventListener('aiTaskInitiated', handleChatOrMessageUpdated as EventListener);
    chatSyncService.addEventListener('aiTaskEnded', handleChatOrMessageUpdated as EventListener);
    
    // Listen for hide chat after unlock event
    window.addEventListener('hideChatAfterUnlock', handleHideChatAfterUnlock);
  });

  onDestroy(() => {
    // Clean up touch timer
    clearTouchTimer();
    
    // Clean up event listeners
    window.removeEventListener(LOCAL_CHAT_LIST_CHANGED_EVENT, handleLocalDraftChanged);
    chatSyncService.removeEventListener('chatUpdated', handleChatOrMessageUpdated);
    chatSyncService.removeEventListener('messageStatusChanged', handleChatOrMessageUpdated);
    chatSyncService.removeEventListener('aiTaskInitiated', handleChatOrMessageUpdated as EventListener);
    chatSyncService.removeEventListener('aiTaskEnded', handleChatOrMessageUpdated as EventListener);
    window.removeEventListener('hideChatAfterUnlock', handleHideChatAfterUnlock);
  });

  function truncateText(textToTruncate: string, maxLength: number = 60): string { // Renamed param
    if (textToTruncate && textToTruncate.length > maxLength) {
      return textToTruncate.substring(0, maxLength) + '...';
    }
    return textToTruncate;
  }

  let isActive = $derived(activeChatId === chat?.chat_id);
  
  // Get unread count from store for this chat
  let unreadCount = $derived($unreadMessagesStore.unreadCounts.get(chat?.chat_id || '') || 0);
  
  // Flag to temporarily suppress auto-clear when user manually marks as unread
  // This prevents the effect from immediately clearing the unread state
  let suppressAutoClear = $state(false);
  
  // Track previous active state to detect when user navigates away
  let wasActive = $state(false);
  
  // Clear unread count when chat becomes active (user is viewing it)
  // But NOT if we just marked it as unread (suppressAutoClear flag)
  $effect(() => {
    if (isActive && chat?.chat_id && unreadCount > 0 && !suppressAutoClear) {
      unreadMessagesStore.clearUnread(chat.chat_id);
    }
  });
  
  // Reset suppressAutoClear when user navigates away from the chat
  // This ensures that when user opens the chat again, it will be marked as read
  $effect(() => {
    if (wasActive && !isActive) {
      // User navigated away from this chat, reset the suppress flag
      suppressAutoClear = false;
    }
    wasActive = isActive;
  });
  
  // Detect if this is a draft-only chat (has draft content but no title and no messages) using Svelte 5 runes
  let isDraftOnly = $derived(chat && draftTextContent && !cachedMetadata?.title && (!lastMessage || lastMessage === null));
  
  // Detect if this is a chat waiting for metadata (new chat that just sent first message)
  // These chats should show message content with status indicator, similar to draft-only but with message
  // CRITICAL: Also check if title is missing even if waiting_for_metadata was cleared (cache might not be updated yet)
  let isWaitingForMetadata = $derived(chat && 
    ((chat.waiting_for_metadata === true) || 
     (!cachedMetadata?.title && !chat.title && lastMessage && (lastMessage.status === 'processing' || lastMessage.status === 'sending'))) 
    && lastMessage);

  // Context menu handlers
  function handleContextMenu(event: MouseEvent) {
    event.preventDefault();
    event.stopPropagation();
    
    contextMenuX = event.clientX;
    contextMenuY = event.clientY;
    showContextMenu = true;
    
    console.debug('[Chat] Context menu opened for chat (right-click):', chat?.chat_id);
  }

  /**
   * Handle touch start for long-press detection
   * Starts a timer that will show the context menu if the touch is held long enough
   */
  function handleTouchStart(event: TouchEvent) {
    // Only handle single touch
    if (event.touches.length !== 1) {
      clearTouchTimer();
      return;
    }

    const touch = event.touches[0];
    touchStartX = touch.clientX;
    touchStartY = touch.clientY;

    // Start long-press timer
    touchTimer = setTimeout(() => {
      // Show context menu at touch location
      contextMenuX = touchStartX;
      contextMenuY = touchStartY;
      showContextMenu = true;
      
      // Vibrate to provide haptic feedback (if supported)
      if (navigator.vibrate) {
        navigator.vibrate(50);
      }
      
      console.debug('[Chat] Context menu opened for chat (long-press):', chat?.chat_id);
    }, LONG_PRESS_DURATION);
  }

  /**
   * Handle touch move - cancel long-press if finger moves too much
   */
  function handleTouchMove(event: TouchEvent) {
    if (!touchTimer || event.touches.length !== 1) {
      return;
    }

    const touch = event.touches[0];
    const deltaX = Math.abs(touch.clientX - touchStartX);
    const deltaY = Math.abs(touch.clientY - touchStartY);

    // If finger moved too much, cancel the long-press
    if (deltaX > TOUCH_MOVE_THRESHOLD || deltaY > TOUCH_MOVE_THRESHOLD) {
      clearTouchTimer();
    }
  }

  /**
   * Handle touch end - cancel long-press timer
   */
  function handleTouchEnd(event: TouchEvent) {
    // If context menu is showing, prevent the default click action
    if (showContextMenu) {
      event.preventDefault();
      event.stopPropagation();
    }
    clearTouchTimer();
  }

  /**
   * Handle touch cancel - cancel long-press timer
   */
  function handleTouchCancel() {
    clearTouchTimer();
  }

  /**
   * Clear the touch timer
   */
  function clearTouchTimer() {
    if (touchTimer) {
      clearTimeout(touchTimer);
      touchTimer = null;
    }
  }

  function handleContextMenuAction(event: CustomEvent<string>) {
    const action = event.detail;
    console.debug('[Chat] Context menu action:', action, 'for chat:', chat?.chat_id, 'selectMode:', selectMode, 'selectedCount:', selectedChatIds.size);
    
    // CRITICAL: If we're in select mode and there are selected chats, dispatch bulk actions to parent
    // Otherwise, handle single-chat actions locally
    if (selectMode && selectedChatIds.size > 0 && (action === 'download' || action === 'copy' || action === 'delete')) {
      // For bulk download, show loading state in the context menu while download is processing
      if (action === 'download') {
        isDownloading = true;
        // Listen for download completion from Chats.svelte
        const onComplete = () => {
          isDownloading = false;
          showContextMenu = false;
          window.removeEventListener('chatBulkDownloadComplete', onComplete);
        };
        window.addEventListener('chatBulkDownloadComplete', onComplete);
        window.dispatchEvent(new CustomEvent('chatContextMenuBulkAction', { detail: action }));
        return;
      }
      // Dispatch bulk action to parent (Chats.svelte)
      window.dispatchEvent(new CustomEvent('chatContextMenuBulkAction', { detail: action }));
      showContextMenu = false;
      return;
    }
    
    switch (action) {
      case 'download':
        // Set loading state, await download, then close context menu
        isDownloading = true;
        handleDownloadChat().finally(() => {
          isDownloading = false;
          showContextMenu = false;
        });
        break;
      case 'copy':
        handleCopyChat();
        break;
      case 'hide':
        handleHideChat();
        break;
      case 'unhide':
        handleUnhideChat();
        break;
      case 'delete':
        handleDeleteChat();
        break;
      case 'close':
        showContextMenu = false;
        break;
      case 'enterSelectMode':
        // Dispatch to parent to enter select mode
        window.dispatchEvent(new CustomEvent('chatContextMenuEnterSelectMode'));
        showContextMenu = false;
        break;
      case 'unselect':
        // Dispatch to parent with chat ID
        if (chat?.chat_id) {
          window.dispatchEvent(new CustomEvent('chatContextMenuUnselect', { detail: chat.chat_id }));
        }
        showContextMenu = false;
        break;
      case 'selectChat':
        // Dispatch to parent with chat ID
        if (chat?.chat_id) {
          window.dispatchEvent(new CustomEvent('chatContextMenuSelect', { detail: chat.chat_id }));
        }
        showContextMenu = false;
        break;
      case 'pin':
        handlePinChat();
        break;
      case 'unpin':
        handleUnpinChat();
        break;
      case 'markUnread':
        handleMarkUnread();
        break;
      case 'markRead':
        handleMarkRead();
        break;
      default:
        console.warn('[Chat] Unknown context menu action:', action);
    }
  }

  /**
   * Build PII export options from the current PII visibility state and message mappings.
   * When PII is hidden (default), the export will contain placeholders instead of originals.
   */
  function buildPIIExportOptions(chatId: string, messages: Message[]): PIIExportOptions | undefined {
    // Collect all PII mappings from user messages
    const allMappings: import('../../types/chat').PIIMapping[] = [];
    for (const msg of messages) {
      if (msg.role === 'user' && msg.pii_mappings && msg.pii_mappings.length > 0) {
        allMappings.push(...msg.pii_mappings);
      }
    }
    // If there are no PII mappings, no special handling needed
    if (allMappings.length === 0) return undefined;

    // Check if PII is currently revealed for this chat
    const isRevealed = piiVisibilityStore.isRevealed(chatId);
    return {
      piiHidden: !isRevealed,
      piiMappings: allMappings,
    };
  }

  /**
   * Download chat as YAML file
   * Supports drafts-only chats (both authenticated and non-authenticated users)
   */
  async function handleDownloadChat() {
    if (!chat) return;
    
    try {
      console.debug('[Chat] Starting download for chat:', chat.chat_id);
      
      // Get all messages for the chat (from static bundle for public chats, from IndexedDB for regular chats)
      // For drafts-only chats, messages will be empty array
      const messages = isPublicChat(chat.chat_id) 
        ? getDemoMessages(chat.chat_id, DEMO_CHATS, LEGAL_CHATS)
        : await (async () => {
          try {
            return await chatDB.getMessagesForChat(chat.chat_id);
          } catch (error: any) {
            // If database is being deleted, return empty array
            if (error?.message?.includes('being deleted') || error?.message?.includes('cannot be initialized')) {
              console.debug(`[Chat] Database is being deleted, skipping message load for ${chat.chat_id}`);
              return [];
            }
            throw error;
          }
        })();
      
      // CRITICAL: For non-authenticated users with sessionStorage-only chats, create a virtual chat object
      // with the draft content from sessionStorage for export
      let chatForExport = chat;
      if (!$authStore.isAuthenticated && !isPublicChat(chat.chat_id) && messages.length === 0) {
        // This is a sessionStorage-only chat (draft-only, no messages)
        // Load the draft from sessionStorage and create a virtual chat object with it
        const { loadSessionStorageDraft, getSessionStorageDraftPreview } = await import('../../services/drafts/sessionStorageDraftService');
        const { tipTapToCanonicalMarkdown } = await import('../../message_parsing/serializers');
        
        const draftTiptapJSON = loadSessionStorageDraft(chat.chat_id);
        if (draftTiptapJSON) {
          const draftMarkdown = tipTapToCanonicalMarkdown(draftTiptapJSON);
          // Create a virtual chat object with the draft content
          chatForExport = {
            ...chat,
            encrypted_draft_md: draftMarkdown, // Store as cleartext (will be exported as-is)
            encrypted_draft_preview: getSessionStorageDraftPreview(chat.chat_id)
          };
          console.debug('[Chat] Created virtual chat object with sessionStorage draft for export');
        }
      }
      
      // Build PII export options: respect the current visibility state
      const piiOptions = buildPIIExportOptions(chat.chat_id, messages);

      // Download as ZIP with YAML, Markdown, and code files, respecting PII visibility
      await downloadChatAsZip(chatForExport, messages, piiOptions);

      console.debug('[Chat] Download completed for chat:', chat.chat_id);
      notificationStore.success('Chat downloaded successfully');
    } catch (error) {
      console.error('[Chat] Error downloading chat:', error);
      notificationStore.error('Failed to download chat. Please try again.');
    }
  }

  /**
   * Copy chat to clipboard
   * Copies YAML with embedded link - when pasted inside OpenMates, only the link is used
   * When pasted outside OpenMates, the full YAML is available
   * Supports drafts-only chats (both authenticated and non-authenticated users)
   */
  async function handleCopyChat() {
    if (!chat) return;
    
    try {
      console.debug('[Chat] Copying chat to clipboard:', chat.chat_id);
      
      // Get all messages for the chat (from static bundle for public chats, from IndexedDB for regular chats)
      // For drafts-only chats, messages will be empty array
      const messages = isPublicChat(chat.chat_id)
        ? getDemoMessages(chat.chat_id, DEMO_CHATS, LEGAL_CHATS)
        : await (async () => {
          try {
            return await chatDB.getMessagesForChat(chat.chat_id);
          } catch (error: any) {
            // If database is being deleted, return empty array
            if (error?.message?.includes('being deleted') || error?.message?.includes('cannot be initialized')) {
              console.debug(`[Chat] Database is being deleted, skipping message load for ${chat.chat_id}`);
              return [];
            }
            throw error;
          }
        })();
      
      // CRITICAL: For non-authenticated users with sessionStorage-only chats, create a virtual chat object
      // with the draft content from sessionStorage for export
      let chatForExport = chat;
      if (!$authStore.isAuthenticated && !isPublicChat(chat.chat_id) && messages.length === 0) {
        // This is a sessionStorage-only chat (draft-only, no messages)
        // Load the draft from sessionStorage and create a virtual chat object with it
        const { loadSessionStorageDraft, getSessionStorageDraftPreview } = await import('../../services/drafts/sessionStorageDraftService');
        const { tipTapToCanonicalMarkdown } = await import('../../message_parsing/serializers');
        
        const draftTiptapJSON = loadSessionStorageDraft(chat.chat_id);
        if (draftTiptapJSON) {
          const draftMarkdown = tipTapToCanonicalMarkdown(draftTiptapJSON);
          // Create a virtual chat object with the draft content
          chatForExport = {
            ...chat,
            encrypted_draft_md: draftMarkdown, // Store as cleartext (will be exported as-is)
            encrypted_draft_preview: getSessionStorageDraftPreview(chat.chat_id)
          };
          console.debug('[Chat] Created virtual chat object with sessionStorage draft for copy');
        }
      }
      
      // Build PII export options: respect the current visibility state.
      // When PII is hidden (default), exported content uses placeholders instead of originals.
      const piiOptions = buildPIIExportOptions(chat.chat_id, messages);

      // Copy to clipboard (YAML with embedded link, handles empty messages array and drafts)
      await copyChatToClipboard(chatForExport, messages, piiOptions);
      
      console.debug('[Chat] Chat copied to clipboard (YAML with embedded link)');
      notificationStore.success('Chat copied to clipboard');
    } catch (error) {
      console.error('[Chat] Error copying chat:', error);
      notificationStore.error('Failed to copy chat. Please try again.');
    }
  }

  /**
   * Hide chat handler
   * Hides a chat by re-encrypting its chat key with the combined secret (master_key + code)
   * If hidden chats are not unlocked, prompts user to unlock first
   * 
   * This function handles:
   * - Normal chats (with or without messages)
   * - Draft-only chats (chats that only have a draft, no messages yet)
   * - Already-hidden chats (re-hiding is a no-op, but handled gracefully)
   * 
   * CRITICAL: Always uses the existing chatKey to prevent sync issues.
   * For draft-only chats, the key may not be in cache yet, so we decrypt
   * it from encrypted_chat_key before re-encrypting with combined secret.
   */
  async function handleHideChat() {
    if (!chat) return;
    
    const chatIdToHide = chat.chat_id;
    
    // Skip public chats (demo/legal) - they use a different hiding mechanism
    if (isDemoChat(chatIdToHide) || isLegalChat(chatIdToHide) || isPublicChat(chatIdToHide)) {
      console.debug('[Chat] Cannot hide public chat via hidden chats feature:', chatIdToHide);
      return;
    }
    
    // Skip incognito chats - they're already session-only
    if (chat.is_incognito) {
      console.debug('[Chat] Cannot hide incognito chat:', chatIdToHide);
      return;
    }
    
    try {
      // Check if hidden chats are unlocked
      const { hiddenChatStore } = await import('../../stores/hiddenChatStore');
      const { hiddenChatService } = await import('../../services/hiddenChatService');
      
      // If hidden chats are locked, prompt for password first
      if (!hiddenChatService.isUnlocked()) {
        // Dispatch event to show overscroll unlock interface for hiding
        window.dispatchEvent(new CustomEvent('showOverscrollUnlockForHide', { 
          detail: { chatId: chatIdToHide } 
        }));
        showContextMenu = false;
        return;
      }
      
      // Hidden chats are already unlocked - we can use the current combined secret
      // Get the current chat key (decrypted with master key)
      // First try: Check cache (fast path for chats that have been accessed)
      let chatKey = chatDB.getChatKey(chatIdToHide);
      
      // Second try: If not in cache, decrypt from encrypted_chat_key
      // This is critical for draft-only chats that haven't loaded their key into cache yet
      if (!chatKey && chat.encrypted_chat_key) {
        console.debug('[Chat] Chat key not in cache, decrypting from encrypted_chat_key for chat:', chatIdToHide);
        
        // Use tryDecryptChatKey to handle both normal and already-hidden chats
        const result = await hiddenChatService.tryDecryptChatKey(chat.encrypted_chat_key);
        
        if (result.chatKey) {
          chatKey = result.chatKey;
          // Cache the key for future operations
          chatDB.setChatKey(chatIdToHide, chatKey);
          console.debug('[Chat] Successfully decrypted and cached chat key for hiding:', chatIdToHide);
          
          // If chat was already hidden, we can skip re-encryption (it's already hidden)
          if (result.isHidden) {
            console.debug('[Chat] Chat is already hidden, no action needed:', chatIdToHide);
            notificationStore.success('Chat is already hidden');
            showContextMenu = false;
            return;
          }
        } else {
          console.error('[Chat] Cannot hide chat: failed to decrypt chat key from encrypted_chat_key');
          notificationStore.error('Failed to hide chat. Could not decrypt chat key.');
          return;
        }
      }
      
      // Final check: If we still don't have a key, the chat is missing encrypted_chat_key
      if (!chatKey) {
        console.error('[Chat] Cannot hide chat: chat key not found and encrypted_chat_key is missing');
        notificationStore.error('Failed to hide chat. Chat key not found.');
        return;
      }
      
      // Re-encrypt chat key with combined secret (using the already-unlocked combined secret)
      const encryptedChatKey = await hiddenChatService.encryptChatKeyWithCombinedSecret(chatKey);
      if (!encryptedChatKey) {
        console.error('[Chat] Failed to encrypt chat key with combined secret');
        notificationStore.error('Failed to hide chat. Encryption failed.');
        return;
      }
      
      // Update chat in database with new encrypted_chat_key
      const updatedChat = {
        ...chat,
        encrypted_chat_key: encryptedChatKey,
        // Don't set is_hidden flag - it will be determined by decryption success/failure
      };
      
      await chatDB.updateChat(updatedChat);
      // Ensure sidebar chat list refreshes (it may be served from cache)
      chatListCache.markDirty();
      
      // Sync to server (the encrypted_chat_key will be synced)
      await chatSyncService.sendUpdateEncryptedChatKey(chatIdToHide, encryptedChatKey);
      
      console.debug('[Chat] Chat hidden successfully:', chatIdToHide);
      notificationStore.success('Chat hidden successfully');
      showContextMenu = false;

      // Hide associated new chat suggestions
      try {
        await chatDB.hideNewChatSuggestionsForChat(chatIdToHide);
        console.debug('[Chat] Hidden associated chat suggestions for:', chatIdToHide);
      } catch (error) {
        console.warn('[Chat] Failed to hide chat suggestions:', error);
        // Continue anyway - chat hiding succeeded
      }

      // Dispatch event to update UI (chat will disappear from main list and move to hidden section)
      // Chats.svelte listens on `window` and will refresh the chat list
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('chatHidden', { detail: { chat_id: chatIdToHide } }));
      }
      
    } catch (error) {
      console.error('[Chat] Error hiding chat:', chatIdToHide, error);
      notificationStore.error('Failed to hide chat. Please try again.');
    }
  }

  async function handleUnhideChat() {
    if (!chat) return;
    
    const chatIdToUnhide = chat.chat_id;
    
    try {
      const { hiddenChatService } = await import('../../services/hiddenChatService');
      
      // Hidden chats must be unlocked to unhide them
      if (!hiddenChatService.isUnlocked()) {
        notificationStore.error('Please unlock hidden chats first to unhide this chat.');
        showContextMenu = false;
        return;
      }
      
      // Unhide the chat (re-encrypt with master key)
      const success = await hiddenChatService.unhideChat(chatIdToUnhide);
      
      if (success) {
        console.debug('[Chat] Chat unhidden successfully:', chatIdToUnhide);

        // Unhide associated new chat suggestions
        try {
          await chatDB.unhideNewChatSuggestionsForChat(chatIdToUnhide);
          console.debug('[Chat] Unhidden associated chat suggestions for:', chatIdToUnhide);
        } catch (error) {
          console.warn('[Chat] Failed to unhide chat suggestions:', error);
          // Continue anyway - chat unhiding succeeded
        }

        // Mark chat list cache as dirty to force refresh
        chatListCache.markDirty();
        // Dispatch event to refresh chat list (chat will move from hidden section to regular list)
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('chatUnhidden', { detail: { chat_id: chatIdToUnhide } }));
        }
        showContextMenu = false;
      } else {
        notificationStore.error('Failed to unhide chat.');
      }
    } catch (error) {
      console.error('[Chat] Error unhiding chat:', error);
      notificationStore.error('Failed to unhide chat.');
    }
  }

  /**
  * Pin chat handler
  * Updates the pinned status to true and dispatches event to refresh the list
  */
  async function handlePinChat() {
    if (!chat) return;

    const chatIdToPin = chat.chat_id;

    try {
      console.debug('[Chat] Pinning chat:', chatIdToPin);

      // Update the chat in IndexedDB - pass full chat object with updated pinned status
      const updatedChat = { ...chat, pinned: true };
      await chatDB.updateChat(updatedChat);

      // Note: We don't mutate the chat prop here - the parent component will update it
      // when it receives the LOCAL_CHAT_LIST_CHANGED_EVENT and refreshes from the database

      // Mark cache as dirty and refresh the list
      chatListCache.markDirty();

      // Dispatch event to refresh the chat list so pinned chat moves to top
      const { LOCAL_CHAT_LIST_CHANGED_EVENT } = await import('../../services/drafts/draftConstants');
      window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, {
        detail: { chat_id: chatIdToPin, pinned: true }
      }));

      // Send update to server via chatSyncService
      if (typeof window !== 'undefined') {
        const { webSocketService } = await import('../../services/websocketService');
        if (webSocketService.isConnected()) {
          const updatePayload = {
            chat_id: chatIdToPin,
            pinned: true
          };
          webSocketService.sendMessage('update_chat', updatePayload);
        }
      }

      console.debug('[Chat] Chat pinned successfully:', chatIdToPin);
      showContextMenu = false;
    } catch (error) {
      console.error('[Chat] Error pinning chat:', error);
      notificationStore.error('Failed to pin chat. Please try again.');
    }
  }

  /**
  * Unpin chat handler
  * Updates the pinned status to false and dispatches event to refresh the list
  */
  async function handleUnpinChat() {
    if (!chat) return;

    const chatIdToUnpin = chat.chat_id;

    try {
      console.debug('[Chat] Unpinning chat:', chatIdToUnpin);

      // Update the chat in IndexedDB - pass full chat object with updated pinned status
      const updatedChat = { ...chat, pinned: false };
      await chatDB.updateChat(updatedChat);

      // Note: We don't mutate the chat prop here - the parent component will update it
      // when it receives the LOCAL_CHAT_LIST_CHANGED_EVENT and refreshes from the database

      // Mark cache as dirty and refresh the list
      chatListCache.markDirty();

      // Dispatch event to refresh the chat list so unpinned chat moves from top
      const { LOCAL_CHAT_LIST_CHANGED_EVENT } = await import('../../services/drafts/draftConstants');
      window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, {
        detail: { chat_id: chatIdToUnpin, pinned: false }
      }));

      // Send update to server via chatSyncService
      if (typeof window !== 'undefined') {
        const { webSocketService } = await import('../../services/websocketService');
        if (webSocketService.isConnected()) {
          const updatePayload = {
            chat_id: chatIdToUnpin,
            pinned: false
          };
          webSocketService.sendMessage('update_chat', updatePayload);
        }
      }

      console.debug('[Chat] Chat unpinned successfully:', chatIdToUnpin);
      showContextMenu = false;
    } catch (error) {
      console.error('[Chat] Error unpinning chat:', error);
      notificationStore.error('Failed to unpin chat. Please try again.');
    }
  }

  /**
   * Mark chat as unread handler
   * Sets unread_count to 1 and syncs across devices via chatSyncService
   * Note: Always sets to 1, never increments beyond 1
   */
  async function handleMarkUnread() {
    if (!chat) return;

    const chatIdToMarkUnread = chat.chat_id;

    try {
      console.debug('[Chat] Marking chat as unread:', chatIdToMarkUnread);

      // Set unread count to 1 (marking as unread) - always 1, never increment
      const newUnreadCount = 1;

      // Suppress auto-clear so the effect doesn't immediately clear this
      // The flag will be cleared when user navigates away and back
      suppressAutoClear = true;

      // Clear existing count first (to ensure we set to exactly 1, not increment)
      unreadMessagesStore.clearUnread(chatIdToMarkUnread);
      // Then set to 1
      unreadMessagesStore.incrementUnread(chatIdToMarkUnread);

      // Update the chat in IndexedDB
      const updatedChat = { ...chat, unread_count: newUnreadCount };
      await chatDB.updateChat(updatedChat);

      // Mark cache as dirty and refresh the list
      chatListCache.markDirty();

      // Dispatch event to refresh the chat list
      window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, {
        detail: { chat_id: chatIdToMarkUnread, unread_count: newUnreadCount }
      }));

      // Send update to server via chatSyncService to sync across devices
      if (chatSyncService) {
        await chatSyncService.sendChatReadStatus(chatIdToMarkUnread, newUnreadCount);
      }

      console.debug('[Chat] Chat marked as unread successfully:', chatIdToMarkUnread);
      showContextMenu = false;
    } catch (error) {
      console.error('[Chat] Error marking chat as unread:', error);
      notificationStore.error('Failed to mark chat as unread. Please try again.');
    }
  }

  /**
   * Mark chat as read handler
   * Sets unread_count to 0 and syncs across devices via chatSyncService
   */
  async function handleMarkRead() {
    if (!chat) return;

    const chatIdToMarkRead = chat.chat_id;

    try {
      console.debug('[Chat] Marking chat as read:', chatIdToMarkRead);

      // Set unread count to 0 (marking as read)
      const newUnreadCount = 0;

      // Clear the suppress flag since user is marking as read
      suppressAutoClear = false;

      // Clear local unread store for immediate UI feedback
      unreadMessagesStore.clearUnread(chatIdToMarkRead);

      // Update the chat in IndexedDB
      const updatedChat = { ...chat, unread_count: newUnreadCount };
      await chatDB.updateChat(updatedChat);

      // Mark cache as dirty and refresh the list
      chatListCache.markDirty();

      // Dispatch event to refresh the chat list
      window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, {
        detail: { chat_id: chatIdToMarkRead, unread_count: newUnreadCount }
      }));

      // Send update to server via chatSyncService to sync across devices
      if (chatSyncService) {
        await chatSyncService.sendChatReadStatus(chatIdToMarkRead, newUnreadCount);
      }

      console.debug('[Chat] Chat marked as read successfully:', chatIdToMarkRead);
      showContextMenu = false;
    } catch (error) {
      console.error('[Chat] Error marking chat as read:', error);
      notificationStore.error('Failed to mark chat as read. Please try again.');
    }
  }

  /**
   * Delete chat handler
   * Expected behavior for DEMO CHATS:
   * - Add chat to hidden_demo_chats in user profile
   * - Save to IndexedDB and sync to server
   * - Dispatch event to update UI
   * 
   * Expected behavior for REAL CHATS:
   * 1. Delete the chat entry and all its messages from IndexedDB FIRST
   * 2. Dispatch chatDeleted event AFTER deletion to update UI components
   * 3. Send request to server to delete chat and messages from server cache and Directus
   * 
   * Expected behavior for SESSIONSTORAGE-ONLY CHATS (non-authenticated users):
   * - Delete draft from sessionStorage
   * - Dispatch event to update UI
   */
  async function handleDeleteChat() {
    if (!chat) return;
    
    const chatIdToDelete = chat.chat_id;
    
    try {
      console.debug('[Chat] Starting deletion for chat:', chatIdToDelete);
      
      // PUBLIC CHAT HANDLING (demo + legal): Add to hidden_demo_chats instead of deleting
      // Legal chats use the same hidden_demo_chats mechanism (even though they're legal, not demo)
      if (isDemoChat(chatIdToDelete) || isLegalChat(chatIdToDelete)) {
        if (!$authStore.isAuthenticated) {
          console.warn('[Chat] Cannot hide demo chat - user not authenticated');
          notificationStore.error('Please sign up to customize your experience');
          return;
        }
        
        console.debug('[Chat] Hiding public chat (demo or legal):', chatIdToDelete);
        
        // Add to hidden_demo_chats array (deduplicate)
        // Note: This field stores both demo and legal chat IDs that should be hidden
        const currentHidden = $userProfile.hidden_demo_chats || [];
        if (!currentHidden.includes(chatIdToDelete)) {
          const updatedHidden = [...currentHidden, chatIdToDelete];
          
          // Update userProfile store (this will trigger reactivity in Chats.svelte)
          userProfile.update(profile => ({
            ...profile,
            hidden_demo_chats: updatedHidden
          }));
          
          // Save to IndexedDB
          const { userDB } = await import('../../services/userDB');
          await userDB.updateUserData({ hidden_demo_chats: updatedHidden });
          
          // TODO: Sync to server (encrypted) - will be implemented in next step
          console.debug('[Chat] Public chat hidden:', chatIdToDelete, 'Total hidden:', updatedHidden.length);
          
          notificationStore.success('Chat hidden successfully');
        } else {
          console.debug('[Chat] Public chat already hidden:', chatIdToDelete);
        }
        
        return;
      }
      
      // CRITICAL: Handle chats for non-authenticated users
      // There are two types:
      // 1. Shared chats - stored in IndexedDB with keys in sharedChatKeyStorage (from share links)
      // 2. Draft-only chats - only exist in sessionStorage
      if (!$authStore.isAuthenticated) {
        // Check if this is a shared chat (has a key in sharedChatKeyStorage)
        const { getSharedChatKey, deleteSharedChatKey } = await import('../../services/sharedChatKeyStorage');
        const sharedKey = await getSharedChatKey(chatIdToDelete);
        
        if (sharedKey) {
          // This is a shared chat - delete from IndexedDB and remove the stored key
          console.debug('[Chat] Deleting shared chat from IndexedDB:', chatIdToDelete);
          
          // Delete from IndexedDB
          await chatDB.deleteChat(chatIdToDelete);
          
          // Delete the shared chat key from storage
          await deleteSharedChatKey(chatIdToDelete);
          
          // Clear from memory cache
          chatDB.clearChatKey(chatIdToDelete);
          
          // Dispatch event to update UI
          chatSyncService.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id: chatIdToDelete } }));
          
          console.debug('[Chat] Shared chat and key deleted:', chatIdToDelete);
          notificationStore.success('Chat deleted successfully');
          return;
        }
        
        // Draft-only chat - only delete from sessionStorage
        console.debug('[Chat] Deleting sessionStorage-only chat (draft-only):', chatIdToDelete);
        
        // Delete draft from sessionStorage
        const { deleteSessionStorageDraft } = await import('../../services/drafts/sessionStorageDraftService');
        deleteSessionStorageDraft(chatIdToDelete);
        
        // Dispatch event to update UI
        const { LOCAL_CHAT_LIST_CHANGED_EVENT } = await import('../../services/drafts/draftConstants');
        window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, { 
          detail: { chat_id: chatIdToDelete, draftDeleted: true } 
        }));
        
        // Also dispatch chatDeleted event for consistency
        chatSyncService.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id: chatIdToDelete } }));
        
        console.debug('[Chat] SessionStorage-only chat deleted:', chatIdToDelete);
        notificationStore.success('Chat deleted successfully');
        return;
      }
      
      // REAL CHAT HANDLING (authenticated users): Delete from IndexedDB and server
      // Step 1: Delete from IndexedDB (local deletion) FIRST
      console.debug('[Chat] Deleting chat from IndexedDB:', chatIdToDelete);
      await chatDB.deleteChat(chatIdToDelete);
      console.debug('[Chat] Chat deleted from IndexedDB:', chatIdToDelete);
      
      // Step 2: Dispatch chatDeleted event AFTER deletion to update UI components
      // This ensures the chat is actually removed from IndexedDB before UI updates
      console.debug('[Chat] Dispatching chatDeleted event for UI update:', chatIdToDelete);
      chatSyncService.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id: chatIdToDelete } }));
      console.debug('[Chat] chatDeleted event dispatched for chat:', chatIdToDelete);
      
      // Step 3: Send delete request to server via chatSyncService
      console.debug('[Chat] Sending delete request to server for chat:', chatIdToDelete);
      await chatSyncService.sendDeleteChat(chatIdToDelete);
      console.debug('[Chat] Delete request sent to server for chat:', chatIdToDelete);
      
    } catch (error) {
      console.error('[Chat] Error deleting chat:', chatIdToDelete, error);
      notificationStore.error('Failed to delete chat. Please try again.');
    }
  }
</script>
 
<div
  class="chat-item-wrapper"
  class:active={isActive}
  role="button"
  tabindex="0"
  oncontextmenu={handleContextMenu}
  ontouchstart={handleTouchStart}
  ontouchmove={handleTouchMove}
  ontouchend={handleTouchEnd}
  ontouchcancel={handleTouchCancel}
>
  {#if chat}
    <div class="chat-item">
      {#if hasWaitingForUser && !currentTypingMateInfo}
        <!-- Waiting for user action (e.g., insufficient credits): draft-like layout with label + message preview -->
        <div class="draft-only-layout">
          <span class="status-message waiting-for-user-label">{displayLabel}</span>
          {#if displayText}
            <span class="draft-content-as-title">{truncateText(displayText, 60)}</span>
          {/if}
        </div>
      {:else if (lastMessage?.status === 'sending' || lastMessage?.status === 'processing' || isWaitingForTitle) && !currentTypingMateInfo}
        <div class="status-only-preview">
          {#if displayLabel}<span class="status-label">{displayLabel}</span>{/if}
          {#if displayText}<span class="status-content-preview">{truncateText(displayText, 60)}</span>{/if}
        </div>
      {:else if isWaitingForMetadata}
        <!-- Chat waiting for metadata: shows message content with status indicator -->
        <!-- Similar to draft-only layout but includes the sent message -->
        <div class="draft-only-layout">
          {#if displayLabel}
            <span class="status-message">{displayLabel}</span>
          {/if}
          <span class="draft-content-as-title">{truncateText(displayText, 60)}</span>
        </div>
      {:else if isDraftOnly}
        <!-- Draft-only chat: left-aligned without mate profile -->
        <div class="draft-only-layout">
          <span class="status-message">{$text('enter_message.draft.text')}</span>
          <span class="draft-content-as-title">{truncateText(draftTextContent, 60)}</span>
        </div>
      {:else}
        <div class="chat-with-profile">
          <div class="mate-profiles-container">
            {#if selectMode}
              <!-- In select mode: show checkbox instead of category circle -->
              <div class="checkbox-wrapper">
                <input
                  type="checkbox"
                  class="chat-checkbox"
                  checked={isSelected}
                  onchange={(e) => {
                    if (onToggleSelection && chat) {
                      onToggleSelection(chat.chat_id);
                    }
                  }}
                  onclick={(e) => {
                    // Prevent the click from bubbling to the parent chat item
                    e.stopPropagation();
                  }}
                  aria-label={isSelected ? 'Unselect chat' : 'Select chat'}
                />
              </div>
            {:else if currentTypingMateInfo?.isTyping && categoryGradientColors}
              <!-- New category circle with gradient and icon -->
              <div class="category-circle-wrapper">
                <div 
                  class="category-circle" 
                  style="background: linear-gradient(135deg, {categoryGradientColors.start}, {categoryGradientColors.end})"
                >
                  <div class="category-icon">
                    {#if categoryIconNames.length > 0 || currentTypingMateInfo?.category}
{@const validIconName = getValidIconName(categoryIconNames, currentTypingMateInfo?.category || 'general_knowledge')}
{@const IconComponent = getLucideIcon(validIconName)}
                      <IconComponent size={16} color="white" />
                    {/if}
                  </div>
                    {#if unreadCount > 0 && !typingIndicatorInTitleView && !displayLabel && lastMessage?.status !== 'processing'}
                      <div class="unread-badge">
                        {unreadCount > 9 ? '9+' : unreadCount}
                      </div>
                    {:else if chat.is_shared}
                    <!-- Share indicator badge: shown when chat is shared (has active share link) -->
                    <div class="share-badge" title="This chat is shared">
                      <LucideIcons.Share2 size={10} color="white" />
                    </div>
                  {/if}
                </div>
              </div>
            {:else}
              <!-- CRITICAL: NO FALLBACK ICONS - only render if category/icon are set by backend -->
              <!-- If chatCategory is null, we should see this visually as missing data (BUG indicator) -->
              {#if chatCategory}
                {@const chatIconName = chatIcon || getFallbackIconForCategory(chatCategory)}
                {@const IconComponent = getLucideIcon(chatIconName)}
                <div class="category-circle-wrapper">
                  <div 
                    class="category-circle" 
                    style={categoryGradientColors ? `background: linear-gradient(135deg, ${categoryGradientColors.start}, ${categoryGradientColors.end})` : 'background: #cccccc'}
                  >
                    <div class="category-icon">
                      <IconComponent size={16} color="white" />
                    </div>
                    {#if unreadCount > 0 && !typingIndicatorInTitleView && !displayLabel && lastMessage?.status !== 'processing'}
                      <div class="unread-badge">
                        {unreadCount > 9 ? '9+' : unreadCount}
                      </div>
                    {:else if chat.is_shared}
                      <!-- Share indicator badge: shown when chat is shared (has active share link) -->
                      <div class="share-badge" title="This chat is shared">
                        <LucideIcons.Share2 size={10} color="white" />
                      </div>
                    {/if}
                  </div>
                </div>
              {:else}
                <!-- Category is null - backend hasn't set it yet or it's a legacy chat -->
                <!-- Show a placeholder circle with question mark to make it obvious -->
                <div class="category-circle-wrapper">
                  <div 
                    class="category-circle missing-category" 
                    style="background: #cccccc"
                    title="Category not set by server"
                  >
                    <div class="category-icon">
                      <LucideIcons.HelpCircle size={16} color="white" />
                    </div>
                    {#if unreadCount > 0 && !typingIndicatorInTitleView && !displayLabel && lastMessage?.status !== 'processing'}
                      <div class="unread-badge">
                        {unreadCount > 9 ? '9+' : unreadCount}
                      </div>
                    {:else if chat.is_shared}
                      <!-- Share indicator badge: shown when chat is shared (has active share link) -->
                      <div class="share-badge" title="This chat is shared">
                        <LucideIcons.Share2 size={10} color="white" />
                      </div>
                    {/if}
                  </div>
                </div>
              {/if}
            {/if}
          </div>
          <div class="chat-content">
            <!-- Demo chats use plaintext title, regular chats use cached decrypted title -->
            <!-- CRITICAL: Never show "Untitled chat" - show "Processing..." status instead if title not ready -->
            <!-- Using {@html} to render HTML styling (e.g., OpenMates branding) -->
            <div class="chat-title-wrapper">
              {#if chat.title || cachedMetadata?.title}
                <span class="chat-title">{@html chat.title || cachedMetadata?.title}</span>
              {:else if isWaitingForTitle}
                <!-- Show "Processing..." as title when waiting for metadata -->
                <span class="chat-title processing-title">{$text('enter_message.processing.text')}</span>
              {:else}
                <!-- Fallback: Only show "Untitled chat" if we're sure metadata is ready (shouldn't happen) -->
                <span class="chat-title">{@html $text('chat.untitled_chat.text')}</span>
              {/if}
              {#if chat.pinned}
                <span class="pin-indicator">
                  <span class="clickable-icon icon_pin" title="Pinned"></span>
                </span>
              {/if}
              {#if chat.is_incognito}
                <span class="incognito-label">
                  <span class="icon icon_incognito"></span>
                  {$text('settings.incognito.text', { default: 'Incognito' })}
                </span>
              {/if}
            </div>
            {#if typingIndicatorInTitleView}
              <span class="status-message">{typingIndicatorInTitleView}</span>
            {:else if displayLabel && !currentTypingMateInfo} 
              <span class="status-message">
                {displayLabel}{#if displayText && displayLabel !== $text('enter_message.draft_with_beginning.text').replace('{draft_beginning}', truncateText(draftTextContent, 30))}&nbsp;{truncateText(displayText, 60)}{/if}
              </span>
            {:else if displayText && !currentTypingMateInfo} 
               <span class="status-message">{truncateText(displayText,60)}</span>
            {/if}
          </div>
        </div>
      {/if}
    </div>
  {:else}
    <div>Loading chat...</div>
  {/if}
</div>

<!-- Context Menu -->
{#if showContextMenu}
  <ChatContextMenu
    x={contextMenuX}
    y={contextMenuY}
    show={showContextMenu}
    chat={chat}
    hideDelete={isDemoChat(chat.chat_id) && (!$authStore.isAuthenticated || $websocketStatus.status !== 'connected')}
    selectMode={selectMode}
    selectedChatIds={selectedChatIds}
    downloading={isDownloading}
    on:close={handleContextMenuAction}
    on:download={handleContextMenuAction}
    on:copy={handleContextMenuAction}
    on:hide={handleContextMenuAction}
    on:unhide={handleContextMenuAction}
    on:pin={handleContextMenuAction}
    on:unpin={handleContextMenuAction}
    on:markUnread={handleContextMenuAction}
    on:markRead={handleContextMenuAction}
    on:delete={handleContextMenuAction}
    on:enterSelectMode={handleContextMenuAction}
    on:unselect={handleContextMenuAction}
    on:selectChat={handleContextMenuAction}
  />
{/if}

<style>
  .chat-item-wrapper {
    cursor: pointer;
    transition: background-color 0.2s ease;
    margin: 0 0 -1px 0;
    /* Prevent text selection during long-press on touch devices */
    -webkit-user-select: none;
    -moz-user-select: none;
    -ms-user-select: none;
    user-select: none;
    /* Prevent callout on iOS during long-press */
    -webkit-touch-callout: none;
  }

  .chat-item-wrapper:first-child {
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
  }

  .chat-item-wrapper:last-child {
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
    margin-bottom: 0;
  }

  .chat-item-wrapper:hover {
    background-color: var(--color-grey-10);
  }

  .chat-item-wrapper.active {
    background-color: var(--color-grey-10);
  }

  .chat-item {
    padding: 12px 16px;
  }

  .chat-with-profile {
    display: flex;
    align-items: center;
    gap: 16px;
    position: relative;
  }

  .mate-profiles-container {
    flex: 0 0 28px;
    position: relative;
    height: 28px;
  }


  .chat-title-wrapper {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  .chat-title {
    font-size: 16px;
    font-weight: 500;
    color: var(--color-text);
    margin-bottom: 2px;
  }

  .pin-indicator {
    display: flex;
    align-items: center;
    opacity: 0.7;
  }

  .pin-indicator .clickable-icon {
    width: 14px;
    height: 14px;
    background: var(--color-primary);
    border-radius: 2px;
    position: relative;
    flex-shrink: 0;
  }


  .status-only-preview { 
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .status-only-preview .status-label { 
    font-family: 'Lexend Deca', sans-serif;
    font-weight: bold;
    font-size: 14px;
    color: var(--color-grey-60);
  }

  .status-only-preview .status-content-preview { 
    font-family: 'Lexend Deca', sans-serif;
    font-weight: bold;
    font-size: 16px;
    color: var(--color-grey-60);
  }

  .chat-content {
    display: flex;
    flex-direction: column;
    flex: 1;
  }

  .status-message {
    font-size: 14px;
    color: var(--color-grey-60);
  }

  .draft-content-as-title {
    font-size: 16px;
    font-weight: 500;
    color: var(--color-grey-60);
    margin-bottom: 2px;
  }

  .draft-only-layout {
    display: flex;
    flex-direction: column;
    flex: 1;
  }

  .unread-badge {
    position: absolute;
    bottom: -2px;
    right: -2px;
    width: 21px;
    height: 21px;
    background: var(--color-button-primary);
    color: white;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    font-weight: 500;
    border: 2px solid var(--color-background);
  }

  /* Share badge: indicates that this chat has an active share link */
  .share-badge {
    position: absolute;
    bottom: -4px;
    right: -4px;
    width: 18px;
    height: 18px;
    background: var(--color-grey-60);
    color: white;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 2px solid var(--color-background);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.15);
  }

  .incognito-label {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 0.75em;
    color: var(--color-grey-60);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-weight: 500;
  }

  .incognito-label .icon {
    width: 12px;
    height: 12px;
    opacity: 0.7;
  }

  /* Category circle styles */
  .category-circle-wrapper {
    flex: 0 0 28px;
    position: relative;
    height: 28px;
  }

  .category-circle {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0px 2px 4px rgba(0, 0, 0, 0.1);
    border: 2px solid var(--color-background);
    transition: all 0.2s ease;
  }

  .category-icon {
    width: 16px;
    height: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  /* Checkbox styles for select mode */
  .checkbox-wrapper {
    flex: 0 0 28px;
    position: relative;
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .chat-checkbox {
    width: 20px;
    height: 20px;
    cursor: pointer;
    accent-color: var(--color-primary);
  }

  .chat-checkbox:focus-visible {
    outline: 2px solid var(--color-primary-focus);
    outline-offset: 2px;
    border-radius: 2px;
  }
</style>
