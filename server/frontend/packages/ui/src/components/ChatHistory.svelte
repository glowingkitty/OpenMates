<script lang="ts">
  import { afterUpdate } from "svelte";
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

  // Reference to the chat history container for scrolling.
  let container: HTMLDivElement;

  // Add prop for message input height
  export let messageInputHeight = 0;

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
   * Converts a message object into its final markdown representation.
   * The generated markdown is logged to the console.
   *
   * @param message - The message to convert.
   * @returns The markdown string.
   */
  function createMarkdown(message: Message): string {
    let markdown = "";
    // Iterate over each part of the message.
    message.messageParts.forEach((part) => {
      if (part.type === "text") {
        markdown += part.content;
      } else if (part.type === "app-cards") {
        // For app cards, output a placeholder string.
        if (Array.isArray(part.content)) {
          part.content.forEach(() => {
            markdown += "[app-card]";
          });
        }
      }
    });
    // Log the final markdown.
    console.log("Final markdown:", markdown.trim());
    return markdown.trim();
  }

  // Every time messages change, scroll the container to the bottom.
  afterUpdate(() => {
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
  });

  // When the messages array changes (e.g. a new message is added),
  // run the markdown conversion for the latest message.
  $: if (messages.length) {
    const latest = messages[messages.length - 1];
    createMarkdown(latest);
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
  
  {#each messages as msg (msg.id)}
    <div class="message-wrapper {msg.role === 'user' ? 'user' : 'mate'}" in:fly={{ duration: 300, y: 20 }}>
      <div in:fade>
        <ChatMessage role={msg.role} messageParts={msg.messageParts} />
      </div>
    </div>
  {/each}
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
    justify-content: flex-end;
    align-items: center;
    padding: 10px;
    box-sizing: border-box;
    -webkit-overflow-scrolling: touch; /* Smooth scrolling on iOS */
  }

  /* Make sure the container can be scrolled */
  .chat-history-container::-webkit-scrollbar {
    width: 8px;
  }

  .chat-history-container::-webkit-scrollbar-track {
    background: transparent;
  }

  .chat-history-container::-webkit-scrollbar-thumb {
    background-color: var(--color-grey-40);
    border-radius: 4px;
  }

  .message-wrapper {
    margin: 5px 0;
    width: 100%;
    max-width: 900px;
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
