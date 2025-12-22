<script lang="ts">
  import { createEventDispatcher, tick, onMount, onDestroy } from "svelte"; // Removed afterUpdate for runes mode compatibility
  import { flip } from 'svelte/animate';
  import ChatMessage from "./ChatMessage.svelte";
  import { fly, fade } from "svelte/transition";
  import type { MessageStatus } from '../types/chat'; // Import global MessageStatus

  // Define types without the export modifier.
  type TextMessagePart = {
    type: "text";
    content: string;
  };

  type AppCardsMessagePart = {
    type: "app-cards";
    content: any[]; // Use more specific type if available.
  };

  type MessagePart = TextMessagePart | AppCardsMessagePart;

  // Define the internal Message type for ChatHistory's own state,
  // tailored for what ChatMessage.svelte needs.
  // This should align with the global Message type from ../types/chat
  import type { Message as GlobalMessage, MessageRole } from '../types/chat';
  import { preprocessTiptapJsonForEmbeds } from './enter_message/utils/tiptapContentProcessor';
  import { parseMarkdownToTiptap } from '../components/enter_message/utils/markdownParser';
  import { parse_message } from '../message_parsing/parse_message';
  import { createTruncatedMessage, truncateTiptapContent } from '../utils/messageTruncation';
  import { locale } from 'svelte-i18n';
  import { contentCache } from '../utils/contentCache';
  import { getDemoMessages, isPublicChat, DEMO_CHATS, LEGAL_CHATS } from '../demo_chats'; // Import demo chat utilities for re-fetching on locale change

  interface InternalMessage {
    id: string; // Derived from message_id
    role: MessageRole;
    category?: string;
    sender_name?: string; // Actual name of the mate
    content: any; // Tiptap JSON content
    status?: MessageStatus; // Status of the message
    is_truncated?: boolean; // Flag indicating if content is truncated
    full_content_length?: number; // Length of full content for reference
    original_message?: GlobalMessage; // Store original message for full content loading
    appCards?: any[]; // App skill preview cards
  }

  // Helper function to map incoming message structure to InternalMessage
  function G_mapToInternalMessage(incomingMessage: GlobalMessage): InternalMessage {
    // incomingMessage.content is now a markdown string (never Tiptap JSON on server!)
    // We need to convert it to Tiptap JSON for display purposes
    let processedContent: any;
    
    if (typeof incomingMessage.content === 'string') {
      // Content is markdown string - convert to Tiptap JSON with unified parsing (includes embed parsing)
      // CRITICAL FIX: Use 'write' mode for streaming messages to show 'processing' status on embeds
      // This ensures users see "processing" state during streaming instead of waiting for embed data
      const parseMode = incomingMessage.status === 'streaming' ? 'write' : 'read';
      const tiptapJson = parse_message(incomingMessage.content, parseMode, { unifiedParsingEnabled: true });
      processedContent = preprocessTiptapJsonForEmbeds(tiptapJson);

      // Apply truncation at TipTap level for user messages to avoid breaking node structure
      if (incomingMessage.role === 'user' && incomingMessage.content.length > 1000) {
        processedContent = truncateTiptapContent(processedContent);
      }
    } else {
      // Fallback for any other format (should not happen with new architecture)
      processedContent = preprocessTiptapJsonForEmbeds(incomingMessage.content as any);
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
      content: processedContent,
      status: incomingMessage.status,
      is_truncated: shouldTruncate,
      full_content_length: shouldTruncate ? incomingMessage.content.length : 0,
      original_message: incomingMessage, // Store original for full content loading
      appCards: (incomingMessage as any).appCards // Preserve appCards if present
    };
  }
 
  // Array that holds all chat messages using $state (Svelte 5 runes mode)
  let messages = $state<InternalMessage[]>([]);

  // Show/hide the messages block for fade-out animation using $state (Svelte 5 runes mode)
  let showMessages = $state(true);

  // Reference to the chat history container for scrolling.
  let container: HTMLDivElement;

  // Props using Svelte 5 runes mode
  let {
    messageInputHeight = 0,
    containerWidth = 0
  }: {
    messageInputHeight?: number;
    containerWidth?: number;
  } = $props();

  // Add reactive statement to handle height changes using $derived (Svelte 5 runes mode)
  let containerStyle = $derived(`bottom: ${messageInputHeight-30}px`);

  const dispatch = createEventDispatcher();

  let lastUserMessageId: string | null = null;
  let shouldScrollToNewUserMessage = false;
  let isScrolling = false;

  // Track current locale reactively to detect changes
  // Use $derived to ensure it's always in sync with $locale
  let currentLocale = $derived($locale || 'en');

  /**
   * Exposed function to add a new message to the chat.
   * This is called from the ActiveChat component when a new message is sent.
   *
   * @param incomingMessage - The new message object, likely conforming to global Message type.
   */
  export function addMessage(incomingMessage: GlobalMessage) {
    console.debug('Adding message to chat history (raw):', incomingMessage);
    const messageForHistory: InternalMessage = G_mapToInternalMessage(incomingMessage);
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
    
    
    const newInternalMessages = newMessagesArray.map(newMessage => {
        const oldMessage = messages.find(m => m.id === newMessage.message_id);
        const newInternalMessage = G_mapToInternalMessage(newMessage);

        // CRITICAL FIX: Skip content optimization for streaming messages AND when locale changes
        // Streaming messages need to re-render on every chunk update
        // When locale changes, we need to re-process content to get correct translations
        // If an old message exists and its content is identical to the new one,
        // reuse the old content object reference to prevent unnecessary re-renders
        // of the ReadOnlyMessage component. BUT skip this for streaming messages and locale changes.
        if (oldMessage &&
            !localeChanged &&
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

  $effect(() => {
    if (container && shouldScrollToNewUserMessage && lastUserMessageId && !isScrolling) {
      isScrolling = true;

      tick().then(() => {
        setTimeout(() => {
          const userMessageElement = container.querySelector(`[data-message-id="${lastUserMessageId}"]`);
          if (userMessageElement) {
            const containerRect = container.getBoundingClientRect();
            const messageRect = userMessageElement.getBoundingClientRect();
            const scrollOffset = messageRect.top - containerRect.top + container.scrollTop - 20;

            container.scrollTo({
              top: scrollOffset,
              behavior: 'smooth'
            });

            shouldScrollToNewUserMessage = false;

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
  let scrollDebounceTimer: NodeJS.Timeout | null = null;
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
    
    const isAtBottom = 
      container.scrollHeight - container.scrollTop - container.clientHeight < 50;
    
    // Dispatch immediate event for UI state changes (button visibility)
    dispatch('scrollPositionUI', { isAtBottom });
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
    class:empty={messages.length === 0}
    bind:this={container}
    style={containerStyle}
    onscroll={handleScroll}
>
    {#if showMessages}
        <div class="chat-history-content" 
             class:has-messages={messages.length > 0}
             transition:fade={{ duration: 100 }} 
             onoutroend={handleOutroEnd}>
            {#each messages as msg (msg.id)}
                <div class="message-wrapper {msg.role === 'user' ? 'user' : 'assistant'}"
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
                        full_content_length={msg.full_content_length}
                        original_message={msg.original_message}
                        containerWidth={containerWidth}
                        appCards={msg.appCards}
                    />
                </div>
            {/each}
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

  .message-wrapper :global(.chat-message) {
    width: 100%;
    max-width: 900px;
  }
</style>
