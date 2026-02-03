<script lang="ts">
  import type { SvelteComponent } from 'svelte';
  import { onMount } from 'svelte';
  import { fade } from 'svelte/transition';
  // Removed afterUpdate import for runes mode compatibility
  import ReadOnlyMessage from './ReadOnlyMessage.svelte';
  import ThinkingSection from './ThinkingSection.svelte';
  import EmbedContextMenu from './embeds/EmbedContextMenu.svelte';
  import MessageContextMenu from './chats/MessageContextMenu.svelte';
  // Legacy embed nodes import removed - now using unified embed system
  import CodeFullscreen from './fullscreen_previews/CodeFullscreen.svelte';
  import Icon from './Icon.svelte';
  import type { MessageStatus, MessageRole } from '../types/chat';
  import { text, settingsDeepLink, panelState } from '@repo/ui'; // For translations
  import { reportIssueStore } from '../stores/reportIssueStore';
  import { messageHighlightStore } from '../stores/messageHighlightStore';
  import { isPublicChat } from '../demo_chats/convertToChat';
  import { chatDB } from '../services/db';
  import { uint8ArrayToUrlSafeBase64 } from '../services/cryptoService';
  import { generateShareKeyBlob } from '../services/shareEncryption';
  import type { AppSettingsMemoriesResponseContent, AppSettingsMemoriesResponseCategory } from '../services/chatSyncServiceHandlersAppSettings';
  import { appSkillsStore } from '../stores/appSkillsStore';
  
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
    model_name = undefined,
    status = undefined,
    messageParts = [],
    appCards = undefined,
    defaultHidden = false,
    content,
    animated = false,
    is_truncated = false,
    original_message = null,
    containerWidth = 0,
    _embedUpdateTimestamp = 0,
    appSettingsMemoriesResponse = undefined,
    // Thinking/Reasoning props for thinking models (Gemini, Anthropic Claude, etc.)
    thinkingContent = undefined,
    isThinkingStreaming = false
  }: {
    role?: MessageRole;
    category?: string;
    sender_name?: string;
    model_name?: string;
    status?: MessageStatus;
    messageParts?: MessagePart[];
    appCards?: AppCardData[];
    defaultHidden?: boolean;
    content: any;
    animated?: boolean;
    is_truncated?: boolean;
    original_message?: any;
    containerWidth?: number;
    _embedUpdateTimestamp?: number; // Used to force re-render when embed data becomes available
    appSettingsMemoriesResponse?: AppSettingsMemoriesResponseContent; // Response to user's app settings/memories request (passed from ChatHistory)
    // Thinking/Reasoning props for thinking models (Gemini, Anthropic Claude, etc.)
    thinkingContent?: string; // Decrypted thinking content
    isThinkingStreaming?: boolean; // Whether thinking is currently streaming
  } = $props();
  
  // State for thinking section expansion
  let thinkingExpanded = $state(false);
  
  /**
   * Get display name for an app settings/memories category.
   * Loads from app metadata using appId and itemType.
   * Returns the translated name if available, otherwise a formatted fallback.
   */
  function getCategoryDisplayName(cat: AppSettingsMemoriesResponseCategory): string {
    const app = appSkillsStore.apps[cat.appId];
    if (app?.settings_and_memories) {
      const category = app.settings_and_memories.find(sm => sm.id === cat.itemType);
      if (category?.name_translation_key) {
        // Use the translation key to get localized name
        // Ensure the key ends with .text as required
        const translationKey = category.name_translation_key.endsWith('.text') 
          ? category.name_translation_key 
          : `${category.name_translation_key}.text`;
        const translated = $text(translationKey);
        if (translated && translated !== translationKey) {
          return translated;
        }
      }
    }
    // Fallback: format itemType as readable string (e.g., "preferred_technologies" -> "Preferred Technologies")
    return cat.itemType.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
  }

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
  let selectedAppId = $state<string | null>(null);
  let selectedSkillId = $state<string | null>(null);

  // Message context menu state
  let showMessageMenu = $state(false);
  let messageMenuX = $state(0);
  let messageMenuY = $state(0);
  let selectable = $state(false);
  let readOnlyMessageComponent = $state<ReturnType<typeof ReadOnlyMessage>>();
  let messageContentElement = $state<HTMLElement>();

  // State for report button hover
  let isReportHovered = $state(false);

  // State for message highlighting
  let isHighlighted = $state(false);

  // Handle message highlighting
  $effect(() => {
    if (original_message?.message_id && $messageHighlightStore === original_message.message_id) {
      isHighlighted = true;
      // Clear highlight after 3 seconds
      const timer = setTimeout(() => {
        isHighlighted = false;
        messageHighlightStore.set(null);
      }, 3000);
      return () => clearTimeout(timer);
    }
  });

  /**
   * Handle reporting a bad answer
   */
  async function handleReportBadAnswer() {
    if (!original_message) return;

    const chatId = original_message.chat_id;
    const messageId = original_message.message_id;

    // Construct the share chat URL (not direct chat access)
    let link = `${window.location.origin}/share/chat/${chatId}`;

    // For non-public chats (real user chats), we MUST include the encryption key
    // so the server admin can decrypt the entire chat to investigate the quality issue.
    if (!isPublicChat(chatId)) {
      try {
        // Get the chat key and convert to base64 format expected by generateShareKeyBlob
        const chatKey = chatDB.getChatKey(chatId);
        if (chatKey) {
          let chatKeyBase64: string;
          if (chatKey instanceof Uint8Array) {
            chatKeyBase64 = btoa(String.fromCharCode(...chatKey));
          } else if (typeof chatKey === 'string') {
            chatKeyBase64 = chatKey;
          } else {
            throw new Error('Unexpected chat key format');
          }

          // Generate a proper share key blob (no expiration, no password for reporting)
          const encryptedBlob = await generateShareKeyBlob(chatId, chatKeyBase64, 0, undefined);

          // Include message ID for highlighting/scrolling to the reported message
          link += `#key=${encryptedBlob}&messageid=${messageId}`;
          console.debug(`[ChatMessage] Generated encrypted share blob and included message ID in report link for real user chat ${chatId}`);
        } else {
          console.warn(`[ChatMessage] Could not find encryption key for real user chat ${chatId} during report`);
        }
      } catch (error) {
        console.error(`[ChatMessage] Error generating share key blob for chat ${chatId}:`, error);
      }
    } else {
      // For public chats, still include message ID for highlighting
      link += `#messageid=${messageId}`;
      console.debug(`[ChatMessage] Included message ID in public chat report link for ${chatId}`);
    }

    const template = $text('chat.report_bad_answer.template.text', { values: { link } });
    const title = $text('chat.report_bad_answer.title.text');

    reportIssueStore.set({
      title: title,
      description: template
    });

    settingsDeepLink.set('report_issue');
    panelState.openSettings();
  }

  /**
   * Deactivates selection mode and clears browser selection
   */
  function deactivateSelection() {
    if (!selectable) return;
    
    selectable = false;
    const selection = window.getSelection();
    if (selection) {
      selection.removeAllRanges();
    }
    console.debug('[ChatMessage] Selection mode deactivated');
  }

  /**
   * Global click handler to detect clicks outside the selectable message
   */
  function handleGlobalClick(event: MouseEvent | TouchEvent) {
    if (!selectable || !messageContentElement) return;

    const target = event.target as Node;
    if (!messageContentElement.contains(target)) {
      deactivateSelection();
    }
  }

  /**
   * Handle context menu (right-click) for the entire message bubble
   */
  function handleMessageContextMenu(event: MouseEvent) {
    // Only show if not clicking on an embed (embeds have their own menu)
    const target = event.target as HTMLElement;
    if (target.closest('[data-embed-id], [data-code-embed], .preview-container, a, .mate-mention')) {
      return;
    }

    // CRITICAL: If selection mode is active and there is a selection, allow browser context menu
    // This allows users to use browser's native Copy/Look up for selected text
    if (selectable) {
      const selection = window.getSelection();
      if (selection && selection.toString().length > 0) {
        // Selection exists, don't prevent default, don't show custom menu
        return;
      }
    }

    event.preventDefault();
    event.stopPropagation();
    
    messageMenuX = event.clientX;
    messageMenuY = event.clientY;
    showMessageMenu = true;
    console.debug('[ChatMessage] Message context menu triggered (right-click)');
  }

  /**
   * Handle keyboard interaction for the message bubble
   */
  function handleMessageKeyDown(event: KeyboardEvent) {
    if (event.key === 'Enter' || event.key === ' ') {
      // Don't trigger if already focusing an interactive element
      const target = event.target as HTMLElement;
      if (target.closest('[data-embed-id], [data-code-embed], .preview-container, a, .mate-mention, button')) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();

      // Show menu at the center of the element for keyboard users
      if (messageContentElement) {
        const rect = messageContentElement.getBoundingClientRect();
        messageMenuX = rect.left + rect.width / 2;
        messageMenuY = rect.top + rect.height / 2;
        showMessageMenu = true;
      }
    }
  }

  // Touch handling for long-press on message bubble
  const LONG_PRESS_DURATION = 500;
  const TOUCH_MOVE_THRESHOLD = 10;
  let messageTouchTimer: ReturnType<typeof setTimeout> | null = null;
  let messageTouchStartX = 0;
  let messageTouchStartY = 0;

  function handleMessageTouchStart(event: TouchEvent) {
    // Only handle single touch
    if (event.touches.length !== 1) {
      clearMessageTouchTimer();
      return;
    }

    // Don't trigger if touching an embed
    const target = event.target as HTMLElement;
    if (target.closest('[data-embed-id], [data-code-embed], .preview-container, a, .mate-mention')) {
      return;
    }

    // CRITICAL: If selection mode is active, don't trigger our custom long-press context menu.
    // This allows the native mobile selection handles and context menu to work normally.
    if (selectable) {
      return;
    }

    const touch = event.touches[0];
    messageTouchStartX = touch.clientX;
    messageTouchStartY = touch.clientY;

    messageTouchTimer = setTimeout(() => {
      messageMenuX = messageTouchStartX;
      messageMenuY = messageTouchStartY;
      showMessageMenu = true;
      
      console.debug('[ChatMessage] Message long-pressed');
      
      if (navigator.vibrate) {
        navigator.vibrate(50);
      }
      messageTouchTimer = null;
    }, LONG_PRESS_DURATION);
  }

  function handleMessageTouchMove(event: TouchEvent) {
    if (!messageTouchTimer) return;
    
    const touch = event.touches[0];
    const deltaX = Math.abs(touch.clientX - messageTouchStartX);
    const deltaY = Math.abs(touch.clientY - messageTouchStartY);

    if (deltaX > TOUCH_MOVE_THRESHOLD || deltaY > TOUCH_MOVE_THRESHOLD) {
      clearMessageTouchTimer();
    }
  }

  function handleMessageTouchEnd() {
    clearMessageTouchTimer();
  }

  function clearMessageTouchTimer() {
    if (messageTouchTimer) {
      clearTimeout(messageTouchTimer);
      messageTouchTimer = null;
    }
  }

  // Removed handleMessageClick to avoid intrusive menu on tap

  /**
   * Copies the full message content to clipboard, or selected text if available
   */
  async function handleCopyMessage() {
    try {
      let contentToCopy: string;
      const selection = window.getSelection();
      
      // If there's a selection and it's within this message, copy only the selection
      if (selectable && selection && selection.toString().length > 0) {
        contentToCopy = selection.toString();
        console.debug('[ChatMessage] Copying selected text');
      } else {
        // Otherwise copy the full message content
        contentToCopy = typeof original_message?.content === 'string' 
          ? original_message.content 
          : JSON.stringify(content);
        console.debug('[ChatMessage] Copying full message content');
      }
        
      await navigator.clipboard.writeText(contentToCopy);
      
      const { notificationStore } = await import('../stores/notificationStore');
      notificationStore.success(
        selectable && selection && selection.toString().length > 0
          ? 'Selected text copied to clipboard'
          : 'Message copied to clipboard'
      );
    } catch (error) {
      console.error('[ChatMessage] Failed to copy message:', error);
    }
  }

  function handleSelectMessage() {
    selectable = true;
    // Call selectAt on the ReadOnlyMessage component with the menu coordinates
    if (readOnlyMessageComponent) {
      readOnlyMessageComponent.selectAt(messageMenuX, messageMenuY);
    }
  }

  // Final cleanup of any pre-existing handlers in template to avoid double calls
  // The logic is now correctly attached programmatically in onMount

  onMount(() => {
    document.addEventListener('mousedown', handleGlobalClick);
    document.addEventListener('touchstart', handleGlobalClick);
    
    const el = messageContentElement;
    if (el) {
      // ONLY attach keydown, remove click to avoid intrusive menu on tap
      el.addEventListener('keydown', handleMessageKeyDown as any);
    }

    return () => {
      document.removeEventListener('mousedown', handleGlobalClick);
      document.removeEventListener('touchstart', handleGlobalClick);
      if (el) {
        el.removeEventListener('keydown', handleMessageKeyDown as any);
      }
    };
  });

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
    selectedAppId = appId;
    selectedSkillId = skillId;
    
    // Determine menu type and embed type based on embed type
    if (node.type.name === 'embed') {
      // Code embeds can have different type values: 'code', 'code-code', 'code-block', 'code-code-group'
      const isCodeEmbed = node.attrs.type === 'code' || 
                          node.attrs.type === 'code-code' || 
                          node.attrs.type === 'code-block' || 
                          node.attrs.type?.startsWith('code-code');
      if (isCodeEmbed) {
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
      } else if (node.attrs.type === 'app-skill-use' && appId === 'web' && skillId === 'search') {
        // Web search skill embed
        menuType = 'web';
        embedType = 'default';
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

  function getEmbedIdFromNode(node: any): string | null {
    const raw = node?.attrs?.id || node?.attrs?.embed_id || node?.attrs?.embedId || node?.attrs?.contentRef;
    if (!raw) return null;
    if (typeof raw === 'string' && raw.startsWith('embed:')) return raw.replace('embed:', '');
    if (typeof raw === 'string') return raw;
    return null;
  }

  function inferEmbedShareType(): string {
    // Prefer app/skill detection for app-skill-use embeds
    if (selectedAppId === 'videos' && selectedSkillId === 'get_transcript') return 'video-transcript';
    if (selectedAppId === 'web' && selectedSkillId === 'search') return 'web_search';

    const type = selectedNode?.attrs?.type;
    if (type === 'website' || type === 'website-group') return 'website';
    if (type === 'videos-video') return 'video';
    // Code embeds can have different type values
    if (type === 'code' || type === 'code-code' || type === 'code-block' || type?.startsWith('code-code')) return 'code';
    if (type === 'pdf') return 'pdf';
    return type || 'embed';
  }

  async function openEmbedShareSettings(embedContext: any) {
    const { navigateToSettings } = await import('../stores/settingsNavigationStore');
    const { settingsDeepLink } = await import('../stores/settingsDeepLinkStore');
    const { panelState } = await import('../stores/panelStateStore');

    (window as unknown as { __embedShareContext?: unknown }).__embedShareContext = embedContext;

    const shareTitle =
      embedContext.type === 'web_search' ? 'Share Web Search' :
      embedContext.type === 'website' ? 'Share Website' :
      embedContext.type === 'video-transcript' ? 'Share Video Transcript' :
      embedContext.type === 'video' ? 'Share Video' :
      embedContext.type === 'code' ? 'Share Code' :
      'Share Embed';

    navigateToSettings('shared/share', shareTitle, 'share', 'settings.share.share_embed.text');
    settingsDeepLink.set('shared/share');
    panelState.openSettings();
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

    if (action === 'share') {
      const embedId = getEmbedIdFromNode(selectedNode);
      if (!embedId) {
        console.warn('[ChatMessage] No embed ID found for share action');
        const { notificationStore } = await import('../stores/notificationStore');
        notificationStore.error('Unable to share this embed. Missing embed ID.');
        showMenu = false;
        selectedNode = null;
        return;
      }

      try {
        const shareType = inferEmbedShareType();
        const embedContext: any = { type: shareType, embed_id: embedId };

        // Best-effort metadata for nicer header display in SettingsShare
        if (shareType === 'website' || shareType === 'video') {
          embedContext.url = selectedNode.attrs?.url;
          embedContext.title = selectedNode.attrs?.title;
        } else if (shareType === 'code') {
          embedContext.filename = selectedNode.attrs?.filename;
          embedContext.language = selectedNode.attrs?.language;
          embedContext.lineCount = selectedNode.attrs?.lineCount;
          embedContext.title = selectedNode.attrs?.filename;
        }

        await openEmbedShareSettings(embedContext);
      } catch (error) {
        console.error('[ChatMessage] Error opening share settings:', error);
        const { notificationStore } = await import('../stores/notificationStore');
        notificationStore.error('Failed to open share menu. Please try again.');
      } finally {
        showMenu = false;
        selectedNode = null;
      }

      return;
    }

    // Handle actions for code embeds
    // Code embeds can have different type values: 'code', 'code-code', 'code-block', etc.
    const isCodeEmbed = selectedNode.attrs.type === 'code' || 
                        selectedNode.attrs.type === 'code-code' || 
                        selectedNode.attrs.type === 'code-block' || 
                        selectedNode.attrs.type?.startsWith('code-code');
    if (menuType === 'code' && selectedNode.type.name === 'embed' && isCodeEmbed) {
      const embedId = getEmbedIdFromNode(selectedNode);

      try {
        let code = selectedNode.attrs?.code || '';
        let language = selectedNode.attrs?.language || 'text';
        let filename = selectedNode.attrs?.filename;

        // Prefer resolving the embed by ID when available (source of truth)
        if (embedId) {
          const { resolveEmbed, decodeToonContent } = await import('../services/embedResolver');
          const embedData = await resolveEmbed(embedId);
          if (embedData?.content) {
            const decodedContent = await decodeToonContent(embedData.content);
            code = decodedContent?.code || code;
            language = decodedContent?.language || language;
            filename = decodedContent?.filename || filename;
          }
        }

        switch (action) {
          case 'copy': {
            if (!code) break;
            await navigator.clipboard.writeText(code);
            const { notificationStore } = await import('../stores/notificationStore');
            notificationStore.success('Code copied to clipboard');
            break;
          }
          case 'download': {
            if (!code) break;
            const { downloadCodeFile } = await import('../services/zipExportService');
            await downloadCodeFile(code, language, filename);
            const { notificationStore } = await import('../stores/notificationStore');
            notificationStore.success('Code file downloaded successfully');
            break;
          }
        }
      } catch (error) {
        console.error('[ChatMessage] Error handling code action:', error);
        const { notificationStore } = await import('../stores/notificationStore');
        notificationStore.error('Failed to perform action');
      } finally {
        showMenu = false;
        selectedNode = null;
      }

      return;
    }

    // Handle actions for web search embeds
    if (menuType === 'web' && selectedNode.type.name === 'embed' && selectedNode.attrs.type === 'app-skill-use') {
      const embedId = getEmbedIdFromNode(selectedNode);
      if (!embedId) {
        console.warn('[ChatMessage] No embed ID found for web search embed');
        showMenu = false;
        selectedNode = null;
        return;
      }

      try {
        const { resolveEmbed, decodeToonContent } = await import('../services/embedResolver');
        const embedData = await resolveEmbed(embedId);
        if (!embedData?.content) return;

        const decodedContent = await decodeToonContent(embedData.content);
        const query = decodedContent?.query || '';
        const provider = decodedContent?.provider || 'Brave Search';
        const results = decodedContent?.results || [];

        if (action === 'copy') {
          let yaml = `query: "${query}"\n`;
          yaml += `provider: "${provider}"\n`;
          yaml += `results:\n`;

          results.forEach((result: any) => {
            yaml += `  - title: "${(result.title || '').replace(/"/g, '\\"')}"\n`;
            yaml += `    url: "${(result.url || '').replace(/"/g, '\\"')}"\n`;
            if (result.snippet) {
              yaml += `    snippet: "${String(result.snippet).replace(/"/g, '\\"')}"\n`;
            }
          });

          await navigator.clipboard.writeText(yaml);
          const { notificationStore } = await import('../stores/notificationStore');
          notificationStore.success('Copied to clipboard');
        }
      } catch (error) {
        console.error('[ChatMessage] Error handling web search action:', error);
        const { notificationStore } = await import('../stores/notificationStore');
        notificationStore.error('Failed to perform action');
      } finally {
        showMenu = false;
        selectedNode = null;
      }

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
            // Handled by generic share handler above
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
          // Handled by generic share handler above
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
    <div 
      bind:this={messageContentElement}
      class="{role === 'user' ? 'user' : 'mate'}-message-content {animated ? 'message-animated' : ''}" 
      class:highlighted={isHighlighted}
      style="opacity: {defaultHidden ? '0' : '1'};"
      role="article"
      oncontextmenu={handleMessageContextMenu}
      ontouchstart={handleMessageTouchStart}
      ontouchmove={handleMessageTouchMove}
      ontouchend={handleMessageTouchEnd}
      ontouchcancel={handleMessageTouchEnd}
    >
      {#if role === 'assistant'}
        <div class="chat-mate-name">{displayName}</div>
      {/if}

      <div class="chat-message-text">
        <!-- Thinking Section: Displayed above message content for thinking models -->
        {#if (thinkingContent || isThinkingStreaming) && role === 'assistant'}
          <ThinkingSection
            thinkingContent={thinkingContent || ''}
            isStreaming={isThinkingStreaming}
            bind:isExpanded={thinkingExpanded}
          />
        {/if}
        
        {#if showFullMessage && fullContent}
          <ReadOnlyMessage 
              bind:this={readOnlyMessageComponent}
              content={fullContent}
              isStreaming={status === 'streaming'}
              {_embedUpdateTimestamp}
              {selectable}
              on:message-embed-click={handleEmbedClick}
          />
        {:else}
          <ReadOnlyMessage 
              bind:this={readOnlyMessageComponent}
              {content}
              isStreaming={status === 'streaming'}
              {_embedUpdateTimestamp}
              {selectable}
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
        <!-- 
          EmbedContextMenu uses callback props instead of Svelte events because
          the menu element is moved to document.body to escape stacking contexts,
          which breaks Svelte's event dispatching system.
        -->
        <EmbedContextMenu
          x={menuX}
          y={menuY}
          show={showMenu}
          embedType={embedType}
          showView={true}
          showShare={true}
          showCopy={showCopyAction}
          showDownload={showDownloadAction}
          onClose={() => {
            showMenu = false;
            selectedNode = null;
          }}
          onView={() => handleMenuAction('view')}
          onShare={() => handleMenuAction('share')}
          onCopy={() => handleMenuAction('copy')}
          onDownload={() => handleMenuAction('download')}
        />
      {/if}

      {#if showMessageMenu}
        <MessageContextMenu
          x={messageMenuX}
          y={messageMenuY}
          show={showMessageMenu}
          onClose={() => showMessageMenu = false}
          onCopy={handleCopyMessage}
          onSelect={handleSelectMessage}
        />
      {/if}
    </div>
    {#if role === 'assistant' && model_name}
      <div class="generated-by-container">
        <div class="generated-by">{$text('chat.generated_by.text', { values: { model: model_name } })}</div>
        <button 
          class="report-bad-answer-btn" 
          class:hovered={isReportHovered}
          onmouseenter={() => isReportHovered = true}
          onmouseleave={() => isReportHovered = false}
          onclick={handleReportBadAnswer}
          aria-label={$text('chat.report_bad_answer.button_text.text')}
        >
          <div class="clickable-icon icon_thumbsdown"></div>
          {#if isReportHovered}
            <span class="report-text" in:fade={{ duration: 150 }}>
              {$text('chat.report_bad_answer.button_text.text')}
            </span>
          {/if}
        </button>
      </div>
    {/if}
    {#if messageStatusText}
      <div class="message-status">
        {messageStatusText}
      </div>
    {/if}
    
    <!-- App Settings & Memories action summary (only for user messages) -->
    <!-- This data comes from system messages stored in chat history and synced across devices -->
    <!-- Display name and icon are loaded client-side from app metadata (not stored in message) -->
    {#if role === 'user' && appSettingsMemoriesResponse}
      <div class="app-settings-memories-summary">
        {#if appSettingsMemoriesResponse.action === 'included' && appSettingsMemoriesResponse.categories}
          <span class="summary-label">{$text('chat.permissions.included_summary.text') || 'Included App settings & memories'}:</span>
          <div class="summary-categories">
            {#each appSettingsMemoriesResponse.categories as cat}
              <span class="category-badge">
                <Icon 
                  name={cat.appId} 
                  type="app" 
                  size="22px"
                  noAnimation={true}
                />
                <span class="badge-text">{getCategoryDisplayName(cat)} ({cat.entryCount})</span>
              </span>
            {/each}
          </div>
        {:else if appSettingsMemoriesResponse.action === 'rejected'}
          <span class="summary-rejected">{$text('chat.permissions.rejected_summary.text') || 'Rejected App settings & memories request.'}</span>
        {/if}
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

  .generated-by {
    font-size: 14px;
    color: var(--color-grey-60);
  }

  .generated-by-container {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 6px;
    margin-left: 12px;
    margin-bottom: 10px;
  }

  .report-bad-answer-btn {
    all: unset;
    display: flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
    padding: 2px 6px;
    border-radius: 6px;
    transition: all 0.2s ease;
    color: var(--color-grey-60);
  }

  .report-bad-answer-btn:hover {
    background-color: var(--color-grey-20);
    color: var(--color-primary);
  }

  .report-bad-answer-btn .clickable-icon {
    width: 16px;
    height: 16px;
    background-color: currentColor;
  }

  .report-text {
    font-size: 12px;
    white-space: nowrap;
  }

  .mate-message-content.highlighted {
    animation: highlight-animation 3s ease-out;
  }

  @keyframes highlight-animation {
    0% {
      background-color: var(--color-primary-transparent, rgba(var(--color-primary-rgb), 0.2));
      box-shadow: 0 0 15px var(--color-primary);
    }
    70% {
      background-color: var(--color-primary-transparent, rgba(var(--color-primary-rgb), 0.2));
      box-shadow: 0 0 10px var(--color-primary);
    }
    100% {
      background-color: transparent;
      box-shadow: none;
    }
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
  
  /* App Settings & Memories Summary Styles */
  .app-settings-memories-summary {
    margin-top: 8px;
    padding: 0;
    text-align: right;
    font-size: 13px;
    color: var(--color-grey-60);
  }
  
  .summary-label {
    display: block;
    margin-bottom: 6px;
    font-weight: 500;
  }
  
  .summary-categories {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 8px;
  }
  
  .category-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: var(--color-grey-15, #f5f5f5);
    border-radius: 12px;
    padding: 4px 10px 4px 4px;
  }
  
  .badge-text {
    font-size: 12px;
    font-weight: 500;
    color: var(--color-font-primary, #000);
  }
  
  .summary-rejected {
    color: var(--color-grey-50);
    font-style: italic;
  }
  
  /* Dark mode support for app settings summary */
  @media (prefers-color-scheme: dark) {
    .category-badge {
      background: var(--color-grey-25, #2a2a2a);
    }
    
    .badge-text {
      color: var(--color-font-primary, #fff);
    }
  }
</style>
