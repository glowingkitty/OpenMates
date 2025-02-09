<script lang="ts">
  import { afterUpdate, createEventDispatcher } from "svelte";
  import ChatMessage from "./ChatMessage.svelte";
  import { fly, fade } from "svelte/transition";

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

  // Define the Message type used in the chat history.
  interface Message {
    id: string;
    role: string; // "user" for your messages or the mate's name.
    messageParts: MessagePart[];
    // Additional properties (e.g. timestamp) can be added here.
  }

  // Array that holds all chat messages.
  let messages: Message[] = [];

  // Show/hide the messages block for fade-out animation.
  let showMessages = true;

  // Reference to the chat history container for scrolling.
  let container: HTMLDivElement;

  // Add prop for message input height
  export let messageInputHeight = 0;

  const dispatch = createEventDispatcher();

  /**
   * Exposed function to add a new message to the chat.
   * This is called from the ActiveChat component when a new message is sent.
   *
   * @param message - The new message object.
   */
  export function addMessage(message: Message) {
    // Append the new message.
    messages = [...messages, message];
  }

  /**
   * Exposed function to clear chat messages.
   * It triggers a fade-out animation and returns a promise that resolves
   * when the fade-out is complete.
   */
  export function clearMessages(): Promise<void> {
    console.log("[ChatHistory] Clearing messages - starting fade out");
    showMessages = false; // This will trigger the fade-out transition
    return new Promise(resolve => {
      outroResolve = resolve; // Store the resolve function
    });
  }

  let outroResolve: () => void; // Function to resolve the clearMessages promise

  /**
   * Called when the fade-out transition finishes.
   * Clears the messages and re-displays the (now empty) chat history.
   */
  function handleOutroEnd() {
    if (!showMessages) {
      console.log("[ChatHistory] Fade out complete, clearing messages");
      messages = []; // Clear messages after fade out completes
      showMessages = true; // Show the (empty) chat history
      if (outroResolve) {
        outroResolve(); // Resolve the promise
        outroResolve = null; // Reset for next time
      }
    }
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
</script>

<!--
  The chat history container:
    - Takes full height and is scrollable.
    - Uses flexbox with justify-content: flex-end so that messages appear at the bottom.
-->
<div 
    class="chat-history-container" 
    bind:this={container}
    style="bottom: {messageInputHeight}px;"
>
    {#if showMessages}
        <div class="chat-history-content" transition:fade={{ duration: 300 }} on:outroend={handleOutroEnd}>
            {#each messages as msg (msg.id)}
                <div class="message-wrapper {msg.role === 'user' ? 'user' : 'mate'}" in:fly={{ duration: 300, y: 20 }}>
                    <div in:fade>
                        <ChatMessage role={msg.role} messageParts={msg.messageParts} />
                    </div>
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
    bottom: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    /* Remove justify-content: flex-end to allow proper scrolling */
    align-items: center;
    padding: 10px;
    box-sizing: border-box;
    -webkit-overflow-scrolling: touch;
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
    &:hover {
      background-color: var(--color-grey-50);
    }
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

  .message-wrapper.mate {
    justify-content: flex-start; /* Mate messages aligned to the left */
  }

  .message-wrapper :global(.chat-message) {
    width: 100%;
    max-width: 900px;
  }
</style>
