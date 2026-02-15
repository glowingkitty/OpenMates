<script lang="ts">
  import { createEventDispatcher, tick, onMount, onDestroy } from "svelte"; // Removed afterUpdate for runes mode compatibility
  import type { SvelteComponent } from 'svelte';
  import { flip } from 'svelte/animate';
  import ChatMessage from "./ChatMessage.svelte";
  import { fade } from "svelte/transition";
  import type { MessageStatus, ProcessingPhase } from '../types/chat'; // Import global MessageStatus and ProcessingPhase

  // Define the internal Message type for ChatHistory's own state,
  // tailored for what ChatMessage.svelte needs.
  // This should align with the global Message type from ../types/chat
  import type { Message as GlobalMessage, MessageRole } from '../types/chat';
  import { preprocessTiptapJsonForEmbeds } from './enter_message/utils/tiptapContentProcessor';
  import { parse_message } from '../message_parsing/parse_message';
  import { truncateTiptapContent } from '../utils/messageTruncation';
  import { restorePIIInText } from './enter_message/services/piiDetectionService';
  import type { PIIMapping } from '../types/chat';
  import { piiVisibilityStore } from '../stores/piiVisibilityStore';
  import { locale } from 'svelte-i18n';
  import { contentCache } from '../utils/contentCache';
  import { getDemoMessages, isPublicChat, DEMO_CHATS, LEGAL_CHATS } from '../demo_chats'; // Import demo chat utilities for re-fetching on locale change
  import { messageHighlightStore } from '../stores/messageHighlightStore';
  import type { 
    AppSettingsMemoriesResponseContent,
    AppSettingsMemoriesRequestContent
  } from '../services/chatSyncServiceHandlersAppSettings';
  import type { SuggestedSettingsMemoryEntry } from '../types/apps';
  
  // Import the permission dialog component and its store for inline rendering
  // The permission dialog is rendered as part of the chat history (scrollable with messages)
  // rather than as a fixed overlay, so users can scroll while the dialog is visible
  import AppSettingsMemoriesPermissionDialog from './AppSettingsMemoriesPermissionDialog.svelte';
  import SettingsMemoriesSuggestions from './SettingsMemoriesSuggestions.svelte';
  import { 
    appSettingsMemoriesPermissionStore,
    isPermissionDialogVisible,
    currentPermissionRequest
  } from '../stores/appSettingsMemoriesPermissionStore';
  import type { PendingPermissionRequest, AppSettingsMemoriesCategory } from '../services/chatSyncServiceHandlersAppSettings';
  import { formatDisplayName, getAppGradient } from '../services/chatSyncServiceHandlersAppSettings';

  type AppCardData = {
    component: new (...args: unknown[]) => SvelteComponent;
    props: Record<string, unknown>;
  };

  type TiptapDoc = {
    type: 'doc';
    content: Array<Record<string, unknown>>;
  };

  interface InternalMessage {
    id: string; // Derived from message_id
    role: MessageRole;
    category?: string;
    sender_name?: string; // Actual name of the mate
    model_name?: string; // Model name for AI messages
    content: unknown; // Tiptap JSON content (shape varies by embed nodes)
    status?: MessageStatus; // Status of the message
    is_truncated?: boolean; // Flag indicating if content is truncated
    full_content_length?: number; // Length of full content for reference
    original_message?: GlobalMessage; // Store original message for full content loading
    appCards?: AppCardData[]; // App skill preview cards (rendered by ChatMessage)
    _embedUpdateTimestamp?: number; // Forces re-render when embed data becomes available
    _embedErrors?: Set<string>; // Embed IDs that errored (tracked by ActiveChat for error banners)
    appSettingsMemoriesResponse?: AppSettingsMemoriesResponseContent; // Response to user's app settings/memories request
    pii_mappings?: PIIMapping[]; // PII mappings for restoration (from user message)
  }

  // Add optional embed/app-card metadata without widening the core message type.
  type MessageWithEmbedMetadata = GlobalMessage & {
    appCards?: AppCardData[];
    _embedUpdateTimestamp?: number;
    _embedErrors?: Set<string>;
  };

  /**
   * Build a cumulative PII mappings lookup from all user messages in the chat.
   * This allows assistant messages to restore PII from any preceding user message.
   * 
   * The approach: Aggregate all PII mappings from user messages, keyed by placeholder.
   * Later messages with the same placeholder override earlier ones (unlikely but handled).
   */
  function buildCumulativePIIMappings(allMessages: GlobalMessage[]): Map<string, PIIMapping> {
    const cumulativeMappings = new Map<string, PIIMapping>();
    
    for (const msg of allMessages) {
      if (msg.role === 'user' && msg.pii_mappings && msg.pii_mappings.length > 0) {
        for (const mapping of msg.pii_mappings) {
          cumulativeMappings.set(mapping.placeholder, mapping);
        }
      }
    }
    
    return cumulativeMappings;
  }

  /**
   * Returns true if the message content (markdown string) contains a focus_mode_activation embed reference.
   */
  function hasFocusModeActivationEmbed(content: unknown): boolean {
    if (typeof content !== 'string') return false;
    return content.includes('"type":"focus_mode_activation"') || content.includes('"type": "focus_mode_activation"');
  }

  /**
   * Merge consecutive assistant messages for display when the previous is a focus mode activation.
   * Backend stores two messages (focus embed, then continuation text). We show one bubble.
   */
  function mergeFocusContinuationForDisplay(incoming: GlobalMessage[]): GlobalMessage[] {
    const result: GlobalMessage[] = [];
    for (let i = 0; i < incoming.length; i++) {
      const prev = result[result.length - 1];
      const curr = incoming[i];
      if (
        prev?.role === 'assistant' &&
        curr.role === 'assistant' &&
        hasFocusModeActivationEmbed(prev.content)
      ) {
        const prevContent = typeof prev.content === 'string' ? prev.content : '';
        const currContent = typeof curr.content === 'string' ? curr.content : '';
        result[result.length - 1] = {
          ...curr,
          message_id: prev.message_id,
          content: prevContent + (prevContent && currContent ? '\n\n' : '') + currContent,
        };
      } else {
        result.push(curr);
      }
    }
    return result;
  }

  /**
   * Restore PII placeholders in markdown content using the provided mappings.
   * Returns the markdown with placeholders replaced by highlighted original values.
   */
  function restorePIIInMarkdown(
    markdown: string, 
    mappings: Map<string, PIIMapping>
  ): string {
    if (mappings.size === 0) return markdown;
    
    // Convert Map to array for the restorePIIInText function
    const mappingsArray = Array.from(mappings.values());
    return restorePIIInText(markdown, mappingsArray);
  }

  // Helper function to map incoming message structure to InternalMessage
  // IMPORTANT: piiMappings parameter is optional - when provided, PII restoration is applied
  function G_mapToInternalMessage(
    incomingMessage: GlobalMessage,
    piiMappings?: Map<string, PIIMapping>
  ): InternalMessage {
    // incomingMessage.content is now a markdown string (never Tiptap JSON on server!)
    // We need to convert it to Tiptap JSON for display purposes
    let processedContent: unknown;
    
    if (typeof incomingMessage.content === 'string') {
      let contentToProcess = incomingMessage.content;
      
      // PII RESTORATION: Restore PII placeholders with original values before parsing
      // This applies to both user and assistant messages when mappings are available
      if (piiMappings && piiMappings.size > 0) {
        contentToProcess = restorePIIInMarkdown(contentToProcess, piiMappings);
      }
      
      // Content is markdown string - convert to Tiptap JSON with unified parsing (includes embed parsing)
      // CRITICAL FIX: Use 'write' mode for streaming messages to show 'processing' status on embeds
      // This ensures users see "processing" state during streaming instead of waiting for embed data
      const parseMode = incomingMessage.status === 'streaming' ? 'write' : 'read';
      const tiptapJson = parse_message(contentToProcess, parseMode, { unifiedParsingEnabled: true });
      processedContent = preprocessTiptapJsonForEmbeds(tiptapJson);

      // Apply truncation at TipTap level for user messages to avoid breaking node structure
      if (incomingMessage.role === 'user' && incomingMessage.content.length > 1000) {
        processedContent = truncateTiptapContent(processedContent);
      }
    } else {
      // Fallback for any other format (should not happen with new architecture)
      const maybeDoc = incomingMessage.content;
      const isTiptapDoc = (value: unknown): value is TiptapDoc => {
        return !!value && typeof value === 'object' && (value as { type?: string }).type === 'doc';
      };
      processedContent = preprocessTiptapJsonForEmbeds(isTiptapDoc(maybeDoc) ? maybeDoc : null);
    }

    // Check if message should be truncated (for UI display purposes)
    const shouldTruncate = incomingMessage.role === 'user' && 
                          incomingMessage.content && 
                          typeof incomingMessage.content === 'string' && 
                          incomingMessage.content.length > 1000;

    return {
      id: incomingMessage.message_id,
      role: incomingMessage.role,
      category: incomingMessage.category,
      sender_name: incomingMessage.sender_name,
      model_name: incomingMessage.model_name,
      content: processedContent,
      status: incomingMessage.status,
      is_truncated: shouldTruncate,
      full_content_length: shouldTruncate ? incomingMessage.content.length : 0,
      original_message: incomingMessage, // Store original for full content loading
      appCards: (incomingMessage as MessageWithEmbedMetadata).appCards, // Preserve appCards if present
      _embedUpdateTimestamp: (incomingMessage as MessageWithEmbedMetadata)._embedUpdateTimestamp, // Force re-render when embed data arrives
      _embedErrors: (incomingMessage as MessageWithEmbedMetadata)._embedErrors, // Propagate embed error tracking from ActiveChat
      pii_mappings: incomingMessage.pii_mappings // Preserve PII mappings
    };
  }
 
  // Array that holds all chat messages using $state (Svelte 5 runes mode)
  let messages = $state<InternalMessage[]>([]);

  /**
   * Parse system message content to check if it's an app_settings_memories_response.
   * Returns the parsed content or null if not a valid response.
   */
  function parseAppSettingsMemoriesResponse(content: unknown): AppSettingsMemoriesResponseContent | null {
    if (typeof content !== 'string') {
      console.warn(`[ChatHistory][parseResponse] content is not a string, got: ${typeof content}`, content);
      return null;
    }
    try {
      const parsed = JSON.parse(content);
      if (parsed.type === 'app_settings_memories_response') {
        return parsed as AppSettingsMemoriesResponseContent;
      }
      console.warn(`[ChatHistory][parseResponse] parsed JSON but type was '${parsed.type}', not 'app_settings_memories_response'`);
    } catch (e) {
      console.warn(`[ChatHistory][parseResponse] JSON.parse failed for content (length=${content.length}):`, content.substring(0, 200), e);
    }
    return null;
  }

  /**
   * Parse system message content to check if it's an app_settings_memories_request.
   * Returns the parsed content or null if not a valid request.
   */
  function parseAppSettingsMemoriesRequest(content: unknown): AppSettingsMemoriesRequestContent | null {
    if (typeof content !== 'string') {
      console.warn(`[ChatHistory][parseRequest] content is not a string, got: ${typeof content}`, content);
      return null;
    }
    try {
      const parsed = JSON.parse(content);
      if (parsed.type === 'app_settings_memories_request') {
        return parsed as AppSettingsMemoriesRequestContent;
      }
    } catch {
      // Not valid JSON, ignore
    }
    return null;
  }

  /**
   * Helper to read thinking entries from the map with a stable signature.
   * This keeps template logic concise and avoids unsupported {@const} placement.
   */
  function getThinkingEntry(messageId: string | undefined) {
    if (!messageId) return undefined;
    return thinkingContentByTask.get(messageId);
  }

  /**
   * Derived state: Create a lookup map of user_message_id → app settings/memories REQUEST.
   * System messages with type 'app_settings_memories_request' contain the request metadata
   * (requested_keys, categories) and should be displayed as part of the user's message, not separately.
   * 
   * Used together with appSettingsMemoriesResponseMap to detect "unpaired" requests
   * (a request without a matching response) which indicates a pending permission dialog.
   * 
   * IMPORTANT: Both this map and the response map use user_message_id from the system message
   * content as the key. This ensures symmetric lookup — a request and its response always
   * map to the same key, preventing false "unpaired" detection.
   */
  let appSettingsMemoriesRequestMap = $derived.by(() => {
    const map = new Map<string, AppSettingsMemoriesRequestContent>();
    
    // Debug: count system messages to understand what we're working with
    const systemMessages = messages.filter(m => m.role === 'system');
    if (systemMessages.length > 0) {
      console.log(`[ChatHistory][RequestMap] Processing ${messages.length} messages (${systemMessages.length} system). System msgs:`,
        systemMessages.map(m => ({
          id: m.id,
          hasOriginal: !!m.original_message,
          hasContent: !!m.original_message?.content,
          contentType: typeof m.original_message?.content,
          contentPreview: typeof m.original_message?.content === 'string' ? m.original_message.content.substring(0, 80) : undefined
        }))
      );
    }
    
    for (const msg of messages) {
      if (msg.role === 'system') {
        const request = parseAppSettingsMemoriesRequest(msg.original_message?.content);
        if (request) {
          map.set(request.user_message_id, request);
        }
      }
    }
    
    if (map.size > 0) {
      console.log(`[ChatHistory][RequestMap] Found ${map.size} request(s):`, [...map.keys()]);
    }
    
    return map;
  });

  /**
   * Derived state: Create a lookup map of user_message_id → app settings/memories response.
   * System messages with type 'app_settings_memories_response' contain the user's decision
   * (included/rejected) and should be displayed as part of the user's message, not separately.
   * 
   * IMPORTANT: Uses user_message_id from the system message content directly as the key,
   * matching the same strategy as the request map. Both request and response system messages
   * store the same user_message_id (the client-generated ID of the triggering user message),
   * so using it directly ensures they always pair correctly.
   * 
   * FALLBACK: If user_message_id is missing from the response content (should not happen
   * in normal flow), falls back to position-based association with the nearest preceding
   * user message.
   */
  let appSettingsMemoriesResponseMap = $derived.by(() => {
    const map = new Map<string, AppSettingsMemoriesResponseContent>();
    
    for (let i = 0; i < messages.length; i++) {
      const msg = messages[i];
      if (msg.role === 'system') {
        const response = parseAppSettingsMemoriesResponse(msg.original_message?.content);
        if (response) {
          console.log(`[ChatHistory][ResponseMap] Found response:`, { user_message_id: response.user_message_id, action: response.action, msgId: msg.id });
          // Use user_message_id directly as the map key — same strategy as the request map.
          // Both request and response system messages store the same user_message_id
          // (the client-generated ID of the user message that triggered the request).
          if (response.user_message_id) {
            map.set(response.user_message_id, response);
          } else {
            // FALLBACK: user_message_id is missing (should not happen in normal flow).
            // Fall back to position-based association with the nearest preceding user message.
            for (let j = i - 1; j >= 0; j--) {
              if (messages[j].role === 'user') {
                map.set(messages[j].id, response);
                console.warn(
                  `[ChatHistory] Response system message missing user_message_id, ` +
                  `fell back to position-based mapping with user message ${messages[j].id}`
                );
                break;
              }
            }
          }
        }
      }
    }
    
    if (map.size > 0) {
      console.log(`[ChatHistory][ResponseMap] Found ${map.size} response(s):`, [...map.keys()]);
    }
    
    return map;
  });

  /**
   * Derived state: Cumulative PII mappings from all user messages.
   * Passed to every ChatMessage so ReadOnlyMessage can apply decorations
   * to highlight restored PII values in both user and assistant messages.
   */
  let cumulativePIIMappingsArray = $derived.by(() => {
    const allMappings: PIIMapping[] = [];
    for (const msg of messages) {
      if (msg.role === 'user' && msg.pii_mappings && msg.pii_mappings.length > 0) {
        allMappings.push(...msg.pii_mappings);
      }
    }
    return allMappings;
  });

  /**
   * Derived state: Filter out system messages for app_settings_memories request and response.
   * Request system messages drive the permission dialog (not rendered as chat bubbles).
   * Response system messages are displayed as part of the user's message (included/rejected badge).
   */
  let displayMessages = $derived.by(() => {
    return messages.filter(msg => {
      if (msg.role === 'system') {
        const response = parseAppSettingsMemoriesResponse(msg.original_message?.content);
        // Filter out app_settings_memories_response system messages
        if (response?.type === 'app_settings_memories_response') {
          return false;
        }
        const request = parseAppSettingsMemoriesRequest(msg.original_message?.content);
        // Filter out app_settings_memories_request system messages
        if (request?.type === 'app_settings_memories_request') {
          return false;
        }
      }
      return true;
    });
  });

  // Show/hide the messages block for fade-out animation using $state (Svelte 5 runes mode)
  let showMessages = $state(true);

  // Reference to the chat history container for scrolling.
  let container: HTMLDivElement;

  // Props using Svelte 5 runes mode
  let {
    messageInputHeight = 0,
    containerWidth = 0,
    currentChatId = undefined,
    processingPhase = null,
    thinkingContentByTask = new Map(),
    settingsMemoriesSuggestions = [],
    rejectedSuggestionHashes = null,
    onSuggestionAdded = undefined,
    onSuggestionRejected = undefined,
    onSuggestionOpenForCustomize = undefined
  }: {
    messageInputHeight?: number;
    containerWidth?: number;
    currentChatId?: string; // Current active chat ID - used to ensure permission dialog only shows in the originating chat
    processingPhase?: ProcessingPhase; // Current phase of the AI processing pipeline (sending → processing → typing → null)
    thinkingContentByTask?: Map<string, { content: string; isStreaming: boolean; signature?: string | null; totalTokens?: number | null }>; // Thinking content from thinking models
    settingsMemoriesSuggestions?: SuggestedSettingsMemoryEntry[]; // Suggested settings/memories entries from AI post-processing
    rejectedSuggestionHashes?: string[] | null; // SHA-256 hashes of rejected suggestions for client-side filtering
    onSuggestionAdded?: (suggestion: SuggestedSettingsMemoryEntry) => void; // Callback when user adds a suggestion
    onSuggestionRejected?: (suggestion: SuggestedSettingsMemoryEntry) => void; // Callback when user rejects a suggestion
    onSuggestionOpenForCustomize?: (suggestion: SuggestedSettingsMemoryEntry) => void; // Callback when user opens suggestion to customize (deep link to create form)
  } = $props();

  // Add reactive statement to handle height changes using $derived (Svelte 5 runes mode)
  let containerStyle = $derived(`bottom: ${messageInputHeight-30}px`);

  // PII visibility: derive whether PII is revealed for the current chat.
  // Default is false (hidden) — user must explicitly toggle to reveal sensitive data.
  let piiRevealedMap = $state<Map<string, boolean>>(new Map());
  // Subscribe to the store to keep piiRevealedMap in sync
  const unsubPiiVisibility = piiVisibilityStore.subscribe(map => {
      piiRevealedMap = map;
  });
  let piiRevealed = $derived(currentChatId ? (piiRevealedMap.get(currentChatId) ?? false) : false);
  
  // CRITICAL: Only show permission dialog if it belongs to the current chat
  // This prevents the dialog from showing in the wrong chat when user switches chats
  // The dialog's chatId must match the currently active chat's ID
  let shouldShowPermissionDialog = $derived(
    $isPermissionDialogVisible && 
    $currentPermissionRequest?.chatId && 
    currentChatId && 
    $currentPermissionRequest.chatId === currentChatId
  );

  /**
   * Derived state: Detect unpaired app settings/memories requests.
   * An "unpaired" request is a request system message that has no matching response system message
   * (both reference the same user_message_id). This indicates the user hasn't responded yet.
   *
   * When an unpaired request is detected for the current chat, the permission dialog is shown
   * automatically. This handles the case where the user logs out/in or refreshes while a
   * permission dialog was pending - the dialog re-appears from the persisted system message.
   */
  let unpairedRequest = $derived.by(() => {
    // Find the first unpaired request in this chat's messages
    for (const [userMessageId, request] of appSettingsMemoriesRequestMap) {
      if (!appSettingsMemoriesResponseMap.has(userMessageId)) {
        console.warn(`[ChatHistory][UnpairedRequest] Request for user_message_id="${userMessageId}" has NO matching response. Response map keys:`, [...appSettingsMemoriesResponseMap.keys()]);
        return request;
      } else {
        console.log(`[ChatHistory][UnpairedRequest] Request for user_message_id="${userMessageId}" is PAIRED with response.`);
      }
    }
    return null;
  });

  /**
   * Effect: When an unpaired request is detected and no dialog is currently visible,
   * rebuild the full PendingPermissionRequest and show the dialog via the store.
   * This handles session recovery (logout/login, refresh, cross-device sync).
   */
  $effect(() => {
    if (!unpairedRequest || !currentChatId) return;
    
    // Don't show if a dialog is already visible (either for this request or another)
    if ($isPermissionDialogVisible) return;

    // Rebuild full categories with display info from the persisted minimal metadata
    const fullCategories: AppSettingsMemoriesCategory[] = unpairedRequest.categories.map(cat => ({
      key: `${cat.appId}-${cat.itemType}`,
      appId: cat.appId,
      itemType: cat.itemType,
      displayName: formatDisplayName(cat.itemType),
      entryCount: cat.entryCount,
      iconGradient: getAppGradient(cat.appId),
      selected: true, // Default all to selected when recovering
    }));

    // Rebuild the PendingPermissionRequest for the store
    const recoveredRequest: PendingPermissionRequest = {
      requestId: unpairedRequest.request_id,
      chatId: currentChatId,
      messageId: unpairedRequest.user_message_id,
      categories: fullCategories,
      yamlContent: '', // YAML content not stored in system message (not needed for dialog)
      createdAt: Date.now(),
    };

    console.info(
      `[ChatHistory] Recovered unpaired permission request ${unpairedRequest.request_id} ` +
      `for chat ${currentChatId} - showing dialog`
    );

    appSettingsMemoriesPermissionStore.showDialog(recoveredRequest);
  });

  // Determine if we should show settings/memories suggestions
  // Only show after the last assistant message when:
  // 1. We have suggestions to show
  // 2. We have a current chat ID
  // 3. The last message is from the assistant (not streaming)
  let shouldShowSettingsMemoriesSuggestions = $derived.by(() => {
    if (!settingsMemoriesSuggestions || settingsMemoriesSuggestions.length === 0) return false;
    if (!currentChatId) return false;
    if (displayMessages.length === 0) return false;
    
    // Check if the last message is from the assistant and not streaming
    const lastMessage = displayMessages[displayMessages.length - 1];
    if (lastMessage.role !== 'assistant') return false;
    if (lastMessage.status === 'streaming') return false;
    
    return true;
  });

  const dispatch = createEventDispatcher();

  // CRITICAL: These must be $state() for Svelte 5 reactivity.
  // The scroll $effect at line ~689 reads these variables, and without $state(),
  // changes to them won't trigger re-execution of the effect — breaking the
  // ChatGPT-style scroll that positions the user message near the top after sending.
  let lastUserMessageId = $state<string | null>(null);
  let shouldScrollToNewUserMessage = $state(false);
  let isScrolling = $state(false);
  
  // Track whether the user has manually scrolled away during streaming.
  // When true, spacer height updates are frozen to prevent disrupting the user's scroll position.
  let userHasScrolledAway = $state(false);

  // Detect if any message is currently streaming
  let isCurrentlyStreaming = $derived(
    messages.some(m => m.status === 'streaming')
  );
  
  // Whether to show the centered AI status overlay.
  // Driven by processingPhase prop from ActiveChat (sending → processing → typing → null).
  // The overlay shows status text during all phases and adds the AI icon during processing/typing.
  let showCenteredIndicator = $derived(processingPhase !== null);
  
  // Whether the streaming spacer should be active.
  // The spacer ensures the scroll position remains valid after the user-message scroll
  // positions the user message near the top of the viewport. Without it, there wouldn't
  // be enough scrollable content to hold that scroll position.
  // The spacer is activated when the user sends a message and deactivated when:
  //   - The AI response finishes (no streaming AND no processing phase), OR
  //   - The safety timeout fires (belt-and-suspenders guard against stuck spacers)
  let isSpacerActive = $state(false);

  // The computed spacer height — fills remaining viewport below the AI response.
  // As the AI response grows, the spacer shrinks. Once the response fills the viewport, spacer = 0.
  let spacerHeight = $state(0);

  // Safety timeout handle — ensures the spacer is never stuck indefinitely.
  // Cleared when the spacer is deactivated normally; fires after 60s as a last resort.
  let spacerSafetyTimeout: ReturnType<typeof setTimeout> | null = null;

  /**
   * Exposed function to add a new message to the chat.
   * This is called from the ActiveChat component when a new message is sent.
   *
   * @param incomingMessage - The new message object, likely conforming to global Message type.
   */
  export function addMessage(incomingMessage: GlobalMessage) {
    console.debug('Adding message to chat history (raw):', incomingMessage);
    
    // Build cumulative PII mappings from existing messages + the new message
    // This allows assistant messages to restore PII from any preceding user message
    const allOriginalMessages = [
      ...messages.map(m => m.original_message).filter((m): m is GlobalMessage => m !== undefined),
      incomingMessage
    ];
    const piiMappings = buildCumulativePIIMappings(allOriginalMessages);
    
    const messageForHistory: InternalMessage = G_mapToInternalMessage(incomingMessage, piiMappings);
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
    isSpacerActive = false;
    spacerHeight = 0;
    userHasScrolledAway = false;
    if (spacerSafetyTimeout) { clearTimeout(spacerSafetyTimeout); spacerSafetyTimeout = null; }
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
      isSpacerActive = false;
      spacerHeight = 0;
      userHasScrolledAway = false;
      if (spacerSafetyTimeout) { clearTimeout(spacerSafetyTimeout); spacerSafetyTimeout = null; }
      showMessages = true; // Show the (empty) chat history
      if (outroResolve) {
        outroResolve(); // Resolve the promise
        outroResolve = null; // Reset for next time
      }
    }
  }

  // Track previous locale to detect changes
  let previousLocale = $state($locale || 'en');

  // Add method to update messages
  export function updateMessages(newMessagesArray: GlobalMessage[]) {
    // Check if locale has changed - if so, force re-processing of all messages
    // Use previousLocale to detect changes since currentLocale is $derived
    const newLocale = $locale || 'en';
    const localeChanged = newLocale !== previousLocale;
    if (localeChanged) {
      // DON'T update previousLocale here - update it after processing messages
      // This ensures localeChanged stays true throughout the message processing
      // Clear cache to ensure fresh processing with new locale
      contentCache.clear();
    }
    
    // Update previousLocale AFTER checking localeChanged but BEFORE processing messages
    // This ensures localeChanged flag is preserved during message processing
    if (localeChanged) {
      previousLocale = newLocale;
    }

    const previousMessagesLength = messages.length;
    
    // Display merge: show focus activation + following assistant as one bubble
    const mergedForDisplay = mergeFocusContinuationForDisplay(newMessagesArray);
    
    // Build cumulative PII mappings from all user messages in the incoming array
    // This allows assistant messages to restore PII from any preceding user message
    const piiMappings = buildCumulativePIIMappings(mergedForDisplay);
    
    const newInternalMessages = mergedForDisplay.map(newMessage => {
        const oldMessage = messages.find(m => m.id === newMessage.message_id);
        const newInternalMessage = G_mapToInternalMessage(newMessage, piiMappings);

        // CRITICAL FIX: Skip content optimization for streaming messages AND when locale changes
        // Streaming messages need to re-render on every chunk update
        // When locale changes, we need to re-process content to get correct translations
        // When embed updates occur (_embedUpdateTimestamp changes), force re-render so embeds display
        // If an old message exists and its content is identical to the new one,
        // reuse the old content object reference to prevent unnecessary re-renders
        // of the ReadOnlyMessage component. BUT skip this for streaming messages, locale changes, and embed updates.
        const hasEmbedUpdate = (newMessage as MessageWithEmbedMetadata)._embedUpdateTimestamp !== undefined;
        
        if (oldMessage &&
            !localeChanged &&
            !hasEmbedUpdate &&
            newMessage.status !== 'streaming') {
            // Compare content to see if it's actually different
            const oldContentStr = JSON.stringify(oldMessage.content);
            const newContentStr = JSON.stringify(newInternalMessage.content);
            if (oldContentStr === newContentStr) {
                // Content is identical, reuse old reference for optimization
                newInternalMessage.content = oldMessage.content;
            } else {
                // Content is different - log for debugging
                console.debug('[ChatHistory] Message content changed for', newMessage.message_id);
            }
        } else if (hasEmbedUpdate) {
            // Embed was updated - force new content to re-render embed NodeViews
            console.debug('[ChatHistory] Embed update detected - forcing new content for', newMessage.message_id);
            newInternalMessage.content = JSON.parse(JSON.stringify(newInternalMessage.content));
        } else if (localeChanged) {
            // Locale changed - always use new content even if it appears identical
            // This ensures translations are refreshed
            // CRITICAL: Force new content object reference to break any object equality checks
            // This ensures ReadOnlyMessage detects the change and re-renders
            console.debug('[ChatHistory] Locale changed - forcing new content for', newMessage.message_id);
            // Create a completely new content object to force reactivity
            // This breaks object reference equality, forcing Svelte to detect the change
            newInternalMessage.content = JSON.parse(JSON.stringify(newInternalMessage.content));
        }
        return newInternalMessage;
    });

    // console.debug('[ChatHistory] updateMessages. Mapped newInternalMessages:', JSON.parse(JSON.stringify(newInternalMessages)));
    // console.debug('[ChatHistory] updateMessages. Current internal messages BEFORE update attempt:', JSON.parse(JSON.stringify(messages)));

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
    // console.debug('[ChatHistory] updateMessages: messages array REPLACED (intelligent assignment). New internal messages:', JSON.parse(JSON.stringify(messages)));
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

  // ChatGPT-like scroll behavior: when user sends a message, scroll so that only
  // the LAST LINE of the user message is visible at the top of the viewport.
  // This leaves maximum space below for the assistant's response to render.
  // The scroll target is computed dynamically from the actual rendered line height
  // so it works correctly regardless of viewport width or message length.
  $effect(() => {
    if (container && shouldScrollToNewUserMessage && lastUserMessageId && !isScrolling) {
      isScrolling = true;
      
      // CRITICAL: Activate the spacer FIRST, before scrolling.
      // The spacer adds enough scrollable height to reach the desired scroll position.
      // Without it, the container's scrollHeight may be too small for the target offset.
      isSpacerActive = true;
      // Set an initial spacer height equal to the viewport height to guarantee
      // enough room to scroll the user message to the top.
      spacerHeight = container.clientHeight;

      // Safety timeout: ensure the spacer is never stuck indefinitely.
      // In normal operation the state-based cleanup deactivates it much sooner,
      // but this guards against any edge case where the state signals are missed.
      if (spacerSafetyTimeout) clearTimeout(spacerSafetyTimeout);
      spacerSafetyTimeout = setTimeout(() => {
        if (isSpacerActive) {
          console.warn('[ChatHistory] Spacer safety timeout fired — force-deactivating stuck spacer');
          isSpacerActive = false;
          spacerHeight = 0;
          userHasScrolledAway = false;
        }
        spacerSafetyTimeout = null;
      }, 60_000);

      // Wait for the spacer to render, then calculate and execute the scroll.
      tick().then(() => {
        setTimeout(() => {
          const userMessageElement = container.querySelector(`[data-message-id="${lastUserMessageId}"]`);
          if (userMessageElement) {
            const containerRect = container.getBoundingClientRect();
            const messageRect = userMessageElement.getBoundingClientRect();
            
            // Measure the actual rendered line height from a text paragraph inside the
            // message bubble. This adapts to any font-size / line-height / viewport width.
            // Falls back to 24px (16px * 1.5 line-height) if the element can't be found.
            let lineHeight = 24;
            const paragraph = userMessageElement.querySelector('.ProseMirror p');
            if (paragraph) {
              const computed = window.getComputedStyle(paragraph);
              const parsed = parseFloat(computed.lineHeight);
              if (!isNaN(parsed) && parsed > 0) {
                lineHeight = parsed;
              }
            }

            // We want the scroll position such that only the last line of text
            // (plus the bubble's bottom padding/chrome) peeks above the viewport top.
            // "visiblePortion" = one line of text + bubble bottom padding (12px) + 
            //   bubble tail/shadow clearance (8px)
            const visiblePortion = lineHeight + 20;

            // topOfMessage in scroll coordinates (relative to container's scroll origin)
            const topOfMessage = messageRect.top - containerRect.top + container.scrollTop;
            // Total rendered height of the message wrapper element
            const messageHeight = messageRect.height;

            // Scroll so that the message is pushed up, leaving only visiblePortion showing.
            // scrollTarget = topOfMessage + (messageHeight - visiblePortion)
            const scrollTarget = topOfMessage + messageHeight - visiblePortion;

            container.scrollTo({
              top: Math.max(0, scrollTarget),
              behavior: 'smooth'
            });

            shouldScrollToNewUserMessage = false;

            setTimeout(() => {
              isScrolling = false;
            }, 800);
          } else {
            shouldScrollToNewUserMessage = false;
            isScrolling = false;
          }
        }, 350);
      });
    }
  });

  // --- Spacer lifecycle: deactivate when AI response is complete ---
  // Uses direct state checks instead of transition detection (wasStreaming).
  // The old approach tracked streaming start/end transitions, which failed when:
  //   - Streaming never technically started (fast/cached/error responses)
  //   - Svelte batched the streaming→completed transition in a single tick
  // Now we simply check: is the spacer still needed? It's needed while either
  // processingPhase is active (sending/processing/typing) or a message is streaming.
  // Once both are false and the initial scroll animation is done, cleanup fires.
  $effect(() => {
    if (!isSpacerActive) return;

    // The spacer is needed while we're waiting for or receiving the AI response.
    // processingPhase covers: sending → processing → typing (set by ActiveChat)
    // isCurrentlyStreaming covers: active streaming chunks arriving
    const isWaitingForResponse = processingPhase !== null || isCurrentlyStreaming;

    if (!isWaitingForResponse && !isScrolling) {
      // Response is complete — deactivate spacer
      isSpacerActive = false;
      spacerHeight = 0;
      userHasScrolledAway = false;
      // Clear safety timeout since spacer was deactivated normally
      if (spacerSafetyTimeout) {
        clearTimeout(spacerSafetyTimeout);
        spacerSafetyTimeout = null;
      }
    }
  });

  // --- Spacer height computation ---
  // The spacer ensures the scroll position remains valid after the user-message scroll
  // positions the user message near the top of the viewport.
  //
  // How it works:
  // 1. User sends a message → scroll positions user message near top → isSpacerActive = true
  // 2. AI response starts streaming below the user message
  // 3. The spacer fills the remaining viewport height below the AI response,
  //    preventing the scroll position from jumping as content grows downward
  // 4. As the AI response grows taller, the spacer shrinks toward 0
  // 5. Once streaming ends, the spacer is removed
  //
  // CRITICAL: We do NOT auto-scroll during streaming. The scroll position stays fixed
  // and the user reads the AI response naturally as it extends downward. This avoids
  // interrupting the user's reading flow.
  $effect(() => {
    if (!container || !isSpacerActive) {
      if (!isSpacerActive) spacerHeight = 0;
      return;
    }
    // Re-run whenever messages change (on each streaming chunk)
    // eslint-disable-next-line @typescript-eslint/no-unused-expressions
    messages;

    // If the user has scrolled away to read older messages, freeze the spacer
    // so their scroll position isn't disrupted by the growing AI response.
    if (userHasScrolledAway) return;

    tick().then(() => {
      if (!container || !isSpacerActive || userHasScrolledAway) return;
      
      // Find the last message element (the streaming AI response)
      const messageWrappers = container.querySelectorAll('[data-message-id]');
      if (messageWrappers.length === 0) return;
      const lastMessageEl = messageWrappers[messageWrappers.length - 1] as HTMLElement;
      
      // The spacer fills the gap between the bottom of the last message and
      // the bottom of the viewport. As the AI response grows, the spacer shrinks.
      const viewportHeight = container.clientHeight;
      const lastMessageHeight = lastMessageEl.offsetHeight;
      
      // 80px accounts for the user message offset at top + padding
      const neededSpacer = Math.max(0, viewportHeight - lastMessageHeight - 80);
      spacerHeight = neededSpacer;
    });
  });

  // Handle scrolling to highlighted message from deep link
  $effect(() => {
    if (container && $messageHighlightStore) {
      const messageId = $messageHighlightStore;
      
      // Wait for messages to render
      tick().then(() => {
        const attemptScroll = (attempts = 0) => {
          const targetMessage = container.querySelector(`[data-message-id="${messageId}"]`);
          
          if (targetMessage) {
            const messageTop = (targetMessage as HTMLElement).offsetTop;
            // Scroll so the message has 100px offset from top
            const scrollPosition = Math.max(0, messageTop - 100);
            
            container.scrollTo({
              top: scrollPosition,
              behavior: 'smooth'
            });
            console.debug(`[ChatHistory] Scrolled to highlighted message ${messageId}`);
          } else if (attempts < 10) {
            // Message not found yet, try again after a short delay
            setTimeout(() => attemptScroll(attempts + 1), 100);
          }
        };
        
        attemptScroll();
      });
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
  
  export function scrollToBottom(smooth = false) {
    if (container) {
      container.scrollTo({
        top: container.scrollHeight,
        behavior: smooth ? 'smooth' : 'auto' // Instant by default for programmatic calls; smooth for user-initiated
      });
    } else {
      console.warn("[ChatHistory] Container not found");
    }
  }

  // Scroll position tracking for cross-device sync
  let scrollDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  let isRestoringScroll = false;
  let scrollFrame: number | null = null;

  // Track scroll position with optimized performance using requestAnimationFrame
  // This ensures smooth scrolling without blocking the main thread
  function handleScroll() {
    // Don't track scroll position during restoration
    if (isRestoringScroll) return;

    // Detect if user has manually scrolled away during streaming.
    // If streaming is active and the user scrolls upward (away from the bottom),
    // freeze spacer updates so their scroll position isn't disrupted.
    if (isCurrentlyStreaming && container) {
      const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
      // If user scrolled more than 150px from the bottom, they're reading older messages
      if (distanceFromBottom > 150) {
        userHasScrolledAway = true;
      } else {
        userHasScrolledAway = false;
      }
    }

    // Performance optimization: Use requestAnimationFrame for immediate UI updates
    // This ensures smooth, jank-free scrolling by syncing with browser repaint cycle
    if (scrollFrame) return; // Skip if frame already scheduled
    
    scrollFrame = requestAnimationFrame(() => {
      // Immediately check if at bottom for UI state (no debounce for responsive UI)
      checkIfAtBottomForUI();
      scrollFrame = null;
    });
    
    // Debounced tracking for scroll position saving (500ms)
    // This prevents excessive IndexedDB writes during scrolling
    if (scrollDebounceTimer) clearTimeout(scrollDebounceTimer);
    
    scrollDebounceTimer = setTimeout(() => {
      trackLastVisibleMessage();
      checkIfScrolledToBottom();
    }, 500);
  }
  
  // Immediate check for UI state - no debouncing
  function checkIfAtBottomForUI() {
    if (!container) return;
    
    const isAtBottomLocal = 
      container.scrollHeight - container.scrollTop - container.clientHeight < 50;
    
    // Check if scrolled to the very top (within 50px threshold)
    const isAtTopLocal = container.scrollTop < 50;
    
    // Dispatch immediate event for UI state changes (button visibility)
    dispatch('scrollPositionUI', { isAtBottom: isAtBottomLocal, isAtTop: isAtTopLocal });
  }

  // Find the last message that's currently visible in viewport
  function trackLastVisibleMessage() {
    if (!container) return;
    
    const messages = container.querySelectorAll('[data-message-id]');
    if (messages.length === 0) return;
    
    const containerRect = container.getBoundingClientRect();
    let lastVisibleMessageId: string | null = null;
    
    // Find the last message that's at least partially visible
    messages.forEach((messageEl: HTMLElement) => {
      const messageRect = messageEl.getBoundingClientRect();
      
      // Check if message is in viewport
      if (messageRect.bottom > containerRect.top && 
          messageRect.top < containerRect.bottom) {
        
        lastVisibleMessageId = messageEl.dataset.messageId || null;
      }
    });
    
    if (lastVisibleMessageId) {
      dispatch('scrollPositionChanged', {
        message_id: lastVisibleMessageId
      });
    }
  }

  // Check if user has scrolled to bottom (mark as read)
  function checkIfScrolledToBottom() {
    if (!container) return;
    
    const isAtBottom = 
      container.scrollHeight - container.scrollTop - container.clientHeight < 50;
    
    if (isAtBottom) {
      // When scrolled to bottom, find the last message and save it as scroll position
      const messages = container.querySelectorAll('[data-message-id]');
      if (messages.length > 0) {
        const lastMessage = messages[messages.length - 1];
        const lastMessageId = lastMessage.getAttribute('data-message-id');
        if (lastMessageId) {
          // Save the last message as scroll position
          dispatch('scrollPositionChanged', {
            message_id: lastMessageId
          });
        }
      }
      
      dispatch('scrolledToBottom');
    }
  }

  // Restore scroll position to a specific message with 70px offset
  export function restoreScrollPosition(messageId: string) {
    if (!container) {
      console.warn('[ChatHistory] Cannot restore scroll: container not ready');
      return;
    }
    
    // Set flag to prevent scroll tracking during restoration
    isRestoringScroll = true;
    
    // Wait for messages to be rendered before attempting to restore scroll position
    const attemptRestore = (attempts = 0) => {
      if (attempts > 10) {
        console.warn(`[ChatHistory] Failed to find anchor message ${messageId} after 10 attempts, scrolling to bottom`);
        scrollToBottom();
        // Reset flag after restoration is complete
        setTimeout(() => { isRestoringScroll = false; }, 100);
        return;
      }
      
      const targetMessage = container.querySelector(`[data-message-id="${messageId}"]`);
      
      if (targetMessage) {
        const messageTop = (targetMessage as HTMLElement).offsetTop;
        // Scroll so the message has 70px offset from top (shows end of previous message)
        const scrollPosition = Math.max(0, messageTop - 70);
        
        container.scrollTo({
          top: scrollPosition,
          behavior: 'auto' // Use instant scroll for restoration
        });
        
        console.debug(`[ChatHistory] Restored scroll to message ${messageId} with 70px offset`);
        // Reset flag after restoration is complete
        setTimeout(() => { isRestoringScroll = false; }, 100);
      } else {
        // Message not found yet, try again after a short delay
        setTimeout(() => attemptRestore(attempts + 1), 50);
      }
    };
    
    requestAnimationFrame(() => attemptRestore());
  }

  // Listen for language changes to force re-processing of messages
  // This ensures translations update immediately when language changes
  // Note: For demo chats, ActiveChat will call updateMessages with newly translated messages
  // This handler ensures non-demo chats also update when language changes
  // CRITICAL: Only listen to 'language-changed-complete' to avoid race conditions
  // ActiveChat's handler will call updateMessages with new messages, which will detect locale change
  // This handler is a fallback for non-demo chats
  onMount(() => {
    const handleLanguageChange = async () => {
      // Clear cache to ensure fresh processing with new locale
      contentCache.clear();
      
      // CRITICAL: Check if messages are from a public chat (demo or legal)
      // If so, re-fetch them with new translations
      // This is a fallback in case ActiveChat's handler didn't run or failed
      if (messages.length > 0 && messages[0].original_message?.chat_id) {
        const chatId = messages[0].original_message.chat_id;
        if (isPublicChat(chatId)) {
          try {
            // Re-fetch messages with new translations
            const newMessages = getDemoMessages(chatId, DEMO_CHATS, LEGAL_CHATS);
            if (newMessages.length > 0) {
              // Call updateMessages to process the new messages
              // This will detect locale change and force re-processing
              updateMessages(newMessages);
              return; // Exit early since updateMessages handled everything
            } else {
              console.warn('[ChatHistory] No messages found for public chat:', chatId);
            }
          } catch (error) {
            console.error('[ChatHistory] Error re-fetching demo messages:', error);
            // Fall through to fallback re-render
          }
        }
      }
      
      // CRITICAL: Don't update previousLocale here - let updateMessages handle it
      // This ensures that when ActiveChat calls updateMessages, it will detect the locale change
      // Only force re-render if updateMessages hasn't been called (non-demo chats)
      // For demo chats, ActiveChat will call updateMessages with new messages
      
      // Force complete re-render by creating entirely new message objects
      // This ensures ReadOnlyMessage components detect the change and re-process content
      // This is especially important for non-demo chats where ActiveChat might not call updateMessages
      // For non-demo chats, we force a re-render which will trigger ReadOnlyMessage to re-process
      messages = messages.map(msg => {
        // Create a completely new message object with new content reference
        // This forces Svelte to detect the change and re-render ReadOnlyMessage
        const newContent = JSON.parse(JSON.stringify(msg.content));
        
        return {
          ...msg,
          content: newContent,
          // Force new object reference for original_message too
          // If original_message has markdown content, it will be re-processed with new locale
          original_message: msg.original_message ? {
            ...msg.original_message,
            // Re-process original message content if it's a string (markdown)
            // This ensures translations are updated when ReadOnlyMessage processes it
            content: typeof msg.original_message.content === 'string' 
              ? msg.original_message.content // Keep markdown string, will be re-processed with new locale
              : msg.original_message.content
          } : msg.original_message
        };
      });
      
    };

    // Listen to language change complete event
    // This fires after ActiveChat has processed, so updateMessages should have been called
    // But we still handle it as a fallback for non-demo chats
    window.addEventListener('language-changed-complete', handleLanguageChange);

    // Cleanup on component destroy
    return () => {
      window.removeEventListener('language-changed-complete', handleLanguageChange);
    };
  });

  // Cleanup on component destroy
  onDestroy(() => {
    // Cancel any pending scroll tracking operations
    if (scrollDebounceTimer) clearTimeout(scrollDebounceTimer);
    if (scrollFrame) cancelAnimationFrame(scrollFrame);
    // Clear spacer safety timeout
    if (spacerSafetyTimeout) clearTimeout(spacerSafetyTimeout);
    // Unsubscribe from PII visibility store
    unsubPiiVisibility();
  });
</script>

<!--
  The chat history container:
    - Takes full height and is scrollable.
    - Messages are aligned to the top for ChatGPT-style behavior.
    - Wrapped in a positioning parent so the AI processing overlay can float above the scroll area.
-->
<div class="chat-history-wrapper" style={containerStyle}>
<div 
    class="chat-history-container" 
    class:empty={displayMessages.length === 0}
    bind:this={container}
    onscroll={handleScroll}
>
    {#if showMessages}
        <div class="chat-history-content" 
             class:has-messages={displayMessages.length > 0}
             transition:fade={{ duration: 100 }} 
             onoutroend={handleOutroEnd}>
            {#each displayMessages as msg, msgIndex (msg.id)}
                <!-- Disable fade/flip animations for streaming and processing messages
                     to prevent visual glitches when content height changes rapidly.
                     Duration 0 effectively disables the animation without removing the directive. -->
                <div class="message-wrapper {msg.role === 'system' ? 'system' : (msg.role === 'user' ? 'user' : 'assistant')}"
                     data-message-id={msg.id}
                     style={`
                         opacity: ${msg.status === 'sending' ? 0.5 : (msg.status === 'failed' ? 0.7 : 1)};
                         ${msg.status === 'failed' ? 'border: 1px solid var(--color-error); border-radius: 12px; padding: 2px;' : ''}
                     `}
                     in:fade={{ duration: (msg.status === 'streaming' || msg.status === 'processing') ? 0 : 300 }}
                     animate:flip={{ duration: (msg.status === 'streaming' || msg.status === 'processing') ? 0 : 250 }}>
                    <ChatMessage
                        role={msg.role}
                        category={msg.category}
                        model_name={msg.model_name}
                        content={msg.content}
                        status={msg.status}
                        is_truncated={msg.is_truncated}
                        original_message={msg.original_message}
                        containerWidth={containerWidth}
                        appCards={msg.appCards}
                        _embedUpdateTimestamp={msg._embedUpdateTimestamp}
                        hasEmbedErrors={msg._embedErrors ? msg._embedErrors.size > 0 : false}
                        appSettingsMemoriesResponse={msg.role === 'user' ? appSettingsMemoriesResponseMap.get(msg.id) : undefined}
                        thinkingContent={msg.role === 'assistant' ? (getThinkingEntry(msg.id)?.content ?? msg.original_message?.thinking_content) : undefined}
                        isThinkingStreaming={msg.role === 'assistant' ? (getThinkingEntry(msg.id)?.isStreaming || false) : false}
                        piiMappings={cumulativePIIMappingsArray}
                        {piiRevealed}
                        messageId={msg.id}
                        userMessageId={msg.original_message?.user_message_id}
                        isFirstMessage={msgIndex === 0}
                    />
                </div>
            {/each}
            
            <!-- App settings/memories permission dialog (inline, scrolls with messages) -->
            <!-- Placed BEFORE the spacer so it appears right under the user message, not pushed below -->
            <!-- CRITICAL: Only show dialog if it belongs to the current chat (prevents showing in wrong chat) -->
            {#if shouldShowPermissionDialog}
                <div class="permission-dialog-wrapper" in:fade={{ duration: 200 }}>
                    <AppSettingsMemoriesPermissionDialog />
                </div>
            {/if}
            
            <!-- Bottom spacer: fills remaining viewport space below messages during streaming.
                 Creates the ChatGPT-like effect where the user message sits near the top
                 with empty space below that gradually fills as the AI response streams in. -->
            {#if spacerHeight > 0}
                <div class="streaming-spacer" style="height: {spacerHeight}px;"></div>
            {/if}
            
            <!-- Settings/memories suggestions shown after the last assistant message -->
            <!-- These are generated during AI post-processing Phase 2 -->
            {#if shouldShowSettingsMemoriesSuggestions && currentChatId}
                <div class="settings-memories-suggestions-wrapper" in:fade={{ duration: 200 }}>
                    <SettingsMemoriesSuggestions
                        suggestions={settingsMemoriesSuggestions}
                        chatId={currentChatId}
                        rejectedHashes={rejectedSuggestionHashes}
                        onSuggestionAdded={onSuggestionAdded}
                        onSuggestionRejected={onSuggestionRejected}
                        onSuggestionOpenForCustomize={onSuggestionOpenForCustomize}
                    />
                </div>
            {/if}
        </div>
    {/if}
    
</div>

<!-- AI Status Overlay: Centered status indicator with progressive phase display.
     Positioned absolutely over the scroll container via the wrapper.
     Shows phased status text (Sending -> Processing steps -> Typing) with optional AI icon.
     The AI icon only appears during processing and typing phases (when showIcon=true).
     Fades out entirely when the assistant response begins streaming. -->
{#if showCenteredIndicator && processingPhase}
    <div class="ai-processing-overlay" transition:fade={{ duration: 200 }}>
        <div class="ai-status-indicator">
            <!-- AI icon: only shown when showIcon is true (processing and typing phases) -->
            {#if processingPhase.phase !== 'sending' && processingPhase.showIcon}
                <div class="ai-processing-icon" transition:fade={{ duration: 300 }}></div>
            {/if}

            <!-- Status text: shown during all phases with shimmer animation.
                 Uses {#key} with absolute positioning so outgoing/incoming text
                 crossfade in the same spot without shifting the layout. -->
            <div class="ai-status-text-container">
                {#key processingPhase.statusLines.join('|')}
                    <div
                        class="ai-status-text"
                        class:phase-sending={processingPhase.phase === 'sending'}
                        class:phase-processing={processingPhase.phase === 'processing'}
                        class:phase-typing={processingPhase.phase === 'typing'}
                        in:fade={{ duration: 200, delay: 150 }}
                        out:fade={{ duration: 150 }}
                    >
                        {#each processingPhase.statusLines as line, index}
                            <span class={index === 0 ? 'status-primary-line' : index === 1 ? 'status-secondary-line' : 'status-tertiary-line'}>{line}</span>
                        {/each}
                    </div>
                {/key}
            </div>
        </div>
    </div>
{/if}
</div>

<style>
  /* Wrapper provides positioning context for the AI processing overlay.
     Takes the same absolute positioning the container previously had. */
  .chat-history-wrapper {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
  }

  .chat-history-container {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    overflow-y: auto;
    overflow-x: hidden; /* Prevent horizontal scrollbar from appearing at certain viewport widths */
    padding: 10px;
    box-sizing: border-box;
    -webkit-overflow-scrolling: touch;
    /* Disable browser's automatic scroll anchoring.
       During streaming, content grows from the bottom which triggers the browser's
       scroll-anchoring algorithm. This fights with our manual scroll management
       and causes unpredictable jumps. We handle scroll position ourselves. */
    overflow-anchor: none;
    /* Add mask for top and bottom fade effect */
    mask-image: linear-gradient(to bottom, 
        rgba(0, 0, 0, 0) 0%, 
        rgba(0, 0, 0, 1) 30px, 
        rgba(0, 0, 0, 1) calc(100% - 30px), 
        rgba(0, 0, 0, 0) 100%
    );
  }

  /* Hide scrollbar and prevent any content height when chat is empty */
  .chat-history-container.empty {
    overflow: hidden;
  }

  /* When empty, ensure content has no height to prevent scrollbar */
  .chat-history-container.empty .chat-history-content {
    height: 0;
    min-height: 0;
    padding-top: 0;
  }

  /* Add styles for the content wrapper - aligned to top for ChatGPT-style behavior */
  .chat-history-content {
    width: 100%;
    max-width: 900px;
    margin: 0 auto;
  }

  /* Only apply padding-top and min-height when there are messages */
  /* This prevents the first message from overlaying the button */
  .chat-history-content.has-messages {
    padding-top: 50px;
    /* Ensure minimum height for proper scrolling when messages exist */
    min-height: 100%;
  }


  /* Permission dialog wrapper - renders as part of chat history */
  /* This allows users to scroll the chat while the dialog is visible */
  .permission-dialog-wrapper {
    width: 100%;
    display: flex;
    justify-content: center;
    padding: 20px 0;
    margin-top: 10px;
  }

  /* Settings/memories suggestions wrapper - shown after last assistant message */
  .settings-memories-suggestions-wrapper {
    width: 100%;
    padding: 10px 0 20px 0;
    margin-top: 5px;
  }

  /* Bottom spacer that fills remaining viewport space during AI streaming.
     Creates visual space below user message that fills as the response streams in. */
  .streaming-spacer {
    flex-shrink: 0;
    pointer-events: none;
    /* Smooth transition as spacer shrinks while AI response grows */
    transition: height 0.15s ease-out;
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

  .message-wrapper.system { /* System messages (e.g., insufficient credits) centered */
    justify-content: center;
  }

  .message-wrapper :global(.chat-message) {
    width: 100%;
    max-width: 900px;
  }

  /* AI Status Overlay: Centered indicator shown during message processing lifecycle.
     Positioned absolutely over the scroll container (sibling, not child).
     This ensures it stays visually centered regardless of scroll position. */
  .ai-processing-overlay {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    display: flex;
    justify-content: center;
    align-items: center;
    pointer-events: none;
    z-index: 10;
  }

  /* Vertical layout container for the AI icon and status text */
  .ai-status-indicator {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
  }

  /* AI icon with shimmer animation — shown during processing and typing phases */
  .ai-processing-icon {
    width: 56px;
    height: 56px;
    -webkit-mask-image: url('@openmates/ui/static/icons/ai.svg');
    mask-image: url('@openmates/ui/static/icons/ai.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
    background: linear-gradient(
      90deg,
      var(--color-grey-30, #ccc) 0%,
      var(--color-grey-30, #ccc) 40%,
      var(--color-grey-10, #f0f0f0) 50%,
      var(--color-grey-30, #ccc) 60%,
      var(--color-grey-30, #ccc) 100%
    );
    background-size: 200% 100%;
    animation: ai-processing-shimmer 1.5s infinite linear;
  }

  /* Fixed-size container for the status text — prevents layout shifts during crossfade.
     The inner .ai-status-text is positioned absolutely so old and new text overlap
     in the same spot during the {#key} transition. */
  .ai-status-text-container {
    position: relative;
    width: 260px;
    min-height: 3.6em; /* enough for 3 lines: typing + model + provider */
  }

  /* Status text below the AI icon — shows phase-specific messages.
     Positioned absolutely within the container to prevent layout jumps during crossfade. */
  .ai-status-text {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 4px;
    font-size: 0.85rem;
    font-style: italic;
    text-align: center;
  }

  /* Shimmer text effect for all phases */
  .ai-status-text.phase-sending,
  .ai-status-text.phase-processing,
  .ai-status-text.phase-typing {
    background: linear-gradient(
      90deg,
      var(--color-grey-60) 0%,
      var(--color-grey-60) 40%,
      var(--color-grey-40) 50%,
      var(--color-grey-60) 60%,
      var(--color-grey-60) 100%
    );
    background-size: 200% 100%;
    background-clip: text;
    -webkit-background-clip: text;
    color: transparent;
    animation: ai-processing-shimmer 1.5s infinite linear;
  }

  /* Primary line (first line): slightly larger for emphasis */
  .ai-status-text .status-primary-line {
    font-size: 0.85rem;
  }

  /* Secondary line (e.g., model name): smaller, more subtle */
  .ai-status-text .status-secondary-line {
    font-size: 0.75rem;
    opacity: 0.8;
  }

  /* Tertiary line (e.g., "via Provider 🇺🇸"): even smaller and more subtle */
  .ai-status-text .status-tertiary-line {
    font-size: 0.7rem;
    opacity: 0.65;
  }

  @keyframes ai-processing-shimmer {
    0% {
      background-position: 200% 0;
    }
    100% {
      background-position: -200% 0;
    }
  }
</style>
