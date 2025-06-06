<script lang="ts">
  import { afterUpdate, createEventDispatcher, tick, onMount } from "svelte"; // Added onMount
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
    // Assuming incomingMessage.content is either TiptapDoc JSON or something else (e.g. plain text for older messages)
    // preprocessTiptapJsonForEmbeds can handle null/undefined or non-doc types.
    let processedContent = preprocessTiptapJsonForEmbeds(incomingMessage.content as any); 

    // If processedContent is an object, deep clone it to ensure ChatMessage
    // receives a new object reference. This helps trigger Svelte's reactivity
    // if the original content object was mutated upstream or if 
    // preprocessTiptapJsonForEmbeds returned the same reference.
    if (typeof processedContent === 'object' && processedContent !== null) {
      try {
        processedContent = JSON.parse(JSON.stringify(processedContent));
      } catch (error) {
        console.error('[ChatHistory] Failed to deep clone processedContent:', error, processedContent);
        // Fallback or decide how to handle non-JSON-serializable content if necessary
      }
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
 
  // Array that holds all chat messages.
  let messages: InternalMessage[] = [];

  // Show/hide the messages block for fade-out animation.
  let showMessages = true;

  // Reference to the chat history container for scrolling.
  let container: HTMLDivElement;

  // Update the messageInputHeight prop to be reactive
  export let messageInputHeight = 0;

  // Add reactive statement to handle height changes
  $: containerStyle = `bottom: ${messageInputHeight}px`;

  const dispatch = createEventDispatcher();

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
    messages = [...messages, messageForHistory];
  }

  /**
   * Exposed function to clear chat messages.
   * It triggers a fade-out animation and returns a promise that resolves
   * when the fade-out is complete.
   */
  export async function clearMessages(): Promise<void> {
    messages = [];
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
    const newInternalMessages = newMessagesArray.map(G_mapToInternalMessage);
    console.debug('[ChatHistory] updateMessages. Mapped newInternalMessages:', JSON.parse(JSON.stringify(newInternalMessages)));
    console.debug('[ChatHistory] updateMessages. Current internal messages BEFORE update attempt:', JSON.parse(JSON.stringify(messages)));

    // The previous comparison logic might have been too aggressive or had a subtle bug,
    // preventing UI updates even when data changed (e.g., message status).
    // By unconditionally assigning `newInternalMessages` to `messages`, we ensure that
    // Svelte's reactivity system is always triggered if `ActiveChat.svelte` passes
    // a new array (which it does) or an array with changed content.
    // `newInternalMessages` is already a new array instance due to `.map()`.
    messages = newInternalMessages;
    // Add a log to confirm this path is taken and what the new messages are.
    console.debug('[ChatHistory] updateMessages: messages array REPLACED (unconditional assignment). New internal messages:', JSON.parse(JSON.stringify(messages)));
    dispatch('messagesChange', { hasMessages: messages.length > 0 });
  }

  onMount(() => {
    console.log('[ChatHistory.svelte] Component Mounted - VERSION_CHECK_LOG_JUNE_4_1658');
  });
 
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

  // Every time messages change, scroll the container to the bottom.
  afterUpdate(() => {
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
  });

  // Watch messages array and dispatch changes
  $: {
    dispatch('messagesChange', { hasMessages: messages.length > 0 });
  }

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
    - Uses flexbox with justify-content: flex-end so that messages appear at the bottom.
-->
<div 
    class="chat-history-container" 
    bind:this={container}
    style={containerStyle}
>
    {#if showMessages}
        <div class="chat-history-content" 
             transition:fade={{ duration: 100 }} 
             on:outroend={handleOutroEnd}>
            {#each messages as msg (msg.id)}
                <div class="message-wrapper {msg.role === 'user' ? 'user' : 'assistant'}"
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
    display: flex;
    flex-direction: column;
    align-items: center;
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

  /* Add styles for the content wrapper */
  .chat-history-content {
    width: 100%;
    /* Add margin-top to account for the top buttons */
    margin-top: 60px;
    /* Push content to the bottom when there are few messages */
    margin-top: auto;
    max-width: 900px;
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

  .message-wrapper.assistant, .message-wrapper.mate { /* Added .assistant */
    justify-content: flex-start; /* Mate messages aligned to the left */
  }

  .message-wrapper :global(.chat-message) {
    width: 100%;
    max-width: 900px;
  }
</style>
