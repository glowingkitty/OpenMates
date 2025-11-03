<script lang="ts">
  import type { Chat, TiptapJSON, Message, AITypingStartedPayload, AITaskInitiatedPayload } from '../../types/chat';
  import { onMount, onDestroy } from 'svelte';
  import { chatSyncService } from '../../services/chatSyncService';
  import { chatDB } from '../../services/db';
  import { notificationStore } from '../../stores/notificationStore';
  import { text } from '@repo/ui'; // Use text store from @repo/ui
  import { aiTypingStore, type AITypingStatus } from '../../stores/aiTypingStore';
  import { decryptWithMasterKey, decryptWithChatKey } from '../../services/cryptoService';
  import { parse_message } from '../../message_parsing/parse_message';
  import { extractUrlFromJsonEmbedBlock } from '../enter_message/services/urlMetadataService';
  import { LOCAL_CHAT_LIST_CHANGED_EVENT } from '../../services/drafts/draftConstants';
  import { chatMetadataCache, type DecryptedChatMetadata } from '../../services/chatMetadataCache';
  import ChatContextMenu from './ChatContextMenu.svelte';
  import { 
    downloadChatAsYaml, 
    copyChatToClipboard 
  } from '../../services/chatExportService';
  import type { DecryptedChatData } from '../../types/chat';
  import { DEMO_CHATS, LEGAL_CHATS, getDemoMessages, isPublicChat, isDemoChat, isLegalChat, getDemoChatById, getLegalChatById } from '../../demo_chats'; // Import demo chat utilities
  import { authStore } from '../../stores/authStore'; // Import authStore to check authentication
  import { userProfile } from '../../stores/userProfile'; // Import userProfile to update hidden_demo_chats
  import { websocketStatus } from '../../stores/websocketStatusStore'; // Import WebSocket status for connection checks
  
  // Import Lucide icons dynamically
  import * as LucideIcons from '@lucide/svelte';

  // Props using Svelte 5 runes
  let { 
    chat,
    activeChatId = undefined
  }: {
    chat: Chat;
    activeChatId?: string | undefined;
  } = $props();
 
  let draftTextContent = $state(''); 
  let displayLabel = $state('');     
  let displayText = $state('');      
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
      console.debug(`[Chat] aiTypingStore changed:`, {
        chatId: value.chatId,
        aiMessageId: value.aiMessageId,
        isTyping: value.isTyping,
        thisChatId: chat.chat_id
      });
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
    try {
      return jsonContent.content?.map((node: any) =>
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
   * Extract text from markdown, replacing json_embed blocks with their URLs
   * for better display in chat previews
   */
  function extractDisplayTextFromMarkdown(markdown: string): string {
    if (!markdown) return '';
    
    try {
      // Replace json_embed code blocks with their URLs for display, ensuring proper spacing
      const displayText = markdown.replace(/```json_embed\n([\s\S]*?)\n```/g, (match, jsonContent) => {
        const url = extractUrlFromJsonEmbedBlock(match);
        if (url) {
          // Ensure the URL has spaces around it for proper separation from surrounding text
          return ` ${url} `;
        }
        return match; // Return original if URL extraction failed
      });
      
      // Clean up multiple spaces and trim
      return displayText.replace(/\s+/g, ' ').trim();
    } catch (error) {
      console.error('[Chat] Error extracting display text from markdown:', error);
      return markdown;
    }
  }

  /**
   * Get gradient colors for a category based on mate configuration
   */
  function getCategoryGradientColors(category: string): { start: string; end: string } | null {
    // Map categories to gradient colors based on mates.yml configuration
    const categoryGradients: Record<string, { start: string; end: string }> = {
      'software_development': { start: '#155D91', end: '#42ABF4' },
      'business_development': { start: '#004040', end: '#008080' },
      'medical_health': { start: '#FD50A0', end: '#F42C2D' },
      'legal_law': { start: '#239CFF', end: '#005BA5' }, // Legacy - kept for backwards compatibility
      'openmates_official': { start: '#6366f1', end: '#4f46e5' }, // Official OpenMates brand colors (indigo)
      'maker_prototyping': { start: '#EA7600', end: '#FBAB59' },
      'marketing_sales': { start: '#FF8C00', end: '#F4B400' },
      'finance': { start: '#119106', end: '#15780D' },
      'design': { start: '#101010', end: '#2E2E2E' },
      'electrical_engineering': { start: '#233888', end: '#2E4EC8' },
      'movies_tv': { start: '#00C2C5', end: '#3170DC' },
      'history': { start: '#4989F2', end: '#2F44BF' },
      'science': { start: '#FF7300', end: '#D5320' },
      'life_coach_psychology': { start: '#FDB250', end: '#F42C2D' },
      'cooking_food': { start: '#FD8450', end: '#F42C2D' },
      'activism': { start: '#F53D00', end: '#F56200' },
      'general_knowledge': { start: '#DE1E66', end: '#FF763B' }
    };
    
    return categoryGradients[category] || null;
  }

  /**
   * Get fallback icon for a category when no icon names are provided
   */
  function getFallbackIconForCategory(category: string): string {
    const categoryIcons: Record<string, string> = {
      'software_development': 'code',
      'business_development': 'briefcase',
      'medical_health': 'heart',
      'legal_law': 'gavel', // Legacy - kept for backwards compatibility
      'openmates_official': 'shield-check', // Official category uses shield icon
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

  /**
   * Get a valid icon name with robust fallback system
   * Tries each provided icon name, then falls back to category-specific icon, then default
   */
  function getValidIconName(providedIconNames: string[], category: string): string {
    // Try each provided icon name in order
    for (const iconName of providedIconNames) {
      if (isValidLucideIcon(iconName)) {
        console.debug(`[Chat] Using valid icon: ${iconName}`);
        return iconName;
      } else {
        console.warn(`[Chat] Invalid icon name provided: ${iconName}, trying next...`);
      }
    }

    // If no valid icons provided, use category-specific fallback
    const categoryFallback = getFallbackIconForCategory(category);
    if (isValidLucideIcon(categoryFallback)) {
      console.debug(`[Chat] Using category fallback icon: ${categoryFallback}`);
      return categoryFallback;
    } else {
      // Final safety net - use default icon
      console.warn(`[Chat] Category fallback icon ${categoryFallback} is invalid, using default`);
      return 'help-circle';
    }
  }

  /**
   * Decrypt chat data on-demand (icon and category)
   */
  async function decryptChatData(chat: Chat): Promise<DecryptedChatData> {
    const result: DecryptedChatData = {};
    
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
   * Get the Lucide icon component by name
   */
  function getLucideIcon(iconName: string) {
    // Convert kebab-case to PascalCase (e.g., 'help-circle' -> 'HelpCircle')
    const pascalCaseName = iconName
      .split('-')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join('');
    
    return LucideIcons[pascalCaseName] || LucideIcons.HelpCircle;
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
      // Public chats have no drafts
      draftTextContent = '';
      
      // Load messages from static bundle instead of IndexedDB (searches both DEMO_CHATS and LEGAL_CHATS)
      const demoMessages = getDemoMessages(currentChat.chat_id, DEMO_CHATS, LEGAL_CHATS);
      lastMessage = demoMessages && demoMessages.length > 0 ? demoMessages[demoMessages.length - 1] : null;
      
      // Category is stored in encrypted_category field (as plaintext for demos)
      chatCategory = currentChat.encrypted_category || null;
      
      // Icon names stored in encrypted_icon field (as comma-separated string for demos)
      // Parse the first icon name from the list
      if (currentChat.encrypted_icon) {
        const iconNames = currentChat.encrypted_icon.split(',');
        chatIcon = iconNames.length > 0 ? iconNames[0] : null;
      } else {
        chatIcon = null;
      }
      
      console.debug(`[Chat] Public chat loaded - title: ${currentChat.title}, category: ${chatCategory}, icon: ${chatIcon}, messages: ${demoMessages.length}`);
      
      // No cached metadata for public chats (they don't use encryption)
      cachedMetadata = null;
      
      // Public chats show no status line (no drafts, no sending status)
      displayLabel = '';
      displayText = '';
      return;
    }

    // REGULAR CHAT HANDLING: Get draft content using cached metadata for performance
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
    const messages = await chatDB.getMessagesForChat(currentChat.chat_id);
    lastMessage = messages && messages.length > 0 ? messages[messages.length - 1] : null;
    
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
      console.debug(`[Chat] Using cached metadata - category: ${chatCategory}, hasIcon: ${!!chatIcon}`);
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

    displayLabel = '';
    displayText = '';

    // Handle sending, processing, and failed states first as they take precedence
    if (lastMessage?.status === 'sending') {
      displayLabel = $text('enter_message.sending.text');
      displayText = typeof lastMessage.content === 'string' ? lastMessage.content : extractTextFromTiptap(lastMessage.content);
    } else if (lastMessage?.status === 'processing') {
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
      await updateDisplayInfo(chat); 
    }
  }

  /**
   * Handles local draft changes for immediate UI refresh
   * This ensures individual Chat components update immediately when drafts are saved locally,
   * by fetching fresh data from the database
   */
  async function handleLocalDraftChanged(event: Event) {
    const customEvent = event as CustomEvent<{ chat_id?: string; draftDeleted?: boolean }>;
    const detail = customEvent.detail;

    // Only update if this event is for our specific chat or if no specific chat is mentioned (general update)
    if (chat && detail && detail.chat_id === chat.chat_id) {
      console.debug('[Chat] Local draft changed for chat:', chat.chat_id);
      
      // Note: Cache invalidation is now handled centrally in Chats.svelte to ensure it works
      // even when individual Chat components are unmounted (e.g., when panel is closed)
      
      // Fetch fresh chat data from database to get updated draft content
      try {
        const freshChat = await chatDB.getChat(chat.chat_id);
        if (freshChat) {
          // Update the current chat data with fresh data and trigger display update
          chat = freshChat;
          await updateDisplayInfo(freshChat);
        }
      } catch (error) {
        console.error('[Chat] Error fetching fresh chat data after local draft change:', error);
        // Fallback: just update display with current chat data
        await updateDisplayInfo(chat);
      }
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
  });

  function truncateText(textToTruncate: string, maxLength: number = 60): string { // Renamed param
    if (textToTruncate && textToTruncate.length > maxLength) {
      return textToTruncate.substring(0, maxLength) + '...';
    }
    return textToTruncate;
  }

  let isActive = $derived(activeChatId === chat?.chat_id);
  
  // Detect if this is a draft-only chat (has draft content but no title and no messages) using Svelte 5 runes
  let isDraftOnly = $derived(chat && draftTextContent && !cachedMetadata?.title && (!lastMessage || lastMessage === null));

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
    console.debug('[Chat] Context menu action:', action, 'for chat:', chat?.chat_id);
    
    switch (action) {
      case 'download':
        handleDownloadChat();
        break;
      case 'copy':
        handleCopyChat();
        break;
      case 'delete':
        handleDeleteChat();
        break;
      case 'close':
        showContextMenu = false;
        break;
      default:
        console.warn('[Chat] Unknown context menu action:', action);
    }
  }

  /**
   * Download chat as YAML file
   */
  async function handleDownloadChat() {
    if (!chat) return;
    
    try {
      console.debug('[Chat] Starting download for chat:', chat.chat_id);
      
      // Get all messages for the chat (from static bundle for public chats, from IndexedDB for regular chats)
      const messages = isPublicChat(chat.chat_id) 
        ? getDemoMessages(chat.chat_id, DEMO_CHATS, LEGAL_CHATS)
        : await chatDB.getMessagesForChat(chat.chat_id);
      
      // Download as YAML
      await downloadChatAsYaml(chat, messages);
      
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
   */
  async function handleCopyChat() {
    if (!chat) return;
    
    try {
      console.debug('[Chat] Copying chat to clipboard:', chat.chat_id);
      
      // Get all messages for the chat (from static bundle for demos, from IndexedDB for regular chats)
      const messages = isDemoChat(chat.chat_id)
        ? getDemoMessages(chat.chat_id, DEMO_CHATS)
        : await chatDB.getMessagesForChat(chat.chat_id);
      
      // Copy to clipboard (YAML with embedded link)
      await copyChatToClipboard(chat, messages);
      
      console.debug('[Chat] Chat copied to clipboard (YAML with embedded link)');
      notificationStore.success('Chat copied to clipboard');
    } catch (error) {
      console.error('[Chat] Error copying chat:', error);
      notificationStore.error('Failed to copy chat. Please try again.');
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
      
      // REAL CHAT HANDLING: Delete from IndexedDB and server
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
  onclick={() => { /* Dispatch an event or call a function to handle chat selection */ }}
  onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { /* Dispatch selection event */ } }}
  oncontextmenu={handleContextMenu}
  ontouchstart={handleTouchStart}
  ontouchmove={handleTouchMove}
  ontouchend={handleTouchEnd}
  ontouchcancel={handleTouchCancel}
>
  {#if chat}
    <div class="chat-item">
      {#if (lastMessage?.status === 'sending' || lastMessage?.status === 'processing') && !currentTypingMateInfo}
        <div class="status-only-preview">
          {#if displayLabel}<span class="status-label">{displayLabel}</span>{/if}
          {#if displayText}<span class="status-content-preview">{truncateText(displayText, 60)}</span>{/if}
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
            {#if currentTypingMateInfo?.isTyping && categoryGradientColors}
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
                  {#if chat.unread_count && chat.unread_count > 0 && !typingIndicatorInTitleView && !displayLabel && lastMessage?.status !== 'processing'}
                    <div class="unread-badge">
                      {chat.unread_count > 9 ? '9+' : chat.unread_count}
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
                    {#if chat.unread_count && chat.unread_count > 0 && !typingIndicatorInTitleView && !displayLabel && lastMessage?.status !== 'processing'}
                      <div class="unread-badge">
                        {chat.unread_count > 9 ? '9+' : chat.unread_count}
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
                    {#if chat.unread_count && chat.unread_count > 0 && !typingIndicatorInTitleView && !displayLabel && lastMessage?.status !== 'processing'}
                      <div class="unread-badge">
                        {chat.unread_count > 9 ? '9+' : chat.unread_count}
                      </div>
                    {/if}
                  </div>
                </div>
              {/if}
            {/if}
          </div>
          <div class="chat-content">
            <!-- Demo chats use plaintext title, regular chats use cached decrypted title -->
            <!-- Using {@html} to render HTML styling (e.g., OpenMates branding) -->
            <span class="chat-title">{@html chat.title || cachedMetadata?.title || $text('chat.untitled_chat.text')}</span>
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
    on:close={handleContextMenuAction}
    on:download={handleContextMenuAction}
    on:copy={handleContextMenuAction}
    on:delete={handleContextMenuAction}
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


  .chat-title {
    font-size: 16px;
    font-weight: 500;
    color: var(--color-text);
    margin-bottom: 2px;
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
    background: var(--color-primary);
    color: white;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    font-weight: 500;
    border: 2px solid var(--color-background);
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
</style>
