<script lang="ts">
  import { createEventDispatcher, tick, onMount, onDestroy } from "svelte"; // Removed afterUpdate for runes mode compatibility
  import type { SvelteComponent } from 'svelte';
  import { flip } from 'svelte/animate';
  import ChatMessage from "./ChatMessage.svelte";
  import { fade } from "svelte/transition";
  import type { MessageStatus } from '../types/chat'; // Import global MessageStatus

  // Define the internal Message type for ChatHistory's own state,
  // tailored for what ChatMessage.svelte needs.
  // This should align with the global Message type from ../types/chat
  import type { Message as GlobalMessage, MessageRole } from '../types/chat';
  import { preprocessTiptapJsonForEmbeds } from './enter_message/utils/tiptapContentProcessor';
  import { parse_message } from '../message_parsing/parse_message';
  import { truncateTiptapContent } from '../utils/messageTruncation';
  import { restorePIIInText } from './enter_message/services/piiDetectionService';
  import type { PIIMapping } from '../types/chat';
  import { locale } from 'svelte-i18n';
  import { contentCache } from '../utils/contentCache';
  import { getDemoMessages, isPublicChat, DEMO_CHATS, LEGAL_CHATS } from '../demo_chats'; // Import demo chat utilities for re-fetching on locale change
  import { messageHighlightStore } from '../stores/messageHighlightStore';
  import type { 
    AppSettingsMemoriesResponseContent
  } from '../services/chatSyncServiceHandlersAppSettings';
  import type { SuggestedSettingsMemoryEntry } from '../types/apps';
  
  // Import the permission dialog component and its store for inline rendering
  // The permission dialog is rendered as part of the chat history (scrollable with messages)
  // rather than as a fixed overlay, so users can scroll while the dialog is visible
  import AppSettingsMemoriesPermissionDialog from './AppSettingsMemoriesPermissionDialog.svelte';
  import SettingsMemoriesSuggestions from './SettingsMemoriesSuggestions.svelte';
  import { 
    isPermissionDialogVisible,
    currentPermissionRequest
  } from '../stores/appSettingsMemoriesPermissionStore';

  type AppCardData = {
    component: new (...args: unknown[]) => SvelteComponent;
    props: Record<string, unknown>;
  };

  type TiptapDoc = {
    type: 'doc';
    content: Array<Record<string, unknown>>;
  };

  interface InternalMessage {
    id: string; // Derived from message_id
    role: MessageRole;
    category?: string;
    sender_name?: string; // Actual name of the mate
    model_name?: string; // Model name for AI messages
    content: unknown; // Tiptap JSON content (shape varies by embed nodes)
    status?: MessageStatus; // Status of the message
    is_truncated?: boolean; // Flag indicating if content is truncated
    full_content_length?: number; // Length of full content for reference
    original_message?: GlobalMessage; // Store original message for full content loading
    appCards?: AppCardData[]; // App skill preview cards (rendered by ChatMessage)
    _embedUpdateTimestamp?: number; // Forces re-render when embed data becomes available
    appSettingsMemoriesResponse?: AppSettingsMemoriesResponseContent; // Response to user's app settings/memories request
    pii_mappings?: PIIMapping[]; // PII mappings for restoration (from user message)
  }

  // Add optional embed/app-card metadata without widening the core message type.
  type MessageWithEmbedMetadata = GlobalMessage & {
    appCards?: AppCardData[];
    _embedUpdateTimestamp?: number;
  };

  /**
   * Build a cumulative PII mappings lookup from all user messages in the chat.
   * This allows assistant messages to restore PII from any preceding user message.
   * 
   * The approach: Aggregate all PII mappings from user messages, keyed by placeholder.
   * Later messages with the same placeholder override earlier ones (unlikely but handled).
   */
  function buildCumulativePIIMappings(allMessages: GlobalMessage[]): Map<string, PIIMapping> {
    const cumulativeMappings = new Map<string, PIIMapping>();
    
    for (const msg of allMessages) {
      if (msg.role === 'user' && msg.pii_mappings && msg.pii_mappings.length > 0) {
        for (const mapping of msg.pii_mappings) {
          cumulativeMappings.set(mapping.placeholder, mapping);
        }
      }
    }
    
    return cumulativeMappings;
  }

  /**
   * Restore PII placeholders in markdown content using the provided mappings.
   * Returns the markdown with placeholders replaced by highlighted original values.
   */
  function restorePIIInMarkdown(
    markdown: string, 
    mappings: Map<string, PIIMapping>
  ): string {
    if (mappings.size === 0) return markdown;
    
    // Convert Map to array for the restorePIIInText function
    const mappingsArray = Array.from(mappings.values());
    return restorePIIInText(markdown, mappingsArray);
  }

  // Helper function to map incoming message structure to InternalMessage
  // IMPORTANT: piiMappings parameter is optional - when provided, PII restoration is applied
  function G_mapToInternalMessage(
    incomingMessage: GlobalMessage,
    piiMappings?: Map<string, PIIMapping>
  ): InternalMessage {
    // incomingMessage.content is now a markdown string (never Tiptap JSON on server!)
    // We need to convert it to Tiptap JSON for display purposes
    let processedContent: unknown;
    
    if (typeof incomingMessage.content === 'string') {
      let contentToProcess = incomingMessage.content;
      
      // PII RESTORATION: Restore PII placeholders with original values before parsing
      // This applies to both user and assistant messages when mappings are available
      if (piiMappings && piiMappings.size > 0) {
        contentToProcess = restorePIIInMarkdown(contentToProcess, piiMappings);
      }
      
      // Content is markdown string - convert to Tiptap JSON with unified parsing (includes embed parsing)
      // CRITICAL FIX: Use 'write' mode for streaming messages to show 'processing' status on embeds
      // This ensures users see "processing" state during streaming instead of waiting for embed data
      const parseMode = incomingMessage.status === 'streaming' ? 'write' : 'read';
      const tiptapJson = parse_message(contentToProcess, parseMode, { unifiedParsingEnabled: true });
      processedContent = preprocessTiptapJsonForEmbeds(tiptapJson);

      // Apply truncation at TipTap level for user messages to avoid breaking node structure
      if (incomingMessage.role === 'user' && incomingMessage.content.length > 1000) {
        processedContent = truncateTiptapContent(processedContent);
      }
    } else {
      // Fallback for any other format (should not happen with new architecture)
      const maybeDoc = incomingMessage.content;
      const isTiptapDoc = (value: unknown): value is TiptapDoc => {
        return !!value && typeof value === 'object' && (value as { type?: string }).type === 'doc';
      };
      processedContent = preprocessTiptapJsonForEmbeds(isTiptapDoc(maybeDoc) ? maybeDoc : null);
    }

    // Check if message should be truncated (for UI display purposes)
    const shouldTruncate = incomingMessage.role === 'user' && 
                          incomingMessage.content && 
                          typeof incomingMessage.content === 'string' && 
                          incomingMessage.content.length > 1000;

    return {
      id: incomingMessage.message_id,
      role: incomingMessage.role,
      category: incomingMessage.category,
      sender_name: incomingMessage.sender_name,
      model_name: incomingMessage.model_name,
      content: processedContent,
      status: incomingMessage.status,
      is_truncated: shouldTruncate,
      full_content_length: shouldTruncate ? incomingMessage.content.length : 0,
      original_message: incomingMessage, // Store original for full content loading
      appCards: (incomingMessage as MessageWithEmbedMetadata).appCards, // Preserve appCards if present
      _embedUpdateTimestamp: (incomingMessage as MessageWithEmbedMetadata)._embedUpdateTimestamp, // Force re-render when embed data arrives
      pii_mappings: incomingMessage.pii_mappings // Preserve PII mappings
    };
  }
 
  // Array that holds all chat messages using $state (Svelte 5 runes mode)
  let messages = $state<InternalMessage[]>([]);

  /**
   * Parse system message content to check if it's an app_settings_memories_response.
   * Returns the parsed content or null if not a valid response.
   */
  function parseAppSettingsMemoriesResponse(content: unknown): AppSettingsMemoriesResponseContent | null {
    if (typeof content !== 'string') return null;
    try {
      const parsed = JSON.parse(content);
      if (parsed.type === 'app_settings_memories_response') {
        return parsed as AppSettingsMemoriesResponseContent;
      }
    } catch {
      // Not valid JSON, ignore
    }
    return null;
  }

  /**
   * Helper to read thinking entries from the map with a stable signature.
   * This keeps template logic concise and avoids unsupported {@const} placement.
   */
  function getThinkingEntry(messageId: string | undefined) {
    if (!messageId) return undefined;
    return thinkingContentByTask.get(messageId);
  }

  /**
   * Derived state: Create a lookup map of user_message_id → app settings/memories response.
   * System messages with type 'app_settings_memories_response' contain the user's decision
   * (included/rejected) and should be displayed as part of the user's message, not separately.
   * 
   * FALLBACK LOGIC: For demo/shared chats, the user_message_id in the system message content
   * may reference the original chat's message ID (which no longer exists). In this case, we
   * fall back to position-based association: find the most recent user message before this
   * system message in the array.
   */
  let appSettingsMemoriesResponseMap = $derived.by(() => {
    const map = new Map<string, AppSettingsMemoriesResponseContent>();
    
    // First, collect all user message IDs for lookup
    const userMessageIds = new Set<string>();
    for (const msg of messages) {
      if (msg.role === 'user') {
        userMessageIds.add(msg.id);
      }
    }
    
    // Now process system messages
    for (let i = 0; i < messages.length; i++) {
      const msg = messages[i];
      if (msg.role === 'system') {
        const response = parseAppSettingsMemoriesResponse(msg.original_message?.content);
        if (response) {
          // Try to use user_message_id if it matches a known user message
          if (response.user_message_id && userMessageIds.has(response.user_message_id)) {
            map.set(response.user_message_id, response);
          } else {
            // FALLBACK: user_message_id doesn't match any user message (common in demo/shared chats)
            // Find the most recent user message before this system message
            for (let j = i - 1; j >= 0; j--) {
              if (messages[j].role === 'user') {
                map.set(messages[j].id, response);
                break;
              }
            }
          }
        }
      }
    }
    
    return map;
  });

  /**
   * Derived state: Filter out system messages that are app_settings_memories_response.
   * These are displayed as part of the user's message, not as separate chat bubbles.
   */
  let displayMessages = $derived.by(() => {
    return messages.filter(msg => {
      if (msg.role === 'system') {
        const response = parseAppSettingsMemoriesResponse(msg.original_message?.content);
        // Filter out app_settings_memories_response system messages
        if (response?.type === 'app_settings_memories_response') {
          return false;
        }
      }
      return true;
    });
  });

  // Show/hide the messages block for fade-out animation using $state (Svelte 5 runes mode)
  let showMessages = $state(true);

  // Reference to the chat history container for scrolling.
  let container: HTMLDivElement;

  // Props using Svelte 5 runes mode
  let {
    messageInputHeight = 0,
    containerWidth = 0,
    currentChatId = undefined,
    thinkingContentByTask = new Map(),
    settingsMemoriesSuggestions = [],
    rejectedSuggestionHashes = null,
    onSuggestionAdded = undefined,
    onSuggestionRejected = undefined
  }: {
    messageInputHeight?: number;
    containerWidth?: number;
    currentChatId?: string; // Current active chat ID - used to ensure permission dialog only shows in the originating chat
    thinkingContentByTask?: Map<string, { content: string; isStreaming: boolean; signature?: string | null; totalTokens?: number | null }>; // Thinking content from thinking models
    settingsMemoriesSuggestions?: SuggestedSettingsMemoryEntry[]; // Suggested settings/memories entries from AI post-processing
    rejectedSuggestionHashes?: string[] | null; // SHA-256 hashes of rejected suggestions for client-side filtering
    onSuggestionAdded?: (suggestion: SuggestedSettingsMemoryEntry) => void; // Callback when user adds a suggestion
    onSuggestionRejected?: (suggestion: SuggestedSettingsMemoryEntry) => void; // Callback when user rejects a suggestion
  } = $props();

  // Add reactive statement to handle height changes using $derived (Svelte 5 runes mode)
  let containerStyle = $derived(`bottom: ${messageInputHeight-30}px`);
  
  // CRITICAL: Only show permission dialog if it belongs to the current chat
  // This prevents the dialog from showing in the wrong chat when user switches chats
  // The dialog's chatId must match the currently active chat's ID
  let shouldShowPermissionDialog = $derived(
    $isPermissionDialogVisible && 
    $currentPermissionRequest?.chatId && 
    currentChatId && 
    $currentPermissionRequest.chatId === currentChatId
  );

  // Determine if we should show settings/memories suggestions
  // Only show after the last assistant message when:
  // 1. We have suggestions to show
  // 2. We have a current chat ID
  // 3. The last message is from the assistant (not streaming)
  let shouldShowSettingsMemoriesSuggestions = $derived.by(() => {
    if (!settingsMemoriesSuggestions || settingsMemoriesSuggestions.length === 0) return false;
    if (!currentChatId) return false;
    if (displayMessages.length === 0) return false;
    
    // Check if the last message is from the assistant and not streaming
    const lastMessage = displayMessages[displayMessages.length - 1];
    if (lastMessage.role !== 'assistant') return false;
    if (lastMessage.status === 'streaming') return false;
    
    return true;
  });

  const dispatch = createEventDispatcher();

  let lastUserMessageId: string | null = null;
  let shouldScrollToNewUserMessage = false;
  let isScrolling = false;

  // Detect if any message is currently streaming
  let isCurrentlyStreaming = $derived(
    messages.some(m => m.status === 'streaming')
  );
  // Track previous streaming state to detect transitions
  let wasStreaming = $state(false);

  // Whether the streaming spacer should be active.
  // The spacer ensures the scroll position remains valid after the user-message scroll
  // positions the user message near the top of the viewport. Without it, there wouldn't
  // be enough scrollable content to hold that scroll position.
  // The spacer is activated when the user sends a message and stays active until streaming ends.
  let isSpacerActive = $state(false);

  // The computed spacer height — fills remaining viewport below the AI response.
  // As the AI response grows, the spacer shrinks. Once the response fills the viewport, spacer = 0.
  let spacerHeight = $state(0);

  /**
   * Exposed function to add a new message to the chat.
   * This is called from the ActiveChat component when a new message is sent.
   *
   * @param incomingMessage - The new message object, likely conforming to global Message type.
   */
  export function addMessage(incomingMessage: GlobalMessage) {
    console.debug('Adding message to chat history (raw):', incomingMessage);
    
    // Build cumulative PII mappings from existing messages + the new message
    // This allows assistant messages to restore PII from any preceding user message
    const allOriginalMessages = [
      ...messages.map(m => m.original_message).filter((m): m is GlobalMessage => m !== undefined),
      incomingMessage
    ];
    const piiMappings = buildCumulativePIIMappings(allOriginalMessages);
    
    const messageForHistory: InternalMessage = G_mapToInternalMessage(incomingMessage, piiMappings);
    console.debug('Adding message to chat history (processed):', messageForHistory);
    
    // Track if this is a new user message for scrolling behavior
    if (messageForHistory.role === 'user') {
      lastUserMessageId = messageForHistory.id;
      shouldScrollToNewUserMessage = true;
    }
    
    messages = [...messages, messageForHistory];
  }

  /**
   * Exposed function to clear chat messages.
   * It triggers a fade-out animation and returns a promise that resolves
   * when the fade-out is complete.
   */
  export async function clearMessages(): Promise<void> {
    messages = [];
    lastUserMessageId = null;
    shouldScrollToNewUserMessage = false;
    isSpacerActive = false;
    spacerHeight = 0;
    await tick();
    dispatch('messagesChange', { hasMessages: false });
  }

  let outroResolve: () => void; // Function to resolve the clearMessages promise

  /**
   * Called when the fade-out transition finishes.
   * Clears the messages and re-displays the (now empty) chat history.
   */
  function handleOutroEnd() {
    if (!showMessages) {
      console.debug("[ChatHistory] Fade out complete, clearing messages");
      messages = []; // Clear messages after fade out completes
      lastUserMessageId = null;
      shouldScrollToNewUserMessage = false;
      isSpacerActive = false;
      spacerHeight = 0;
      showMessages = true; // Show the (empty) chat history
      if (outroResolve) {
        outroResolve(); // Resolve the promise
        outroResolve = null; // Reset for next time
      }
    }
  }

  // Track previous locale to detect changes
  let previousLocale = $state($locale || 'en');

  // Add method to update messages
  export function updateMessages(newMessagesArray: GlobalMessage[]) {
    // Check if locale has changed - if so, force re-processing of all messages
    // Use previousLocale to detect changes since currentLocale is $derived
    const newLocale = $locale || 'en';
    const localeChanged = newLocale !== previousLocale;
    if (localeChanged) {
      // DON'T update previousLocale here - update it after processing messages
      // This ensures localeChanged stays true throughout the message processing
      // Clear cache to ensure fresh processing with new locale
      contentCache.clear();
    }
    
    // Update previousLocale AFTER checking localeChanged but BEFORE processing messages
    // This ensures localeChanged flag is preserved during message processing
    if (localeChanged) {
      previousLocale = newLocale;
    }

    const previousMessagesLength = messages.length;
    
    // Build cumulative PII mappings from all user messages in the incoming array
    // This allows assistant messages to restore PII from any preceding user message
    const piiMappings = buildCumulativePIIMappings(newMessagesArray);
    
    const newInternalMessages = newMessagesArray.map(newMessage => {
        const oldMessage = messages.find(m => m.id === newMessage.message_id);
        const newInternalMessage = G_mapToInternalMessage(newMessage, piiMappings);

        // CRITICAL FIX: Skip content optimization for streaming messages AND when locale changes
        // Streaming messages need to re-render on every chunk update
        // When locale changes, we need to re-process content to get correct translations
        // When embed updates occur (_embedUpdateTimestamp changes), force re-render so embeds display
        // If an old message exists and its content is identical to the new one,
        // reuse the old content object reference to prevent unnecessary re-renders
        // of the ReadOnlyMessage component. BUT skip this for streaming messages, locale changes, and embed updates.
        const hasEmbedUpdate = (newMessage as MessageWithEmbedMetadata)._embedUpdateTimestamp !== undefined;
        
        if (oldMessage &&
            !localeChanged &&
            !hasEmbedUpdate &&
            newMessage.status !== 'streaming') {
            // Compare content to see if it's actually different
            const oldContentStr = JSON.stringify(oldMessage.content);
            const newContentStr = JSON.stringify(newInternalMessage.content);
            if (oldContentStr === newContentStr) {
                // Content is identical, reuse old reference for optimization
                newInternalMessage.content = oldMessage.content;
            } else {
                // Content is different - log for debugging
                console.debug('[ChatHistory] Message content changed for', newMessage.message_id);
            }
        } else if (hasEmbedUpdate) {
            // Embed was updated - force new content to re-render embed NodeViews
            console.debug('[ChatHistory] Embed update detected - forcing new content for', newMessage.message_id);
            newInternalMessage.content = JSON.parse(JSON.stringify(newInternalMessage.content));
        } else if (localeChanged) {
            // Locale changed - always use new content even if it appears identical
            // This ensures translations are refreshed
            // CRITICAL: Force new content object reference to break any object equality checks
            // This ensures ReadOnlyMessage detects the change and re-renders
            console.debug('[ChatHistory] Locale changed - forcing new content for', newMessage.message_id);
            // Create a completely new content object to force reactivity
            // This breaks object reference equality, forcing Svelte to detect the change
            newInternalMessage.content = JSON.parse(JSON.stringify(newInternalMessage.content));
        }
        return newInternalMessage;
    });

    // console.debug('[ChatHistory] updateMessages. Mapped newInternalMessages:', JSON.parse(JSON.stringify(newInternalMessages)));
    // console.debug('[ChatHistory] updateMessages. Current internal messages BEFORE update attempt:', JSON.parse(JSON.stringify(messages)));

    // Check if a new user message was added
    if (newInternalMessages.length > previousMessagesLength) {
      const newMessage = newInternalMessages[newInternalMessages.length - 1];
      if (newMessage.role === 'user') {
        lastUserMessageId = newMessage.id;
        shouldScrollToNewUserMessage = true;
      }
    }

    messages = newInternalMessages;
    // Add a log to confirm this path is taken and what the new messages are.
    // console.debug('[ChatHistory] updateMessages: messages array REPLACED (intelligent assignment). New internal messages:', JSON.parse(JSON.stringify(messages)));
    dispatch('messagesChange', { hasMessages: messages.length > 0 });
  }
 
  /**
   * Updates specific message's status in the messages array and dispatches an update
   */
  export function updateMessageStatus(messageId: string, status: MessageStatus) {
    messages = messages.map(msg => 
        msg.id === messageId ? { ...msg, status } : msg
    );
    // Dispatch an event so ActiveChat knows the messages have changed
    // messages.map already returns a new array, so Svelte will detect the change.
    dispatch('messagesStatusChanged', { messages });
  }

  // ChatGPT-like scroll behavior: when user sends a message, scroll to position
  // the BOTTOM of the user message near the top of the viewport (showing last 1-2 lines)
  // This leaves maximum space below for the assistant's response to render
  $effect(() => {
    if (container && shouldScrollToNewUserMessage && lastUserMessageId && !isScrolling) {
      isScrolling = true;

      tick().then(() => {
        setTimeout(() => {
          const userMessageElement = container.querySelector(`[data-message-id="${lastUserMessageId}"]`);
          if (userMessageElement) {
            const containerRect = container.getBoundingClientRect();
            const messageRect = userMessageElement.getBoundingClientRect();
            
            // Calculate scroll position to show the BOTTOM of the user message near the top
            // messageRect.bottom gives us the bottom edge of the message
            // We want the bottom of the message to be ~60px from the top of the viewport
            // This shows the last 1-2 lines of the user message with space below for the response
            const bottomOfMessage = messageRect.bottom - containerRect.top + container.scrollTop;
            const scrollOffset = bottomOfMessage - 60; // 60px from top to show last lines

            container.scrollTo({
              top: Math.max(0, scrollOffset), // Don't scroll to negative
              behavior: 'smooth'
            });

            shouldScrollToNewUserMessage = false;
            // Activate the spacer: ensures there's enough scrollable height below the
            // user message so this scroll position remains valid as the AI response streams in.
            // The spacer fills the viewport below the user message and shrinks as the response grows.
            isSpacerActive = true;

            setTimeout(() => {
              isScrolling = false;
            }, 800);
          } else {
            shouldScrollToNewUserMessage = false;
            isScrolling = false;
          }
        }, 350);
      });
    }
  });

  // --- Streaming lifecycle: deactivate spacer when streaming ends ---
  $effect(() => {
    if (isCurrentlyStreaming && !wasStreaming) {
      // Streaming just started
      wasStreaming = true;
    } else if (!isCurrentlyStreaming && wasStreaming) {
      // Streaming ended — deactivate spacer and reset
      wasStreaming = false;
      isSpacerActive = false;
      spacerHeight = 0;
    }
  });

  // --- Spacer height computation ---
  // The spacer ensures the scroll position remains valid after the user-message scroll
  // positions the user message near the top of the viewport.
  //
  // How it works:
  // 1. User sends a message → scroll positions user message near top → isSpacerActive = true
  // 2. AI response starts streaming below the user message
  // 3. The spacer fills the remaining viewport height below the AI response,
  //    preventing the scroll position from jumping as content grows downward
  // 4. As the AI response grows taller, the spacer shrinks toward 0
  // 5. Once streaming ends, the spacer is removed
  //
  // CRITICAL: We do NOT auto-scroll during streaming. The scroll position stays fixed
  // and the user reads the AI response naturally as it extends downward. This avoids
  // interrupting the user's reading flow.
  $effect(() => {
    if (!container || !isSpacerActive) {
      if (!isSpacerActive) spacerHeight = 0;
      return;
    }
    // Re-run whenever messages change (on each streaming chunk)
    // eslint-disable-next-line @typescript-eslint/no-unused-expressions
    messages;

    tick().then(() => {
      if (!container || !isSpacerActive) return;
      
      // Find the last message element (the streaming AI response)
      const messageWrappers = container.querySelectorAll('[data-message-id]');
      if (messageWrappers.length === 0) return;
      const lastMessageEl = messageWrappers[messageWrappers.length - 1] as HTMLElement;
      
      // The spacer fills the gap between the bottom of the last message and
      // the bottom of the viewport. As the AI response grows, the spacer shrinks.
      const viewportHeight = container.clientHeight;
      const lastMessageHeight = lastMessageEl.offsetHeight;
      
      // 80px accounts for the user message offset at top + padding
      const neededSpacer = Math.max(0, viewportHeight - lastMessageHeight - 80);
      spacerHeight = neededSpacer;
    });
  });

  // Handle scrolling to highlighted message from deep link
  $effect(() => {
    if (container && $messageHighlightStore) {
      const messageId = $messageHighlightStore;
      
      // Wait for messages to render
      tick().then(() => {
        const attemptScroll = (attempts = 0) => {
          const targetMessage = container.querySelector(`[data-message-id="${messageId}"]`);
          
          if (targetMessage) {
            const messageTop = (targetMessage as HTMLElement).offsetTop;
            // Scroll so the message has 100px offset from top
            const scrollPosition = Math.max(0, messageTop - 100);
            
            container.scrollTo({
              top: scrollPosition,
              behavior: 'smooth'
            });
            console.debug(`[ChatHistory] Scrolled to highlighted message ${messageId}`);
          } else if (attempts < 10) {
            // Message not found yet, try again after a short delay
            setTimeout(() => attemptScroll(attempts + 1), 100);
          }
        };
        
        attemptScroll();
      });
    }
  });

  // Watch messages array and dispatch changes using $effect (Svelte 5 runes mode)
  $effect(() => {
    dispatch('messagesChange', { hasMessages: messages.length > 0 });
  });


  // Update the scroll methods to use the correct container reference
  export function scrollToTop() {
    if (container) {
      container.scrollTo({
        top: 0,
        behavior: 'smooth'
      });
    } else {
      console.warn("[ChatHistory] Container not found");
    }
  }
  
  export function scrollToBottom() {
    if (container) {
      container.scrollTo({
        top: container.scrollHeight,
        behavior: 'auto' // Use instant scroll to avoid animation
      });
    } else {
      console.warn("[ChatHistory] Container not found");
    }
  }

  // Scroll position tracking for cross-device sync
  let scrollDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  let isRestoringScroll = false;
  let scrollFrame: number | null = null;

  // Track scroll position with optimized performance using requestAnimationFrame
  // This ensures smooth scrolling without blocking the main thread
  function handleScroll() {
    // Don't track scroll position during restoration
    if (isRestoringScroll) return;

    // Performance optimization: Use requestAnimationFrame for immediate UI updates
    // This ensures smooth, jank-free scrolling by syncing with browser repaint cycle
    if (scrollFrame) return; // Skip if frame already scheduled
    
    scrollFrame = requestAnimationFrame(() => {
      // Immediately check if at bottom for UI state (no debounce for responsive UI)
      checkIfAtBottomForUI();
      scrollFrame = null;
    });
    
    // Debounced tracking for scroll position saving (500ms)
    // This prevents excessive IndexedDB writes during scrolling
    if (scrollDebounceTimer) clearTimeout(scrollDebounceTimer);
    
    scrollDebounceTimer = setTimeout(() => {
      trackLastVisibleMessage();
      checkIfScrolledToBottom();
    }, 500);
  }
  
  // Immediate check for UI state - no debouncing
  function checkIfAtBottomForUI() {
    if (!container) return;
    
    const isAtBottomLocal = 
      container.scrollHeight - container.scrollTop - container.clientHeight < 50;
    
    // Dispatch immediate event for UI state changes (button visibility)
    dispatch('scrollPositionUI', { isAtBottom: isAtBottomLocal });
  }

  // Find the last message that's currently visible in viewport
  function trackLastVisibleMessage() {
    if (!container) return;
    
    const messages = container.querySelectorAll('[data-message-id]');
    if (messages.length === 0) return;
    
    const containerRect = container.getBoundingClientRect();
    let lastVisibleMessageId: string | null = null;
    
    // Find the last message that's at least partially visible
    messages.forEach((messageEl: HTMLElement) => {
      const messageRect = messageEl.getBoundingClientRect();
      
      // Check if message is in viewport
      if (messageRect.bottom > containerRect.top && 
          messageRect.top < containerRect.bottom) {
        
        lastVisibleMessageId = messageEl.dataset.messageId || null;
      }
    });
    
    if (lastVisibleMessageId) {
      dispatch('scrollPositionChanged', {
        message_id: lastVisibleMessageId
      });
    }
  }

  // Check if user has scrolled to bottom (mark as read)
  function checkIfScrolledToBottom() {
    if (!container) return;
    
    const isAtBottom = 
      container.scrollHeight - container.scrollTop - container.clientHeight < 50;
    
    if (isAtBottom) {
      // When scrolled to bottom, find the last message and save it as scroll position
      const messages = container.querySelectorAll('[data-message-id]');
      if (messages.length > 0) {
        const lastMessage = messages[messages.length - 1];
        const lastMessageId = lastMessage.getAttribute('data-message-id');
        if (lastMessageId) {
          // Save the last message as scroll position
          dispatch('scrollPositionChanged', {
            message_id: lastMessageId
          });
        }
      }
      
      dispatch('scrolledToBottom');
    }
  }

  // Restore scroll position to a specific message with 70px offset
  export function restoreScrollPosition(messageId: string) {
    if (!container) {
      console.warn('[ChatHistory] Cannot restore scroll: container not ready');
      return;
    }
    
    // Set flag to prevent scroll tracking during restoration
    isRestoringScroll = true;
    
    // Wait for messages to be rendered before attempting to restore scroll position
    const attemptRestore = (attempts = 0) => {
      if (attempts > 10) {
        console.warn(`[ChatHistory] Failed to find anchor message ${messageId} after 10 attempts, scrolling to bottom`);
        scrollToBottom();
        // Reset flag after restoration is complete
        setTimeout(() => { isRestoringScroll = false; }, 100);
        return;
      }
      
      const targetMessage = container.querySelector(`[data-message-id="${messageId}"]`);
      
      if (targetMessage) {
        const messageTop = (targetMessage as HTMLElement).offsetTop;
        // Scroll so the message has 70px offset from top (shows end of previous message)
        const scrollPosition = Math.max(0, messageTop - 70);
        
        container.scrollTo({
          top: scrollPosition,
          behavior: 'auto' // Use instant scroll for restoration
        });
        
        console.debug(`[ChatHistory] Restored scroll to message ${messageId} with 70px offset`);
        // Reset flag after restoration is complete
        setTimeout(() => { isRestoringScroll = false; }, 100);
      } else {
        // Message not found yet, try again after a short delay
        setTimeout(() => attemptRestore(attempts + 1), 50);
      }
    };
    
    requestAnimationFrame(() => attemptRestore());
  }

  // Listen for language changes to force re-processing of messages
  // This ensures translations update immediately when language changes
  // Note: For demo chats, ActiveChat will call updateMessages with newly translated messages
  // This handler ensures non-demo chats also update when language changes
  // CRITICAL: Only listen to 'language-changed-complete' to avoid race conditions
  // ActiveChat's handler will call updateMessages with new messages, which will detect locale change
  // This handler is a fallback for non-demo chats
  onMount(() => {
    const handleLanguageChange = async () => {
      // Clear cache to ensure fresh processing with new locale
      contentCache.clear();
      
      // CRITICAL: Check if messages are from a public chat (demo or legal)
      // If so, re-fetch them with new translations
      // This is a fallback in case ActiveChat's handler didn't run or failed
      if (messages.length > 0 && messages[0].original_message?.chat_id) {
        const chatId = messages[0].original_message.chat_id;
        if (isPublicChat(chatId)) {
          try {
            // Re-fetch messages with new translations
            const newMessages = getDemoMessages(chatId, DEMO_CHATS, LEGAL_CHATS);
            if (newMessages.length > 0) {
              // Call updateMessages to process the new messages
              // This will detect locale change and force re-processing
              updateMessages(newMessages);
              return; // Exit early since updateMessages handled everything
            } else {
              console.warn('[ChatHistory] No messages found for public chat:', chatId);
            }
          } catch (error) {
            console.error('[ChatHistory] Error re-fetching demo messages:', error);
            // Fall through to fallback re-render
          }
        }
      }
      
      // CRITICAL: Don't update previousLocale here - let updateMessages handle it
      // This ensures that when ActiveChat calls updateMessages, it will detect the locale change
      // Only force re-render if updateMessages hasn't been called (non-demo chats)
      // For demo chats, ActiveChat will call updateMessages with new messages
      
      // Force complete re-render by creating entirely new message objects
      // This ensures ReadOnlyMessage components detect the change and re-process content
      // This is especially important for non-demo chats where ActiveChat might not call updateMessages
      // For non-demo chats, we force a re-render which will trigger ReadOnlyMessage to re-process
      messages = messages.map(msg => {
        // Create a completely new message object with new content reference
        // This forces Svelte to detect the change and re-render ReadOnlyMessage
        const newContent = JSON.parse(JSON.stringify(msg.content));
        
        return {
          ...msg,
          content: newContent,
          // Force new object reference for original_message too
          // If original_message has markdown content, it will be re-processed with new locale
          original_message: msg.original_message ? {
            ...msg.original_message,
            // Re-process original message content if it's a string (markdown)
            // This ensures translations are updated when ReadOnlyMessage processes it
            content: typeof msg.original_message.content === 'string' 
              ? msg.original_message.content // Keep markdown string, will be re-processed with new locale
              : msg.original_message.content
          } : msg.original_message
        };
      });
      
    };

    // Listen to language change complete event
    // This fires after ActiveChat has processed, so updateMessages should have been called
    // But we still handle it as a fallback for non-demo chats
    window.addEventListener('language-changed-complete', handleLanguageChange);

    // Cleanup on component destroy
    return () => {
      window.removeEventListener('language-changed-complete', handleLanguageChange);
    };
  });

  // Cleanup on component destroy
  onDestroy(() => {
    // Cancel any pending scroll tracking operations
    if (scrollDebounceTimer) clearTimeout(scrollDebounceTimer);
    if (scrollFrame) cancelAnimationFrame(scrollFrame);
  });
</script>

<!--
  The chat history container:
    - Takes full height and is scrollable.
    - Messages are aligned to the top for ChatGPT-style behavior.
-->
<div 
    class="chat-history-container" 
    class:empty={displayMessages.length === 0}
    bind:this={container}
    style={containerStyle}
    onscroll={handleScroll}
>
    {#if showMessages}
        <div class="chat-history-content" 
             class:has-messages={displayMessages.length > 0}
             transition:fade={{ duration: 100 }} 
             onoutroend={handleOutroEnd}>
            {#each displayMessages as msg (msg.id)}
                <div class="message-wrapper {msg.role === 'system' ? 'system' : (msg.role === 'user' ? 'user' : 'assistant')}"
                     data-message-id={msg.id}
                     style={`
                         opacity: ${msg.status === 'sending' ? 0.5 : (msg.status === 'failed' ? 0.7 : 1)};
                         ${msg.status === 'failed' ? 'border: 1px solid var(--color-error); border-radius: 12px; padding: 2px;' : ''}
                     `}
                     in:fade={{ duration: 300 }}
                     animate:flip={{ duration: 250 }}>
                    <ChatMessage
                        role={msg.role}
                        category={msg.category}
                        model_name={msg.model_name}
                        content={msg.content}
                        status={msg.status}
                        is_truncated={msg.is_truncated}
                        original_message={msg.original_message}
                        containerWidth={containerWidth}
                        appCards={msg.appCards}
                        _embedUpdateTimestamp={msg._embedUpdateTimestamp}
                        appSettingsMemoriesResponse={msg.role === 'user' ? appSettingsMemoriesResponseMap.get(msg.id) : undefined}
                        thinkingContent={msg.role === 'assistant' ? (getThinkingEntry(msg.id)?.content ?? msg.original_message?.thinking_content) : undefined}
                        isThinkingStreaming={msg.role === 'assistant' ? (getThinkingEntry(msg.id)?.isStreaming || false) : false}
                    />
                </div>
            {/each}
            
            <!-- Bottom spacer: fills remaining viewport space below messages during streaming.
                 Creates the ChatGPT-like effect where the user message sits near the top
                 with empty space below that gradually fills as the AI response streams in. -->
            {#if spacerHeight > 0}
                <div class="streaming-spacer" style="height: {spacerHeight}px;"></div>
            {/if}
            
            <!-- App settings/memories permission dialog (inline, scrolls with messages) -->
            <!-- This is rendered as part of the chat history so users can scroll while dialog is visible -->
            <!-- CRITICAL: Only show dialog if it belongs to the current chat (prevents showing in wrong chat) -->
            {#if shouldShowPermissionDialog}
                <div class="permission-dialog-wrapper" in:fade={{ duration: 200 }}>
                    <AppSettingsMemoriesPermissionDialog />
                </div>
            {/if}
            
            <!-- Settings/memories suggestions shown after the last assistant message -->
            <!-- These are generated during AI post-processing Phase 2 -->
            {#if shouldShowSettingsMemoriesSuggestions && currentChatId}
                <div class="settings-memories-suggestions-wrapper" in:fade={{ duration: 200 }}>
                    <SettingsMemoriesSuggestions
                        suggestions={settingsMemoriesSuggestions}
                        chatId={currentChatId}
                        rejectedHashes={rejectedSuggestionHashes}
                        onSuggestionAdded={onSuggestionAdded}
                        onSuggestionRejected={onSuggestionRejected}
                    />
                </div>
            {/if}
        </div>
    {/if}
</div>

<style>
  .chat-history-container {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    overflow-y: auto;
    overflow-x: hidden; /* Prevent horizontal scrollbar from appearing at certain viewport widths */
    padding: 10px;
    box-sizing: border-box;
    -webkit-overflow-scrolling: touch;
    /* Add mask for top and bottom fade effect */
    mask-image: linear-gradient(to bottom, 
        rgba(0, 0, 0, 0) 0%, 
        rgba(0, 0, 0, 1) 30px, 
        rgba(0, 0, 0, 1) calc(100% - 30px), 
        rgba(0, 0, 0, 0) 100%
    );
  }

  /* Hide scrollbar and prevent any content height when chat is empty */
  .chat-history-container.empty {
    overflow: hidden;
  }

  /* When empty, ensure content has no height to prevent scrollbar */
  .chat-history-container.empty .chat-history-content {
    height: 0;
    min-height: 0;
    padding-top: 0;
  }

  /* Add styles for the content wrapper - aligned to top for ChatGPT-style behavior */
  .chat-history-content {
    width: 100%;
    max-width: 900px;
    margin: 0 auto;
  }

  /* Only apply padding-top and min-height when there are messages */
  /* This prevents the first message from overlaying the button */
  .chat-history-content.has-messages {
    padding-top: 50px;
    /* Ensure minimum height for proper scrolling when messages exist */
    min-height: 100%;
  }


  /* Permission dialog wrapper - renders as part of chat history */
  /* This allows users to scroll the chat while the dialog is visible */
  .permission-dialog-wrapper {
    width: 100%;
    display: flex;
    justify-content: center;
    padding: 20px 0;
    margin-top: 10px;
  }

  /* Settings/memories suggestions wrapper - shown after last assistant message */
  .settings-memories-suggestions-wrapper {
    width: 100%;
    padding: 10px 0 20px 0;
    margin-top: 5px;
  }

  /* Bottom spacer that fills remaining viewport space during AI streaming.
     Creates visual space below user message that fills as the response streams in. */
  .streaming-spacer {
    flex-shrink: 0;
    pointer-events: none;
    /* Smooth transition as spacer shrinks while AI response grows */
    transition: height 0.15s ease-out;
  }

  .message-wrapper {
    margin: 5px 0;
    width: 100%;
    display: flex;
    flex-shrink: 0;
  }

  .message-wrapper.user {
    justify-content: flex-end; /* User messages aligned to the right */
  }

  .message-wrapper.assistant { /* Assistant messages aligned to the left */
    justify-content: flex-start;
  }

  .message-wrapper.system { /* System messages (e.g., insufficient credits) centered */
    justify-content: center;
  }

  .message-wrapper :global(.chat-message) {
    width: 100%;
    max-width: 900px;
  }
</style>
