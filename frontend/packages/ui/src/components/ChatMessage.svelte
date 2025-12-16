<script lang="ts">
  import type { SvelteComponent } from 'svelte';
  // Removed afterUpdate import for runes mode compatibility
  import ReadOnlyMessage from './ReadOnlyMessage.svelte';
  import EmbedContextMenu from './embeds/EmbedContextMenu.svelte';
  // Legacy embed nodes import removed - now using unified embed system
  import CodeFullscreen from './fullscreen_previews/CodeFullscreen.svelte';
  import type { MessageStatus, MessageRole } from '../types/chat';
  import { text } from '@repo/ui'; // For translations
  
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

  // All props using Svelte 5 runes mode (single $props() call)
  let { 
    role = 'user',
    category = undefined,
    sender_name = undefined,
    status = undefined,
    messageParts = [],
    appCards = undefined,
    defaultHidden = false,
    content,
    animated = false,
    is_truncated = false,
    full_content_length = 0,
    original_message = null,
    containerWidth = 0
  }: {
    role?: MessageRole;
    category?: string;
    sender_name?: string;
    status?: MessageStatus;
    messageParts?: MessagePart[];
    appCards?: AppCardData[];
    defaultHidden?: boolean;
    content: any;
    animated?: boolean;
    is_truncated?: boolean;
    full_content_length?: number;
    original_message?: any;
    containerWidth?: number;
  } = $props();

  // State for truncated message handling
  let showFullMessage = $state(false);
  let fullContent = $state(null);
  let isLoadingFullContent = $state(false);

  // Determine if we should use mobile-stacked layout based on container width
  // Breakpoint is 500px to match the original media query
  let shouldStackMobile = $derived(containerWidth > 0 && containerWidth <= 500);

  // If appCards is provided, add it to messageParts using $effect (Svelte 5 runes mode)
  $effect(() => {
    if (appCards && (!messageParts || messageParts.length === 0)) {
      messageParts = [
        { type: 'text', content: '' },
        { type: 'app-cards', content: appCards }
      ];
    }
  });

  // Determine display name for assistant messages using $derived (Svelte 5 runes mode)
  // Special handling for openmates_official category
  let displayName = $derived(role === 'user' ? '' : 
                    sender_name ? (sender_name.charAt(0).toUpperCase() + sender_name.slice(1)) : 
                    category === 'openmates_official' ? 'OpenMates' :
                    category ? $text(`mates.${category}.text`, { default: category.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) }) :
                    'Assistant');

  // animated prop is now included in the main $props() call above

  // Add menu state using $state (Svelte 5 runes mode)
  let showMenu = $state(false);
  let menuX = $state(0);
  let menuY = $state(0);
  let menuType = $state<'default' | 'pdf' | 'web' | 'video-transcript' | 'video' | 'code'>('default');
  let selectedNode = $state<any>(null);
  let embedType = $state<'code' | 'video' | 'website' | 'pdf' | 'default'>('default');

  // Add state for fullscreen using $state (Svelte 5 runes mode)
  let showFullscreen = $state(false);
  let fullscreenData = $state({
    code: '',
    filename: '',
    language: '',
    lineCount: 0
  });

  // Handle embed menu events (right-click context menu)
  function handleEmbedClick(event: CustomEvent) {
    const { view, node, dom, rect, x, y } = event.detail;
    console.debug('[ChatMessage] Embed right-clicked:', { view, node, dom, rect, x, y });

    if (!dom) return;

    // Use the actual click coordinates (x, y) for menu positioning
    // This positions the menu at the actual clicked point, not the center of the embed
    // Fallback to center if coordinates not provided (for backwards compatibility)
    menuX = x !== undefined ? x : (rect.left + (rect.width / 2));
    menuY = y !== undefined ? y : (rect.top + (rect.height / 2));

    selectedNode = node;
    
    // Detect embed type from node attributes and DOM data attributes
    // Check DOM element for data attributes first (more reliable for app-skill-use embeds)
    const appId = dom.getAttribute('data-app-id');
    const skillId = dom.getAttribute('data-skill-id');
    
    // Determine menu type and embed type based on embed type
    if (node.type.name === 'embed') {
      if (node.attrs.type === 'code') {
        menuType = 'code';
        embedType = 'code';
      } else if (node.attrs.type === 'pdf') {
        menuType = 'pdf';
        embedType = 'pdf';
      } else if (node.attrs.type === 'website' || node.attrs.type === 'website-group') {
        menuType = 'web';
        embedType = 'website';
      } else if (node.attrs.type === 'videos-video') {
        // Video embed (YouTube, etc.)
        menuType = 'video';
        embedType = 'video';
      } else if (node.attrs.type === 'app-skill-use' && appId === 'videos' && skillId === 'get_transcript') {
        // Video transcript embed
        menuType = 'video-transcript';
        embedType = 'video';
      } else {
        menuType = 'default';
        embedType = 'default';
      }
    } else {
      menuType = 'default';
      embedType = 'default';
    }

    showMenu = true;
  }

  // Update handleMenuAction to support video transcript and video embed actions
  async function handleMenuAction(action: string) {
    if (!selectedNode) return;

    // Legacy node handlers removed - now using unified embed system
    // Actions are handled directly below

    // Handle fullscreen for supported node types
    // Dispatch embedfullscreen event to open fullscreen (same as clicking the embed)
    if (action === 'view') {
        // Get embed ID from node attributes
        const embedId = selectedNode.attrs?.id || selectedNode.attrs?.contentRef?.replace('embed:', '');
        
        if (!embedId) {
            console.warn('[ChatMessage] No embed ID found for view action');
            showMenu = false;
            selectedNode = null;
            return;
        }
        
        // Map embed type to the format expected by ActiveChat
        // ActiveChat expects: 'code-code', 'videos-video', 'website', 'app-skill-use', etc.
        let fullscreenEmbedType = selectedNode.attrs?.type || selectedNode.type.name;
        
        // Normalize embed type names to match what ActiveChat expects
        if (fullscreenEmbedType === 'code') {
            fullscreenEmbedType = 'code-code';
        } else if (fullscreenEmbedType === 'videos-video') {
            fullscreenEmbedType = 'videos-video'; // Already correct
        } else if (fullscreenEmbedType === 'website' || fullscreenEmbedType === 'website-group') {
            fullscreenEmbedType = 'website';
        } else if (fullscreenEmbedType === 'app-skill-use') {
            fullscreenEmbedType = 'app-skill-use'; // Already correct
        }
        
        // Dispatch embedfullscreen event to trigger fullscreen (ActiveChat will handle it)
        // This is the same event that embeds dispatch when clicked
        // Use document.dispatchEvent (not window) to match how renderers do it
        const embedFullscreenEvent = new CustomEvent('embedfullscreen', {
            bubbles: true,
            cancelable: true,
            detail: {
                embedId,
                embedType: fullscreenEmbedType,
                attrs: selectedNode.attrs,
                embedData: null, // Will be loaded by ActiveChat if needed
                decodedContent: null // Will be loaded by ActiveChat if needed
            }
        });
        
        // Dispatch the event on document (same as renderers do)
        document.dispatchEvent(embedFullscreenEvent);
        
        console.debug('[ChatMessage] Dispatched embedfullscreen event for view action:', {
            embedId,
            embedType: fullscreenEmbedType,
            nodeType: selectedNode.type.name,
            nodeAttrs: selectedNode.attrs
        });
        
        showMenu = false;
        selectedNode = null;
        return;
    }

    // Handle actions for video transcript embeds
    if (menuType === 'video-transcript' && selectedNode.type.name === 'embed' && selectedNode.attrs.type === 'app-skill-use') {
      const embedId = selectedNode.attrs.contentRef?.replace('embed:', '');
      if (!embedId) {
        console.warn('[ChatMessage] No embed ID found for video transcript embed');
        showMenu = false;
        selectedNode = null;
        return;
      }

      try {
        // Load embed data to get transcript content
        const { resolveEmbed, decodeToonContent } = await import('../services/embedResolver');
        const embedData = await resolveEmbed(embedId);
        if (!embedData?.content) {
          console.warn('[ChatMessage] No embed data found for video transcript');
          showMenu = false;
          selectedNode = null;
          return;
        }

        const decodedContent = await decodeToonContent(embedData.content);
        const results = decodedContent.results || [];
        const firstResult = results[0] || {};
        const videoTitle = firstResult.metadata?.title || firstResult.url || 'Video Transcript';
        const videoUrl = firstResult.url || '';

        switch (action) {
          case 'copy':
            // Copy transcript as formatted markdown
            const transcriptText = results
              .filter((r: any) => r.transcript)
              .map((r: any) => {
                let content = '';
                if (r.metadata?.title) {
                  content += `# ${r.metadata.title}\n\n`;
                }
                if (r.url) {
                  content += `Source: ${r.url}\n\n`;
                }
                if (r.word_count) {
                  content += `Word count: ${r.word_count.toLocaleString()}\n\n`;
                }
                content += r.transcript || '';
                return content;
              })
              .join('\n\n---\n\n');
            
            if (transcriptText) {
              await navigator.clipboard.writeText(transcriptText);
              const { notificationStore } = await import('../stores/notificationStore');
              notificationStore.success('Transcript copied to clipboard');
            }
            break;

          case 'download':
            // Download transcript as markdown file
            const downloadText = results
              .filter((r: any) => r.transcript)
              .map((r: any) => {
                let content = '';
                if (r.metadata?.title) {
                  content += `# ${r.metadata.title}\n\n`;
                }
                if (r.url) {
                  content += `Source: ${r.url}\n\n`;
                }
                if (r.word_count) {
                  content += `Word count: ${r.word_count.toLocaleString()}\n\n`;
                }
                content += r.transcript || '';
                return content;
              })
              .join('\n\n---\n\n');
            
            if (downloadText) {
              const blob = new Blob([downloadText], { type: 'text/markdown' });
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url;
              a.download = `${videoTitle.replace(/[^a-z0-9]/gi, '_').toLowerCase()}_transcript.md`;
              document.body.appendChild(a);
              a.click();
              document.body.removeChild(a);
              URL.revokeObjectURL(url);
            }
            break;

          case 'share':
            // Share functionality (placeholder for now)
            console.debug('[ChatMessage] Share action for video transcript (not yet implemented)');
            const { notificationStore: shareNotificationStore } = await import('../stores/notificationStore');
            shareNotificationStore.info('Share functionality coming soon');
            break;
        }
      } catch (error) {
        console.error('[ChatMessage] Error handling video transcript action:', error);
        const { notificationStore } = await import('../stores/notificationStore');
        notificationStore.error('Failed to perform action');
      }
    }
    // Handle actions for video embeds
    else if (menuType === 'video' && selectedNode.type.name === 'embed' && selectedNode.attrs.type === 'videos-video') {
      const videoUrl = selectedNode.attrs.url || '';
      
      switch (action) {
        case 'copy':
          // Copy video URL to clipboard
          if (videoUrl) {
            try {
              await navigator.clipboard.writeText(videoUrl);
              const { notificationStore } = await import('../stores/notificationStore');
              notificationStore.success('Video URL copied to clipboard');
            } catch (error) {
              console.error('[ChatMessage] Failed to copy video URL:', error);
              const { notificationStore } = await import('../stores/notificationStore');
              notificationStore.error('Failed to copy URL to clipboard');
            }
          }
          break;

        case 'share':
          // Share functionality (placeholder for now)
          console.debug('[ChatMessage] Share action for video (not yet implemented)');
          const { notificationStore: shareNotificationStore } = await import('../stores/notificationStore');
          shareNotificationStore.info('Share functionality coming soon');
          break;
      }
    }
    // Handle other actions for legacy embed types
    else {
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
    }

    showMenu = false;
    selectedNode = null;
  }

  // Add handler for closing fullscreen
  function handleCloseFullscreen() {
    showFullscreen = false;
  }

  // Add reactive statement to handle status changes using $derived (Svelte 5 runes mode)
  // Note: 'processing' status is NOT shown under the message - it's shown in the typing indicator area instead
  let messageStatusText = $derived(status === 'sending' ? $text('enter_message.sending.text') :
                      status === 'waiting_for_internet' ? $text('enter_message.waiting_for_internet.text') : '');

  // Functions for handling truncated message display
  async function handleShowFullMessage() {
    if (showFullMessage || !original_message) return;
    
    isLoadingFullContent = true;
    try {
      // Import chatDB dynamically to avoid circular dependencies
      const { chatDB } = await import('../services/db');
      
      // Load full content from IndexedDB
      const fullMessage = await chatDB.getMessage(original_message.message_id);
      if (fullMessage) {
        // Convert the full markdown content to TipTap JSON with unified parsing (includes embed parsing)
        const { parse_message } = await import('../message_parsing/parse_message');
        const { preprocessTiptapJsonForEmbeds } = await import('./enter_message/utils/tiptapContentProcessor');

        const tiptapJson = parse_message(fullMessage.content, 'read', { unifiedParsingEnabled: true });
        fullContent = preprocessTiptapJsonForEmbeds(tiptapJson);
        showFullMessage = true;
      }
    } catch (error) {
      console.error('Error loading full message:', error);
    } finally {
      isLoadingFullContent = false;
    }
  }
  
  function handleHideFullMessage() {
    showFullMessage = false;
    fullContent = null;
  }
</script>

<div class="chat-message {role}" class:pending={status === 'sending' || status === 'waiting_for_internet'} class:assistant={role === 'assistant'} class:user={role === 'user'} class:mobile-stacked={role === 'assistant' && shouldStackMobile}>
  {#if role === 'assistant'}
    <!-- Use openmates_official category for official messages (shows favicon, no AI badge) -->
    <div class="mate-profile {category || 'default'}" class:mate-profile-small-mobile={shouldStackMobile}></div>
  {/if}

  <div class="message-align-{role === 'user' ? 'right' : 'left'}" class:mobile-full-width={role === 'assistant' && shouldStackMobile}>
    <div class="{role === 'user' ? 'user' : 'mate'}-message-content {animated ? 'message-animated' : ''} " style="opacity: {defaultHidden ? '0' : '1'};">
      {#if role === 'assistant'}
        <div class="chat-mate-name">{displayName}</div>
      {/if}

      <div class="chat-message-text">
        {#if showFullMessage && fullContent}
          <ReadOnlyMessage 
              content={fullContent}
              isStreaming={status === 'streaming'}
              on:message-embed-click={handleEmbedClick}
          />
        {:else}
          <ReadOnlyMessage 
              {content}
              isStreaming={status === 'streaming'}
              on:message-embed-click={handleEmbedClick}
          />
        {/if}
        
        {#if is_truncated && role === 'user'}
          <div class="message-truncation-controls">
            {#if !showFullMessage}
              <button 
                class="show-full-message-btn"
                onclick={handleShowFullMessage}
                disabled={isLoadingFullContent}
              >
                {#if isLoadingFullContent}
                  {$text('chat.loading.text')}
                {:else}
                  {$text('chat.show_full_message.text')}
                {/if}
              </button>
            {:else}
              <button 
                class="hide-full-message-btn"
                onclick={handleHideFullMessage}
              >
                {$text('chat.hide_full_message.text')}
              </button>
            {/if}
          </div>
        {/if}
      </div>

      {#if showMenu}
        {@const showCopyAction = menuType === 'code' || menuType === 'video' || menuType === 'video-transcript' || menuType === 'web'}
        {@const showDownloadAction = menuType === 'code' || menuType === 'video-transcript' || menuType === 'pdf'}
        <EmbedContextMenu
          x={menuX}
          y={menuY}
          show={showMenu}
          embedType={embedType}
          showView={true}
          showShare={true}
          showCopy={showCopyAction}
          showDownload={showDownloadAction}
          on:close={() => {
            showMenu = false;
            selectedNode = null;
          }}
          on:view={() => handleMenuAction('view')}
          on:share={() => handleMenuAction('share')}
          on:copy={() => handleMenuAction('copy')}
          on:download={() => handleMenuAction('download')}
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

  .message-truncation-controls {
    margin-top: 8px;
    text-align: center;
  }
  
  .show-full-message-btn,
  .hide-full-message-btn {
    background: none;
    border: none;
    color: var(--color-primary);
    cursor: pointer;
    font-size: 0.9em;
    text-decoration: underline;
    padding: 4px 8px;
    border-radius: 4px;
    transition: background-color 0.2s ease;
  }
  
  .show-full-message-btn:hover,
  .hide-full-message-btn:hover {
    background-color: var(--color-background-secondary);
  }
  
  .show-full-message-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
</style>
