<script lang="ts">
  import type { SvelteComponent } from 'svelte';
  import { afterUpdate } from 'svelte';
  import ReadOnlyMessage from './ReadOnlyMessage.svelte';
  
  export let role: 'user' | string = 'user';
  
  // Define types for message content parts
  type AppCardData = {
    component: new (...args: any[]) => SvelteComponent;
    props: Record<string, any>;
  };
  
  // Use a discriminated union so that "text" parts only have a string and "app-cards" parts only have AppCardData[]
  type TextMessagePart = {
    type: 'text';
    content: string;
  };

  type AppCardsMessagePart = {
    type: 'app-cards';
    content: AppCardData[];
  };

  type MessagePart = TextMessagePart | AppCardsMessagePart;

  export let messageParts: MessagePart[] = [];
  export let showScrollableContainer: boolean = false;
  export let appCards: AppCardData[] | undefined = undefined;
  export let defaultHidden: boolean = false;
  export let content: any; // Tiptap JSON content

  // If appCards is provided, add it to messageParts
  $: if (appCards && (!messageParts || messageParts.length === 0)) {
    messageParts = [
      { type: 'text', content: '' },
      { type: 'app-cards', content: appCards }
    ];
  }

  // Capitalize first letter of mate name
  $: displayName = role === 'user' ? '' : role.charAt(0).toUpperCase() + role.slice(1);

  // Add new prop for animation control
  export let animated: boolean = false;

  /**
   * Converts a message object into its final markdown representation.
   * The generated markdown is logged to the console.
   *
   * @param messageParts - The message parts to convert.
   * @returns The markdown string.
   */
  function createMarkdown(messageParts: MessagePart[]): string {
    let markdown = "";
    // Iterate over each part of the message.
    if (Array.isArray(messageParts)) {
      messageParts.forEach((part) => {
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
    } else {
      console.warn("messageParts is not an array:", messageParts); // Log a warning if messageParts is not an array.
    }

    // Log the final markdown.
    console.log("Final markdown:", markdown.trim());
    return markdown.trim();
  }

  // afterUpdate(() => {
  //   createMarkdown(messageParts);
  // });
</script>

<div class="chat-message">
  {#if role !== 'user'}
    <div class="mate-profile {role}"></div>
  {/if}

  <div class="message-align-{role === 'user' ? 'right' : 'left'}">
    <div class="{role === 'user' ? 'user' : 'mate'}-message-content {animated ? 'message-animated' : ''} " style="opacity: {defaultHidden ? '0' : '1'};">
      {#if role !== 'user'}
        <div class="chat-mate-name">{displayName}</div>
      {/if}

      <div class="chat-message-text">
        <ReadOnlyMessage {content} />
      </div>
    </div>
  </div>
</div>

<style>
  .chat-app-cards-container {
    display: flex;
    gap: 20px;
    margin-top: 15px;
  }

  .chat-app-cards-container.scrollable {
    overflow-x: auto;
    padding-bottom: 15px;
    /* Enable smooth scrolling */
    scroll-behavior: smooth;
    /* Hide scrollbar but keep functionality */
    scrollbar-width: none;
    -ms-overflow-style: none;
  }

  .chat-app-cards-container.scrollable::-webkit-scrollbar {
    display: none;
  }

  .text-content {
    margin-bottom: 15px;
    white-space: pre-line;
  }

  /* Remove margin from last text content */
  .text-content:last-child {
    margin-bottom: 0;
  }

  /* Adjust line breaks to have a more natural spacing */
  :global(.text-content br) {
    display: block;
    content: "";
    margin-top: 0.25em;
  }
</style>