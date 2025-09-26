<script lang="ts">
  import { createEventDispatcher, tick, onMount } from "svelte"; // Removed afterUpdate for runes mode compatibility
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

  interface InternalMessage {
    id: string; // Derived from message_id
    role: MessageRole;
    category?: string;
    sender_name?: string; // Actual name of the mate
    content: any; // Tiptap JSON content
    status?: MessageStatus; // Status of the message
  }

  // Helper function to map incoming message structure to InternalMessage
  function G_mapToInternalMessage(incomingMessage: GlobalMessage): InternalMessage {
    // incomingMessage.content is now a markdown string (never Tiptap JSON on server!)
    // We need to convert it to Tiptap JSON for display purposes
    let processedContent: any;
    
    if (typeof incomingMessage.content === 'string') {
      // Content is markdown string - convert to Tiptap JSON for display
      const tiptapJson = parseMarkdownToTiptap(incomingMessage.content);
      processedContent = preprocessTiptapJsonForEmbeds(tiptapJson);
    } else {
      // Fallback for any other format (should not happen with new architecture)
      processedContent = preprocessTiptapJsonForEmbeds(incomingMessage.content as any);
    }

    return {
      id: incomingMessage.message_id,
      role: incomingMessage.role,
      category: incomingMessage.category,
      sender_name: incomingMessage.sender_name,
      content: processedContent,
      status: incomingMessage.status,
    };
  }
 
  // Array that holds all chat messages using $state (Svelte 5 runes mode)
  let messages = $state<InternalMessage[]>([]);

  // Show/hide the messages block for fade-out animation using $state (Svelte 5 runes mode)
  let showMessages = $state(true);

  // Reference to the chat history container for scrolling.
  let container: HTMLDivElement;

  // Props using Svelte 5 runes mode
  let { messageInputHeight = 0 }: { messageInputHeight?: number } = $props();

  // Add reactive statement to handle height changes using $derived (Svelte 5 runes mode)
  let containerStyle = $derived(`bottom: ${messageInputHeight}px`);

  const dispatch = createEventDispatcher();

  // Track the last user message to implement ChatGPT-style scrolling
  let lastUserMessageId: string | null = null;
  let shouldScrollToNewUserMessage = false;

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

  // Add method to update messages
  export function updateMessages(newMessagesArray: GlobalMessage[]) {
    console.debug('[ChatHistory] updateMessages CALLED. Raw newMessagesArray:', JSON.parse(JSON.stringify(newMessagesArray)));
    
    const previousMessagesLength = messages.length;
    const newInternalMessages = newMessagesArray.map(newMessage => {
        const oldMessage = messages.find(m => m.id === newMessage.message_id);
        const newInternalMessage = G_mapToInternalMessage(newMessage);

        // If an old message exists and its content is identical to the new one,
        // reuse the old content object reference to prevent unnecessary re-renders
        // of the ReadOnlyMessage component.
        if (oldMessage && JSON.stringify(oldMessage.content) === JSON.stringify(newInternalMessage.content)) {
            newInternalMessage.content = oldMessage.content;
        }
        return newInternalMessage;
    });

    console.debug('[ChatHistory] updateMessages. Mapped newInternalMessages:', JSON.parse(JSON.stringify(newInternalMessages)));
    console.debug('[ChatHistory] updateMessages. Current internal messages BEFORE update attempt:', JSON.parse(JSON.stringify(messages)));

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
    console.debug('[ChatHistory] updateMessages: messages array REPLACED (intelligent assignment). New internal messages:', JSON.parse(JSON.stringify(messages)));
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

  // Implement ChatGPT-style scrolling behavior using $effect (Svelte 5 runes mode)
  $effect(() => {
    if (container && shouldScrollToNewUserMessage && lastUserMessageId) {
      // Find the user message element
      const userMessageElement = container.querySelector(`[data-message-id="${lastUserMessageId}"]`);
      if (userMessageElement) {
        // Scroll so the user message appears at the top of the visible area
        const containerRect = container.getBoundingClientRect();
        const messageRect = userMessageElement.getBoundingClientRect();
        const scrollOffset = messageRect.top - containerRect.top + container.scrollTop - 20; // 20px padding from top
        
        container.scrollTo({
          top: scrollOffset,
          behavior: 'smooth'
        });
        
        shouldScrollToNewUserMessage = false;
      }
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
        behavior: 'smooth'
      });
    } else {
      console.warn("[ChatHistory] Container not found");
    }
  }
</script>

<!--
  The chat history container:
    - Takes full height and is scrollable.
    - Messages are aligned to the top for ChatGPT-style behavior.
-->
<div 
    class="chat-history-container" 
    bind:this={container}
    style={containerStyle}
>
    {#if showMessages}
        <div class="chat-history-content" 
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
                        content={msg.content}
                        status={msg.status}
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

  /* Add styles for the content wrapper - aligned to top for ChatGPT-style behavior */
  .chat-history-content {
    width: 100%;
    max-width: 900px;
    margin: 0 auto;
    /* Add margin-top to account for the top buttons */
    /* Removed padding to not show scroll when there is nothing to scroll*/
    /* padding-top: 60px; */
    /* Ensure minimum height for proper scrolling */
    min-height: 100%;
  }

  /* Make sure the container can be scrolled */
  .chat-history-container::-webkit-scrollbar {
    width: 8px;
    height: 8px;
  }

  .chat-history-container::-webkit-scrollbar-track {
    background: rgba(0, 0, 0, 0.1);
    border-radius: 4px;
  }

  .chat-history-container::-webkit-scrollbar-thumb {
    background-color: var(--color-grey-40);
    border-radius: 4px;
  }
  .chat-history-container::-webkit-scrollbar-thumb:hover {
    background-color: var(--color-grey-50);
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
