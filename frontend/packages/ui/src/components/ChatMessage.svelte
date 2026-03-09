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
  import type { MessageStatus, MessageRole, Message } from '../types/chat';
  import { text, settingsDeepLink, panelState } from '@repo/ui'; // For translations
  import { getModelDisplayName, getModelByNameOrId } from '../utils/modelDisplayName';
  import { getMatesById } from '../data/matesMetadata';
import { reportIssueStore } from '../stores/reportIssueStore';
import { messageHighlightStore, searchTextHighlightStore } from '../stores/messageHighlightStore';
import { pendingUploadStore, type EmbedProgress } from '../stores/pendingUploadStore';
  import { chatDB } from '../services/db';
  import { chatSyncService } from '../services/chatSyncService';
  import type { AppSettingsMemoriesResponseContent, AppSettingsMemoriesResponseCategory } from '../services/chatSyncServiceHandlersAppSettings';
  import { appSkillsStore } from '../stores/appSkillsStore';
  import { writeEmbedToClipboard, writeMessageWithEmbedsToClipboard } from '../message_parsing/serializers';
  import type { TipTapNode } from '../message_parsing/types';
  import { copyToClipboard } from '../utils/clipboardUtils';
  import { chatDebugStore } from '../stores/chatDebugStore';
  
  // Define types for message content parts
  type AppCardData = {
    component: new (...args: unknown[]) => SvelteComponent;
    props: Record<string, unknown>;
  };

  /** Minimal ProseMirror node shape used for embed context menus */
  interface ProseMirrorNodeLike {
    type: { name: string };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- ProseMirror node attrs are dynamically keyed with mixed value types
    attrs: Record<string, any>;
    content?: ProseMirrorNodeLike[];
  }

  /** Embed share context passed to share settings */
  interface EmbedShareContext {
    type: string;
    embed_id: string;
    url?: string;
    title?: string;
    filename?: string;
    language?: string;
    lineCount?: number;
  }
  
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
    userMessageId = undefined,
    onDeleteMessage = undefined,
    isFirstMessage = false,
    isCreditsRestored = false,
    onResend = undefined
  }: {
    role?: MessageRole;
    category?: string;
    sender_name?: string;
    model_name?: string;
    status?: MessageStatus;
    messageParts?: MessagePart[];
    appCards?: AppCardData[];
    defaultHidden?: boolean;
    content: string | Record<string, unknown> | null;
    animated?: boolean;
    is_truncated?: boolean;
    original_message?: (Partial<Message> & { is_incognito?: boolean }) | null;
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
    onDeleteMessage?: () => void; // Callback when user confirms message deletion
    isFirstMessage?: boolean; // Whether this is the first message in the chat (delete is disabled for first messages)
    /** True when this message has status 'waiting_for_user' (credits rejection) AND
     *  the user now has credits again. Replaces the "Buy Credits" UI with a
     *  "Credits restored" banner and a "Resend message" button. */
    isCreditsRestored?: boolean;
    /** Callback to resend the original message after credits are restored.
     *  Called when the user clicks "Resend message" in the credits-restored banner. */
    onResend?: () => void;
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
        // Guard: $text() returns the key itself when no translation is found
        const translated = $text(category.name_translation_key);
        if (translated && translated !== category.name_translation_key) {
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

  // Effective role: forces assistant messages with 'waiting_for_user' status to render
  // as system notices. This handles messages persisted in the DB before the role fix was
  // deployed (they have role='assistant' + status='waiting_for_user' + category set).
  // Normal assistant messages never have 'waiting_for_user' status, so this is safe.
  let effectiveRole = $derived(
    role === 'assistant' && status === 'waiting_for_user' ? 'system' as const : role
  );

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

  // Raw content displayed in debug mode — shows the original stored text (JSON/markdown)
  // without any rendering, so embed placeholders and raw structure are visible.
  let debugRawContent = $derived(
    typeof original_message?.content === 'string'
      ? original_message.content
      : (content !== null && content !== undefined ? JSON.stringify(content, null, 2) : '')
  );
  
  // Get the chat ID from the original message (needed for ExampleChatsGroup exclusion)
  let currentChatId = $derived(original_message?.chat_id || 'demo-for-everyone');

  /**
   * Whether the fork action is disabled for this message.
   * Fork is disabled for incognito chats and when no messageId is available.
   * We check original_message.is_incognito (if available) as a fast path.
   * The authoritative check is done in the service layer.
   */
  let isForkDisabled = $derived(
    !messageId ||
    !original_message?.chat_id ||
    !!original_message?.is_incognito
  );

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
  // Compression summary expand/collapse state
  let compressionExpanded = $state(false);

  // Whether this is a compression summary system message
  let isCompressionSummary = $derived(
    category === 'compression_summary' || original_message?.category === 'compression_summary'
  );

  // Get the plaintext content for compression summary display
  let compressionSummaryText = $derived.by(() => {
    if (!isCompressionSummary) return '';
    if (typeof original_message?.content === 'string') return original_message.content;
    if (typeof content === 'string') return content;
    return '';
  });

  // Show first 3 lines of compression summary by default, full text when expanded
  let compressionPreviewLines = $derived.by(() => {
    if (!compressionSummaryText) return '';
    const lines = compressionSummaryText.split('\n');
    if (lines.length <= 4 || compressionExpanded) return compressionSummaryText;
    return lines.slice(0, 4).join('\n') + '...';
  });

  let compressionNeedsExpand = $derived.by(() => {
    if (!compressionSummaryText) return false;
    return compressionSummaryText.split('\n').length > 4;
  });

  // Special handling for openmates_official category
  let displayName = $derived(role === 'user' ? '' : 
                    sender_name ? (sender_name.charAt(0).toUpperCase() + sender_name.slice(1)) : 
                    category === 'openmates_official' ? 'OpenMates' :
                    category ? $text(`mates.${category}`) :
                    'Assistant');

  // animated prop is now included in the main $props() call above

  /**
   * Whether the current category corresponds to a real AI mate whose detail
   * page can be opened in settings. Excludes 'openmates_official' and any
   * category not found in matesMetadata.
   */
  const _matesById = getMatesById();
  let isMateClickable = $derived(
      !!category && category !== 'openmates_official' && !!_matesById[category]
  );

  /**
   * Open the settings panel deep-linked to this mate's detail page.
   */
  function openMateSettings() {
      if (!category || !isMateClickable) return;
      settingsDeepLink.set(`mates/${category}`);
      panelState.openSettings();
  }

  // Add menu state using $state (Svelte 5 runes mode)
  let showMenu = $state(false);
  let menuX = $state(0);
  let menuY = $state(0);
  let menuType = $state<'default' | 'pdf' | 'web' | 'video-transcript' | 'video' | 'code' | 'focusMode'>('default');
  let selectedNode = $state<ProseMirrorNodeLike | null>(null);
  let embedType = $state<'code' | 'video' | 'website' | 'pdf' | 'focusMode' | 'default'>('default');
  let selectedAppId = $state<string | null>(null);
  let selectedSkillId = $state<string | null>(null);
  let selectedFocusId = $state<string | null>(null);
  let selectedFocusModeName = $state<string | null>(null);
  // Embed ID extracted from the DOM element's data-embed-id attribute.
  // This is more reliable than extracting from the ProseMirror node attrs because
  // for grouped embeds the ProseMirror node is the group (not the individual embed),
  // while the DOM element always refers to the specific embed that was right-clicked.
  let selectedDomEmbedId = $state<string | null>(null);

  // Message context menu state
  let showMessageMenu = $state(false);
  let messageMenuX = $state(0);
  let messageMenuY = $state(0);
  let selectable = $state(false);
  let readOnlyMessageComponent = $state<ReturnType<typeof ReadOnlyMessage>>();
  let messageContentElement = $state<HTMLElement>();

  // State for report button hover
  let isReportHovered = $state(false);

  /**
   * Counter incremented each time ReadOnlyMessage signals that its TipTap editor has
   * finished creating and text nodes are now in the DOM. This acts as an extra reactive
   * dependency for the search-highlight $effect so that it re-runs even when the query
   * and the container element have not changed (e.g. lazy IntersectionObserver init fires
   * AFTER the highlight $effect already ran and found no text nodes to highlight).
   */
  let contentReadyCounter = $state(0);

  /**
   * Listener effect: attaches a 'contentready' event handler to messageContentElement.
   * ReadOnlyMessage dispatches this event (bubbling) after createEditor() completes,
   * which triggers the highlight $effect below to re-run via contentReadyCounter.
   */
  $effect(() => {
    const container = messageContentElement;
    if (!container) return;

    function onContentReady() {
      contentReadyCounter++;
    }

    container.addEventListener('contentready', onContentReady);
    return () => {
      container.removeEventListener('contentready', onContentReady);
    };
  });

  /**
   * In-chat search text highlighting.
   * When search is open and has a query, walks the DOM text nodes inside the message
   * content and wraps matching substrings in <mark class="search-match"> elements.
   * Cleans up (removes marks) when the query changes or search closes.
   *
   * IMPORTANT: The DOM walk is deferred to a requestAnimationFrame callback so it runs
   * AFTER Svelte and the markdown renderer have finished painting the message content.
   * Without this deferral the TreeWalker finds no text nodes because child components
   * (e.g. ReadOnlyMessage / markdown renderer) have not yet rendered their content into
   * messageContentElement when the $effect first fires.
   *
   * contentReadyCounter is also tracked as a dependency so this effect re-runs when
   * ReadOnlyMessage's lazy IntersectionObserver finally creates the TipTap editor and
   * text nodes become available (which can happen AFTER the initial rAF already fired).
   */
  $effect(() => {
    const query = $searchTextHighlightStore;
    const container = messageContentElement;
    // Track contentReadyCounter so the effect re-runs when ReadOnlyMessage content lands
    const _contentReady = contentReadyCounter; // eslint-disable-line @typescript-eslint/no-unused-vars
    if (!container) return;

    // Cancel any previously queued (but not-yet-fired) highlight update.
    let rafHandle: number | null = null;

    function removeExistingMarks(el: HTMLElement) {
      // Clean up any <mark class="search-match"> nodes left by a previous run.
      // We collect them first because replacing nodes while iterating is unsafe.
      const marks = Array.from(el.querySelectorAll('mark.search-match'));
      for (const mark of marks) {
        const parent = mark.parentNode;
        if (parent) {
          parent.replaceChild(document.createTextNode(mark.textContent || ''), mark);
          parent.normalize();
        }
      }
    }

    function applyHighlights() {
      // Guard: container may have been removed from DOM since the RAF was queued
      if (!container.isConnected) return;

      // Always clean up previous highlights first
      removeExistingMarks(container);

      if (!query || query.trim().length === 0) return;

      const lowerQuery = query.toLowerCase().trim();
      if (!lowerQuery) return;

      // Walk all text nodes in the message content.
      // Runs in rAF so the markdown renderer has already painted its content.
      const walker = document.createTreeWalker(
        container,
        NodeFilter.SHOW_TEXT,
        null,
      );

      const textNodes: Text[] = [];
      let node: Node | null;
      while ((node = walker.nextNode())) {
        textNodes.push(node as Text);
      }

      // Process each text node — wrap matches in <mark class="search-match">
      for (const textNode of textNodes) {
        const textContent = textNode.textContent || '';
        const lowerContent = textContent.toLowerCase();
        const firstIdx = lowerContent.indexOf(lowerQuery);
        if (firstIdx === -1) continue;

        // Build a document fragment with highlighted runs
        const fragment = document.createDocumentFragment();
        let lastIdx = 0;
        let searchFrom = 0;

        while (searchFrom < lowerContent.length) {
          const idx = lowerContent.indexOf(lowerQuery, searchFrom);
          if (idx === -1) break;

          // Text before the match
          if (idx > lastIdx) {
            fragment.appendChild(document.createTextNode(textContent.slice(lastIdx, idx)));
          }

          // The match — wrapped in <mark>
          const mark = document.createElement('mark');
          mark.className = 'search-match';
          mark.textContent = textContent.slice(idx, idx + lowerQuery.length);
          fragment.appendChild(mark);

          lastIdx = idx + lowerQuery.length;
          searchFrom = lastIdx;
        }

        // Remaining text after the last match
        if (lastIdx < textContent.length) {
          fragment.appendChild(document.createTextNode(textContent.slice(lastIdx)));
        }

        // Replace the original text node with the fragment
        textNode.parentNode?.replaceChild(fragment, textNode);
      }
    }

    // If there's no query, remove existing marks synchronously (no need to defer cleanup).
    if (!query || query.trim().length === 0) {
      removeExistingMarks(container);
      return;
    }

    // Defer DOM walk to the next animation frame so that all child components
    // (markdown renderer, etc.) have had a chance to render their content first.
    rafHandle = requestAnimationFrame(applyHighlights);

    // Cleanup: cancel the pending frame if the effect re-runs before it fires
    // (e.g. query changed again, or the component is destroyed).
    return () => {
      if (rafHandle !== null) {
        cancelAnimationFrame(rafHandle);
      }
      // Also clean up any marks when the effect is torn down (e.g. search closed)
      if (container.isConnected) {
        removeExistingMarks(container);
      }
    };
  });

  /**
   * Handle search result click highlighting — pulse the matched text marks.
   * When the user clicks a search result snippet, messageHighlightStore is set to
   * this message's ID. Instead of blinking the whole message bubble, we add
   * class 'search-match-active' to all <mark class="search-match"> elements in the
   * message, which triggers a CSS opacity pulse animation.
   * The class is cleared after the animation completes (~1.2s).
   */
  $effect(() => {
    if (original_message?.message_id && $messageHighlightStore === original_message.message_id) {
      const container = messageContentElement;
      if (!container) return;

      // Apply pulse to all match marks currently in the message.
      // They may not yet exist if the highlight $effect hasn't run yet (lazy init).
      // We queue the pulse in a rAF so that the highlight $effect has a chance to
      // run first (it also uses rAF internally).
      let rafHandle: number | null = null;
      rafHandle = requestAnimationFrame(() => {
        const marks = Array.from(container.querySelectorAll('mark.search-match'));
        for (const mark of marks) {
          mark.classList.add('search-match-active');
        }
        // Remove the active class after animation completes
        const timer = setTimeout(() => {
          const activeMarks = Array.from(container.querySelectorAll('mark.search-match-active'));
          for (const mark of activeMarks) {
            mark.classList.remove('search-match-active');
          }
          messageHighlightStore.set(null);
        }, 1200);
        return () => clearTimeout(timer);
      });
      return () => {
        if (rafHandle !== null) cancelAnimationFrame(rafHandle);
      };
    }
  });

  /**
   * Handle reporting a bad answer.
   * Pre-fills the report issue form with context and enables the "share chat" toggle
   * so the admin can access the full chat for investigation.
   */
  function handleReportBadAnswer() {
    if (!original_message) return;

    const title = $text('chat.report_bad_answer.title');

    reportIssueStore.set({
      title: title,
      shareChat: true
    });

    settingsDeepLink.set('report_issue');
    panelState.openSettings();
    
    // Paste a translated retry prompt into the message input so the user can
    // immediately ask the assistant to try again with web search / app skills.
    const retryText = $text('chat.report_bad_answer.retry_message');
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
   * Handle deleting this message from chat history.
   * Deletes from IndexedDB locally, then sends server request to remove from cache and Directus.
   * If this is an assistant message, also deletes the triggering user message (and vice versa).
   */
  async function handleDeleteMessage() {
    if (!messageId || !original_message?.chat_id) {
      console.error('[ChatMessage] Cannot delete: missing messageId or chat_id');
      return;
    }

    const chatId = original_message.chat_id;
    console.debug(`[ChatMessage] Deleting message ${messageId} from chat ${chatId}`);

    try {
      // Extract embed references from message content and clean them up from IndexedDB
      const embedIdsToDelete: string[] = [];
      const messageContent = typeof original_message?.content === 'string' ? original_message.content : '';
      
      if (messageContent) {
        try {
          const { extractEmbedReferences } = await import('../services/embedResolver');
          const { embedStore } = await import('../services/embedStore');
          const { computeSHA256 } = await import('../message_parsing/utils');
          
          const embedRefs = extractEmbedReferences(messageContent);
          
          if (embedRefs.length > 0) {
            const hashedChatId = await computeSHA256(chatId);
            
            for (const ref of embedRefs) {
              try {
                const hashedEmbedId = await computeSHA256(ref.embed_id);
                const isShared = await embedStore.isEmbedUsedByOtherChats(hashedEmbedId, hashedChatId);
                
                if (isShared) {
                  console.debug(`[ChatMessage] Embed ${ref.embed_id} is shared, skipping deletion`);
                } else {
                  await embedStore.deleteEmbed(ref.embed_id, hashedEmbedId);
                  embedIdsToDelete.push(ref.embed_id);
                  console.debug(`[ChatMessage] Deleted embed ${ref.embed_id} from IndexedDB`);
                }
              } catch (embedErr) {
                console.warn(`[ChatMessage] Error processing embed ${ref.embed_id} for deletion:`, embedErr);
              }
            }
            
            if (embedIdsToDelete.length > 0) {
              console.debug(`[ChatMessage] Deleted ${embedIdsToDelete.length} embeds from IndexedDB`);
            }
          }
        } catch (embedErr) {
          console.warn('[ChatMessage] Error extracting/deleting embeds:', embedErr);
        }
      }

      // Delete the message from local IndexedDB
      await chatDB.deleteMessage(messageId);

      // Send server request to delete from cache and Directus (including embed IDs for server cleanup)
      try {
        await chatSyncService.sendDeleteMessage(
          chatId, messageId,
          embedIdsToDelete.length > 0 ? embedIdsToDelete : undefined
        );
      } catch (err) {
        console.error('[ChatMessage] Error sending delete_message to server (local deletion succeeded):', err);
      }

      // If this is an assistant message and we know the triggering user message, delete it too
      // If this is a user message, try to find and delete the assistant response
      if (role === 'assistant' && userMessageId) {
        try {
          await chatDB.deleteMessage(userMessageId);
          await chatSyncService.sendDeleteMessage(chatId, userMessageId);
        } catch (err) {
          console.error('[ChatMessage] Error deleting paired user message:', err);
        }
      }

      // Notify parent component via callback (if provided by ChatHistory)
      onDeleteMessage?.();

      // Also dispatch a global event so ChatHistory/ActiveChat can react
      chatSyncService.dispatchEvent(
        new CustomEvent('messageDeleted', {
          detail: { chatId, messageId },
        }),
      );
    } catch (err) {
      console.error('[ChatMessage] Error deleting message:', err);
    }
  }

  /**
   * Open the Fork Conversation settings panel for this message.
   * Sets window.__forkContext with the necessary data, then navigates to the
   * fork settings panel via settingsDeepLink + panelState.openSettings().
   *
   * The fork includes all messages up to and including this one (inclusive).
   * Disabled for incognito chats.
   */
  async function handleFork() {
    if (!messageId || !currentChatId) return;

    const chatId = currentChatId;

    // Load chat title and message count for the fork context
    let defaultTitle = '';
    let messageCount = 0;
    try {
      const { decryptWithChatKey } = await import('../services/cryptoService');
      const chat = await chatDB.getChat(chatId);
      if (chat?.encrypted_title) {
        const key = chatDB.getChatKey(chatId);
        if (key) {
          defaultTitle = await decryptWithChatKey(chat.encrypted_title, key) ?? '';
        }
      }
      // Count messages up to and including this one
      const allMsgs = await chatDB.getMessagesForChat(chatId);
      allMsgs.sort((a, b) => (a.created_at ?? 0) - (b.created_at ?? 0));
      const idx = allMsgs.findIndex(m => m.message_id === messageId);
      messageCount = idx >= 0 ? idx + 1 : allMsgs.length;
    } catch (err) {
      console.warn('[ChatMessage] handleFork: could not load chat metadata:', err);
    }

    // Pass context via window global (same pattern as __embedShareContext)
    (window as Window & { __forkContext?: unknown }).__forkContext = {
      sourceChatId: chatId,
      upToMessageId: messageId,
      defaultTitle,
      messageCount,
    };

    settingsDeepLink.set('fork');
    panelState.openSettings();
    showMessageMenu = false;

    console.debug('[ChatMessage] Fork context set, opening fork settings:', { chatId, messageId, messageCount });
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
   *
   * When copying a full message (not a text selection), if the message contains embeds,
   * the clipboard also carries structured embed reference data
   * ("application/x-openmates-embed" MIME type) alongside the text.
   * This allows pasting the message into MessageInput and having the embeds rendered
   * as live embed cards rather than plain markdown text.
   */
  async function handleCopyMessage() {
    try {
      let contentToCopy: string;
      const selection = window.getSelection();
      const isCopyingSelection = selectable && selection && selection.toString().length > 0;
      
      // If there's a selection and it's within this message, copy only the selection
      if (isCopyingSelection) {
        contentToCopy = selection!.toString();
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
      
      if (isCopyingSelection) {
        // Plain text copy for selections — no embed reference needed.
        // Uses the unified ClipboardService (writeText → execCommand fallback).
        const clipResult = await copyToClipboard(contentToCopy);
        if (!clipResult.success) throw new Error(clipResult.error || 'Copy failed');
      } else {
        // Full message copy: extract embed node attributes from the TipTap document
        // so the clipboard carries structured embed references alongside the text.
        // The ReadOnlyMessage component renders the TipTap doc; we parse the markdown
        // to extract embed nodes without depending on the DOM.
        let embedAttrs: import('../message_parsing/types').EmbedNodeAttributes[] = [];
        try {
          const { parse_message } = await import('../message_parsing/parse_message');
          const rawMarkdown = typeof original_message?.content === 'string'
            ? original_message.content
            : '';
          if (rawMarkdown) {
            const tiptapDoc = parse_message(rawMarkdown, 'read', { unifiedParsingEnabled: true });
            // Walk the TipTap document to collect embed nodes
            const collectEmbeds = (nodes: TipTapNode[]): void => {
              for (const node of nodes ?? []) {
                if (node.type === 'embed' && node.attrs?.contentRef?.startsWith('embed:')) {
                  embedAttrs.push(node.attrs as unknown as import('../message_parsing/types').EmbedNodeAttributes);
                }
                if (node.content) collectEmbeds(node.content);
              }
            };
            collectEmbeds(tiptapDoc?.content ?? []);
          }
        } catch (parseErr) {
          // Non-critical: if parsing fails, fall back to plain text copy
          console.warn('[ChatMessage] Failed to extract embed nodes for clipboard:', parseErr);
          embedAttrs = [];
        }

        // Write embed references + message text to clipboard using dual-MIME ClipboardItem.
        // When pasted inside OpenMates MessageInput, the paste handler reads the embed
        // JSON and re-inserts the embed nodes. When pasted externally, text/plain is used.
        await writeMessageWithEmbedsToClipboard(embedAttrs, contentToCopy);
      }
      
      const { notificationStore } = await import('../stores/notificationStore');
      notificationStore.success(
        isCopyingSelection
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
      el.addEventListener('keydown', handleMessageKeyDown as EventListener);
    }

    return () => {
      document.removeEventListener('mousedown', handleGlobalClick);
      document.removeEventListener('touchstart', handleGlobalClick);
      if (el) {
        el.removeEventListener('keydown', handleMessageKeyDown as EventListener);
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
    // Store the embed ID from the DOM (reliable for both individual and grouped embeds)
    selectedDomEmbedId = dom.getAttribute('data-embed-id');
    
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
      } else if (node.attrs.type === 'app-skill-use' || node.attrs.type === 'app-skill-use-group') {
        // App skill embeds (individual or grouped) - determine menu type based on appId/skillId
        // For grouped embeds, the DOM element still refers to the specific embed that was right-clicked
        // so appId/skillId from the DOM are correct even when the ProseMirror node is the group
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

  function getEmbedIdFromNode(node: ProseMirrorNodeLike | null): string | null {
    // CRITICAL: Prioritize contentRef over attrs.id because attrs.id is a TipTap-generated UUID
    // (from generateUUID() in embedParsing.ts) and NOT the actual embed ID stored in EmbedStore.
    // The real embed ID lives in contentRef as "embed:<embed_id>".
    const contentRef = node?.attrs?.contentRef;
    if (typeof contentRef === 'string' && contentRef.startsWith('embed:')) {
      return contentRef.replace('embed:', '');
    }
    // Fallback to other attributes (for non-standard embed types)
    const raw = node?.attrs?.embed_id || node?.attrs?.embedId || node?.attrs?.id;
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

  async function openEmbedShareSettings(embedContext: EmbedShareContext) {
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

    navigateToSettings('shared/share', shareTitle, 'share', 'settings.share.share_embed');
    settingsDeepLink.set('shared/share');
    panelState.openSettings();
  }

  // Update handleMenuAction to support video transcript and video embed actions
  async function handleMenuAction(action: string) {
    if (!selectedNode) return;

    // Snapshot node attrs immediately. The EmbedContextMenu onClose callback fires as soon
    // as a menu button is clicked (before this async function resolves), which sets
    // selectedNode = null. All async paths below must use this snapshot instead of
    // accessing selectedNode.attrs after any await to avoid "Cannot read properties of null".
    // Cast via unknown so TypeScript accepts it as EmbedNodeAttributes across all call sites.
    const snapshotAttrs = selectedNode.attrs as unknown as import('../message_parsing/types').EmbedNodeAttributes;

    // Legacy node handlers removed - now using unified embed system
    // Actions are handled directly below

    // Handle fullscreen for supported node types
    // Dispatch embedfullscreen event to open fullscreen (same as clicking the embed)
    if (action === 'view') {
        // Get embed ID - prefer DOM-extracted ID (works for both individual and grouped embeds),
        // then try contentRef (real embed ID), and finally attrs.id as last resort
        const embedId = selectedDomEmbedId || selectedNode.attrs?.contentRef?.replace('embed:', '') || selectedNode.attrs?.id;
        
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
        } else if (fullscreenEmbedType === 'app-skill-use' || fullscreenEmbedType === 'app-skill-use-group') {
            fullscreenEmbedType = 'app-skill-use'; // Normalize group type to individual for fullscreen
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
      const embedId = selectedDomEmbedId || getEmbedIdFromNode(selectedNode);
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
        const embedContext: EmbedShareContext = { type: shareType, embed_id: embedId };

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
      // Snapshot inline attrs for fallback (used when no embedId or resolve fails)
      const inlineCode = selectedNode.attrs?.code || '';
      const inlineLanguage = selectedNode.attrs?.language || 'text';
      const inlineFilename = selectedNode.attrs?.filename;

      try {
        if (action === 'copy') {
          // Build content promise that resolves the embed if possible, falling back to inline attrs.
          // The promise is constructed WITHOUT await so writeEmbedToClipboard can call
          // navigator.clipboard.write() synchronously (Safari gesture-token compatibility).
          const codePromise: Promise<string> = embedId
            ? import('../services/embedResolver').then(({ resolveEmbed, decodeToonContent }) =>
                resolveEmbed(embedId).then(async (embedData) => {
                  if (embedData?.content) {
                    const decoded = await decodeToonContent(embedData.content);
                    return decoded?.code || inlineCode;
                  }
                  return inlineCode;
                })
              )
            : Promise.resolve(inlineCode);

          // Initiate clipboard write immediately (synchronous within the gesture context).
          const copyDone = writeEmbedToClipboard(snapshotAttrs, codePromise);

          // Await resolution to show notification; rethrow errors to the outer catch.
          const code = await codePromise;
          await copyDone;
          if (code) {
            const { notificationStore } = await import('../stores/notificationStore');
            notificationStore.success('Code copied to clipboard');
          }
        } else if (action === 'download') {
          // Download does not need the gesture-token trick — just resolve normally.
          let code = inlineCode;
          let language = inlineLanguage;
          let filename = inlineFilename;
          if (embedId) {
            const { resolveEmbed, decodeToonContent } = await import('../services/embedResolver');
            const embedData = await resolveEmbed(embedId);
            if (embedData?.content) {
              const decoded = await decodeToonContent(embedData.content);
              code = decoded?.code || code;
              language = decoded?.language || language;
              filename = decoded?.filename || filename;
            }
          }
          if (code) {
            const { downloadCodeFile } = await import('../services/zipExportService');
            await downloadCodeFile(code, language, filename);
            const { notificationStore } = await import('../stores/notificationStore');
            notificationStore.success('Code file downloaded successfully');
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
        if (action === 'copy') {
          // Build the markdown text promise without awaiting — enables synchronous
          // navigator.clipboard.write() call for Safari gesture-token compatibility.
          // Format: bold labels + bullet-point URLs so it reads well in any text editor.
          const mdPromise: Promise<string> = import('../services/embedResolver').then(
            ({ resolveEmbed, decodeToonContent }) =>
              resolveEmbed(embedId).then(async (embedData) => {
                if (!embedData?.content) {
                  console.warn('[ChatMessage] No embed data found for web search embed, cannot copy');
                  return '';
                }
                const decodedContent = await decodeToonContent(embedData.content);
                const query = decodedContent?.query || '';
                const provider = decodedContent?.provider || 'Brave Search';
                const results = decodedContent?.results || [];

                let md = `*Query:*\n"${query}"\n\n`;
                md += `*Provider:*\n${provider}\n\n`;
                md += `*Results:*\n`;
                results.forEach((result: { url?: string }) => {
                  if (result.url) md += `- ${result.url}\n`;
                });
                return md.trimEnd();
              })
          );

          // Initiate clipboard write immediately (synchronous within the gesture context).
          const copyDone = writeEmbedToClipboard(snapshotAttrs, mdPromise);

          // Await both to surface errors and show notification.
          const md = await mdPromise;
          await copyDone;
          if (md) {
            const { notificationStore } = await import('../stores/notificationStore');
            notificationStore.success('Copied to clipboard');
          }
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
        if (action === 'copy') {
          // Build transcript text promise without awaiting — Safari gesture-token fix.
          const transcriptPromise: Promise<string> = import('../services/embedResolver').then(
            ({ resolveEmbed, decodeToonContent }) =>
              resolveEmbed(embedId).then(async (embedData) => {
                if (!embedData?.content) {
                  console.warn('[ChatMessage] No embed data found for video transcript');
                  return '';
                }
                const decodedContent = await decodeToonContent(embedData.content);
                const results = decodedContent.results || [];
                return results
                  .filter((r: { transcript?: string; url?: string; word_count?: number; metadata?: { title?: string } }) => r.transcript)
                  .map((r: { transcript?: string; url?: string; word_count?: number; metadata?: { title?: string } }) => {
                    let content = '';
                    if (r.metadata?.title) content += `# ${r.metadata.title}\n\n`;
                    if (r.url) content += `Source: ${r.url}\n\n`;
                    if (r.word_count) content += `Word count: ${r.word_count.toLocaleString()}\n\n`;
                    content += r.transcript || '';
                    return content;
                  })
                  .join('\n\n---\n\n');
              })
          );

          // Initiate clipboard write immediately (synchronous within the gesture context).
          const copyDone = writeEmbedToClipboard(snapshotAttrs, transcriptPromise);

          const transcriptText = await transcriptPromise;
          await copyDone;
          if (transcriptText) {
            const { notificationStore } = await import('../stores/notificationStore');
            notificationStore.success('Transcript copied to clipboard');
          }
        } else if (action === 'download') {
          // Download does not need the gesture-token trick — resolve normally.
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
          const downloadText = results
            .filter((r: { transcript?: string; url?: string; word_count?: number; metadata?: { title?: string } }) => r.transcript)
            .map((r: { transcript?: string; url?: string; word_count?: number; metadata?: { title?: string } }) => {
              let content = '';
              if (r.metadata?.title) content += `# ${r.metadata.title}\n\n`;
              if (r.url) content += `Source: ${r.url}\n\n`;
              if (r.word_count) content += `Word count: ${r.word_count.toLocaleString()}\n\n`;
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
        } else if (action === 'share') {
          // Handled by generic share handler above
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
          // Copy video URL to clipboard.
          // videoUrl is already known — no async resolution needed.
          // writeEmbedToClipboard accepts a plain string; it wraps it in a resolved
          // promise internally, so the ClipboardItem is still constructed synchronously.
          if (videoUrl) {
            try {
              await writeEmbedToClipboard(snapshotAttrs, videoUrl);
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
    // These handlers cover all app skills that support copy/download from the context menu.
    // Also handles app-skill-use-group nodes: when the user right-clicks an individual embed
    // inside a group, ProseMirror resolves to the group node, but the DOM element still refers
    // to the specific embed (via data-embed-id). We use selectedDomEmbedId for reliable ID lookup.
    else if (selectedNode.type.name === 'embed' && (selectedNode.attrs.type === 'app-skill-use' || selectedNode.attrs.type === 'app-skill-use-group') && selectedAppId) {
      // Prefer the embed ID from the DOM element (reliable for both individual and grouped embeds)
      // Fall back to ProseMirror node attrs for non-grouped embeds
      const embedId = selectedDomEmbedId || getEmbedIdFromNode(selectedNode);
      if (!embedId) {
        console.warn('[ChatMessage] No embed ID found for app-skill-use embed action');
        showMenu = false;
        selectedNode = null;
        return;
      }

      try {
        if (action === 'copy') {
          // --- Safari gesture-token-safe copy path ---
          //
          // For ALL copy actions in this block we follow the same pattern:
          //   1. Build a Promise<string> that resolves the embed content WITHOUT awaiting it.
          //   2. Call writeEmbedToClipboard(attrs, promise) SYNCHRONOUSLY — this calls
          //      navigator.clipboard.write() before any await, preserving Safari's gesture token.
          //   3. Await the content promise and the copy promise to surface errors + show notification.
          //
          // The content-extraction logic is identical to the old await-based code — it is just
          // wrapped in a .then() chain instead of being awaited inline.

          // Snapshot appId/skillId for use inside the promise (these may change after await)
          const appId = selectedAppId;
          const skillId = selectedSkillId;

          const contentPromise: Promise<string> = import('../services/embedResolver').then(
            ({ resolveEmbed, decodeToonContent }) =>
              resolveEmbed(embedId).then(async (embedData): Promise<string> => {
                if (!embedData?.content) {
                  console.warn('[ChatMessage] No embed data found for app-skill-use embed (copy):', embedId);
                  return '';
                }
                const decodedContent: Record<string, unknown> = typeof embedData.content === 'string'
                  ? await decodeToonContent(embedData.content)
                  : embedData.content as Record<string, unknown>;
                if (!decodedContent) {
                  console.warn('[ChatMessage] Failed to decode content for embed (copy):', embedId);
                  return '';
                }

                // --- Docs: strip HTML to plain text ---
                if (appId === 'docs') {
                  const htmlContent = (decodedContent.html as string) || '';
                  const tempDiv = document.createElement('div');
                  tempDiv.innerHTML = htmlContent;
                  return tempDiv.textContent || tempDiv.innerText || '';
                }

                // --- Sheets: convert markdown table to TSV (tab-separated values) ---
                // TSV pastes directly into Excel/Google Sheets as individual cells
                // (comma-separated CSV would require the "Import" dialog on most apps).
                if (appId === 'sheets') {
                  const tableContent = (decodedContent.code as string) || (decodedContent.table as string) || '';
                  if (!tableContent) return '';
                  // Filter out separator rows (---|---|---) and empty lines
                  const lines = tableContent.split('\n').filter((l: string) => l.trim() && !l.trim().match(/^[\s|:-]+$/));
                  return lines.map((line: string) =>
                    line.split('|')
                      .map((cell: string) => cell.trim())
                      .filter((cell: string) => cell !== '')
                      .join('\t')
                  ).join('\n');
                }

                // --- Web Read / News Read: article markdown with source URLs ---
                if ((appId === 'web' || appId === 'news') && skillId === 'read') {
                  const results = (decodedContent.results as Array<{ markdown?: string; title?: string; url?: string }>) || [];
                  const textParts = results.map(r => {
                    let part = '';
                    if (r.title) part += `# ${r.title}\n\n`;
                    if (r.url) part += `*Source:* ${r.url}\n\n`;
                    if (r.markdown) part += r.markdown;
                    return part;
                  }).filter(Boolean);
                  return textParts.join('\n\n---\n\n');
                }

                // --- Videos/News Search: query + provider + bullet-point URLs ---
                // Same format as web search (handled in the separate menuType='web' block above,
                // but videos/news search reach this block via selectedAppId/selectedSkillId).
                if ((appId === 'videos' || appId === 'news') && skillId === 'search') {
                  const query = (decodedContent.query as string) || '';
                  const provider = (decodedContent.provider as string) || '';
                  const results = (decodedContent.results as Array<{ url?: string; title?: string }>) || [];
                  let md = `*Query:*\n"${query}"\n\n`;
                  if (provider) md += `*Provider:*\n${provider}\n\n`;
                  md += `*Results:*\n`;
                  results.forEach((r: { url?: string }) => {
                    if (r.url) md += `- ${r.url}\n`;
                  });
                  return md.trimEnd();
                }

                // --- Math Calculate ---
                if (appId === 'math' && skillId === 'calculate') {
                  interface CalculateResult { expression?: string; result?: string; result_type?: string; mode?: string; steps?: string[]; error?: string; }
                  const query = (decodedContent.query as string) || '';
                  const results = (decodedContent.results as CalculateResult[]) || [];
                  const lines: string[] = [];
                  if (query) lines.push(`Expression: ${query}`);
                  for (const r of results) {
                    if (r.expression && r.expression !== query) lines.push(`  ${r.expression}`);
                    if (r.result) lines.push(`= ${r.result}${r.result_type ? ` (${r.result_type})` : ''}`);
                    if (r.error) lines.push(`Error: ${r.error}`);
                    if (r.steps && r.steps.length > 0) lines.push(...r.steps.map((s, i) => `  Step ${i + 1}: ${s}`));
                  }
                  return lines.join('\n') || query;
                }

                // --- Math Plot ---
                if (appId === 'math' && skillId === 'plot') {
                  // plot_spec is the canonical field; expression is the legacy name before rename
                  const plotSpec = (decodedContent.plot_spec as string) || (decodedContent.expression as string) || '';
                  const title = (decodedContent.title as string) || '';
                  const lines: string[] = [];
                  if (title) lines.push(`Plot: ${title}`);
                  if (plotSpec) lines.push(plotSpec);
                  return lines.join('\n') || plotSpec;
                }

                // --- Generic fallback: build readable text from scalar fields ---
                // Produces a readable plain-text representation of decodedContent so every
                // embed type gets a working Copy button automatically.
                const SKIP_KEYS = new Set([
                  'aes_key', 'aes_nonce', 's3_key', 's3_base_url', 'iv',
                  'thumbnail_s3_key', 'screenshot_s3_keys', 'thumbnail_url',
                ]);
                const TITLE_KEYS = ['title', 'query', 'name', 'prompt', 'expression', 'plot_spec'];

                const titleLines: string[] = [];
                for (const key of TITLE_KEYS) {
                  const v = decodedContent[key];
                  if (typeof v === 'string' && v.trim()) {
                    titleLines.push(`${key}: ${v.trim()}`);
                  }
                }
                const bodyLines: string[] = [];
                for (const [key, val] of Object.entries(decodedContent)) {
                  if (SKIP_KEYS.has(key)) continue;
                  if (TITLE_KEYS.includes(key)) continue;
                  if (typeof val === 'string' && val.trim()) {
                    bodyLines.push(`${key}: ${val.trim()}`);
                  } else if (typeof val === 'number') {
                    bodyLines.push(`${key}: ${val}`);
                  }
                }
                const allLines = [...titleLines, ...bodyLines];
                return allLines.join('\n') || JSON.stringify(decodedContent, null, 2);
              })
          );

          // Initiate clipboard write SYNCHRONOUSLY (preserves Safari gesture token).
          const copyDone = writeEmbedToClipboard(snapshotAttrs, contentPromise);

          // Now await content + copy completion to surface errors and show notification.
          const plainText = await contentPromise;
          await copyDone;

          const { notificationStore } = await import('../stores/notificationStore');
          if (plainText) {
            notificationStore.success('Copied to clipboard');
          }
        } else {
          // --- Non-copy actions: download etc. (no gesture-token requirement) ---
          // Resolve embed data sequentially — these actions don't touch the clipboard.
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

          // --- Docs: download (docx) ---
          else if (selectedAppId === 'docs' && action === 'download') {
            const htmlContent = (decodedContent.html as string) || '';
            const docTitle = (decodedContent.title as string) || '';
            const docFilename = (decodedContent.filename as string) || docTitle || 'document';
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

          // --- Sheets: download (TSV) ---
          // Tab-separated format: pastes directly as separate cells in Excel / Google Sheets.
          // File extension is .tsv; most spreadsheet apps recognise it without an import dialog.
          else if (selectedAppId === 'sheets' && action === 'download') {
            const tableContent = (decodedContent.code as string) || (decodedContent.table as string) || '';
            const sheetTitle = (decodedContent.title as string) || 'table';
            if (tableContent) {
              const lines = tableContent.split('\n').filter((l: string) => l.trim() && !l.trim().match(/^[\s|:-]+$/));
              const tsv = lines.map((line: string) =>
                line.split('|')
                  .map((cell: string) => cell.trim())
                  .filter((cell: string) => cell !== '')
                  .join('\t')
              ).join('\n');
              const blob = new Blob([tsv], { type: 'text/tab-separated-values;charset=utf-8;' });
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url;
              a.download = `${sheetTitle.replace(/[^a-z0-9]/gi, '_').toLowerCase()}.tsv`;
              document.body.appendChild(a);
              a.click();
              document.body.removeChild(a);
              URL.revokeObjectURL(url);
              const { notificationStore } = await import('../stores/notificationStore');
              notificationStore.success('Table downloaded');
            }
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
    // Handle other actions for direct-type embeds (sheets-sheet, docs-doc, code-code, etc.)
    // and legacy embed types that are not app-skill-use.
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

        case 'copy': {
          // Use snapshotAttrs (captured at function start) — selectedNode is nulled
          // by the EmbedContextMenu onClose before this async path completes.
          //
          // Safari gesture-token pattern: build a Promise<string> for the content,
          // call writeEmbedToClipboard IMMEDIATELY (no await before it), then await
          // to surface errors and show a notification.
          const embedType = snapshotAttrs?.type as string | undefined;
          const contentRef = snapshotAttrs?.contentRef as string | undefined;
          const embedId = contentRef?.startsWith('embed:') ? contentRef.replace('embed:', '') : null;

          if (embedId) {
            // Build content promise without awaiting.
            const contentPromise: Promise<string> = import('../services/embedResolver').then(
              ({ resolveEmbed, decodeToonContent }) =>
                resolveEmbed(embedId).then(async (embedData): Promise<string> => {
                  const decodedContent = embedData?.content
                    ? (typeof embedData.content === 'string'
                        ? await decodeToonContent(embedData.content)
                        : embedData.content as Record<string, unknown>)
                    : null;

                  if (!decodedContent) return '';

                  if (embedType === 'sheets-sheet' || embedType === 'sheets-sheet-group') {
                    const tableContent = (decodedContent.code as string) || (decodedContent.table as string) || '';
                    if (!tableContent) return '';
                    const lines = tableContent.split('\n').filter((l: string) => l.trim() && !l.trim().match(/^[\s|:-]+$/));
                    return lines.map((line: string) =>
                      line.split('|')
                        .map((cell: string) => cell.trim())
                        .filter((cell: string) => cell !== '')
                        .map((cell: string) => `"${cell.replace(/"/g, '""')}"`)
                        .join(',')
                    ).join('\n');
                  }
                  if (embedType === 'docs-doc') {
                    const htmlContent = (decodedContent.html as string) || '';
                    if (!htmlContent) return '';
                    const tempDiv = document.createElement('div');
                    tempDiv.innerHTML = htmlContent;
                    return tempDiv.textContent || tempDiv.innerText || '';
                  }
                  if (embedType === 'code-code' || embedType?.startsWith('code-')) {
                    return (decodedContent.code as string) || (decodedContent.content as string) || '';
                  }
                  // Generic: extract readable scalar fields, skip internal keys
                  const SKIP_KEYS = new Set(['aes_key', 'aes_nonce', 's3_key', 's3_base_url', 'iv', 'thumbnail_s3_key', 'screenshot_s3_keys', 'thumbnail_url']);
                  return Object.entries(decodedContent)
                    .filter(([k, v]) => !SKIP_KEYS.has(k) && (typeof v === 'string' || typeof v === 'number'))
                    .map(([k, v]) => `${k}: ${v}`)
                    .join('\n');
                })
            );

            try {
              // Initiate clipboard write SYNCHRONOUSLY (preserves Safari gesture token).
              const copyDone = writeEmbedToClipboard(snapshotAttrs, contentPromise);

              const plainText = await contentPromise;
              await copyDone;

              if (plainText) {
                const { notificationStore } = await import('../stores/notificationStore');
                notificationStore.success('Copied to clipboard');
              } else {
                // Fallback: legacy embeds may have url or src
                const legacyUrl = (snapshotAttrs as unknown as Record<string, unknown>).url as string | undefined;
                if (legacyUrl) {
                  await writeEmbedToClipboard(snapshotAttrs, legacyUrl);
                  const { notificationStore } = await import('../stores/notificationStore');
                  notificationStore.success('Copied to clipboard');
                }
              }
            } catch (err) {
              console.error('[ChatMessage] Error copying direct-type embed:', err);
              const { notificationStore } = await import('../stores/notificationStore');
              notificationStore.error('Failed to copy');
            }
          } else {
            // Legacy embeds with no contentRef: copy url if available.
            // Already known synchronously — no gesture-token issue.
            const legacyUrl = (snapshotAttrs as unknown as Record<string, unknown>).url as string | undefined;
            if (legacyUrl) {
              await writeEmbedToClipboard(snapshotAttrs, legacyUrl);
            }
          }
          break;
        }
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
  let messageStatusText = $derived(status === 'sending' ? $text('enter_message.sending') :
                      status === 'waiting_for_internet' ? $text('enter_message.waiting_for_internet') :
                      status === 'waiting_for_upload' ? $text('enter_message.waiting_for_upload') : '');

  // Reactive embed upload progress for messages with status 'waiting_for_upload'.
  // Reads from the global pendingUploadStore and derives the list of per-embed
  // progress entries that belong to THIS message (matched by messageId).
  let uploadEmbedProgressList = $derived((() => {
    if (status !== 'waiting_for_upload' || !original_message?.message_id) return [] as EmbedProgress[];
    const allPending = $pendingUploadStore;
    const chatId = original_message.chat_id as string | undefined;
    if (!chatId) return [] as EmbedProgress[];
    const queue = allPending.get(chatId);
    if (!queue) return [] as EmbedProgress[];
    // Find the pending send whose messageId matches this message
    const ctx = queue.find(c => c.messageId === original_message.message_id);
    if (!ctx) return [] as EmbedProgress[];
    return Array.from(ctx.embedProgress.values()) as EmbedProgress[];
  })());

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

{#if effectiveRole === 'system'}
  <!-- System message: rendered as a smaller centered notice (e.g., reminders, insufficient credits) -->
  <!-- NOTE: content may be TipTap JSON (converted by G_mapToInternalMessage), so we prefer
       the original plaintext from original_message.content for display.
       Uses effectiveRole instead of role so that legacy assistant messages with
       waiting_for_user status (persisted before role fix) also render as system notices. -->
  <div class="chat-message system" class:compression-summary={isCompressionSummary}>
    {#if isCompressionSummary}
      <!-- Compression summary: wider card with expand/collapse.
           Rendered as a styled card instead of the small centered notice. -->
      <div class="compression-summary-card">
        <div class="compression-summary-header">
          <span class="compression-summary-icon">&#x1F4DD;</span>
          <span class="compression-summary-title">{$text('chat.compression.summary_title')}</span>
        </div>
        <div class="compression-summary-body" class:expanded={compressionExpanded}>
          <pre class="compression-summary-text">{compressionPreviewLines}</pre>
        </div>
        {#if compressionNeedsExpand}
          <button
            class="compression-summary-toggle"
            onclick={() => { compressionExpanded = !compressionExpanded; }}
          >
            {compressionExpanded ? $text('chat.compression.show_less') : $text('chat.compression.show_more')}
          </button>
        {/if}
      </div>
    {:else}
    <div class="system-message-notice">
      {#if status === 'waiting_for_user' && isCreditsRestored}
        <!-- Credits restored: show positive message + Resend button.
             The original rejection text is replaced so the chat looks clean after recovery. -->
        <span class="system-message-text credits-restored-text">
          {$text('chat.credits_restored_message')}
        </span>
        <button
          class="system-message-action-btn credits-restored-btn"
          onclick={onResend}
        >
          {$text('chat.credits_restored_resend')}
        </button>
      {:else}
        <!-- Normal system message (e.g., credit rejection notice) -->
        <span class="system-message-text">{typeof content === 'string' ? content : (typeof original_message?.content === 'string' ? original_message.content : '')}</span>
        {#if status === 'waiting_for_user'}
          <!-- Credit rejection: show a button to navigate to billing/buy-credits -->
          <button
            class="system-message-action-btn"
            onclick={() => {
              settingsDeepLink.set('billing/buy-credits');
              panelState.openSettings();
            }}
          >
            {$text('chat.insufficient_credits_buy')}
          </button>
        {/if}
      {/if}
    </div>
    {/if}
  </div>
{:else}
<div class="chat-message {effectiveRole}" class:pending={status === 'sending' || status === 'waiting_for_internet'} class:assistant={effectiveRole === 'assistant'} class:user={effectiveRole === 'user'} class:mobile-stacked={effectiveRole === 'assistant' && shouldStackMobile}>
  {#if effectiveRole === 'assistant'}
    <!-- Mate profile image: clickable for real mates (opens mate detail in settings) -->
    {#if isMateClickable}
      <button
        type="button"
        class="mate-profile-link"
        onclick={openMateSettings}
        aria-label={displayName}
        title={displayName}
      >
        <div class="mate-profile {category || 'default'}" class:mate-profile-small-mobile={shouldStackMobile}></div>
      </button>
    {:else}
      <div class="mate-profile {category || 'default'}" class:mate-profile-small-mobile={shouldStackMobile}></div>
    {/if}
  {/if}

  <div class="message-align-{role === 'user' ? 'right' : 'left'}" class:mobile-full-width={role === 'assistant' && shouldStackMobile} class:mobile-compact={role === 'user' && shouldStackMobile}>
    <div 
      bind:this={messageContentElement}
      class="{role === 'user' ? 'user' : 'mate'}-message-content {animated ? 'message-animated' : ''}" 
      style="opacity: {defaultHidden ? '0' : '1'};"
      role="article"
      oncontextmenu={handleMessageContextMenu}
      ontouchstart={handleMessageTouchStart}
      ontouchmove={handleMessageTouchMove}
      ontouchend={handleMessageTouchEnd}
      ontouchcancel={handleMessageTouchEnd}
    >
      {#if role === 'assistant'}
        {#if isMateClickable}
          <button
            type="button"
            class="chat-mate-name chat-mate-name-link"
            onclick={openMateSettings}
          >{displayName}</button>
        {:else}
          <div class="chat-mate-name">{displayName}</div>
        {/if}
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
        
        {#if $chatDebugStore.rawTextMode}
          <!-- Debug mode: render raw stored content without any processing -->
          <pre class="debug-raw-content">{debugRawContent}</pre>
        {:else if showFullMessage && fullContent}
          <ReadOnlyMessage 
              bind:this={readOnlyMessageComponent}
              content={fullContent}
              isStreaming={status === 'streaming'}
              {_embedUpdateTimestamp}
              {selectable}
              {piiMappings}
              {piiRevealed}
              {role}
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
              {role}
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
                  {$text('chat.loading')}
                {:else}
                  {$text('chat.show_full_message')}
                {/if}
              </button>
            {:else}
              <button 
                class="hide-full-message-btn"
                onclick={handleHideFullMessage}
              >
                {$text('chat.hide_full_message')}
              </button>
            {/if}
          </div>
        {/if}
      </div>

      {#if showMenu}
        {@const isFocusMode = menuType === 'focusMode'}
        <!-- Copy is available for all finished embeds outside focus mode.
             Each embed type has a specific handler in handleMenuAction; unknown types
             fall back to a generic decodedContent serializer so every future embed
             automatically gets a working Copy button without any extra wiring. -->
        {@const showCopyAction = !isFocusMode}
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
            selectedDomEmbedId = null;
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
           onDelete={messageId && !isFirstMessage ? handleDeleteMessage : undefined}
           disableDelete={isFirstMessage}
           onFork={handleFork}
           disableFork={isForkDisabled}
           {messageId}
           {userMessageId}
           {role}
         />
       {/if}
    </div>
    {#if role === 'assistant' && model_name}
      <div class="generated-by-container">
        <button class="generated-by" style="all: unset; cursor: pointer; font-size: 14px; color: var(--color-grey-60);" onclick={handleGeneratedByClick}>{$text('chat.generated_by', { values: { model: getModelDisplayName(model_name) } })}</button>
        <button 
          class="report-bad-answer-btn" 
          class:hovered={isReportHovered}
          onmouseenter={() => isReportHovered = true}
          onmouseleave={() => isReportHovered = false}
          onclick={handleReportBadAnswer}
          aria-label={$text('chat.report_bad_answer.button_text')}
        >
          <div class="clickable-icon icon_thumbsdown"></div>
          {#if isReportHovered}
            <span class="report-text" in:fade={{ duration: 150 }}>
              {$text('chat.report_bad_answer.button_text')}
            </span>
          {/if}
        </button>
      </div>
    {/if}
    {#if role === 'assistant' && hasEmbedErrors}
      <div class="embed-error-banner">
        <span class="embed-error-text">
          {$text('chat.embed_error.message')}
          <span class="embed-error-link" onclick={handleReportEmbedError} onkeydown={(e) => { if (e.key === 'Enter') handleReportEmbedError(); }} role="button" tabindex="0">
            {$text('chat.embed_error.report_link')}
          </span>
        </span>
      </div>
    {/if}
    {#if messageStatusText}
      <div class="message-status">
        {messageStatusText}
      </div>
    {/if}
    {#if status === 'waiting_for_upload' && uploadEmbedProgressList.length > 0}
      <!-- Per-embed upload progress bars shown under queued messages -->
      <div class="upload-progress-list">
        {#each uploadEmbedProgressList as embedProg (embedProg.embedId)}
          <div class="upload-progress-item">
            <span class="upload-progress-label">{embedProg.label}</span>
            {#if embedProg.status === 'uploading'}
              <span class="upload-progress-text">
                {$text('enter_message.upload_progress.uploading', { values: { percent: embedProg.uploadPercent } })}
              </span>
              <div class="upload-progress-bar-track">
                <div class="upload-progress-bar-fill" style="width: {embedProg.uploadPercent}%"></div>
              </div>
            {:else if embedProg.status === 'transcribing'}
              <span class="upload-progress-text">{$text('enter_message.upload_progress.transcribing')}</span>
            {:else if embedProg.status === 'processing'}
              <span class="upload-progress-text">{$text('enter_message.upload_progress.processing')}</span>
            {:else if embedProg.status === 'error'}
              <span class="upload-progress-text upload-progress-error">{$text('enter_message.upload_progress.error')}</span>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
    
    <!-- App Settings & Memories action summary (only for user messages) -->
    <!-- This data comes from system messages stored in chat history and synced across devices -->
    <!-- Display name and icon are loaded client-side from app metadata (not stored in message) -->
    {#if role === 'user' && appSettingsMemoriesResponse}
      <div class="app-settings-memories-summary">
        {#if appSettingsMemoriesResponse.action === 'included' && appSettingsMemoriesResponse.categories}
          <span class="summary-label">{$text('chat.permissions.included_summary')}:</span>
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
                  size="18px"
                  noAnimation={true}
                />
                <span class="badge-text">{getCategoryDisplayName(cat)} ({cat.entryCount})</span>
              </button>
            {/each}
          </div>
        {:else if appSettingsMemoriesResponse.action === 'rejected'}
          <span class="summary-rejected">{$text('chat.permissions.rejected_summary')}</span>
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

  /* Action button inside system message notices (e.g., "Buy Credits" for insufficient credits).
     display:block ensures it appears on its own line below the notice text. */
  .system-message-action-btn {
    display: block;
    margin: 8px auto 0;
    padding: 6px 16px;
    font-size: 13px;
    font-weight: 500;
    color: var(--color-text-on-primary, #fff);
    background: var(--color-button-primary, #e65c3a);
    border: none;
    border-radius: 8px;
    cursor: pointer;
    transition: opacity 0.15s ease;
  }

  .system-message-action-btn:hover {
    opacity: 0.85;
  }

  /* Credits-restored variant: positive green tone to signal good news. */
  .credits-restored-text {
    color: var(--color-grey-80, #ccc);
  }

  .credits-restored-btn {
    background: var(--color-success, #28a745);
  }

  /* Compression summary card: wider card with expand/collapse for AI-generated chat summaries.
     Replaces the small centered notice with a readable card showing the summary content. */
  .chat-message.compression-summary {
    justify-content: center;
    padding: 12px 16px;
  }

  .compression-summary-card {
    max-width: 90%;
    width: 600px;
    background: var(--color-grey-15, rgba(255, 255, 255, 0.05));
    border: 1px solid var(--color-grey-20, rgba(255, 255, 255, 0.08));
    border-radius: 16px;
    padding: 16px 20px;
    text-align: left;
  }

  .compression-summary-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
  }

  .compression-summary-icon {
    font-size: 16px;
    line-height: 1;
  }

  .compression-summary-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-grey-80, #ccc);
  }

  .compression-summary-body {
    overflow: hidden;
  }

  .compression-summary-text {
    font-family: inherit;
    font-size: 13px;
    line-height: 1.5;
    color: var(--color-grey-60, #888);
    white-space: pre-wrap;
    word-wrap: break-word;
    margin: 0;
    padding: 0;
    background: none;
    border: none;
  }

  .compression-summary-toggle {
    display: block;
    margin-top: 8px;
    padding: 4px 0;
    font-size: 12px;
    font-weight: 500;
    color: var(--color-button-primary, #e65c3a);
    background: none;
    border: none;
    cursor: pointer;
    transition: opacity 0.15s ease;
  }

  .compression-summary-toggle:hover {
    opacity: 0.7;
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

  /* Note: .mate-message-content.highlighted and @keyframes highlight-animation have been
   * removed. Clicking a search result now highlights the matched text (mark.search-match-active)
   * instead of blinking the entire message bubble. See match-pulse keyframes near search-match CSS. */

  /* In-chat search text highlighting — <mark class="search-match"> injected via DOM.
   * Uses a yellow background highlight instead of color change.
   * Must override the global `mark` rule in fonts.css which uses -webkit-text-fill-color:transparent
   * (gradient text effect). That property takes priority over `color` in WebKit/Blink, making the
   * text invisible unless we explicitly reset it here. */
  :global(mark.search-match) {
    background: none;
    background-color: rgba(255, 213, 0, 0.4);
    /* Reset WebKit gradient-text trick from global mark rule in fonts.css */
    -webkit-background-clip: unset;
    background-clip: unset;
    -webkit-text-fill-color: unset;
    color: inherit;
    font-weight: inherit;
    border-radius: 2px;
    padding: 1px 0;
  }

  /* When a search result is clicked, pulse the matched text to higher opacity and back */
  :global(mark.search-match.search-match-active) {
    animation: match-pulse 1.2s ease-out forwards;
  }

  @keyframes match-pulse {
    0%   { background-color: rgba(255, 213, 0, 0.9); }
    60%  { background-color: rgba(255, 213, 0, 0.9); }
    100% { background-color: rgba(255, 213, 0, 0.4); }
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

  /* Debug mode: raw text view of stored message content */
  .debug-raw-content {
    font-family: monospace;
    font-size: 0.8rem;
    white-space: pre-wrap;
    word-break: break-all;
    background-color: var(--color-grey-10);
    color: var(--color-font-primary);
    border: 1px solid var(--color-grey-30);
    border-radius: 6px;
    padding: 10px 12px;
    margin: 0;
    line-height: 1.5;
    overflow-x: auto;
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

  /* Upload progress list shown under waiting_for_upload messages */
  .upload-progress-list {
    margin-top: 6px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .upload-progress-item {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  .upload-progress-label {
    font-size: 11px;
    color: var(--color-font-secondary);
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex-shrink: 0;
  }

  .upload-progress-text {
    font-size: 11px;
    color: var(--color-font-tertiary);
    flex-shrink: 0;
  }

  .upload-progress-error {
    color: var(--color-error, #e53935);
  }

  .upload-progress-bar-track {
    flex: 1;
    min-width: 40px;
    height: 3px;
    background: var(--color-grey-20, rgba(255, 255, 255, 0.12));
    border-radius: 2px;
    overflow: hidden;
  }

  .upload-progress-bar-fill {
    height: 100%;
    background: var(--color-primary);
    border-radius: 2px;
    transition: width 0.2s ease;
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
    margin-top: 6px;
    padding: 0;
    text-align: right;
    font-size: 12px;
    color: var(--color-grey-60);
  }
  
  .summary-label {
    display: block;
    margin-bottom: 4px;
    font-weight: 500;
  }
  
  .summary-categories {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 4px;
  }
  
  .category-badge {
    /* Reset global button styles */
    all: unset;
    /* Re-apply only what we need */
    box-sizing: border-box;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    background: var(--color-grey-15, #f5f5f5);
    border-radius: 8px;
    padding: 2px 8px 2px 4px;
    cursor: pointer;
    transition: background-color 0.15s ease;
  }
  
  .category-badge:hover {
    background: var(--color-grey-20, #e8e8e8);
  }
  
  .badge-text {
    font-size: 11px;
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
