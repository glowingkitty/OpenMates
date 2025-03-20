<script lang="ts">
  import type { SvelteComponent } from 'svelte';
  import { afterUpdate } from 'svelte';
  import ReadOnlyMessage from './ReadOnlyMessage.svelte';
  import PressAndHoldMenu from './enter_message/in_message_previews/PressAndHoldMenu.svelte';
  import * as EmbedNodes from './enter_message/extensions/embeds';
  import CodeFullscreen from './fullscreen_previews/CodeFullscreen.svelte';
  import type { MessageStatus } from '../types/chat';
  
  export let role: 'user' | string = 'user';
  export let status: MessageStatus | undefined = undefined;
  
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

  // Add menu state
  let showMenu = false;
  let menuX = 0;
  let menuY = 0;
  let menuType: 'default' | 'pdf' | 'web' = 'default';
  let selectedNode: any = null;

  // Add state for fullscreen
  let showFullscreen = false;
  let fullscreenData = {
    code: '',
    filename: '',
    language: '',
    lineCount: 0
  };

  // Handle embed menu events
  function handleEmbedClick(event: CustomEvent) {
    const { view, node, dom, rect } = event.detail;
    console.debug('[ChatMessage] Embed clicked:', { view, node, dom, rect });

    if (!dom) return;

    const container = dom.closest('.chat-message-text');
    if (!container) return;

    // Use the rect from the event for more accurate positioning
    menuX = rect.left - container.getBoundingClientRect().left + (rect.width / 2);
    menuY = rect.top - container.getBoundingClientRect().top;

    selectedNode = node;
    menuType = node.type.name === 'pdfEmbed' ? 'pdf' : 
               node.type.name === 'webPreview' ? 'web' : 
               'default';

    showMenu = true;
  }

  // Update handleMenuAction
  async function handleMenuAction(action: string) {
    if (!selectedNode) return;

    // Use the node's original handlers
    const nodeType = EmbedNodes[selectedNode.type.name];
    if (nodeType?.options?.handleAction) {
        nodeType.options.handleAction(action, selectedNode);
    }

    // Handle fullscreen for supported node types
    if (action === 'view') {
        if (selectedNode.type.name === 'codeEmbed') {
            try {
                const response = await fetch(selectedNode.attrs.src);
                const code = await response.text();
                fullscreenData = {
                    code,
                    filename: selectedNode.attrs.filename,
                    language: selectedNode.attrs.language,
                    lineCount: code.split('\n').length
                };
                showFullscreen = true;
                showMenu = false;
                selectedNode = null;
                return;
            } catch (error) {
                console.error('Error loading code content:', error);
            }
        }
        
        // Fallback to opening in new tab for other types
        if (selectedNode.attrs?.src || selectedNode.attrs?.url) {
            window.open(selectedNode.attrs.src || selectedNode.attrs.url, '_blank');
        }
    }

    // Handle other actions
    switch (action) {
        case 'download':
            if (selectedNode.attrs?.src) {
                const a = document.createElement('a');
                a.href = selectedNode.attrs.src;
                a.download = selectedNode.attrs.filename || '';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
            }
            break;
        case 'copy':
            if (selectedNode.attrs?.url || selectedNode.attrs?.src) {
                navigator.clipboard.writeText(selectedNode.attrs.url || selectedNode.attrs.src);
            }
            break;
    }

    showMenu = false;
    selectedNode = null;
  }

  // Add handler for closing fullscreen
  function handleCloseFullscreen() {
    showFullscreen = false;
  }

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
    console.debug("Final markdown:", markdown.trim());
    return markdown.trim();
  }

  // afterUpdate(() => {
  //   createMarkdown(messageParts);
  // });

  // Add reactive statement to handle status changes
  $: messageStatusText = status === 'pending' ? 'Sending...' : 
                      status === 'waiting_for_internet' ? 'Waiting to reconnect to internet...' : '';
</script>

<div class="chat-message {role}" class:pending={status === 'pending' || status === 'waiting_for_internet'}>
  {#if role !== 'user'}
    <div class="mate-profile {role}"></div>
  {/if}

  <div class="message-align-{role === 'user' ? 'right' : 'left'}">
    <div class="{role === 'user' ? 'user' : 'mate'}-message-content {animated ? 'message-animated' : ''} " style="opacity: {defaultHidden ? '0' : '1'};">
      {#if role !== 'user'}
        <div class="chat-mate-name">{displayName}</div>
      {/if}

      <div class="chat-message-text">
        <ReadOnlyMessage 
            {content} 
            on:message-embed-click={handleEmbedClick}
        />
      </div>

      {#if showMenu}
        <PressAndHoldMenu
          x={menuX}
          y={menuY}
          show={showMenu}
          type={menuType}
          isYouTube={selectedNode?.attrs?.isYouTube || false}
          hideDelete={true}
          on:close={() => {
            showMenu = false;
            selectedNode = null;
          }}
          on:view={() => handleMenuAction('view')}
          on:download={() => handleMenuAction('download')}
          on:copy={() => handleMenuAction('copy')}
        />
      {/if}
    </div>
    {#if messageStatusText}
      <div class="message-status">
        {messageStatusText}
      </div>
    {/if}
  </div>
</div>

{#if showFullscreen}
    <CodeFullscreen 
        code={fullscreenData.code}
        filename={fullscreenData.filename}
        language={fullscreenData.language}
        lineCount={fullscreenData.lineCount}
        onClose={handleCloseFullscreen}
    />
{/if}

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

  .chat-message-text {
    position: relative; /* Add this to properly position the menu */
  }

  .pending {
    opacity: 0.7;
  }

  .message-status {
    font-size: 12px;
    color: var(--color-font-tertiary);
    margin-top: 4px;
    text-align: right;
  }
</style>