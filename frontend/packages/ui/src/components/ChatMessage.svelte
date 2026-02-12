<script lang="ts">
  import type { SvelteComponent } from 'svelte';
  import { onMount } from 'svelte';
  import { fade } from 'svelte/transition';
  // Removed afterUpdate import for runes mode compatibility
  import ReadOnlyMessage from './ReadOnlyMessage.svelte';
  import DemoMessageContent from './DemoMessageContent.svelte';
  import ThinkingSection from './ThinkingSection.svelte';
  import EmbedContextMenu from './embeds/EmbedContextMenu.svelte';
  import MessageContextMenu from './chats/MessageContextMenu.svelte';
  // Legacy embed nodes import removed - now using unified embed system
  import CodeFullscreen from './fullscreen_previews/CodeFullscreen.svelte';
  import Icon from './Icon.svelte';
  import type { MessageStatus, MessageRole } from '../types/chat';
  import { text, settingsDeepLink, panelState } from '@repo/ui'; // For translations
  import { getModelDisplayName, getModelByNameOrId } from '../utils/modelDisplayName';
  import { reportIssueStore } from '../stores/reportIssueStore';
  import { messageHighlightStore } from '../stores/messageHighlightStore';
  import { chatDB } from '../services/db';
  import { uint8ArrayToUrlSafeBase64 } from '../services/cryptoService';
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
    hasEmbedErrors = false,
    appSettingsMemoriesResponse = undefined,
    // Thinking/Reasoning props for thinking models (Gemini, Anthropic Claude, etc.)
    thinkingContent = undefined,
    isThinkingStreaming = false,
    piiMappings = undefined,
    piiRevealed = false,
    // Message identification props (for usage/cost lookup in message context menu)
    messageId = undefined,
    userMessageId = undefined
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
    hasEmbedErrors?: boolean; // Whether any embeds in this message failed (shows error banner)
    appSettingsMemoriesResponse?: AppSettingsMemoriesResponseContent; // Response to user's app settings/memories request (passed from ChatHistory)
    // Thinking/Reasoning props for thinking models (Gemini, Anthropic Claude, etc.)
    thinkingContent?: string; // Decrypted thinking content
    isThinkingStreaming?: boolean; // Whether thinking is currently streaming
    piiMappings?: import('../types/chat').PIIMapping[]; // Cumulative PII mappings for decoration highlighting
    piiRevealed?: boolean; // Whether PII original values are visible (false = placeholders shown, true = originals shown)
    // Message identification props (for usage/cost lookup in message context menu)
    messageId?: string; // Message ID for cost lookup
    userMessageId?: string; // User message ID that triggered this response (usage records are stored with this ID)
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

  // Check if original_message content contains special placeholders (used in demo chats)
  // When present, we use DemoMessageContent for special placeholder handling
  // We check original_message.content because at this point `content` is already TipTap JSON
  // NOTE: Uses [[...]] instead of {...} to avoid ICU MessageFormat variable interpolation in svelte-i18n
  const DEMO_PLACEHOLDERS = [
    '[[example_chats_group]]',
    '[[dev_example_chats_group]]',
    '[[app_store_group]]',
    '[[skills_group]]',
    '[[focus_modes_group]]',
    '[[settings_memories_group]]',
    '[[dev_app_store_group]]',
    '[[dev_skills_group]]',
    '[[dev_focus_modes_group]]',
    '[[dev_settings_memories_group]]',
    '[[for_developers_embed]]',
  ];
  let hasExampleChatsPlaceholder = $derived((() => {
    const originalContent = original_message?.content;
    if (typeof originalContent === 'string') {
      return DEMO_PLACEHOLDERS.some(p => originalContent.includes(p));
    }
    return false;
  })());
  
  // Get the original markdown content (for DemoMessageContent which needs the raw markdown)
  let originalMarkdownContent = $derived(
    typeof original_message?.content === 'string' ? original_message.content : ''
  );
  
  // Get the chat ID from the original message (needed for ExampleChatsGroup exclusion)
  let currentChatId = $derived(original_message?.chat_id || 'demo-for-everyone');

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
  let menuType = $state<'default' | 'pdf' | 'web' | 'video-transcript' | 'video' | 'code' | 'focusMode'>('default');
  let selectedNode = $state<any>(null);
  let embedType = $state<'code' | 'video' | 'website' | 'pdf' | 'focusMode' | 'default'>('default');
  let selectedAppId = $state<string | null>(null);
  let selectedSkillId = $state<string | null>(null);
  let selectedFocusId = $state<string | null>(null);
  let selectedFocusModeName = $state<string | null>(null);

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
   * Handle reporting a bad answer.
   * Pre-fills the report issue form with context and enables the "share chat" toggle
   * so the admin can access the full chat for investigation.
   */
  function handleReportBadAnswer() {
    if (!original_message) return;

    const title = $text('chat.report_bad_answer.title.text');

    reportIssueStore.set({
      title: title,
      shareChat: true
    });

    settingsDeepLink.set('report_issue');
    panelState.openSettings();
    
    // Paste a translated retry prompt into the message input so the user can
    // immediately ask the assistant to try again with web search / app skills.
    const retryText = $text('chat.report_bad_answer.retry_message.text');
    if (retryText) {
      window.dispatchEvent(new CustomEvent('setRetryMessage', { detail: { text: retryText } }));
    }
  }

  /**
   * Opens the report issue settings page pre-filled with context about a failed embed/skill.
   * Enables the "share chat" toggle so the admin can investigate.
   */
  function handleReportEmbedError() {
    if (!original_message) return;

    reportIssueStore.set({
      title: 'App skill processing error',
      shareChat: true
    });

    settingsDeepLink.set('report_issue');
    panelState.openSettings();
  }

  /**
   * Navigate to the AI Ask model details page in the app store settings.
   * Resolves the model_name (display name or ID) to its model ID for deep linking.
   */
  function handleGeneratedByClick() {
    if (!model_name) return;
    const modelMeta = getModelByNameOrId(model_name);
    if (modelMeta) {
      // Deep link to the model details page in the AI Ask skill settings
      settingsDeepLink.set(`app_store/ai/skill/ask/model/${modelMeta.id}`);
      panelState.openSettings();
    }
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
   * Copies the full message content to clipboard, or selected text if available.
   * Respects PII visibility state: when PII is hidden, placeholders are used
   * instead of original values in the copied content.
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
        // original_message.content has PLACEHOLDERS (raw from DB).
        // When PII is revealed, we need to restore originals for the user.
        // When PII is hidden, the raw content already has placeholders — use as-is.
        contentToCopy = typeof original_message?.content === 'string' 
          ? original_message.content 
          : JSON.stringify(content);
        
        if (piiRevealed && piiMappings && piiMappings.length > 0) {
          // Revealed mode: user wants originals — restore placeholders → originals
          const { restorePIIInText } = await import('./enter_message/services/piiDetectionService');
          contentToCopy = restorePIIInText(contentToCopy, piiMappings);
          console.debug('[ChatMessage] Restored PII originals for copy (revealed mode)');
        } else {
          console.debug('[ChatMessage] Copying message with placeholders (hidden mode)');
        }
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
    const focusIdAttr = dom.getAttribute('data-focus-id');
    const focusModeNameAttr = dom.getAttribute('data-focus-mode-name');
    const embedTypeAttr = dom.getAttribute('data-embed-type');
    selectedAppId = appId;
    selectedSkillId = skillId;
    selectedFocusId = focusIdAttr;
    selectedFocusModeName = focusModeNameAttr;
    
    // Determine menu type and embed type based on embed type
    if (node.type.name === 'embed') {
      // Focus mode activation embed
      if (node.attrs.type === 'focus-mode-activation' || embedTypeAttr === 'focus-mode-activation') {
        menuType = 'focusMode';
        embedType = 'focusMode';
      // Code embeds can have different type values: 'code', 'code-code', 'code-block', 'code-code-group'
      } else if (node.attrs.type === 'code' || 
                          node.attrs.type === 'code-code' || 
                          node.attrs.type === 'code-block' || 
                          node.attrs.type?.startsWith('code-code')) {
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
      } else if (node.attrs.type === 'app-skill-use') {
        // App skill embeds - determine menu type based on appId/skillId
        if (appId === 'videos' && skillId === 'get_transcript') {
          menuType = 'video-transcript';
          embedType = 'video';
        } else if (appId === 'web' && skillId === 'search') {
          menuType = 'web';
          embedType = 'default';
        } else {
          // All other app-skill-use embeds: use appId-skillId as menuType
          // This enables context-menu actions based on the specific app/skill combination
          menuType = 'default';
          embedType = 'default';
        }
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

    // Handle actions for focus mode embeds
    if (menuType === 'focusMode') {
      if (action === 'deactivate') {
        console.debug('[ChatMessage] Focus mode deactivation requested via context menu:', selectedFocusId);
        // Dispatch deactivation event (handled by ActiveChat or a global listener)
        document.dispatchEvent(
          new CustomEvent('focusModeDeactivated', {
            bubbles: true,
            detail: {
              focusId: selectedFocusId,
              appId: selectedAppId,
              focusModeName: selectedFocusModeName,
            },
          }),
        );
      } else if (action === 'details') {
        console.debug('[ChatMessage] Focus mode details requested via context menu:', selectedFocusId);
        // Navigate to the focus mode details page in settings / app store
        document.dispatchEvent(
          new CustomEvent('focusModeDetailsRequested', {
            bubbles: true,
            detail: {
              focusId: selectedFocusId,
              appId: selectedAppId,
            },
          }),
        );
      }

      showMenu = false;
      selectedNode = null;
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
    // Handle actions for app-skill-use embeds based on appId/skillId
    // These handlers cover all app skills that support copy/download from the context menu
    else if (selectedNode.type.name === 'embed' && selectedNode.attrs.type === 'app-skill-use' && selectedAppId) {
      const embedId = getEmbedIdFromNode(selectedNode);
      if (!embedId) {
        console.warn('[ChatMessage] No embed ID found for app-skill-use embed action');
        showMenu = false;
        selectedNode = null;
        return;
      }

      try {
        const { resolveEmbed, decodeToonContent } = await import('../services/embedResolver');
        const embedData = await resolveEmbed(embedId);
        if (!embedData?.content) {
          console.warn('[ChatMessage] No embed data found for app-skill-use embed:', embedId);
          showMenu = false;
          selectedNode = null;
          return;
        }
        const decodedContent = typeof embedData.content === 'string'
          ? await decodeToonContent(embedData.content)
          : embedData.content as Record<string, unknown>;
        if (!decodedContent) {
          console.warn('[ChatMessage] Failed to decode content for embed:', embedId);
          showMenu = false;
          selectedNode = null;
          return;
        }

        // --- Images: download original image with prompt-based filename and metadata ---
        if (selectedAppId === 'images' && action === 'download') {
          const files = decodedContent.files as { original?: { s3_key: string; format?: string } } | undefined;
          const s3BaseUrl = decodedContent.s3_base_url as string | undefined;
          const aesKey = decodedContent.aes_key as string | undefined;
          const aesNonce = decodedContent.aes_nonce as string | undefined;
          const imagePrompt = decodedContent.prompt as string | undefined;
          const imageModel = decodedContent.model as string | undefined;
          const imageGeneratedAt = decodedContent.generated_at as string | undefined;

          if (files?.original?.s3_key && s3BaseUrl && aesKey && aesNonce) {
            try {
              const { fetchAndDecryptImage } = await import('./embeds/images/imageEmbedCrypto');
              const { generateImageFilename, embedPngMetadata } = await import('./embeds/images/imageDownloadUtils');
              const blob = await fetchAndDecryptImage(
                s3BaseUrl,
                files.original.s3_key,
                aesKey,
                aesNonce
              );
              const ext = files.original.format || 'png';
              
              // Embed PNG tEXt metadata (prompt, model, software) for file manager visibility
              let downloadBlob: Blob = blob;
              if (ext === 'png') {
                const arrayBuffer = await blob.arrayBuffer();
                const metadataBytes = embedPngMetadata(arrayBuffer, {
                  prompt: imagePrompt,
                  model: imageModel,
                  software: 'OpenMates',
                  generatedAt: imageGeneratedAt
                });
                // Copy into a plain ArrayBuffer to satisfy BlobPart typing
                const ab = new ArrayBuffer(metadataBytes.byteLength);
                new Uint8Array(ab).set(metadataBytes);
                downloadBlob = new Blob([ab], { type: 'image/png' });
              }
              
              const filename = generateImageFilename(imagePrompt, ext);
              
              const url = URL.createObjectURL(downloadBlob);
              const a = document.createElement('a');
              a.href = url;
              a.download = filename;
              document.body.appendChild(a);
              a.click();
              document.body.removeChild(a);
              URL.revokeObjectURL(url);
              const { notificationStore } = await import('../stores/notificationStore');
              notificationStore.success('Image downloaded');
            } catch (err) {
              console.error('[ChatMessage] Error downloading image:', err);
              const { notificationStore } = await import('../stores/notificationStore');
              notificationStore.error('Failed to download image');
            }
          } else {
            const { notificationStore } = await import('../stores/notificationStore');
            notificationStore.error('Original image not available');
          }
        }

        // --- Docs: copy (plain text) or download (docx) ---
        else if (selectedAppId === 'docs') {
          const htmlContent = (decodedContent.html as string) || '';
          const docTitle = (decodedContent.title as string) || '';
          const docFilename = (decodedContent.filename as string) || docTitle || 'document';

          if (action === 'copy') {
            // Strip HTML to plain text
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = htmlContent;
            const plainText = tempDiv.textContent || tempDiv.innerText || '';
            if (plainText) {
              await navigator.clipboard.writeText(plainText);
              const { notificationStore } = await import('../stores/notificationStore');
              notificationStore.success('Document copied to clipboard');
            }
          } else if (action === 'download') {
            try {
              const { asBlob } = await import('html-docx-js-typescript');
              const fullHtml = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${docTitle}</title></head><body>${htmlContent}</body></html>`;
              const blob = await asBlob(fullHtml) as Blob;
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url;
              a.download = docFilename.endsWith('.docx') ? docFilename : `${docFilename}.docx`;
              document.body.appendChild(a);
              a.click();
              document.body.removeChild(a);
              URL.revokeObjectURL(url);
              const { notificationStore } = await import('../stores/notificationStore');
              notificationStore.success('Document downloaded');
            } catch (err) {
              console.error('[ChatMessage] Error downloading document:', err);
              const { notificationStore } = await import('../stores/notificationStore');
              notificationStore.error('Failed to download document');
            }
          }
        }

        // --- Sheets: copy (CSV or markdown) or download (CSV) ---
        else if (selectedAppId === 'sheets') {
          const tableContent = (decodedContent.code as string) || (decodedContent.table as string) || '';
          const sheetTitle = (decodedContent.title as string) || 'table';

          if (action === 'copy') {
            // Copy as CSV format for easy pasting into spreadsheet apps
            if (tableContent) {
              // Convert markdown table to CSV
              const lines = tableContent.split('\n').filter((l: string) => l.trim() && !l.trim().match(/^[\s|:-]+$/));
              const csv = lines.map((line: string) =>
                line.split('|')
                  .map((cell: string) => cell.trim())
                  .filter((cell: string) => cell !== '')
                  .map((cell: string) => `"${cell.replace(/"/g, '""')}"`)
                  .join(',')
              ).join('\n');
              await navigator.clipboard.writeText(csv);
              const { notificationStore } = await import('../stores/notificationStore');
              notificationStore.success('Table copied as CSV');
            }
          } else if (action === 'download') {
            if (tableContent) {
              const lines = tableContent.split('\n').filter((l: string) => l.trim() && !l.trim().match(/^[\s|:-]+$/));
              const csv = lines.map((line: string) =>
                line.split('|')
                  .map((cell: string) => cell.trim())
                  .filter((cell: string) => cell !== '')
                  .map((cell: string) => `"${cell.replace(/"/g, '""')}"`)
                  .join(',')
              ).join('\n');
              const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url;
              a.download = `${sheetTitle.replace(/[^a-z0-9]/gi, '_').toLowerCase()}.csv`;
              document.body.appendChild(a);
              a.click();
              document.body.removeChild(a);
              URL.revokeObjectURL(url);
              const { notificationStore } = await import('../stores/notificationStore');
              notificationStore.success('Table downloaded as CSV');
            }
          }
        }

        // --- Web Read: copy article text ---
        else if (selectedAppId === 'web' && selectedSkillId === 'read' && action === 'copy') {
          const results = (decodedContent.results as Array<{ markdown?: string; title?: string; url?: string }>) || [];
          const textParts = results.map(r => {
            let part = '';
            if (r.title) part += `# ${r.title}\n\n`;
            if (r.url) part += `Source: ${r.url}\n\n`;
            if (r.markdown) part += r.markdown;
            return part;
          }).filter(Boolean);
          if (textParts.length > 0) {
            await navigator.clipboard.writeText(textParts.join('\n\n---\n\n'));
            const { notificationStore } = await import('../stores/notificationStore');
            notificationStore.success('Article copied to clipboard');
          }
        }

        // --- News Read: copy article text ---
        else if (selectedAppId === 'news' && selectedSkillId === 'read' && action === 'copy') {
          const results = (decodedContent.results as Array<{ markdown?: string; title?: string; url?: string }>) || [];
          const textParts = results.map(r => {
            let part = '';
            if (r.title) part += `# ${r.title}\n\n`;
            if (r.url) part += `Source: ${r.url}\n\n`;
            if (r.markdown) part += r.markdown;
            return part;
          }).filter(Boolean);
          if (textParts.length > 0) {
            await navigator.clipboard.writeText(textParts.join('\n\n---\n\n'));
            const { notificationStore } = await import('../stores/notificationStore');
            notificationStore.success('Article copied to clipboard');
          }
        }
      } catch (error) {
        console.error('[ChatMessage] Error handling app-skill-use action:', error);
        const { notificationStore } = await import('../stores/notificationStore');
        notificationStore.error('Failed to perform action');
      } finally {
        showMenu = false;
        selectedNode = null;
      }

      return;
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

{#if role === 'system'}
  <!-- System message: rendered as a smaller centered notice (e.g., reminders, insufficient credits) -->
  <!-- NOTE: content may be TipTap JSON (converted by G_mapToInternalMessage), so we prefer
       the original plaintext from original_message.content for display -->
  <div class="chat-message system">
    <div class="system-message-notice">
      <span class="system-message-text">{typeof content === 'string' ? content : (typeof original_message?.content === 'string' ? original_message.content : '')}</span>
    </div>
  </div>
{:else}
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
        
        <!-- AI Loading Indicator: Shown for placeholder assistant messages during processing.
             Displays a shimmer animation while waiting for the AI to start streaming.
             This is replaced by ReadOnlyMessage once streaming begins. -->
        {#if role === 'assistant' && status === 'processing' && (!content || (typeof content === 'string' && content.length === 0))}
          <div class="ai-loading-indicator">
            <div class="ai-loading-dots">
              <span class="ai-loading-dot"></span>
              <span class="ai-loading-dot"></span>
              <span class="ai-loading-dot"></span>
            </div>
          </div>
        {:else if showFullMessage && fullContent}
          <ReadOnlyMessage 
              bind:this={readOnlyMessageComponent}
              content={fullContent}
              isStreaming={status === 'streaming'}
              {_embedUpdateTimestamp}
              {selectable}
              {piiMappings}
              {piiRevealed}
              on:message-embed-click={handleEmbedClick}
          />
        {:else if hasExampleChatsPlaceholder}
          <!-- Demo chat with {example_chats_group} placeholder - use special component -->
          <DemoMessageContent
              content={originalMarkdownContent}
              chatId={currentChatId}
              isStreaming={status === 'streaming'}
              {selectable}
          />
        {:else}
          <ReadOnlyMessage 
              bind:this={readOnlyMessageComponent}
              {content}
              isStreaming={status === 'streaming'}
              {_embedUpdateTimestamp}
              {selectable}
              {piiMappings}
              {piiRevealed}
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
        {@const isFocusMode = menuType === 'focusMode'}
        {@const showCopyAction = !isFocusMode && (
          menuType === 'code' || menuType === 'video' || menuType === 'video-transcript' || menuType === 'web' ||
          /* App-skill-use embeds that support copy (matching fullscreen onCopy capability) */
          (selectedAppId === 'docs') ||
          (selectedAppId === 'sheets') ||
          (selectedAppId === 'web' && selectedSkillId === 'read') ||
          (selectedAppId === 'news' && selectedSkillId === 'read')
        )}
        {@const showDownloadAction = !isFocusMode && (
          menuType === 'code' || menuType === 'video-transcript' || menuType === 'pdf' ||
          /* App-skill-use embeds that support download (matching fullscreen onDownload capability) */
          (selectedAppId === 'images') ||
          (selectedAppId === 'docs') ||
          (selectedAppId === 'sheets')
        )}
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
          showView={!isFocusMode}
          showShare={!isFocusMode}
          showCopy={showCopyAction}
          showDownload={showDownloadAction}
          showDeactivate={isFocusMode}
          showDetails={isFocusMode}
          messageId={messageId}
          onClose={() => {
            showMenu = false;
            selectedNode = null;
          }}
          onView={() => handleMenuAction('view')}
          onShare={() => handleMenuAction('share')}
          onCopy={() => handleMenuAction('copy')}
          onDownload={() => handleMenuAction('download')}
          onDeactivate={() => handleMenuAction('deactivate')}
          onDetails={() => handleMenuAction('details')}
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
          {messageId}
          {userMessageId}
          {role}
        />
      {/if}
    </div>
    {#if role === 'assistant' && model_name}
      <div class="generated-by-container">
        <button class="generated-by" style="all: unset; cursor: pointer; font-size: 14px; color: var(--color-grey-60);" onclick={handleGeneratedByClick}>{$text('chat.generated_by.text', { values: { model: getModelDisplayName(model_name) } })}</button>
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
    {#if role === 'assistant' && hasEmbedErrors}
      <div class="embed-error-banner">
        <span class="embed-error-text">
          {$text('chat.embed_error.message.text')}
          <span class="embed-error-link" onclick={handleReportEmbedError} onkeydown={(e) => { if (e.key === 'Enter') handleReportEmbedError(); }} role="button" tabindex="0">
            {$text('chat.embed_error.report_link.text')}
          </span>
        </span>
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
              <button 
                type="button"
                class="category-badge"
                onclick={() => {
                  // Navigate to app settings/memories category via deep link
                  const path = `app_store/${cat.appId}/settings_memories/${cat.itemType}`;
                  settingsDeepLink.set(path);
                  panelState.openSettings();
                }}
              >
                <Icon 
                  name={cat.appId} 
                  type="app" 
                  size="22px"
                  noAnimation={true}
                />
                <span class="badge-text">{getCategoryDisplayName(cat)} ({cat.entryCount})</span>
              </button>
            {/each}
          </div>
        {:else if appSettingsMemoriesResponse.action === 'rejected'}
          <span class="summary-rejected">{$text('chat.permissions.rejected_summary.text') || 'Rejected App settings & memories request.'}</span>
        {/if}
      </div>
    {/if}
  </div>
</div>
{/if}

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
  /* AI Loading Indicator: Shown inside assistant message bubble during processing.
     Three pulsing dots that indicate the AI is working on a response.
     Uses the primary gradient color for brand consistency. */
  .ai-loading-indicator {
    display: flex;
    align-items: center;
    padding: 8px 4px;
    min-height: 24px;
  }

  .ai-loading-dots {
    display: flex;
    gap: 6px;
    align-items: center;
  }

  .ai-loading-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--color-primary, linear-gradient(135deg, #667eea 0%, #764ba2 100%));
    opacity: 0.4;
    animation: ai-dot-pulse 1.4s ease-in-out infinite;
  }

  .ai-loading-dot:nth-child(2) {
    animation-delay: 0.2s;
  }

  .ai-loading-dot:nth-child(3) {
    animation-delay: 0.4s;
  }

  @keyframes ai-dot-pulse {
    0%, 80%, 100% {
      opacity: 0.4;
      transform: scale(0.8);
    }
    40% {
      opacity: 1;
      transform: scale(1);
    }
  }

  /* System message notice: smaller text, centered, used for credit errors etc. */
  .chat-message.system {
    display: flex;
    justify-content: center;
    padding: 8px 0;
  }

  .system-message-notice {
    max-width: 80%;
    text-align: center;
    padding: 8px 16px;
    border-radius: 12px;
    background: var(--color-grey-15, rgba(255, 255, 255, 0.05));
  }

  .system-message-text {
    font-size: 13px;
    line-height: 1.4;
    color: var(--color-grey-60, #888);
  }

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

  /* Error banner shown below assistant messages when an app skill embed fails */
  .embed-error-banner {
    margin-top: 8px;
    margin-left: 12px;
    padding: 6px 10px;
    border-radius: 8px;
    background: var(--color-grey-15, rgba(255, 255, 255, 0.05));
  }

  .embed-error-text {
    font-size: 13px;
    color: var(--color-grey-60, #888);
    line-height: 1.4;
  }

  .embed-error-link {
    color: var(--color-primary);
    cursor: pointer;
    text-decoration: underline;
    text-decoration-style: dotted;
    text-underline-offset: 2px;
  }

  .embed-error-link:hover {
    text-decoration-style: solid;
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
    text-decoration: none;
    cursor: pointer;
    transition: background-color 0.15s ease;
    border: none;
    font-family: inherit;
  }
  
  .category-badge:hover {
    background: var(--color-grey-20, #e8e8e8);
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
    
    .category-badge:hover {
      background: var(--color-grey-30, #3a3a3a);
    }
    
    .badge-text {
      color: var(--color-font-primary, #fff);
    }
  }
</style>
