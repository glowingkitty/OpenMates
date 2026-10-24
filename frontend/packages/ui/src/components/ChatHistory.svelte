<script lang="ts">
import { storageArchiveFetch } from "../config/api";

  import { searchResultImageUrl } from '../utils/searchPreviewImages';
  import { collectHeaderImageRefs } from './embeds/embedPreviewHydration';
  import { embedStore, embedRefIndexVersion } from '../services/embedStore';
  import { createEventDispatcher, tick, onMount, onDestroy, untrack } from "svelte"; // Removed afterUpdate for runes mode compatibility
  import type { Snippet, SvelteComponent } from 'svelte';
  import { flip } from 'svelte/animate';
  import { parseMemoryRequest, mergeMemoryRequests } from "../utils/appMemoryRequests";
  import ChatMessage from "./ChatMessage.svelte";
  import ChatMessageTimeline from './ChatMessageTimeline.svelte';
  import { messageBookmarksStore, getMessageBookmarkIds, loadMessageBookmarks, toggleMessageBookmark, clearTransientMessageBookmarks, type BookmarkMode } from '../services/messageBookmarks';
  import { fetchTimelinePage, fetchTimelineSection, type TimelineCursor } from '../services/chatTimeline';
  import { mergeTimelineEntries, pairTimelineExchange, timelineResponseId, buildTimelineExchangeIndex, type TimelineEntry, type TimelinePreview } from '../utils/chatTimeline';
  import { getWorkspaceCacheEpoch } from '../services/workspaceCacheLifecycle';
  import AgentContextMessage from './AgentContextMessage.svelte';
  import { parseAgentContextEvent, type ProjectAuthoringRecommendation } from '../utils/agentContextEvents';
  import { associateLoadedMemories } from '../utils/associateLoadedMemories';
  import { projectAuthoringJobs, saveProjectAuthoring } from '../services/projectAuthoringClientService';
  import FollowUpSuggestions from './FollowUpSuggestions.svelte';
  import QuickTipsCard from './QuickTipsCard.svelte';
  import { fade } from "svelte/transition";
  import type { MessageStatus, ProcessingPhase, ResumeCardImageBubble } from '../types/chat'; // Import global MessageStatus and ProcessingPhase
  import type { QuickTipDefinition } from '../data/quickTips';

  // Define the internal Message type for ChatHistory's own state,
  // tailored for what ChatMessage.svelte needs.
  // This should align with the global Message type from ../types/chat
  import type { ChatCompressionCheckpoint, Message as GlobalMessage, MessageRole } from '../types/chat';
  import { preprocessTiptapJsonForEmbeds } from './enter_message/utils/tiptapContentProcessor';
  import { parse_message } from '../message_parsing/parse_message';
  import {
    createAssistantRenderPlan,
    type AssistantRenderPlan,
  } from '../message_parsing/streamingMessageBlocks';
  import { StreamingRenderScheduler } from '../message_parsing/streamingRenderScheduler';
  import { truncateTiptapContent } from '../utils/messageTruncation';
  import { orderSharedInteractiveQuestionMessages } from '../utils/sharedInteractiveQuestionOrdering';
  import { restorePIIInText } from './enter_message/services/piiDetectionService';
  import { voiceTranscriptDisplayText } from '../utils/voiceTranscriptDisplay';
  import type { PIIMapping } from '../types/chat';
  import { piiVisibilityStore } from '../stores/piiVisibilityStore';
  import { editMessageStore } from '../stores/editMessageStore';
  import { locale } from 'svelte-i18n';
  import { contentCache } from '../utils/contentCache';
  import { getDemoMessages, isPublicChat, DEMO_CHATS } from '../demo_chats'; // Import demo chat utilities for re-fetching on locale change
  import { messageHighlightStore } from '../stores/messageHighlightStore';
  import type { 
    AppSettingsMemoriesResponseContent,
    AppSettingsMemoriesRequestContent
  } from '../services/chatSyncServiceHandlersAppSettings';
    
  // ChatHeader: permanent display-only card shown at the top of new chats (title + category circle)
  import ChatHeader from './ChatHeader.svelte';
  import HighlightNavigationOverlay from './HighlightNavigationOverlay.svelte';
  import {
    selectHighlightStatsForChat,
    selectHighlightsForChatFlat,
  } from '../stores/messageHighlightsStore';
  import {
    highlightNavigationStore,
    setOrderedHighlights,
    jumpToFirstHighlight,
  } from '../stores/highlightNavigationStore';
  import WebhookPendingBanner from './WebhookPendingBanner.svelte';
  // Note: Icon was previously used for preprocessing step cards (now removed).
  // If Icon is needed elsewhere in future, re-import it.

  // Import the permission dialog component and its store for inline rendering
  // The permission dialog is rendered as part of the chat history (scrollable with messages)
  // rather than as a fixed overlay, so users can scroll while the dialog is visible
  import AppSettingsMemoriesPermissionDialog from './AppSettingsMemoriesPermissionDialog.svelte';
  import ConnectedAccountPermissionDialog from './ConnectedAccountPermissionDialog.svelte';
  import ProjectFileApprovalCard from './projects/ProjectFileApprovalCard.svelte';
  import RemoteCommandReviewCard from './projects/RemoteCommandReviewCard.svelte';
  import { remoteCommandEntries, resolveRemoteCommandApproval, requestRemoteCommandStop } from '../stores/remoteCommandApprovalStore';
  import { projectFileApprovals, resolveProjectFileApproval } from '../stores/projectFileApprovalStore';
  import { 
    appSettingsMemoriesPermissionStore,
    isPermissionDialogVisible,
    currentPermissionRequest
  } from '../stores/appSettingsMemoriesPermissionStore';
  import {
    currentConnectedAccountPermissionRequest,
    isConnectedAccountPermissionVisible
  } from '../stores/connectedAccountPermissionStore';
  import type { PendingPermissionRequest, AppSettingsMemoriesCategory } from '../services/chatSyncServiceHandlersAppSettings';
  import { formatDisplayName, getAppGradient } from '../services/chatSyncServiceHandlersAppSettings';
  import { text } from '@repo/ui'; // Used for compression summary UI labels
  import { chatDebugStore } from '../stores/chatDebugStore';
  import { introBannerVisible } from '../stores/uiStateStore';
  import { decodeToonContent, loadEmbedsWithRetry, resolveEmbed } from '../services/embedResolver';
  import { MAX_WIDTH_PREVIEW_THUMBNAIL, proxyImage } from '../utils/imageProxy';
  import { extractSearchResultsFromContent } from './embeds/embedPreviewHydration';
  import { chatDB } from '../services/db';
  import { chatKeyManager } from '../services/encryption/ChatKeyManager';
  import { authStore } from '../stores/authStore';
  import { userProfile } from '../stores/userProfile';
  import { activeTeamId } from '../stores/teamStore';
  import TeamChatReminder from './teams/TeamChatReminder.svelte';
  import { computeSHA256 } from '../message_parsing/utils';
  import { loadTeamMembers, loadTeamMemberAvatar } from '../services/teamService';
  import { webSocketService } from '../services/websocketService';
  import { getApiEndpoint } from '../config/api';
  import { reportIssueStore } from '../stores/reportIssueStore';
  import { settingsDeepLink } from '../stores/settingsDeepLinkStore';
  import { panelState } from '../stores/panelStateStore';
  import { chatSyncService } from '../services/chatSyncService';
  import {
    NORMAL_MESSAGE_PAGE_LIMIT,
    pruneDecryptedMessageWindow,
  } from '../utils/messageWindowPruning';

  const FORGOTTEN_MESSAGE_PAGE_LIMIT = NORMAL_MESSAGE_PAGE_LIMIT;
  let currentUserHash = $state<string | null>(null);
  let teamMemberProfiles = $state<Record<string, { userId?: string; displayName?: string; avatarUrl?: string }>>({});
  $effect(() => {
    const userId = $userProfile.user_id;
    currentUserHash = null;
    if (!userId) return;
    let cancelled = false;
    void computeSHA256(userId).then((hash) => {
      if (!cancelled) currentUserHash = hash;
    });
    return () => { cancelled = true; };
  });
  $effect(() => {
    const teamId = $activeTeamId;
    const chatId = currentChatId;
    const accountId = $userProfile.user_id;
    teamMemberProfiles = {};
    if (!teamId || !chatId || !accountId) return;
    let cancelled = false;
    const avatarUrls: string[] = [];
    void (async () => {
      try {
        const members = await loadTeamMembers(teamId);
        const entries = await Promise.all(members.map(async (member) => {
          const hash = member.hashed_user_id || (member.user_id ? await computeSHA256(member.user_id) : null);
          if (!hash) return null;
          return [hash, { userId: member.user_id, displayName: member.profile?.display_name }] as const;
        }));
        if (cancelled) return;
        // Member links become usable as soon as identity arrives; an optional
        // profile-image download must not delay navigation for every member.
        teamMemberProfiles = Object.fromEntries(entries.filter((entry): entry is NonNullable<typeof entry> => entry !== null));
        await Promise.all(members.map(async (member, index) => {
          const entry = entries[index];
          if (!entry) return;
          const avatarUrl = await loadTeamMemberAvatar(teamId, member).catch(() => null);
          if (!avatarUrl) return;
          if (cancelled) { URL.revokeObjectURL(avatarUrl); return; }
          avatarUrls.push(avatarUrl);
          teamMemberProfiles = {
            ...teamMemberProfiles,
            [entry[0]]: { ...teamMemberProfiles[entry[0]], avatarUrl },
          };
        }));
      } catch { /* The encrypted per-message sender name remains the fallback. */ }
    })();
    return () => {
      cancelled = true;
      for (const url of avatarUrls) URL.revokeObjectURL(url);
    };
  });
  const OLDER_MESSAGES_AUTOLOAD_THRESHOLD_PX = 180;

  async function startContextAuthoring(recommendation: ProjectAuthoringRecommendation): Promise<void> {
    if (!currentChatId || recommendation.chat_id !== currentChatId) throw new Error('authoring_chat_changed');
    const { startProjectAuthoring } = await import('../services/projectAuthoringClientService');
    await startProjectAuthoring(recommendation);
  }

  type AppCardData = {
    component: new (...args: unknown[]) => SvelteComponent;
    props: Record<string, unknown>;
  };

  type TiptapDoc = {
    type: 'doc';
    content: Array<Record<string, unknown>>;
  };

  type TiptapNode = {
    type?: string;
    attrs?: Record<string, unknown>;
    content?: TiptapNode[];
  };

  type ImageSearchCandidate = {
    parentEmbedId: string;
    childEmbedIds: string[];
  };

  type HeaderImageBubble = {
    imageUrl: string;
    parentEmbedId: string;
    childEmbedId: string;
    title?: string;
  };

  type ImageResultContent = {
    title?: string;
    image_url?: string;
    thumbnail_url?: string;
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

  const RAW_CHAT_ERROR_KEYS = new Set(['chat.an_error_occured', 'chat.an_error_occurred']);

  function isRawChatErrorMessage(content: unknown): boolean {
    return typeof content === 'string' && RAW_CHAT_ERROR_KEYS.has(content.trim());
  }

  function normalizeRawChatErrorMessage(content: string): string {
    return isRawChatErrorMessage(content) ? $text('chat.an_error_occured') : content;
  }

  /** Merge only explicit focus-mode assistant continuations for display. */
  function mergeAssistantContinuationsForDisplay(incoming: GlobalMessage[]): GlobalMessage[] {
    const result: GlobalMessage[] = [];
    for (let i = 0; i < incoming.length; i++) {
      const prev = result[result.length - 1];
      const curr = incoming[i];
      const isAssistantContinuation = Boolean(
        prev?.role === 'assistant' &&
        curr.role === 'assistant' &&
        !isRawChatErrorMessage(curr.content) &&
        hasFocusModeActivationEmbed(prev.content)
      );
      if (
        isAssistantContinuation
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

  const assistantRenderPlans = new Map<string, AssistantRenderPlan>();

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
      let contentToProcess = voiceTranscriptDisplayText(normalizeRawChatErrorMessage(incomingMessage.content), incomingMessage.role);
      
      // PII RESTORATION: Restore PII placeholders with original values before parsing
      // This applies to both user and assistant messages when mappings are available
      if (piiMappings && piiMappings.size > 0) {
        contentToProcess = restorePIIInMarkdown(contentToProcess, piiMappings);
      }
      
      if (incomingMessage.role === 'assistant') {
        const plan = createAssistantRenderPlan(contentToProcess, {
          phase: incomingMessage.status === 'streaming' ? 'streaming' : 'final',
          previous: assistantRenderPlans.get(incomingMessage.message_id),
          chatId: incomingMessage.chat_id,
        });
        assistantRenderPlans.set(incomingMessage.message_id, plan);
        processedContent = plan.document;
      } else {
        const tiptapJson = parse_message(contentToProcess, 'read', {
          unifiedParsingEnabled: true,
          role: incomingMessage.role
        });
        processedContent = preprocessTiptapJsonForEmbeds(tiptapJson);
      }

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
  type ScheduledAssistantRender = {
    message: GlobalMessage;
    piiMappings: Map<string, PIIMapping>;
  };
  const streamingRenderSchedulers = new Map<string, StreamingRenderScheduler<ScheduledAssistantRender>>();
  const streamingRenderRevisions = new Map<string, { content: string; revision: number }>();

  function getStreamingRenderScheduler(messageId: string): StreamingRenderScheduler<ScheduledAssistantRender> {
    const existing = streamingRenderSchedulers.get(messageId);
    if (existing) return existing;

    const scheduler = new StreamingRenderScheduler<ScheduledAssistantRender>({
      onFlush: ({ message, piiMappings }, revision) => {
        if (streamingRenderRevisions.get(messageId)?.revision !== revision) return;
        const compiled = G_mapToInternalMessage(message, piiMappings);
        messages = messages.map(current => current.id === messageId ? compiled : current);
      },
    });
    streamingRenderSchedulers.set(messageId, scheduler);
    return scheduler;
  }

  function cancelStreamingRender(messageId: string): void {
    streamingRenderSchedulers.get(messageId)?.cancel();
    streamingRenderSchedulers.delete(messageId);
    streamingRenderRevisions.delete(messageId);
  }

  function cancelAllStreamingRenders(): void {
    for (const scheduler of streamingRenderSchedulers.values()) scheduler.cancel();
    streamingRenderSchedulers.clear();
    streamingRenderRevisions.clear();
    assistantRenderPlans.clear();
  }
  let headerImageBubbles = $state<HeaderImageBubble[] | null>(null);
  let headerImageBubbleRequestId = 0;
  let headerImageBubbleCandidateKey = '';
  let headerImageBubbleChatKey: string | null = null;
  let headerImageBubbleRetryTick = $state(0);
  let headerImageBubbleRetryTimer: ReturnType<typeof setTimeout> | null = null;
  let headerImageBubbleRetryBaseKey = '';
  let headerImageBubbleRetryCount = 0;
  let headerImageBubbleChildIdsByParent = $state<Map<string, string[]>>(new Map());
  const HEADER_IMAGE_BUBBLE_LIMIT = 8;
  const HEADER_IMAGE_BUBBLE_RETRY_LIMIT = 10;
  const HEADER_IMAGE_BUBBLE_RETRY_DELAY_MS = 1000;
  const VIRTUALIZATION_THRESHOLD = 160;
  const VIRTUALIZATION_OVERSCAN = 24;
  const VIRTUALIZATION_ESTIMATED_MESSAGE_HEIGHT = 132;
  const VIRTUALIZATION_MIN_RENDERED_MESSAGES = 48;
  let virtualStartIndex = $state(0);
  let virtualEndIndex = $state(VIRTUALIZATION_MIN_RENDERED_MESSAGES);

  function normalizeEmbedIds(embedIds: unknown): string[] {
    if (typeof embedIds === 'string') {
      return embedIds.split('|').map(id => id.trim()).filter(Boolean);
    }
    if (Array.isArray(embedIds)) {
      return embedIds.filter((id): id is string => typeof id === 'string' && id.length > 0);
    }
    return [];
  }

  function rememberHeaderImageBubbleChildIds(parentEmbedId: unknown, childEmbedIds: unknown): void {
    if (typeof parentEmbedId !== 'string') return;
    const normalizedChildIds = normalizeEmbedIds(childEmbedIds);
    if (normalizedChildIds.length === 0) return;

    const existingChildIds = headerImageBubbleChildIdsByParent.get(parentEmbedId) ?? [];
    if (existingChildIds.join('|') === normalizedChildIds.join('|')) return;

    headerImageBubbleChildIdsByParent = new Map(headerImageBubbleChildIdsByParent).set(parentEmbedId, normalizedChildIds);
    headerImageBubbleRetryTick += 1;
  }

  function mergeEmbedIds(...groups: string[][]): string[] {
    return [...new Set(groups.flat())];
  }

  function clearHeaderImageBubbleRetry() {
    if (!headerImageBubbleRetryTimer) return;
    clearTimeout(headerImageBubbleRetryTimer);
    headerImageBubbleRetryTimer = null;
  }

  function scheduleHeaderImageBubbleRetry(baseKey: string): boolean {
    if (headerImageBubbleRetryTimer || headerImageBubbleRetryCount >= HEADER_IMAGE_BUBBLE_RETRY_LIMIT) return false;

    headerImageBubbleRetryCount += 1;
    headerImageBubbleRetryTimer = setTimeout(() => {
      headerImageBubbleRetryTimer = null;
      if (headerImageBubbleRetryBaseKey === baseKey) {
        headerImageBubbleRetryTick += 1;
      }
    }, HEADER_IMAGE_BUBBLE_RETRY_DELAY_MS);
    return true;
  }

  function flattenImagePreviewResults(values: unknown[]): ImageResultContent[] {
    const results: ImageResultContent[] = [];

    for (const value of values) {
      if (!value || typeof value !== 'object') continue;

      const record = value as Record<string, unknown>;
      if (Array.isArray(record.results)) {
        results.push(...flattenImagePreviewResults(record.results));
        continue;
      }

      if (isImageResultContent(record)) {
        results.push(record);
      }
    }

    return results;
  }

  function parseImagePreviewResultsJson(value: unknown): ImageResultContent[] {
    if (typeof value !== 'string' || !value.trim()) return [];
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? flattenImagePreviewResults(parsed) : [];
    } catch {
      return [];
    }
  }

  function isImageResultContent(value: unknown): value is ImageResultContent {
    return !!value && typeof value === 'object';
  }

  function getParentPreviewImageResults(decodedParent: Record<string, unknown> | null): ImageResultContent[] {
    if (!decodedParent) return [];

    const previewResults = extractSearchResultsFromContent(
      decodedParent,
      ['preview_results', 'preview_thumbnails', 'results'],
    );
    const flattenedPreviewResults = flattenImagePreviewResults(previewResults);
    if (flattenedPreviewResults.length > 0) return flattenedPreviewResults;

    return parseImagePreviewResultsJson(decodedParent.preview_results_json);
  }

  function appendHeaderImageBubble(
    result: ImageResultContent,
    bubbles: HeaderImageBubble[],
    seen: Set<string>,
    parentEmbedId: string,
    childEmbedId: string,
  ): boolean {
    const rawUrl = searchResultImageUrl(result);
    if (!rawUrl || seen.has(rawUrl)) return false;

    seen.add(rawUrl);
    bubbles.push({
      imageUrl: proxyImage(rawUrl, MAX_WIDTH_PREVIEW_THUMBNAIL),
      parentEmbedId,
      childEmbedId,
      title: result.title,
    });
    return bubbles.length >= HEADER_IMAGE_BUBBLE_LIMIT;
  }

  function collectImageSearchCandidates(node: TiptapNode | undefined, candidates: ImageSearchCandidate[]) {
    if (!node) return;

    const attrs = node.attrs;
    if (attrs) {
      const groupedItems = attrs.groupedItems;
      if (Array.isArray(groupedItems)) {
        for (const item of groupedItems) collectImageSearchCandidates({ attrs: item as Record<string, unknown> }, candidates);
      }

      const appId = attrs.app_id;
      const skillId = attrs.skill_id;
      const contentRef = attrs.contentRef;
      if ((appId === 'images' || appId === 'news' || appId === 'web' || appId === 'events') && skillId === 'search' && typeof contentRef === 'string' && contentRef.startsWith('embed:')) {
        const parentEmbedId = contentRef.slice('embed:'.length);
        candidates.push({
          parentEmbedId,
          childEmbedIds: mergeEmbedIds(
            normalizeEmbedIds(attrs.embed_ids),
            headerImageBubbleChildIdsByParent.get(parentEmbedId) ?? [],
          ),
        });
      }
    }

    if (Array.isArray(node.content)) {
      for (const child of node.content) collectImageSearchCandidates(child, candidates);
    }
  }

  async function resolveHeaderImageBubbles(candidates: ImageSearchCandidate[], linkedRefs: string[], chatId: string | null): Promise<HeaderImageBubble[]> {
    const seen = new Set<string>();
    const bubbles: HeaderImageBubble[] = [];

    // Explicit assistant references outrank parent preview order across all searches.
    // Resolve actual child IDs so clicking a bubble opens the referenced result.
    for (const ref of linkedRefs) {
      const embedId = await embedStore.resolveByRefDeep(ref, chatId);
      if (!embedId) continue;
      const linkedEmbed = await resolveEmbed(embedId);
      const decoded = linkedEmbed?.content ? await decodeToonContent(linkedEmbed.content) : null;
      if (!decoded || typeof decoded !== 'object') continue;
      const rawEntry = await embedStore.getRawEntry(`embed:${embedId}`);
      const parentId = rawEntry?.parent_embed_id || embedId;
      if (appendHeaderImageBubble(decoded, bubbles, seen, parentId, embedId)) return bubbles;
      for (const result of getParentPreviewImageResults(decoded)) {
        if (appendHeaderImageBubble(result, bubbles, seen, embedId, embedId)) return bubbles;
      }
    }

    for (const candidate of candidates) {
      let childEmbedIds = candidate.childEmbedIds;
      const parentEmbed = await resolveEmbed(candidate.parentEmbedId);
      const decodedParent = parentEmbed?.content ? await decodeToonContent(parentEmbed.content) : null;

      const parentPreviewResults = getParentPreviewImageResults(decodedParent);
      for (let index = 0; index < parentPreviewResults.length; index += 1) {
        if (appendHeaderImageBubble(
          parentPreviewResults[index],
          bubbles,
          seen,
          candidate.parentEmbedId,
          `${candidate.parentEmbedId}:preview:${index}`,
        )) {
          return bubbles;
        }
      }

      // Parent metadata already carries the visible images; avoid duplicate child hydration.
      if (parentPreviewResults.some(result => searchResultImageUrl(result))) continue;

      if (childEmbedIds.length === 0) {
        childEmbedIds = normalizeEmbedIds(decodedParent?.embed_ids ?? parentEmbed?.embed_ids);
      }
      if (childEmbedIds.length === 0) continue;

      const remainingCount = HEADER_IMAGE_BUBBLE_LIMIT - bubbles.length;
      const childEmbeds = await loadEmbedsWithRetry(childEmbedIds.slice(0, remainingCount), 3, 250);
      for (const childEmbed of childEmbeds) {
        const decodedChild = childEmbed.content ? await decodeToonContent(childEmbed.content) as ImageResultContent | null : null;
        const childResults = decodedChild ? flattenImagePreviewResults([decodedChild]) : [];
        for (const childResult of childResults) {
          if (appendHeaderImageBubble(childResult, bubbles, seen, candidate.parentEmbedId, childEmbed.embed_id)) return bubbles;
        }
      }
    }

    return bubbles;
  }

  async function persistResumeCardImageBubbles(bubbles: ResumeCardImageBubble[] | null): Promise<void> {
    if (!currentChatId || isIncognito || isPublicChat(currentChatId)) return;

    try {
      const chat = await chatDB.getChat(currentChatId);
      if (!chat) return;

      const nextBubbles = bubbles?.slice(0, 2) ?? null;
      const current = chat.resume_card_image_bubbles ?? null;
      if (JSON.stringify(current) === JSON.stringify(nextBubbles)) return;

      await chatDB.updateChat({
        ...chat,
        resume_card_image_bubbles: nextBubbles,
      });
    } catch (error) {
      console.warn('[ChatHistory] Failed to persist resume card image bubbles:', error);
    }
  }

  /**
   * Parse system message content to check if it's an app_settings_memories_response.
   * Returns the parsed content or null if not a valid response.
   */
  function parseAppSettingsMemoriesResponse(content: unknown): AppSettingsMemoriesResponseContent | null {
    if (typeof content !== 'string') {
      console.warn(`[ChatHistory][parseResponse] content is not a string, got: ${typeof content}`, content);
      return null;
    }
    // Fast-path: valid app_settings_memories_response JSON always starts with '{'.
    // Skip JSON.parse entirely for plain-text system messages (e.g. credits rejection)
    // to avoid noisy parse-failure warnings on every render.
    if (!content.trimStart().startsWith('{')) return null;
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
    
    for (const msg of messages) {
      if (msg.role === 'system') {
        const request = parseMemoryRequest(msg.original_message?.content, msg.original_message?.message_id ?? msg.id);
        if (request) {
          const previous = map.get(request.user_message_id);
          map.set(request.user_message_id, previous?.request_id === request.request_id
            ? mergeMemoryRequests(previous, request) : request);
        }
      }
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
  // --- Compression / forgotten messages ---
  let timelineCatalogue = $state<TimelineEntry[]>([]);
  let timelineSection = $state<GlobalMessage[] | null>(null);
  let timelineCatalogueLoading = $state(false);
  let timelineCatalogueIncomplete = $state(false);
  let timelineVisibleMessageId = $state<string | null>(null);
  let timelineHostEl = $state<HTMLDivElement | null>(null);
  let timelineContentEl = $state<HTMLDivElement | null>(null);
  let timelineLeft = $state(0);
  let timelineSafeTop = $state(8);
  let timelineNarrow = $state(true);
  let timelinePinnedId: string | null = null;
  let timelineNavigating = $state(false);
  let timelineCursor: TimelineCursor | null = null;
  let timelineGeneration = 0;
  let timelineController: AbortController | null = null;
  const timelineSections = new Map<string, Promise<GlobalMessage[]>>();
  $effect(() => {
    const scope = timelineScopeKey;
    const remote = timelineRemoteEnabled;
    timelineController?.abort();
    timelineController = new AbortController();
    timelineGeneration++;
    timelineCatalogue = [];
    timelineCursor = null;
    timelineSection = null;
    timelineVisibleMessageId = null;
    timelinePinnedId = null;
    timelineNavigating = false;
    timelineCatalogueIncomplete = remote;
    timelineCatalogueLoading = false;
    timelineSections.clear();
    if (remote) untrack(() => void readTimelineCatalogue());
    return () => { void scope; timelineController?.abort(); };
  });

  async function readTimelineCatalogue(): Promise<void> {
    if (!currentChatId || timelineCatalogueLoading || !timelineController) return;
    const generation = timelineGeneration;
    const chatId = currentChatId;
    const shared = isSharedChat;
    const signal = timelineController.signal;
    timelineCatalogueLoading = true;
    try {
      do {
        const page = await fetchTimelinePage(chatId, shared, timelineCursor, signal);
        if (generation !== timelineGeneration || signal.aborted) return;
        timelineCatalogue = mergeTimelineEntries(page.entries, timelineCatalogue);
        timelineCursor = page.before;
        timelineCatalogueIncomplete = page.has_more;
      } while (timelineCatalogueIncomplete);
    } catch (error) {
      if (generation === timelineGeneration && !signal.aborted) {
        // Diagnostics contain only fixed read/validation errors, never message bodies.
        console.warn('[ChatHistory] Timeline catalogue unavailable', error instanceof Error ? error.message : 'Unknown read error');
        timelineCatalogueIncomplete = true;
      }
    } finally {
      if (generation === timelineGeneration) timelineCatalogueLoading = false;
    }
  }

  async function readTimelineSection(entry: TimelineEntry): Promise<GlobalMessage[]> {
    if (!currentChatId) throw new Error('No active timeline');
    const responseId = timelineResponseId(timelineAllEntries, entry.message_id);
    for (const rows of [sourceMessages, oldCompressedMessages]) {
      if (rows.some(message => message.message_id === entry.message_id)) {
        const pair = pairTimelineExchange(rows, entry.message_id, pendingAssistantResponse?.userMessageId);
        if (pair.assistant || (!responseId && entry.message_id === timelineUserEntries[timelineUserEntries.length - 1]?.message_id)) return rows;
      }
    }
    const cached = timelineSections.get(entry.message_id);
    if (cached) return cached;
    const chatId = currentChatId;
    const scope = timelineScopeKey;
    const epoch = getWorkspaceCacheEpoch();
    const generation = timelineGeneration;
    const operation = fetchTimelineSection(chatId, entry.message_id, isSharedChat, responseId).then(rows => {
      if (scope !== timelineScopeKey || epoch !== getWorkspaceCacheEpoch() || generation !== timelineGeneration) throw new Error('Timeline scope changed');
      pairTimelineExchange(rows, entry.message_id);
      return rows;
    });
    timelineSections.set(entry.message_id, operation);
    while (timelineSections.size > 6) timelineSections.delete(timelineSections.keys().next().value!);
    try { return await operation; }
    catch (error) { if (timelineSections.get(entry.message_id) === operation) timelineSections.delete(entry.message_id); throw error; }
  }

  async function previewTimelineExchange(entry: TimelineEntry): Promise<TimelinePreview> {
    return pairTimelineExchange(await readTimelineSection(entry), entry.message_id, pendingAssistantResponse?.userMessageId);
  }

  function timelineTarget(id: string): HTMLElement | undefined {
    return [...container.querySelectorAll<HTMLElement>('.message-wrapper[data-message-id]')]
      .find(node => node.dataset.messageId === id);
  }

  async function positionTimelineTarget(id: string, scope: string, generation: number): Promise<void> {
    if (!container) throw new Error('Timeline viewport unavailable');
    timelineNavigating = true;
    ensureVirtualMessageRendered(id);
    await tick();
    try {
      await new Promise<void>((resolve, reject) => {
        const deadline = performance.now() + 2400;
        let stableSince = performance.now(), previousHeight = -1;
        const align = () => {
          if (scope !== timelineScopeKey || generation !== timelineGeneration) return reject(new Error('Timeline scope changed'));
          const target = timelineTarget(id);
          if (target) {
            const viewport = container.getBoundingClientRect(), row = target.getBoundingClientRect();
            const desired = Math.max(0, Math.min(container.scrollHeight - container.clientHeight,
              container.scrollTop + row.top - viewport.top - 70));
            const aligned = Math.abs(container.scrollTop - desired) < 2;
            if (!aligned || previousHeight !== container.scrollHeight) stableSince = performance.now();
            previousHeight = container.scrollHeight;
            container.scrollTo({ top: desired, behavior: 'instant' });
            if (aligned && performance.now() - stableSince >= 120 && row.top < viewport.bottom && row.bottom > viewport.top) return resolve();
          }
          if (performance.now() >= deadline) return reject(new Error('Timeline target could not be positioned'));
          requestAnimationFrame(align);
        };
        requestAnimationFrame(align);
      });
    } finally {
      if (scope === timelineScopeKey && generation === timelineGeneration) {
        timelineNavigating = false;
        checkIfAtBottomForUI();
      }
    }
  }

  async function activateTimelineExchange(entry: TimelineEntry): Promise<void> {
    const scope = timelineScopeKey, generation = timelineGeneration;
    const rows = await readTimelineSection(entry);
    if (scope !== timelineScopeKey || generation !== timelineGeneration) throw new Error('Timeline scope changed');
    const previous = { section: timelineSection, visible: timelineVisibleMessageId, top: container?.scrollTop ?? 0, pin: timelinePinnedId, start: virtualStartIndex, end: virtualEndIndex };
    cancelPendingNewUserMessageScroll();
    if (scrollDebounceTimer) clearTimeout(scrollDebounceTimer);
    shouldScrollToNewUserMessage = false;
    isSpacerActive = false;
    spacerHeight = 0;
    userHasScrolledAway = true;
    timelinePinnedId = null;
    timelineSection = rows;
    timelineVisibleMessageId = entry.message_id;
    await tick();
    try {
      await positionTimelineTarget(entry.message_id, scope, generation);
      timelinePinnedId = entry.message_id;
    } catch (error) {
      if (scope === timelineScopeKey && generation === timelineGeneration) {
        timelineSection = previous.section; timelineVisibleMessageId = previous.visible;
        clampVirtualRange(previous.start, previous.end);
        await tick(); container.scrollTop = previous.top; timelinePinnedId = previous.pin;
      }
      throw error;
    }
  }

  async function leaveTimelineSection(): Promise<void> {
    const scope = timelineScopeKey, generation = timelineGeneration;
    timelinePinnedId = null;
    timelineSection = null;
    await tick();
    const latest = displayMessages[displayMessages.length - 1];
    if (latest) {
      timelineVisibleMessageId = latest.id;
      await positionTimelineTarget(latest.id, scope, generation);
    } else scrollToBottom();
  }

  // Measure the pane itself so phones and narrow split panes share disclosure.
  // The wide rail remains beside the message lane; narrow rails overlay it.
  $effect(() => {
    const host = timelineHostEl, content = timelineContentEl, header = headerWrapperEl;
    if (!host || !content) return;
    let frame = 0;
    const measure = (resize = false) => {
      const hostRect = host.getBoundingClientRect(), lane = content.getBoundingClientRect();
      timelineNarrow = host.clientWidth <= 730;
      timelineLeft = Math.max(0, lane.left - hostRect.left + parseFloat(getComputedStyle(content).paddingLeft) - 52);
      const banner = header?.getBoundingClientRect();
      timelineSafeTop = banner && banner.bottom > hostRect.top && banner.top < hostRect.bottom
        ? Math.max(8, banner.bottom - hostRect.top + 8) : 8;
      if (resize && timelinePinnedId && !timelineNavigating) {
        const target = timelineTarget(timelinePinnedId);
        if (target) container.scrollTop += target.getBoundingClientRect().top - container.getBoundingClientRect().top - 70;
      }
    };
    const onScroll = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(() => measure()); };
    const observer = new ResizeObserver(() => measure(true));
    observer.observe(host); observer.observe(content); if (header) observer.observe(header);
    const release = () => releaseTimelinePin();
    container.addEventListener('scroll', onScroll, { passive: true });
    container.addEventListener('wheel', release, { passive: true });
    container.addEventListener('pointerdown', release, { passive: true });
    container.addEventListener('keydown', releaseTimelinePin);
    measure();
    return () => {
      observer.disconnect(); container.removeEventListener('scroll', onScroll); cancelAnimationFrame(frame);
      container.removeEventListener('wheel', release); container.removeEventListener('pointerdown', release);
      container.removeEventListener('keydown', releaseTimelinePin);
    };
  });

  function releaseTimelinePin(event?: KeyboardEvent): void {
    if (!event || ['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(event.key)) timelinePinnedId = null;
  }

  // Whether the user has toggled "Show earlier messages" to see messages before the compression summary.
  let showForgottenMessages = $state(false);
  let oldCompressedMessages = $state<GlobalMessage[]>([]);
  let oldCompressedMessagesLoading = $state(false);
  let oldCompressedMessagesHasMore = $state(false);
  let oldCompressedMessagesNextBeforeTimestamp = $state<number | null>(null);
  let oldCompressedMessagesNextBeforeMessageId = $state<string | null>(null);
  let oldCompressedMessagesCheckpointId = $state<string | null>(null);
  const LOCAL_FORGOTTEN_CURSOR_SENTINEL = '\uffff';

  let latestCompressionCheckpoint = $derived.by(() => {
    if (!compressionCheckpoints || compressionCheckpoints.length === 0) return null;
    return [...compressionCheckpoints].sort((a, b) => b.created_at - a.created_at)[0];
  });

  let locallyAvailableForgottenMessages = $derived.by(() => {
    if (!latestCompressionCheckpoint) return [] as typeof messages;
    return messages.filter(
      (msg) => (msg.original_message?.created_at ?? 0) <= latestCompressionCheckpoint.compressed_up_to_timestamp,
    );
  });

  $effect(() => {
    const checkpointId = latestCompressionCheckpoint?.id ?? null;
    if (checkpointId === oldCompressedMessagesCheckpointId) return;
    oldCompressedMessagesCheckpointId = checkpointId;
    oldCompressedMessages = [];
    oldCompressedMessagesHasMore = false;
    oldCompressedMessagesNextBeforeTimestamp = null;
    oldCompressedMessagesNextBeforeMessageId = null;
    showForgottenMessages = false;
  });

  function makeCompressionSummaryMessage(checkpoint: ChatCompressionCheckpoint): InternalMessage {
    return G_mapToInternalMessage({
      message_id: checkpoint.id,
      chat_id: checkpoint.chat_id,
      role: 'system',
      category: 'compression_summary',
      content: checkpoint.summary || '',
      created_at: checkpoint.created_at,
      status: 'synced',
    });
  }

  /**
   * Find the index of the compression summary system message in the messages array.
   * Returns -1 if no compression summary exists. Used to split messages into
   * "forgotten" (before summary) and "active" (summary + after) groups.
   */
  let compressionSummaryIndex = $derived.by(() => {
    if (latestCompressionCheckpoint) return 0;
    for (let i = 0; i < messages.length; i++) {
      const msg = messages[i];
      if (
        msg.role === 'system' &&
        (msg.category === 'compression_summary' ||
         msg.original_message?.category === 'compression_summary')
      ) {
        return i;
      }
    }
    return -1;
  });

  /** True when this chat has a compression summary, so the forgotten messages UI should appear. */
  let hasCompressionSummary = $derived(compressionSummaryIndex >= 0);

  /** Messages before the compression summary (the "forgotten" ones). */
  let forgottenMessages = $derived.by(() => {
    if (latestCompressionCheckpoint) {
      const loadedMessages = oldCompressedMessages.map((message) => G_mapToInternalMessage(message));
      return loadedMessages.length > 0 ? loadedMessages : locallyAvailableForgottenMessages;
    }
    if (!hasCompressionSummary) return [] as typeof messages;
    return messages.slice(0, compressionSummaryIndex);
  });

  let candidateDisplayMessages = $derived.by(() => {
    if (timelineSection) {
      const mappings = buildCumulativePIIMappings(timelineSection);
      return timelineSection.map(message => G_mapToInternalMessage(message, mappings));
    }
    if (latestCompressionCheckpoint) {
      const summaryMessage = makeCompressionSummaryMessage(latestCompressionCheckpoint);
      const recentMessages = messages.filter(
        (msg) => (msg.original_message?.created_at ?? 0) > latestCompressionCheckpoint.compressed_up_to_timestamp,
      );
      return showForgottenMessages
        ? [...forgottenMessages, summaryMessage, ...recentMessages]
        : [summaryMessage, ...recentMessages];
    }
    // Start with either all messages or only post-summary messages
    let base = hasCompressionSummary && !showForgottenMessages
      ? messages.slice(compressionSummaryIndex)
      : messages;

    return base;
  });

  let loadedMemoryAssociation = $derived.by(() => associateLoadedMemories(candidateDisplayMessages, pendingAssistantResponse
    ? { taskId: pendingAssistantResponse.taskId, userMessageId: pendingAssistantResponse.userMessageId, chatId: currentChatId }
    : null));

  let displayMessages = $derived.by(() => {
    return candidateDisplayMessages.filter(msg => {
      if (msg.role === 'system') {
        if (loadedMemoryAssociation.attachedReceiptIds.has(msg.id)) return false;
        const response = parseAppSettingsMemoriesResponse(msg.original_message?.content);
        // Filter out app_settings_memories_response system messages
        if (response?.type === 'app_settings_memories_response') {
          return false;
        }
        const request = parseMemoryRequest(msg.original_message?.content, msg.original_message?.message_id ?? msg.id);
        // Filter out app_settings_memories_request system messages
        if (request?.type === 'app_settings_memories_request') {
          return false;
        }
      }
      return true;
    });
  });

  let shouldVirtualizeMessages = $derived(
    displayMessages.length > VIRTUALIZATION_THRESHOLD && !messages.some(m => m.status === 'streaming'),
  );

  let virtualizedDisplayMessages = $derived.by(() => {
    if (!shouldVirtualizeMessages) return displayMessages;
    const safeStart = Math.max(0, Math.min(virtualStartIndex, displayMessages.length));
    const safeEnd = Math.max(
      safeStart,
      Math.min(virtualEndIndex, displayMessages.length),
    );
    return displayMessages.slice(safeStart, safeEnd);
  });

  let virtualTopSpacerHeight = $derived(
    shouldVirtualizeMessages
      ? Math.max(0, virtualStartIndex * VIRTUALIZATION_ESTIMATED_MESSAGE_HEIGHT)
      : 0,
  );

  let virtualBottomSpacerHeight = $derived(
    shouldVirtualizeMessages
      ? Math.max(0, (displayMessages.length - virtualEndIndex) * VIRTUALIZATION_ESTIMATED_MESSAGE_HEIGHT)
      : 0,
  );

  function clampVirtualRange(startIndex: number, endIndex: number): void {
    if (!shouldVirtualizeMessages) {
      virtualStartIndex = 0;
      virtualEndIndex = displayMessages.length;
      return;
    }

    const total = displayMessages.length;
    const minimumEnd = startIndex + VIRTUALIZATION_MIN_RENDERED_MESSAGES;
    virtualStartIndex = Math.max(0, Math.min(startIndex, total));
    virtualEndIndex = Math.max(
      virtualStartIndex,
      Math.min(Math.max(endIndex, minimumEnd), total),
    );
  }

  function updateVirtualRangeAroundScroll(): void {
    if (!container || !shouldVirtualizeMessages) return;
    const firstVisibleEstimate = Math.floor(container.scrollTop / VIRTUALIZATION_ESTIMATED_MESSAGE_HEIGHT);
    const visibleEstimate = Math.ceil(container.clientHeight / VIRTUALIZATION_ESTIMATED_MESSAGE_HEIGHT);
    clampVirtualRange(
      firstVisibleEstimate - VIRTUALIZATION_OVERSCAN,
      firstVisibleEstimate + visibleEstimate + VIRTUALIZATION_OVERSCAN,
    );
  }

  function ensureVirtualMessageRendered(messageId: string): void {
    if (!shouldVirtualizeMessages) return;
    const index = displayMessages.findIndex((message) => message.id === messageId);
    if (index < 0) return;
    clampVirtualRange(index - VIRTUALIZATION_OVERSCAN, index + VIRTUALIZATION_OVERSCAN + 1);
    if (container) {
      container.scrollTop = Math.max(0, index * VIRTUALIZATION_ESTIMATED_MESSAGE_HEIGHT - 70);
    }
  }

  async function toggleForgottenMessages(): Promise<void> {
    if (!latestCompressionCheckpoint) {
      showForgottenMessages = !showForgottenMessages;
      return;
    }
    if (!showForgottenMessages && oldCompressedMessages.length === 0) {
      await loadForgottenMessagePage();
    }
    showForgottenMessages = !showForgottenMessages;
  }

  async function loadForgottenMessagePage(): Promise<void> {
    if (!latestCompressionCheckpoint || oldCompressedMessagesLoading) return;
    oldCompressedMessagesLoading = true;
    const beforeTimestamp = oldCompressedMessagesNextBeforeTimestamp ?? latestCompressionCheckpoint.compressed_up_to_timestamp;
    const beforeMessageId = oldCompressedMessagesNextBeforeMessageId ?? undefined;
    try {
      if (isSharedChat) {
        const params = new URLSearchParams({
          checkpoint_id: latestCompressionCheckpoint.id,
          before_timestamp: String(beforeTimestamp),
          limit: String(FORGOTTEN_MESSAGE_PAGE_LIMIT),
        });
        if (beforeMessageId) params.set('before_message_id', beforeMessageId);
        const response = await storageArchiveFetch(getApiEndpoint(`/v1/share/chat/${latestCompressionCheckpoint.chat_id}/messages?${params.toString()}`));
        if (!response.ok) throw new Error(`Shared forgotten-message fetch failed: ${response.status}`);
        await handleOldMessagesResponse(await response.json() as {
          chat_id: string;
          checkpoint_id: string;
          messages?: Array<string | GlobalMessage>;
          has_more?: boolean;
          next_before_timestamp?: number | null;
          next_before_message_id?: string | null;
        });
        return;
      }
      // Retained local rows can be only a fragment of a compressed prefix.
      // Show them promptly, then fetch the canonical page with the original
      // cursor so a cache fragment cannot conceal missing archived messages.
      await loadLocalForgottenMessagePage(beforeTimestamp, beforeMessageId);
      await webSocketService.sendMessage('get_compressed_chat_old_messages', {
        chat_id: latestCompressionCheckpoint.chat_id,
        checkpoint_id: latestCompressionCheckpoint.id,
        before_timestamp: beforeTimestamp,
        before_message_id: beforeMessageId,
        limit: FORGOTTEN_MESSAGE_PAGE_LIMIT,
      });
    } catch (error) {
      oldCompressedMessagesLoading = false;
      console.warn('[ChatHistory] Failed to load forgotten messages', error);
    }
  }

  async function loadLocalForgottenMessagePage(
    beforeTimestamp: number,
    beforeMessageId: string | undefined,
  ): Promise<boolean> {
    if (!latestCompressionCheckpoint) return false;
    try {
      const window = await chatDB.getMessageWindowForChat(latestCompressionCheckpoint.chat_id, {
        direction: 'before',
        beforeTimestamp,
        beforeMessageId: beforeMessageId ?? LOCAL_FORGOTTEN_CURSOR_SENTINEL,
        limit: FORGOTTEN_MESSAGE_PAGE_LIMIT,
      });
      const messagesBeforeBoundary = window.messages.filter(
        (message) => message.created_at <= latestCompressionCheckpoint!.compressed_up_to_timestamp,
      );
      if (messagesBeforeBoundary.length === 0) return false;

      await chatDB.recordMessageWindowPage(latestCompressionCheckpoint.chat_id, window, {
        direction: 'before',
        pageKind: 'forgotten',
      });

      const existingIds = new Set(oldCompressedMessages.map((message) => message.message_id));
      const newMessages = messagesBeforeBoundary.filter((message) => !existingIds.has(message.message_id));
      oldCompressedMessages = [...newMessages, ...oldCompressedMessages].sort(
        (a, b) => a.created_at - b.created_at || a.message_id.localeCompare(b.message_id),
      );
      oldCompressedMessagesHasMore = window.hasMoreBefore;
      oldCompressedMessagesNextBeforeTimestamp = window.startCursor;
      oldCompressedMessagesNextBeforeMessageId = window.startCursorMessageId;
      return true;
    } catch (error) {
      console.warn('[ChatHistory] Failed to read local forgotten messages', error);
      return false;
    }
  }

  function getOlderMessagesCursor(): InternalMessage | null {
    return messages.find((message) => {
      if (message.role === 'system' && message.category === 'compression_summary') return false;
      if (isForgottenMessage(message)) return false;
      return !!message.original_message?.created_at && !!message.id;
    }) ?? null;
  }

  function requestOlderMessages(): void {
    if (timelineSection) return;
    const cursorMessage = getOlderMessagesCursor();
    if (!hasOlderMessages || olderMessagesLoading || !cursorMessage?.original_message) return;
    dispatch('loadOlderMessages', {
      beforeTimestamp: cursorMessage.original_message.created_at,
      beforeMessageId: cursorMessage.id,
      firstMessageId: cursorMessage.id,
    });
  }

  function isForgottenMessage(msg: InternalMessage): boolean {
    if (!latestCompressionCheckpoint) return false;
    if (isCompressionSummaryMessage(msg)) return false;
    return (msg.original_message?.created_at ?? 0) <= latestCompressionCheckpoint.compressed_up_to_timestamp;
  }

  function isCompressionSummaryMessage(msg: InternalMessage): boolean {
    return msg.role === 'system' && (msg.category === 'compression_summary' || msg.original_message?.category === 'compression_summary');
  }

  async function handleOldMessagesResponse(payload: {
    chat_id: string;
    checkpoint_id: string;
    messages?: Array<string | GlobalMessage>;
    has_more?: boolean;
    next_before_timestamp?: number | null;
    next_before_message_id?: string | null;
  }): Promise<void> {
    if (!latestCompressionCheckpoint || payload.checkpoint_id !== latestCompressionCheckpoint.id) return;
    const prepared: GlobalMessage[] = [];
    for (const item of payload.messages || []) {
      let message = item as GlobalMessage;
      if (typeof item === 'string') {
        try {
          message = JSON.parse(item) as GlobalMessage;
        } catch {
          continue;
        }
      }
      if (!message.message_id && (message as GlobalMessage & { id?: string }).id) {
        message.message_id = (message as GlobalMessage & { id?: string }).id!;
      }
      if (!message.chat_id) message.chat_id = payload.chat_id;
      if (!message.status) message.status = 'delivered';
      try {
        prepared.push(await chatDB.decryptMessageFields(message, payload.chat_id));
      } catch (error) {
        console.warn('[ChatHistory] Failed to decrypt compressed old message', message.message_id, error);
      }
    }
    const existingIds = new Set(oldCompressedMessages.map((message) => message.message_id));
    oldCompressedMessages = [
      ...prepared.filter((message) => !existingIds.has(message.message_id)),
      ...oldCompressedMessages,
    ].sort((a, b) => a.created_at - b.created_at || a.message_id.localeCompare(b.message_id));
    oldCompressedMessagesHasMore = !!payload.has_more;
    oldCompressedMessagesNextBeforeTimestamp = payload.next_before_timestamp ?? null;
    oldCompressedMessagesNextBeforeMessageId = payload.next_before_message_id ?? null;
    oldCompressedMessagesLoading = false;
  }

  let debugChatCopied = $state(false);
  let debugChatCopyTimer: ReturnType<typeof setTimeout> | null = null;

  function copyDebugChatText(): void {
    const text = $chatDebugStore.chatReport;
    if (!text) return;
    void navigator.clipboard.writeText(text).then(() => {
      debugChatCopied = true;
      if (debugChatCopyTimer) clearTimeout(debugChatCopyTimer);
      debugChatCopyTimer = setTimeout(() => { debugChatCopied = false; }, 2000);
    });
  }

  let lastAssistantMessageId = $derived.by(() => {
    for (let i = displayMessages.length - 1; i >= 0; i--) {
      if (displayMessages[i].role === 'assistant') {
        return displayMessages[i].id;
      }
    }
    return null;
  });

  const ASSISTANT_RATING_VALUES = [1, 2, 3, 4, 5] as const;
  const ASSISTANT_FEEDBACK_STORAGE_KEY = 'openmates.assistantFeedback.submitted.v1';
  const ASSISTANT_FEEDBACK_THANKS_VISIBLE_MS = 2600;
  const ASSISTANT_FEEDBACK_THANKS_FADE_MS = 260;
  let assistantFeedbackMessageId = $state<string | null>(null);
  let selectedAssistantRating = $state<number | null>(null);
  let assistantFeedbackSubmitted = $state(false);
  let submittedAssistantFeedbackKeys = $state<string[]>([]);
  let assistantFeedbackThanksState = $state<'hidden' | 'visible' | 'hiding'>('hidden');
  let assistantFeedbackThanksTimer: ReturnType<typeof setTimeout> | null = null;
  let assistantFeedbackThanksCleanupTimer: ReturnType<typeof setTimeout> | null = null;

  // Show/hide the messages block for fade-out animation using $state (Svelte 5 runes mode)
  let showMessages = $state(true);
  const HISTORY_REVEAL_DURATION_MS = 180;
  let historyRevealMessageIds = $state<Set<string>>(new Set());
  let historyRevealTimer: ReturnType<typeof setTimeout> | null = null;

  function revealLoadedHistory(messageIds: string[]) {
    if (historyRevealTimer) clearTimeout(historyRevealTimer);
    historyRevealMessageIds = new Set(messageIds);
    historyRevealTimer = setTimeout(() => {
      historyRevealMessageIds = new Set();
      historyRevealTimer = null;
    }, HISTORY_REVEAL_DURATION_MS);
  }

  // Reference to the chat history container for scrolling.
  let container: HTMLDivElement;

  // Bound to the chat-header-wrapper div; used by the IntersectionObserver below.
  let headerWrapperEl = $state<HTMLElement | null>(null);
  let callStripStuck = $state(false);

  function observeCallHeaderEnd(node: HTMLElement) {
    const scrollRoot = node.closest<HTMLElement>('.chat-history-container');
    if (!scrollRoot) return;
    let disposed = false;
    let strip: HTMLElement | null = null;
    const stageHeightProperty = '--voice-call-stage-max-height';
    function measureCallStage() {
      if (disposed) return;
      // Actions can mount before their following sibling. Keep observing the
      // stable strip so media insertion/replacement also updates the allowance.
      const sibling = node.nextElementSibling;
      if (sibling instanceof HTMLElement && sibling.classList.contains('voice-call-strip') && sibling !== strip) {
        if (strip) {
          resizeObserver.unobserve(strip);
          strip.style.removeProperty(stageHeightProperty);
        }
        strip = sibling;
        resizeObserver.observe(strip);
      }
      if (!strip) return;
      const bar = strip.querySelector<HTMLElement>('.voice-call-bar');
      if (!bar) return;
      const media = bar.querySelector<HTMLElement>('.call-media');
      const toolbarHeight = bar.offsetHeight - (media?.offsetHeight ?? 0);
      const rootStyle = getComputedStyle(scrollRoot);
      const padding = Number.parseFloat(rootStyle.paddingTop) + Number.parseFloat(rootStyle.paddingBottom);
      // The composer shrinks this scrollport independently of the window. The
      // whole sticky strip must fit here, including its toolbar and padding.
      const availableHeight = Math.max(0, Math.floor(scrollRoot.clientHeight - padding - toolbarHeight));
      const value = `${availableHeight}px`;
      if (strip.style.getPropertyValue(stageHeightProperty) !== value) strip.style.setProperty(stageHeightProperty, value);
    }
    const resizeObserver = new ResizeObserver(measureCallStage);
    resizeObserver.observe(scrollRoot);
    void tick().then(measureCallStage);
    const observer = new IntersectionObserver(([entry]) => {
      const stuck = !entry.isIntersecting && !!entry.rootBounds &&
        entry.boundingClientRect.bottom <= entry.rootBounds.top;
      callStripStuck = stuck;
      voiceCallBridge?.onStickyChange(stuck);
    }, { root: scrollRoot, threshold: 0 });
    observer.observe(node);
    return { destroy() {
      disposed = true;
      observer.disconnect();
      resizeObserver.disconnect();
      // The property belongs to this strip, never the shared scroll root, so an
      // outgoing chat cannot remove a newer chat's measured allowance.
      strip?.style.removeProperty(stageHeightProperty);
      voiceCallBridge?.onStickyChange(false);
    } };
  }

  // The intro video now uses the full banner as a media hero. Keep auth CTAs in
  // the app header so the banner can stay focused on playback.
  const showSignupCta = $derived(false);

  // Keep introBannerVisible in sync with whether the banner is visible in the viewport.
  // When it is visible, Header hides its own signup button so there's no duplicate CTA.
  $effect(() => {
    if (!headerWrapperEl || !showSignupCta) {
      introBannerVisible.set(false);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => { introBannerVisible.set(entry.isIntersecting); },
      { threshold: 0.1 }
    );
    observer.observe(headerWrapperEl);
    return () => {
      observer.disconnect();
      introBannerVisible.set(false);
    };
  });

  // Props using Svelte 5 runes mode
  let {
    disablePointerEvents = false,
    messageInputHeight = 0,
    sourceMessages = [],
    containerWidth = 0,
    currentChatId = undefined,
    processingPhase = null,
    pendingAssistantResponse = null,
    activeAssistantTurn = null,
    thinkingContentByTask = new Map(),
    // Chat header props: shown at the top of new chats only.
    // chatTitle / chatCategory / chatIcon are the decrypted metadata once received.
    // isNewChatGeneratingTitle=true shows the "Generating title..." placeholder instead.
    chatTitle = '',
    provisionalChatTitle = '',
    chatCategory = null,
    chatIcon = null,
    chatSummary = null,
    chatHeaderRenderKey = 0,
    chatCreatedAt = null,
    chatTimeLabel = 'started',
    isDraftOnly = false,
    isNewChatGeneratingTitle = false,
    isNewChatCreditsError = false,
    isCreditsRestored = false,
    onResend = undefined,
    isIncognito = false,
    isExampleChat = false,
    isSharedChat = false,
    isDirectChat = false,
    videoMp4Url = null,
    videoTeaserUrl = null,
    videoTeaserMp4Url = null,
    videoTeaserWebpUrl = null,
    backgroundFrames = null,
    autoplayVideo = false,
    followUpSuggestions = [],
    quickTipSlugs = [],
    compressionCheckpoints = [],
    hasOlderMessages = false,
    olderMessagesLoading = false,
    onSuggestionClick = undefined,
    onChatNavigate = undefined,
    onSpeakMessage = undefined,
    canSpeakMessage = undefined,
    onQueuedEdit = undefined,
    onQueuedSteer = undefined,
    queuedActionBusyMessageId = null,
    queuedActionErrors = {},
    canAnnotate = true,
    voiceCallBridge = undefined,
    timelineOverlayOpen = $bindable(false),
    timelinePanelId = undefined,
  }: {
    disablePointerEvents?: boolean;
    timelineOverlayOpen?: boolean;
    timelinePanelId?: string;
    voiceCallBridge?: { controls: Snippet<[boolean]>; onStickyChange: (stuck: boolean) => void };
    messageInputHeight?: number;
    sourceMessages?: GlobalMessage[];
    containerWidth?: number;
    currentChatId?: string; // Current active chat ID - used to ensure permission dialog only shows in the originating chat
    processingPhase?: ProcessingPhase; // Current phase of the AI processing pipeline (sending → processing → typing → null)
    pendingAssistantResponse?: {
      taskId: string; userMessageId: string; category?: string | null;
      modelName?: string | null; serverRegion?: string | null;
    } | null;
    activeAssistantTurn?: { taskId: string; userMessageId: string } | null;
    thinkingContentByTask?: Map<string, { content: string; isStreaming: boolean; signature?: string | null; totalTokens?: number | null }>; // Thinking content from thinking models

    /** Decrypted title to show in the permanent header card (new chats only). */
    chatTitle?: string;
    provisionalChatTitle?: string;
    /** Decrypted category (e.g. "technology") for the gradient circle (new chats only). */
    chatCategory?: string | null;
    /** Decrypted icon name (e.g. "cpu") for the category circle (new chats only). */
    chatIcon?: string | null;
    /** Decrypted chat summary — shown as 14px text below the title if available. */
    chatSummary?: string | null;
    /** Incremented by ActiveChat when fullscreen layout changes require a clean header repaint. */
    chatHeaderRenderKey?: number;
    /** Unix timestamp in seconds of when the chat was created or published. */
    chatCreatedAt?: number | null;
    /** Label variant for the timestamp line in the header banner. */
    chatTimeLabel?: 'started' | 'published' | 'saved';
    /** True when this is a persisted draft shell with no sent messages or generated metadata. */
    isDraftOnly?: boolean;
    /** True while the server is still generating the title/category/icon for a new chat.
     *  Shows the "Creating new chat ..." shimmer placeholder instead of the full card. */
    isNewChatGeneratingTitle?: boolean;
    /** True when the first message on this new chat was rejected due to insufficient credits.
     *  Keeps the header banner visible with a "Not enough credits" state instead of dismissing it. */
    isNewChatCreditsError?: boolean;
    /** True when the user now has credits again after a credits rejection.
     *  Passed through to ChatMessage so the system notice can switch to "Resend message" mode. */
    isCreditsRestored?: boolean;
    /** Callback to resend the original message after credits are restored.
     *  Passed through to ChatMessage; called when the user clicks "Resend message". */
    onResend?: () => void;
    /** True when the active chat is an incognito chat.
     *  Shows the incognito-specific ChatHeader variant immediately (no shimmer needed). */
    isIncognito?: boolean;
    /** False when the viewer is looking at a shared chat they don't own.
     *  Passed through to every ChatMessage to hide the Highlight entry points
     *  (context menu + selection toolbar). Mirrors the backend owner-only
     *  enforcement in message_highlight_handlers. Defaults to true. */
    canAnnotate?: boolean;
    /** True when the active chat is a pre-made example chat.
     *  Shows an "Example chat" badge in the ChatHeader. */
    isExampleChat?: boolean;
    /** True when the active chat was opened from a shared-chat link. */
    isSharedChat?: boolean;
    isDirectChat?: boolean;
    /** api.video MP4 URL. Only used to gate the play button in the chat header —
     *  the full MP4 is loaded on demand when the user clicks play. */
    videoMp4Url?: string | null;
    /** Tiny silent autoplay teaser rendered before the user clicks the full video. */
    videoTeaserUrl?: string | null;
    /** MP4 fallback for browsers that cannot play the WebM teaser. */
    videoTeaserMp4Url?: string | null;
    /** WebP poster/fallback for the silent autoplay teaser. */
    videoTeaserWebpUrl?: string | null;
    /** Background frame image URLs rendered inside the chat header's 16:9 media
     *  frame as a crossfading Ken-Burns slideshow. */
    backgroundFrames?: string[] | null;
    /** When true, auto-starts video playback on mount (from &autoplay-video deep link). */
    autoplayVideo?: boolean;
    /** Follow-up suggestions to display below the last assistant message.
     *  Passed from ActiveChat; shown without input-focus requirement so users
     *  see them immediately without clicking the message input. */
    followUpSuggestions?: string[];
    quickTipSlugs?: string[];
    /** Callback fired when the user clicks a follow-up suggestion. */
    onSuggestionClick?: (suggestion: string) => void;
    onChatNavigate?: (chatId: string) => Promise<void> | void;
    onSpeakMessage?: (messageId: string, content: string) => Promise<void> | void;
    canSpeakMessage?: (messageId: string) => boolean;
    /** Actions for a user message waiting on assistant work. */
    onQueuedEdit?: (message: GlobalMessage) => void;
    onQueuedSteer?: (message: GlobalMessage) => void | Promise<void>;
    queuedActionBusyMessageId?: string | null;
    queuedActionErrors?: Record<string, string>;
    compressionCheckpoints?: ChatCompressionCheckpoint[];
    hasOlderMessages?: boolean;
    olderMessagesLoading?: boolean;
  } = $props();

  let timelineScopeKey = $derived(`${currentChatId ?? ''}:${$activeTeamId ?? ''}:${$userProfile.user_id ?? ''}`);
  let timelineRemoteEnabled = $derived(!!currentChatId && !isExampleChat && !isIncognito && (isSharedChat || $authStore.isAuthenticated));
  let timelineAllEntries = $derived(mergeTimelineEntries(timelineCatalogue, sourceMessages, oldCompressedMessages));
  const bookmarkMode = $derived<BookmarkMode>(isIncognito ? 'transient' : $authStore.isAuthenticated ? 'account' : 'device');
  const bookmarkedIds = $derived.by(() => {
    void $messageBookmarksStore; void $userProfile.encrypted_settings;
    return currentChatId ? getMessageBookmarkIds(currentChatId, bookmarkMode) : new Set<string>();
  });
  const timelineIndex = $derived(buildTimelineExchangeIndex(timelineAllEntries, bookmarkedIds));
  const timelineUserEntries = $derived(timelineIndex.entries);
  const timelineEnabled = $derived(timelineIndex.answeredCount >= 2);
  $effect(() => {
    void timelineScopeKey; void timelineNarrow; void timelineEnabled; void disablePointerEvents;
    timelineOverlayOpen = false;
  });
  $effect(() => {
    void timelineScopeKey;
    dispatch('timelineStateChange', { available: timelineEnabled && !disablePointerEvents, narrow: timelineNarrow });
  });
  $effect(() => {
    const chatId = currentChatId, mode = bookmarkMode;
    void timelineScopeKey; void $userProfile.encrypted_settings; void $messageBookmarksStore.localRevision;
    if (chatId) void loadMessageBookmarks(chatId, mode).catch(() => { /* A toggle exposes a retryable save failure. */ });
  });
  $effect(() => {
    const chatId = currentChatId, mode = bookmarkMode;
    return () => { if (chatId && mode === 'transient') clearTransientMessageBookmarks(chatId); };
  });
  function toggleBookmark(messageId: string): Promise<void> {
    if (!currentChatId) return Promise.reject(new Error('Bookmark chat unavailable'));
    return toggleMessageBookmark(currentChatId, messageId, bookmarkMode, timelineIndex.legacyAliases.get(messageId) ?? []);
  }
  let timelineCurrentId = $derived.by(() => {
    const index = timelineAllEntries.findIndex(entry => entry.message_id === timelineVisibleMessageId);
    if (index < 0) return timelineUserEntries[timelineUserEntries.length - 1]?.message_id ?? null;
    const current = timelineAllEntries[index];
    if (current.role === 'user') return current.message_id;
    if (current.user_message_id) return current.user_message_id;
    for (let i = index; i >= 0; i--) if (timelineAllEntries[i].role === 'user') return timelineAllEntries[i].message_id;
    return null;
  });

  const showPendingAssistantResponse = $derived(!timelineSection && !!pendingAssistantResponse
    && !displayMessages.some((message) => message.role === 'assistant'
      && (message.id === pendingAssistantResponse.taskId
        || message.original_message?.user_message_id === pendingAssistantResponse.userMessageId)));


  let hydratedQuickTipSlugs = $state<string[]>([]);
  let effectiveQuickTipSlugs = $derived(
    quickTipSlugs.length > 0 ? quickTipSlugs : hydratedQuickTipSlugs
  );
  // Persisted tips are a login-recovery fallback only; once live props own a chat,
  // do not revive its previous tips after a later message clears them.
  let quickTipPropsSeenChatId: string | null = null;
  let quickTipHydrationAttemptKey: string | null = null;
  let quickTipKeyReadyVersion = $state(0);
  let quickTipHydrationGeneration = 0;

  onMount(() => chatKeyManager.onKeyReady((chatId) => {
    if (chatId === currentChatId) quickTipKeyReadyVersion += 1;
  }));

  $effect(() => {
    const isAuthenticated = $authStore.isAuthenticated;
    const chatId = currentChatId;
    const lastMessageRole = sourceMessages[sourceMessages.length - 1]?.role;
    const hydrationAttemptKey = chatId ? `${chatId}:${quickTipKeyReadyVersion}` : null;
    const generation = ++quickTipHydrationGeneration;

    if (!isAuthenticated) {
      hydratedQuickTipSlugs = [];
      quickTipPropsSeenChatId = null;
      quickTipHydrationAttemptKey = null;
      return;
    }
    if (quickTipSlugs.length > 0) {
      hydratedQuickTipSlugs = [];
      quickTipPropsSeenChatId = chatId ?? null;
      return;
    }
    if (
      !chatId ||
      lastMessageRole !== 'assistant' ||
      isPublicChat(chatId) ||
      quickTipPropsSeenChatId === chatId ||
      quickTipHydrationAttemptKey === hydrationAttemptKey
    ) {
      hydratedQuickTipSlugs = [];
      return;
    }
    hydratedQuickTipSlugs = [];
    quickTipHydrationAttemptKey = hydrationAttemptKey;

    void (async () => {
      try {
        const storedChat = await chatDB.getChat(chatId);
        if (!storedChat?.encrypted_quick_tip_slugs) return;
        const chatKey = await chatKeyManager.getKey(chatId);
        if (!chatKey) return;
        const { decryptArrayWithChatKey } = await import('../services/cryptoService');
        const slugs = await decryptArrayWithChatKey(storedChat.encrypted_quick_tip_slugs, chatKey) || [];
        if (
          generation === quickTipHydrationGeneration &&
          $authStore.isAuthenticated &&
          currentChatId === chatId &&
          quickTipSlugs.length === 0
        ) {
          hydratedQuickTipSlugs = slugs;
        }
      } catch (error) {
        console.error(`[ChatHistory] Failed to hydrate quick tips for chat ${chatId}:`, error);
      }
    })();
  });

  let lastSourceSyncChatKey = $state<string | undefined>(undefined);

  $effect(() => {
    const incomingMessages = sourceMessages;
    const sourceChatKey = currentChatId ?? incomingMessages[0]?.chat_id;
    const sourceChatChanged = sourceChatKey !== lastSourceSyncChatKey;
    const internalMessagesEmpty = untrack(() => messages.length === 0);

    if (incomingMessages.length === 0) {
      if (sourceChatChanged) {
        lastSourceSyncChatKey = sourceChatKey;
        untrack(() => updateMessages([]));
      }
      return;
    }

    if (!internalMessagesEmpty && !sourceChatChanged) return;
    lastSourceSyncChatKey = sourceChatKey;
    untrack(() => updateMessages(incomingMessages));
  });

  const COMPOSER_CLEARANCE_PX = 24;
  // Add reactive statement to handle height changes using $derived (Svelte 5 runes mode)
  let containerStyle = $derived(`bottom: ${Math.max(0, messageInputHeight + COMPOSER_CLEARANCE_PX)}px`);

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

  let shouldShowConnectedAccountPermissionDialog = $derived(
    $isConnectedAccountPermissionVisible &&
    $currentConnectedAccountPermissionRequest?.chatId &&
    currentChatId &&
    $currentConnectedAccountPermissionRequest.chatId === currentChatId
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
      responseTransport: unpairedRequest.response_transport,
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

  // Effect: Auto-dismiss dialog when response arrives from another device.
  // The show-dialog effect above only fires when unpairedRequest is non-null.
  // This complementary effect hides the dialog when the response system message
  // arrives (via cross-device broadcast or sync) and unpairedRequest becomes null.
  $effect(() => {
    if (unpairedRequest === null && $isPermissionDialogVisible &&
        $currentPermissionRequest?.chatId === currentChatId) {
      console.info(
        `[ChatHistory] Permission response detected (cross-device sync) ` +
        `for chat ${currentChatId} — dismissing dialog`
      );
      appSettingsMemoriesPermissionStore.hideDialog();
    }
  });

  // Determine if we should show settings/memories suggestions
  // Only show after the last assistant message when:
  // 1. We have suggestions to show
  // 2. We have a current chat ID
  // 3. The last message is from the assistant (not streaming)

  const dispatch = createEventDispatcher();

  // CRITICAL: These must be $state() for Svelte 5 reactivity.
  // The scroll $effect at line ~689 reads these variables, and without $state(),
  // changes to them won't trigger re-execution of the effect — breaking the
  // ChatGPT-style scroll that positions the user message near the top after sending.
  let lastUserMessageId = $state<string | null>(null);
  let shouldScrollToNewUserMessage = $state(false);
  let isScrolling = $state(false);
  let newUserMessageScrollEpoch = 0;
  let pendingNewUserMessageScrollTimer: ReturnType<typeof setTimeout> | null = null;

  function cancelPendingNewUserMessageScroll(): void {
    newUserMessageScrollEpoch += 1;
    if (pendingNewUserMessageScrollTimer) clearTimeout(pendingNewUserMessageScrollTimer);
    pendingNewUserMessageScrollTimer = null;
  }

  // Track whether the scroll container is at the very top.
  // Used to conditionally suppress the top gradient fade on .chat-history-container
  // so the banner (which sits at the top) isn't clipped by the fade when in view.
  // Starts true since the chat opens scrolled to the top.
  let isAtTop = $state(true);
  
  // Track whether the user has manually scrolled away during streaming.
  // When true, spacer height updates are frozen to prevent disrupting the user's scroll position.
  let userHasScrolledAway = $state(false);

  // Detect if any message is currently streaming
  let isCurrentlyStreaming = $derived(
    messages.some(m => m.status === 'streaming')
  );

  /**
   * Show follow-up suggestions below the last assistant message when:
   * 1. There are suggestions to show
   * 2. The last message is from the assistant
   * 3. No message is currently streaming
   */
  let showFollowUpSuggestionsInHistory = $derived(
    followUpSuggestions.length > 0 &&
    lastAssistantMessageId !== null &&
    !isCurrentlyStreaming
  );

  let showQuickTipsInHistory = $derived(
    effectiveQuickTipSlugs.length > 0 &&
    lastAssistantMessageId !== null &&
    !isCurrentlyStreaming
  );

  let showAssistantFeedback = $derived(
    lastAssistantMessageId !== null &&
    !isCurrentlyStreaming
  );

  let assistantFeedbackKey = $derived(
    currentChatId && lastAssistantMessageId ? `${currentChatId}:${lastAssistantMessageId}` : null
  );

  function handleQuickTipAction(tip: QuickTipDefinition): void {
    dispatch('quickTipAction', tip);
  }

  $effect(() => {
    const submittedForCurrentMessage = assistantFeedbackKey !== null && submittedAssistantFeedbackKeys.includes(assistantFeedbackKey);
    if (assistantFeedbackMessageId === lastAssistantMessageId && assistantFeedbackSubmitted === submittedForCurrentMessage) return;

    assistantFeedbackMessageId = lastAssistantMessageId;
    selectedAssistantRating = null;
    assistantFeedbackSubmitted = submittedForCurrentMessage;
    assistantFeedbackThanksState = 'hidden';
    clearAssistantFeedbackThanksTimers();
  });

  onMount(() => {
    submittedAssistantFeedbackKeys = loadSubmittedAssistantFeedbackKeys();
  });

  onMount(() => {
    const handleEmbedUpdated = (event: Event) => {
      const detail = (event as CustomEvent<{
        embed_id?: string;
        child_embed_ids?: string[] | string;
        embed_ids?: string[] | string;
      }>).detail;
      rememberHeaderImageBubbleChildIds(detail?.embed_id, detail?.child_embed_ids ?? detail?.embed_ids);
    };

    chatSyncService.addEventListener('embedUpdated', handleEmbedUpdated);
    return () => chatSyncService.removeEventListener('embedUpdated', handleEmbedUpdated);
  });

  onDestroy(() => {
    timelineGeneration++;
    timelineController?.abort();
    timelineSections.clear();
    clearAssistantFeedbackThanksTimers();
  });

  function loadSubmittedAssistantFeedbackKeys(): string[] {
    try {
      const stored = localStorage.getItem(ASSISTANT_FEEDBACK_STORAGE_KEY);
      const parsed: unknown = stored ? JSON.parse(stored) : [];
      return Array.isArray(parsed) ? parsed.filter((key): key is string => typeof key === 'string') : [];
    } catch (error) {
      console.warn('[ChatHistory] Failed to load submitted assistant feedback state', error);
      return [];
    }
  }

  function persistSubmittedAssistantFeedbackKey(key: string): void {
    const nextKeys = [key, ...submittedAssistantFeedbackKeys.filter((existing) => existing !== key)].slice(0, 200);
    submittedAssistantFeedbackKeys = nextKeys;
    try {
      localStorage.setItem(ASSISTANT_FEEDBACK_STORAGE_KEY, JSON.stringify(nextKeys));
    } catch (error) {
      console.warn('[ChatHistory] Failed to persist submitted assistant feedback state', error);
    }
  }

  function clearAssistantFeedbackThanksTimers(): void {
    if (assistantFeedbackThanksTimer) clearTimeout(assistantFeedbackThanksTimer);
    if (assistantFeedbackThanksCleanupTimer) clearTimeout(assistantFeedbackThanksCleanupTimer);
    assistantFeedbackThanksTimer = null;
    assistantFeedbackThanksCleanupTimer = null;
  }

  function showAssistantFeedbackThanks(): void {
    clearAssistantFeedbackThanksTimers();
    assistantFeedbackThanksState = 'visible';
    assistantFeedbackThanksTimer = setTimeout(() => {
      assistantFeedbackThanksState = 'hiding';
      assistantFeedbackThanksCleanupTimer = setTimeout(() => {
        assistantFeedbackThanksState = 'hidden';
        assistantFeedbackThanksCleanupTimer = null;
      }, ASSISTANT_FEEDBACK_THANKS_FADE_MS);
      assistantFeedbackThanksTimer = null;
    }, ASSISTANT_FEEDBACK_THANKS_VISIBLE_MS);
  }

  function openReportIssue(issueType: 'bug_report' | 'feature_request', title?: string): void {
    reportIssueStore.set({
      title: title ?? (issueType === 'feature_request'
        ? $text('chat.request_feature_prefill')
        : ''),
      issueType,
      shareChat: true,
    });
    settingsDeepLink.set('report_issue');
    panelState.openSettings();
  }

  function handleAssistantFeedbackSubmit(): void {
    if (selectedAssistantRating === null) return;

    if (assistantFeedbackKey) {
      persistSubmittedAssistantFeedbackKey(assistantFeedbackKey);
    }
    assistantFeedbackSubmitted = true;
    showAssistantFeedbackThanks();

    if (selectedAssistantRating <= 3) {
      openReportIssue('bug_report', $text('chat.assistant_feedback.report_title'));
    }
  }
  
  // NOTE: The centered AI status overlay has been removed. The spacer system directly uses
  // `processingPhase !== null` to know when AI processing is happening (affects scroll behaviour).

  let chatHeaderWritable = $derived(
    !!currentChatId &&
    !isIncognito &&
    !isExampleChat &&
    !isSharedChat &&
    !isDraftOnly &&
    !isPublicChat(currentChatId)
  );

  // Whether to show the chat header card (or its loading placeholder) at the top of the chat.
  // Owned writable chats keep the unified detail shell visible even while encrypted
  // metadata is still catching up after hash/cold-boot navigation.
  // The header is visible as long as any of these are true:
  //   a) isNewChatGeneratingTitle is true (shimmer placeholder state), or
  //   b) we have a title (loaded state; category may be missing on older partial metadata), or
  //   c) isNewChatCreditsError is true (credits error state), or
  //   d) isIncognito is true (always show the incognito header immediately), or
  //   e) isSharedChat is true (badge remains visible even if shared metadata has no title), or
  //   f) this is an owned writable chat whose encrypted title is not yet available.
  let showChatHeader = $derived(
    !isDraftOnly && (isIncognito || isNewChatGeneratingTitle || isNewChatCreditsError || !!chatTitle || isSharedChat || isDirectChat || chatHeaderWritable),
  );

  async function saveChatHeaderTitle(title: string): Promise<void> {
    if (!currentChatId || !chatHeaderWritable) throw new Error('Chat title is read-only');
    await chatSyncService.sendUpdateTitle(currentChatId, title);
  }

  async function saveChatHeaderSummary(summary: string): Promise<void> {
    if (!currentChatId || !chatHeaderWritable) throw new Error('Chat summary is read-only');
    await chatSyncService.sendUpdateSummary(currentChatId, summary);
  }

  $effect(() => {
    const chatKey = currentChatId;
    if (headerImageBubbleChatKey !== chatKey) {
      headerImageBubbleChatKey = chatKey;
      headerImageBubbles = null;
      headerImageBubbleRequestId += 1;
    }
    const retryTick = headerImageBubbleRetryTick;

    if (!showChatHeader || isIncognito || isNewChatGeneratingTitle || isNewChatCreditsError) {
      headerImageBubbleRequestId += 1;
      headerImageBubbleCandidateKey = '';
      headerImageBubbleRetryBaseKey = '';
      headerImageBubbleRetryCount = 0;
      clearHeaderImageBubbleRetry();
      headerImageBubbles = null;
      void persistResumeCardImageBubbles(null);
      return;
    }

    const candidates: ImageSearchCandidate[] = [];
    const linkedRefs = Array.from(new Set(messages
      .filter(message => message.role === 'assistant')
      .flatMap(message => collectHeaderImageRefs(message.content))));
    const refIndexVersion = $embedRefIndexVersion;
    for (const message of messages) {
      collectImageSearchCandidates(message.content as TiptapNode | undefined, candidates);
    }

    if (candidates.length === 0 && linkedRefs.length === 0) {
      headerImageBubbleRequestId += 1;
      headerImageBubbleCandidateKey = '';
      headerImageBubbleRetryBaseKey = '';
      headerImageBubbleRetryCount = 0;
      clearHeaderImageBubbleRetry();
      headerImageBubbles = null;
      void persistResumeCardImageBubbles(null);
      return;
    }

    const embedUpdateKey = messages
      .map(message => message._embedUpdateTimestamp ?? '')
      .join('|');
    const baseCandidateKey = `${chatKey}:${candidates
      .map(candidate => `${candidate.parentEmbedId}:${candidate.childEmbedIds.join('|')}`)
      .join(';')}#${embedUpdateKey}#${linkedRefs.join('|')}#${refIndexVersion}`;
    if (baseCandidateKey !== headerImageBubbleRetryBaseKey) {
      headerImageBubbleRetryBaseKey = baseCandidateKey;
      headerImageBubbleRetryCount = 0;
      clearHeaderImageBubbleRetry();
    }

    const candidateKey = `${baseCandidateKey}#retry:${retryTick}`;
    if (candidateKey === headerImageBubbleCandidateKey) return;
    headerImageBubbleCandidateKey = candidateKey;
    const requestId = ++headerImageBubbleRequestId;

    resolveHeaderImageBubbles(candidates, linkedRefs, chatKey)
      .then((bubbles) => {
        if (requestId !== headerImageBubbleRequestId) return;
        headerImageBubbles = bubbles.length > 0 ? bubbles : null;
        if (bubbles.length > 0) {
          headerImageBubbleRetryCount = 0;
          clearHeaderImageBubbleRetry();
          void persistResumeCardImageBubbles(bubbles.map(({ imageUrl, title }) => ({ imageUrl, title })).slice(0, 2));
          return;
        }

        if (!scheduleHeaderImageBubbleRetry(baseCandidateKey)) {
          void persistResumeCardImageBubbles(null);
        }
      })
      .catch((error) => {
        if (requestId !== headerImageBubbleRequestId) return;
        console.warn('[ChatHistory] Failed to resolve image-search header bubbles:', error);
        headerImageBubbles = null;
        if (!scheduleHeaderImageBubbleRetry(baseCandidateKey)) {
          void persistResumeCardImageBubbles(null);
        }
      });
  });

  // ─── Highlights aggregation for ChatHeader pill + navigation overlay ─────
  // Per-chat reactive selectors. The store is keyed by chat_id so switching
  // chats just re-binds the derived to a new slice.
  let highlightStatsStore = $derived(
    currentChatId ? selectHighlightStatsForChat(currentChatId) : null,
  );
  let highlightStats = $state<{ highlights: number; comments: number } | null>(null);
  $effect(() => {
    if (!highlightStatsStore) { highlightStats = null; return; }
    const unsub = highlightStatsStore.subscribe((v) => { highlightStats = v; });
    return unsub;
  });

  // Sync ordered highlight list into the navigation store whenever it changes.
  let highlightsFlatStore = $derived(
    currentChatId ? selectHighlightsForChatFlat(currentChatId) : null,
  );
  $effect(() => {
    if (!highlightsFlatStore || !currentChatId) return;
    const unsub = highlightsFlatStore.subscribe((list) => {
      setOrderedHighlights(currentChatId!, list);
    });
    return unsub;
  });

  function handleHighlightJump() {
    jumpToFirstHighlight();
  }

  // Active highlight DOM rect for the navigation overlay. The overlay needs
  // a DOMRect anchor, so on every `jumpRequestId` tick we re-query the page
  // for the currently-focused highlight box via its data-testid + data id.
  let overlayAnchorRect = $state<DOMRect | null>(null);
  $effect(() => {
    const navState = $highlightNavigationStore;
    void navState.jumpRequestId;
    if (!navState.focusedHighlightId) { overlayAnchorRect = null; return; }
    // Defer to next frame so the box has rendered after scrollIntoView.
    requestAnimationFrame(() => {
      const el = document.querySelector(
        `[data-testid="message-highlight-box"][data-highlight-id="${navState.focusedHighlightId}"]`,
      ) as HTMLElement | null;
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        // Defer rect capture until after smooth-scroll settles.
        setTimeout(() => {
          overlayAnchorRect = el.getBoundingClientRect();
        }, 350);
      }
    });
  });
  
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
    
    // Build cumulative PII mappings from existing messages + the new message
    // This allows assistant messages to restore PII from any preceding user message
    const allOriginalMessages = [
      ...messages.map(m => m.original_message).filter((m): m is GlobalMessage => m !== undefined),
      incomingMessage
    ];
    const piiMappings = buildCumulativePIIMappings(allOriginalMessages);
    
    const messageForHistory: InternalMessage = G_mapToInternalMessage(incomingMessage, piiMappings);
    
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
    cancelAllStreamingRenders();
    cancelPendingNewUserMessageScroll();
    isScrolling = false;
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
      cancelPendingNewUserMessageScroll();
      isScrolling = false;
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
  // isNewChat keeps optimistic rows out of the saved-history entrance animation.
  export function updateMessages(newMessagesArray: GlobalMessage[], isNewChat = false) {
    if (newMessagesArray.length === 0) {
      cancelPendingNewUserMessageScroll();
      lastUserMessageId = null;
      shouldScrollToNewUserMessage = false;
      isScrolling = false;
      isSpacerActive = false;
      spacerHeight = 0;
      userHasScrolledAway = false;
      if (spacerSafetyTimeout) { clearTimeout(spacerSafetyTimeout); spacerSafetyTimeout = null; }
    }
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
    
    const orderedMessages = orderSharedInteractiveQuestionMessages(newMessagesArray);

    // Display merge: show focus activation + following assistant as one bubble
    const mergedForDisplay = mergeAssistantContinuationsForDisplay(orderedMessages);
    
    // Build cumulative PII mappings from all user messages in the incoming array
    // This allows assistant messages to restore PII from any preceding user message
    const piiMappings = buildCumulativePIIMappings(mergedForDisplay);
    const scheduledAssistantRenders: Array<{
      scheduler: StreamingRenderScheduler<ScheduledAssistantRender>;
      value: ScheduledAssistantRender;
      revision: number;
      semanticBoundary: boolean;
    }> = [];
    const activeStreamingMessageIds = new Set<string>();
    
    const newInternalMessages = mergedForDisplay.map(newMessage => {
        const oldMessage = messages.find(m => m.id === newMessage.message_id);
        const hasEmbedUpdate = (newMessage as MessageWithEmbedMetadata)._embedUpdateTimestamp !== undefined;

        if (
            newMessage.role === 'assistant' &&
            newMessage.status === 'streaming' &&
            typeof newMessage.content === 'string'
        ) {
            activeStreamingMessageIds.add(newMessage.message_id);

            if (!oldMessage || localeChanged || hasEmbedUpdate) {
                cancelStreamingRender(newMessage.message_id);
                const revision = 1;
                streamingRenderRevisions.set(newMessage.message_id, {
                    content: newMessage.content,
                    revision,
                });
                getStreamingRenderScheduler(newMessage.message_id).seedRenderedRevision(revision);
                return G_mapToInternalMessage(newMessage, piiMappings);
            }

            const previousRevision = streamingRenderRevisions.get(newMessage.message_id);
            if (previousRevision?.content === newMessage.content) {
                return {
                    ...oldMessage,
                    status: newMessage.status,
                    original_message: newMessage,
                    appCards: (newMessage as MessageWithEmbedMetadata).appCards,
                };
            }

            const revision = (previousRevision?.revision ?? 0) + 1;
            streamingRenderRevisions.set(newMessage.message_id, {
                content: newMessage.content,
                revision,
            });
            scheduledAssistantRenders.push({
              scheduler: getStreamingRenderScheduler(newMessage.message_id),
              value: { message: newMessage, piiMappings },
              revision,
              semanticBoundary: newMessage.content.slice(previousRevision?.content.length || 0).includes('\n\n') ||
                /```\s*$/.test(newMessage.content),
            });

            // Keep the last compiled document until the per-message scheduler flushes.
            return {
                ...oldMessage,
                status: newMessage.status,
                original_message: newMessage,
                appCards: (newMessage as MessageWithEmbedMetadata).appCards,
            };
        }

        cancelStreamingRender(newMessage.message_id);

        // PERFORMANCE OPTIMIZATION: Skip G_mapToInternalMessage entirely for messages
        // whose raw content, status, and metadata have not changed since the last render.
        //
        // This is the critical fix for the user-message re-render glitch: every AI streaming
        // chunk triggers updateMessages() with the full messages array. Without this guard,
        // G_mapToInternalMessage is called for EVERY message on EVERY chunk, including user
        // messages with large image embeds. G_mapToInternalMessage calls parse_message →
        // preprocessTiptapJsonForEmbeds → embed resolver, which fires network requests for
        // every image embed on every AI response chunk.
        //
        // We can safely skip processing when ALL of the following hold:
        //   1. An existing InternalMessage for this id exists (already processed before)
        //   2. The locale has not changed (no retranslation needed)
        //   3. No embed update timestamp is present (no forced embed re-render)
        //   4. The message is not currently streaming (streaming needs live updates)
        //   5. The raw content string is identical (nothing actually changed)
        //   6. The status is identical (status changes must be reflected)
        //   7. The appCards reference is identical (app cards unchanged)
        if (
            oldMessage &&
            !localeChanged &&
            !hasEmbedUpdate &&
            newMessage.status !== 'streaming' &&
            oldMessage.status === newMessage.status &&
            oldMessage.original_message?.queue_revision === newMessage.queue_revision &&
            oldMessage.original_message?.queue_mode === newMessage.queue_mode &&
            oldMessage.original_message?.queue_dispatch_status === newMessage.queue_dispatch_status &&
            oldMessage.original_message?.encrypted_pii_mappings === newMessage.encrypted_pii_mappings &&
            oldMessage.appCards === (newMessage as MessageWithEmbedMetadata).appCards &&
            oldMessage.original_message?.content === newMessage.content
        ) {
            // Raw content and status identical — reuse the existing InternalMessage entirely.
            // This avoids all parsing, embed resolution, and network fetches.
            return oldMessage;
        }

        const newInternalMessage = G_mapToInternalMessage(newMessage, piiMappings);

        // CRITICAL FIX: Skip content optimization for streaming messages AND when locale changes
        // Streaming messages need to re-render on every chunk update
        // When locale changes, we need to re-process content to get correct translations
        // When embed updates occur (_embedUpdateTimestamp changes), force re-render so embeds display
        // If an old message exists and its content is identical to the new one,
        // reuse the old content object reference to prevent unnecessary re-renders
        // of the ReadOnlyMessage component. BUT skip this for streaming messages, locale changes, and embed updates.
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
            }
        } else if (hasEmbedUpdate) {
            // Embed was updated - force new content to re-render embed NodeViews
            newInternalMessage.content = JSON.parse(JSON.stringify(newInternalMessage.content));
        } else if (localeChanged) {
            // Locale changed - always use new content even if it appears identical
            // This ensures translations are refreshed
            // CRITICAL: Force new content object reference to break any object equality checks
            // This ensures ReadOnlyMessage detects the change and re-renders
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

    const prunedWindow = pruneDecryptedMessageWindow(newInternalMessages, {
      compressionCheckpoints,
    });
    if (!isNewChat && previousMessagesLength === 0 && currentChatId && newInternalMessages.length > 0 &&
        newInternalMessages.every(message => message.status === 'synced')) {
      // Only saved rows participate in the one-time reveal. An optimistic user
      // message and a live assistant stream remain immediately visible.
      const savedIds = newInternalMessages
        .filter(message => message.status === 'synced')
        .map(message => message.id);
      if (savedIds.length > 0) revealLoadedHistory(savedIds);
    }
    if (prunedWindow.prunedCount > 0) {
      console.debug(`[ChatHistory] Pruned ${prunedWindow.prunedCount} decrypted normal message(s) from active UI window`);
    }
    messages = prunedWindow.messages;
    const renderedMessageIds = new Set(messages.map(message => message.id));
    for (const messageId of streamingRenderSchedulers.keys()) {
      if (!activeStreamingMessageIds.has(messageId) || !renderedMessageIds.has(messageId)) {
        cancelStreamingRender(messageId);
      }
    }
    for (const messageId of assistantRenderPlans.keys()) {
      if (!renderedMessageIds.has(messageId)) assistantRenderPlans.delete(messageId);
    }
    for (const { scheduler, value, revision, semanticBoundary } of scheduledAssistantRenders) {
      scheduler.update(value, revision);
      if (semanticBoundary) scheduler.flushSemanticBoundary();
    }
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

  // Make room for the response once its first content and the generated header
  // are rendered. Later chunks never restart this one-time scroll.
  $effect(() => {
    if (isNewChatGeneratingTitle || timelineSection) return;
    if (container && shouldScrollToNewUserMessage && lastUserMessageId && !isScrolling) {
      const userIndex = messages.findIndex(message => message.id === lastUserMessageId);
      const responseStarted = userIndex >= 0 && messages.slice(userIndex + 1).some(message =>
        message.role === 'assistant' && message.original_message?.content?.trim()
      );
      if (!responseStarted) return;
      const scrollContainer = container;
      const scrollMessageId = lastUserMessageId;
      cancelPendingNewUserMessageScroll();
      const scrollEpoch = newUserMessageScrollEpoch;
      const isCurrentScroll = () => scrollEpoch === newUserMessageScrollEpoch
        && container === scrollContainer && scrollContainer.isConnected
        && lastUserMessageId === scrollMessageId && shouldScrollToNewUserMessage;
      const abandonStaleScroll = () => {
        if (scrollEpoch !== newUserMessageScrollEpoch) return;
        shouldScrollToNewUserMessage = false;
        isScrolling = false;
        isSpacerActive = false;
        spacerHeight = 0;
        if (spacerSafetyTimeout) { clearTimeout(spacerSafetyTimeout); spacerSafetyTimeout = null; }
      };
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
        if (!isCurrentScroll()) { abandonStaleScroll(); return; }
        pendingNewUserMessageScrollTimer = setTimeout(() => {
          pendingNewUserMessageScrollTimer = null;
          if (!isCurrentScroll()) { abandonStaleScroll(); return; }
          const userMessageElement = scrollContainer.querySelector(`[data-message-id="${scrollMessageId}"]`);
          if (userMessageElement) {
            const containerRect = scrollContainer.getBoundingClientRect();
            const messageRect = userMessageElement.getBoundingClientRect();
            
            // Use actual text-line rectangles: paragraph margins and editor
            // padding are not text and must not consume either visible line.
            const textElement = userMessageElement.querySelector('.ProseMirror');
            const lineTops: number[] = [];
            if (textElement) {
              const walker = document.createTreeWalker(textElement, NodeFilter.SHOW_TEXT);
              const range = document.createRange();
              while (walker.nextNode()) {
                if (!walker.currentNode.textContent?.trim()) continue;
                range.selectNodeContents(walker.currentNode);
                for (const rect of range.getClientRects()) {
                  if (rect.width > 0 && rect.height > 0) lineTops.push(rect.top);
                }
              }
            }
            const distinctLines = lineTops.sort((a, b) => a - b)
              .filter((top, index, tops) => index === 0 || top - tops[index - 1] > 2);
            const visibleTextTop = distinctLines.at(-2) ?? distinctLines.at(-1) ?? messageRect.top;
            // Keep both lines beneath the container's 30px top fade.
            const scrollTarget = Math.floor(visibleTextTop - containerRect.top + scrollContainer.scrollTop - 30);

            scrollContainer.scrollTo({
              top: Math.max(0, scrollTarget),
              behavior: 'smooth'
            });

            shouldScrollToNewUserMessage = false;

            setTimeout(() => {
              if (scrollEpoch === newUserMessageScrollEpoch) isScrolling = false;
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

  // Handle scrolling to highlighted message from search or deep link.
  //
  // The messageHighlightStore is set by handleSearchMessageSnippetClick in Chats.svelte
  // AFTER the chat is selected, so ChatHistory is already mounting when this effect fires.
  // We still retry up to 30 times (3 seconds) to account for messages loading from IndexedDB.
  //
  // Two-phase scrolling:
  //   Phase 1 — Scroll the message element into view (message may still be rendering).
  //   Phase 2 — After a brief delay for the in-message mark highlights to be applied
  //             (ChatMessage.svelte adds them in a requestAnimationFrame), scroll to the
  //             first <mark class="search-match"> inside the message so the exact match
  //             is centered in the viewport, not just the top of the message.
  $effect(() => {
    if (container && $messageHighlightStore) {
      const messageId = $messageHighlightStore;
      
      // Wait for Svelte to apply pending DOM updates before querying
      tick().then(() => {
        // Retry loop: messages may still be loading from IndexedDB when this fires.
        // 30 attempts × 100 ms = up to 3 seconds of patience.
        const MAX_ATTEMPTS = 30;
        const attemptScroll = (attempts = 0) => {
          const targetMessage = container.querySelector(`[data-message-id="${messageId}"]`);
          
          if (targetMessage) {
            const messageTop = (targetMessage as HTMLElement).offsetTop;
            // Phase 1: Scroll so the message has 100px of breathing room from the top
            const scrollPosition = Math.max(0, messageTop - 100);
            container.scrollTo({
              top: scrollPosition,
              behavior: 'smooth'
            });
            console.debug(`[ChatHistory] Scrolled to highlighted message ${messageId} (attempt ${attempts + 1})`);

            // Phase 2: After two rAF cycles (enough for ChatMessage's own rAF to fire
            // and apply <mark class="search-match"> nodes), scroll to the first match
            // element so the exact matched text is visible, not just the message header.
            // We use two nested requestAnimationFrame calls:
            //   - First rAF: Svelte/markdown renderer has painted
            //   - Second rAF: ChatMessage's highlight rAF has fired and marks are in DOM
            requestAnimationFrame(() => {
              requestAnimationFrame(() => {
                const firstMark = targetMessage.querySelector('mark.search-match');
                if (firstMark) {
                  firstMark.scrollIntoView({ block: 'center', behavior: 'smooth' });
                  console.debug(`[ChatHistory] Scrolled to first search-match mark in message ${messageId}`);
                }
              });
            });
          } else if (attempts < MAX_ATTEMPTS) {
            // Message not found yet — messages may still be decrypting from IndexedDB
            setTimeout(() => attemptScroll(attempts + 1), 100);
          } else {
            console.warn(`[ChatHistory] Could not find message element for id ${messageId} after ${MAX_ATTEMPTS} attempts`);
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
    timelinePinnedId = null;
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
    if (timelineSection !== null) { void leaveTimelineSection(); return; }
    timelinePinnedId = null;
    if (container) {
      container.scrollTo({
        top: container.scrollHeight,
        behavior: smooth ? 'smooth' : 'auto' // Instant by default for programmatic calls; smooth for user-initiated
      });
    } else {
      console.warn("[ChatHistory] Container not found");
    }
  }

  /**
   * Scroll to the top of the last assistant message so the user can read the
   * response from the beginning. Used when navigating from a background-chat
   * notification where the user hasn't seen the reply yet.
   *
   * Shows a small sliver of the preceding user message (≈40px) so context is
   * clear, then the assistant message starts at the top of the visible area.
   * Falls back to scrollToBottom() if no assistant message is found.
   */
  export function scrollToLatestAssistantMessage() {
    if (!container) {
      console.warn("[ChatHistory] Container not found for scrollToLatestAssistantMessage");
      return;
    }

    const attemptScroll = (attempts = 0) => {
      // Find all assistant message wrapper elements by their CSS class
      // (ChatHistory renders assistant messages with class "message-wrapper assistant")
      const assistantMessages = container.querySelectorAll('.message-wrapper.assistant');
      const lastAssistant = assistantMessages[assistantMessages.length - 1] as HTMLElement | undefined;

      if (lastAssistant) {
        // Scroll so the top of the assistant message is ~40px from the top of the
        // container – showing a thin sliver of the user message above for context.
        const scrollPosition = Math.max(0, lastAssistant.offsetTop - 40);
        container.scrollTo({ top: scrollPosition, behavior: 'auto' });
        console.debug(`[ChatHistory] Scrolled to top of latest assistant message (offsetTop=${lastAssistant.offsetTop})`);
      } else if (attempts < 15) {
        // Messages may not be in the DOM yet – retry after a short delay
        setTimeout(() => attemptScroll(attempts + 1), 50);
      } else {
        console.warn("[ChatHistory] No assistant message found after retries – falling back to scrollToBottom");
        scrollToBottom();
      }
    };

    requestAnimationFrame(() => attemptScroll());
  }

  // Scroll position tracking for cross-device sync
  let scrollDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  let isRestoringScroll = $state(false);
  let scrollFrame: number | null = null;

  // Track scroll position with optimized performance using requestAnimationFrame
  // This ensures smooth scrolling without blocking the main thread
  function handleScroll() {
    // Don't track scroll position during restoration
    if (isRestoringScroll || timelineNavigating || timelinePinnedId) return;

    updateVirtualRangeAroundScroll();

    if (
      container &&
      container.scrollTop <= OLDER_MESSAGES_AUTOLOAD_THRESHOLD_PX &&
      hasOlderMessages &&
      !isSharedChat &&
      !olderMessagesLoading
    ) {
      requestOlderMessages();
    }

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
    
    const isAtBottomLocal = timelineSection === null &&
      container.scrollHeight - container.scrollTop - container.clientHeight < 50;
    
    // Check if scrolled to the very top (within 50px threshold)
    const isAtTopLocal = container.scrollTop < 50;
    
    // Update local isAtTop state so the mask-image CSS can toggle without re-rendering
    isAtTop = isAtTopLocal;
    
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
      timelineVisibleMessageId = lastVisibleMessageId;
      dispatch('scrollPositionChanged', {
        message_id: lastVisibleMessageId
      });
    }
  }

  // Check if user has scrolled to bottom (mark as read)
  function checkIfScrolledToBottom() {
    if (!container || timelineSection !== null) return;
    
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
    // Background repair/restoration of the live window must not move a reader
    // who deliberately opened a historical timeline section.
    if (timelineSection) return;
    restoreHistoryPosition(messageId);
  }

  function restoreHistoryPosition(messageId: string) {
    if (!container) {
      console.warn('[ChatHistory] Cannot restore scroll: container not ready');
      return;
    }
    
    // Set flag to prevent scroll tracking during restoration
    isRestoringScroll = true;
    ensureVirtualMessageRendered(messageId);
    
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
            const newMessages = getDemoMessages(chatId, DEMO_CHATS);
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

    const handleOldMessagesWsResponse = (payload: unknown) => {
      void handleOldMessagesResponse(payload as { chat_id: string; checkpoint_id: string; messages?: Array<string | GlobalMessage> });
    };
    webSocketService.on('compressed_chat_old_messages_response', handleOldMessagesWsResponse);

    // Cleanup on component destroy
    return () => {
      window.removeEventListener('language-changed-complete', handleLanguageChange);
      webSocketService.off('compressed_chat_old_messages_response', handleOldMessagesWsResponse);
    };
  });

  $effect(() => {
    if (!shouldVirtualizeMessages) {
      virtualStartIndex = 0;
      virtualEndIndex = displayMessages.length;
      return;
    }

    if (timelineNavigating || timelinePinnedId) return;
    updateVirtualRangeAroundScroll();
    if (virtualEndIndex <= virtualStartIndex) {
      clampVirtualRange(0, VIRTUALIZATION_MIN_RENDERED_MESSAGES);
    }
  });

  // Cleanup on component destroy
  onDestroy(() => {
    cancelAllStreamingRenders();
    cancelPendingNewUserMessageScroll();
    if (historyRevealTimer) clearTimeout(historyRevealTimer);
    // Cancel any pending scroll tracking operations
    if (scrollDebounceTimer) clearTimeout(scrollDebounceTimer);
    if (scrollFrame) cancelAnimationFrame(scrollFrame);
    // Clear spacer safety timeout
    if (spacerSafetyTimeout) clearTimeout(spacerSafetyTimeout);
    clearHeaderImageBubbleRetry();
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
<div class="chat-history-wrapper" bind:this={timelineHostEl} class:disable-pointer-events={disablePointerEvents} style={containerStyle}>
{#if !disablePointerEvents && timelineEnabled}
  <ChatMessageTimeline entries={timelineUserEntries} contextKey={timelineScopeKey}
    answeredCount={timelineIndex.answeredCount} railLeft={timelineNarrow ? 8 : timelineLeft} safeTop={timelineSafeTop}
    id={timelinePanelId} pill={timelineNarrow} open={!timelineNarrow || timelineOverlayOpen}
    bookmarkedIds={timelineIndex.assistantBookmarks} onToggleBookmark={toggleBookmark}
    compressionBoundary={latestCompressionCheckpoint?.compressed_up_to_timestamp ?? null}
    currentId={timelineCurrentId} catalogueLoading={timelineCatalogueLoading} catalogueIncomplete={timelineCatalogueIncomplete}
    onPreview={previewTimelineExchange} onActivate={activateTimelineExchange}
    onLoadEarlier={() => void readTimelineCatalogue()} />
{/if}
<div 
    class="chat-history-container"
    class:has-call-strip={!!voiceCallBridge}
    data-testid="chat-history-container"
    data-scroll-state={timelineNavigating || isRestoringScroll || isScrolling || shouldScrollToNewUserMessage ? 'busy' : 'ready'}
    class:empty={displayMessages.length === 0}
    class:is-at-top={isAtTop}
    bind:this={container}
    onscroll={handleScroll}
>
    <!-- Chat header banner: absolutely positioned at the top of the scroll container
         so it spans the full width regardless of the .chat-history-content max-width.
         Scrolls naturally with the content because it lives in the scroll container. -->
    {#if showChatHeader}
        <div class="chat-header-wrapper" bind:this={headerWrapperEl}>
            {#key `${currentChatId ?? 'new'}:${chatHeaderRenderKey}`}
            <ChatHeader
                title={chatTitle}
                {provisionalChatTitle}
                {currentChatId}
                category={chatCategory}
                icon={chatIcon}
                summary={chatSummary}
                {chatCreatedAt}
                {chatTimeLabel}
                {isDraftOnly}
                isLoading={isNewChatGeneratingTitle}
                isCreditsError={isNewChatCreditsError}
                {isIncognito}
                {isExampleChat}
                {isSharedChat}
                {isDirectChat}
                {videoMp4Url}
                {videoTeaserUrl}
                {videoTeaserMp4Url}
                {videoTeaserWebpUrl}
                {backgroundFrames}
                {headerImageBubbles}
                {highlightStats}
                onHighlightJump={handleHighlightJump}
                {autoplayVideo}
                {showSignupCta}
                writable={chatHeaderWritable}
                onSaveTitle={saveChatHeaderTitle}
                onSaveDescription={saveChatHeaderSummary}
            />
            {/key}
        </div>
    {/if}

    {#if voiceCallBridge}
      <div class="call-header-end" use:observeCallHeaderEnd aria-hidden="true"></div>
      <div class="voice-call-strip" class:stuck={callStripStuck} data-testid="voice-call-strip">
        {@render voiceCallBridge.controls(callStripStuck)}
      </div>
    {/if}

    <!-- Floating up/down arrows for highlight navigation. Only visible when
         more than one highlight exists and the user has opened navigation. -->
    <HighlightNavigationOverlay anchorRect={overlayAnchorRect} />

    <!-- Pending webhook approval banner. Visible only when the active chat
         originates from a webhook key with require_confirmation=true and the
         user has not yet clicked Process or Reject. -->
    <WebhookPendingBanner />

    {#if showMessages}
        <div class="chat-history-content" bind:this={timelineContentEl} class:has-timeline={timelineEnabled}
             data-testid="chat-history-content"
              class:has-messages={displayMessages.length > 0}
              class:has-header={showChatHeader}
              class:has-team-reminder={Boolean($activeTeamId && !isExampleChat && !isSharedChat)}
              data-virtualized={shouldVirtualizeMessages ? 'true' : 'false'}
              data-source-message-count={sourceMessages.length}
              data-current-chat-id={currentChatId ?? ''}
              data-rendered-message-count={virtualizedDisplayMessages.length}
             transition:fade={{ duration: 100 }} 
             onoutroend={handleOutroEnd}>

            {#if $activeTeamId && !isExampleChat && !isSharedChat}
              <div class="message-wrapper system" data-testid="team-reminder-wrapper">
                <TeamChatReminder />
              </div>
            {/if}

            {#if isSharedChat && hasOlderMessages}
              <button
                type="button"
                class="forgotten-messages-btn secondary"
                data-testid="shared-message-load-more"
                disabled={olderMessagesLoading}
                onclick={requestOlderMessages}
              >{$text('chats.loadMore.button')}</button>
            {/if}

            <!-- "Show earlier messages" toggle: appears when compression summary exists.
                 When collapsed, messages before the summary are hidden. -->
            {#if hasCompressionSummary && !timelineSection}
              <div class="forgotten-messages-toggle">
                <button
                  class="forgotten-messages-btn"
                  data-testid="show-forgotten-messages"
                  onclick={() => { void toggleForgottenMessages(); }}
                >
                  {showForgottenMessages
                    ? $text('chat.compression.hide_forgotten')
                    : (oldCompressedMessagesLoading ? $text('chat.compression.loading_messages') : $text('chat.compression.show_forgotten'))}
                  {#if !showForgottenMessages && forgottenMessages.length > 0}
                    <span class="forgotten-count">({forgottenMessages.length})</span>
                  {/if}
                </button>
                {#if showForgottenMessages && oldCompressedMessagesHasMore}
                  <button
                    class="forgotten-messages-btn secondary"
                    data-testid="show-more-forgotten-messages"
                    onclick={() => { void loadForgottenMessagePage(); }}
                    disabled={oldCompressedMessagesLoading}
                  >
                    {oldCompressedMessagesLoading ? $text('chat.compression.loading_messages') : $text('chat.compression.show_more_forgotten')}
                  </button>
                {/if}
                {#if showForgottenMessages && forgottenMessages.length > 0}
                  <p class="forgotten-messages-note" id="forgotten-messages-note">
                    {$text('chat.compression.forgotten_note')}
                  </p>
                {/if}
              </div>
            {/if}

            {#if timelineSection && timelineSection.some(message => latestCompressionCheckpoint && message.created_at <= latestCompressionCheckpoint.compressed_up_to_timestamp)}
              <p class="forgotten-messages-note" id="forgotten-messages-note">{$text('chat.compression.forgotten_note')}</p>
            {/if}

            {#if virtualTopSpacerHeight > 0}
              <div class="virtual-message-spacer" style="height: {virtualTopSpacerHeight}px;" aria-hidden="true"></div>
            {/if}

            {#each virtualizedDisplayMessages as msg, msgIndex (msg.id)}
                {@const agentContext = msg.role === 'system' ? parseAgentContextEvent(msg.original_message?.content ?? msg.content) : null}
                {@const speechContent = typeof msg.original_message?.content === 'string'
                  ? msg.original_message.content
                  : typeof msg.content === 'string' ? msg.content : null}
                <!-- Disable fade/flip animations for streaming and processing messages
                     to prevent visual glitches when content height changes rapidly.
                     Duration 0 effectively disables the animation without removing the directive. -->
                <div class="message-wrapper {msg.role === 'system' ? 'system' : (msg.role === 'user' ? 'user' : 'assistant')}"
                      class:target-message={$messageHighlightStore === msg.id}
                      class:forgotten-message={isForgottenMessage(msg)}
                      class:compression-boundary-wrapper={showForgottenMessages && isCompressionSummaryMessage(msg)}
                      data-testid="message-{msg.role === 'system' ? 'system' : (msg.role === 'user' ? 'user' : 'assistant')}"
                      data-forgotten={isForgottenMessage(msg) ? 'true' : 'false'}
                      data-message-id={msg.id}
					  data-history-reveal={historyRevealMessageIds.has(msg.id) ? 'true' : 'false'}
					  data-status={msg.status}
                      data-streaming={msg.status === 'streaming' ? 'true' : 'false'}
                      aria-describedby={isForgottenMessage(msg) ? 'forgotten-messages-note' : undefined}
                      style={`
                            opacity: ${($editMessageStore && $editMessageStore.chatId === currentChatId && (msg.original_message?.created_at ?? 0) >= $editMessageStore.createdAt) ? 0.4 : (msg.status === 'sending' ? 0.5 : (msg.status === 'failed' ? 0.7 : 1))};
                         ${($editMessageStore && $editMessageStore.chatId === currentChatId && (msg.original_message?.created_at ?? 0) >= $editMessageStore.createdAt) ? 'pointer-events: none;' : ''}
                         ${msg.status === 'failed' ? 'border: 1px solid var(--color-error); border-radius: 12px; padding: 2px;' : ''}
                      `}
                      in:fade={{ duration: 0 }}
                      animate:flip={{ duration: (msg.status === 'streaming' || msg.status === 'processing') ? 0 : 250 }}>
                    {#if agentContext}
                      <AgentContextMessage event={agentContext} onAuthoring={startContextAuthoring} jobs={Object.values($projectAuthoringJobs)} onSaveJob={saveProjectAuthoring} />
                    {:else}
                    <ChatMessage
                        role={msg.role}
                        teamId={$activeTeamId ?? undefined}
                        senderUserId={msg.original_message?.hashed_user_id
                          ? teamMemberProfiles[msg.original_message.hashed_user_id]?.userId : undefined}
                        category={msg.category}
                        sender_name={msg.role === 'user' && msg.original_message?.hashed_user_id
                          ? teamMemberProfiles[msg.original_message.hashed_user_id]?.displayName || msg.sender_name
                          : msg.sender_name}
                        remoteHumanAvatarUrl={msg.original_message?.hashed_user_id
                          ? teamMemberProfiles[msg.original_message.hashed_user_id]?.avatarUrl : undefined}
                        isOwnUserMessage={!$activeTeamId || (msg.original_message?.hashed_user_id
                          ? msg.original_message.hashed_user_id === currentUserHash
                          : msg.status === 'sending' || msg.status === 'waiting_for_internet' || msg.status === 'waiting_for_upload')}
                        model_name={msg.model_name}
                        server_region={msg.role === 'assistant' && pendingAssistantResponse
                          && msg.original_message?.user_message_id === pendingAssistantResponse.userMessageId
                          ? pendingAssistantResponse.serverRegion : undefined}
                        content={msg.content as string | Record<string, unknown> | null}
                        status={msg.status}
                        assistantTurnActive={msg.role === 'assistant' && (
                          (!!activeAssistantTurn && (msg.id === activeAssistantTurn.taskId
                            || (!!msg.original_message?.user_message_id
                              && msg.original_message.user_message_id === activeAssistantTurn.userMessageId)))
                          || (!!pendingAssistantResponse && (msg.id === pendingAssistantResponse.taskId
                            || (!!msg.original_message?.user_message_id
                              && msg.original_message.user_message_id === pendingAssistantResponse.userMessageId))))}
                        is_truncated={msg.is_truncated}
                        original_message={msg.original_message}
                        containerWidth={containerWidth}
                        appCards={msg.appCards}
                        _embedUpdateTimestamp={msg._embedUpdateTimestamp}
                        hasEmbedErrors={msg._embedErrors ? msg._embedErrors.size > 0 : false}
                        appSettingsMemoriesResponse={msg.role === 'user' ? appSettingsMemoriesResponseMap.get(msg.id) : undefined}
                        loadedMemories={msg.role === 'assistant' ? loadedMemoryAssociation.byAssistantId.get(msg.id) ?? [] : []}
                        thinkingContent={msg.role === 'assistant' ? (getThinkingEntry(msg.id)?.content ?? msg.original_message?.thinking_content) : undefined}
                        isThinkingStreaming={msg.role === 'assistant' ? (getThinkingEntry(msg.id)?.isStreaming || false) : false}
                        piiMappings={cumulativePIIMappingsArray}
                        {piiRevealed}
                        messageId={msg.id}
                        userMessageId={msg.original_message?.user_message_id}
                        isFirstMessage={(shouldVirtualizeMessages ? virtualStartIndex + msgIndex : msgIndex) === 0}
                        {isCreditsRestored}
                        {onResend}
                        {onChatNavigate}
                        {canAnnotate}
                        isForgottenMessage={isForgottenMessage(msg)}
                        bookmarkAction={msg.role === 'assistant' ? {
                          active: timelineIndex.assistantBookmarks.has(msg.id), onToggle: () => toggleBookmark(msg.id)
                        } : undefined}
                        onSpeak={msg.role === 'assistant' && onSpeakMessage && speechContent && (canSpeakMessage?.(msg.id) ?? true)
                          ? () => onSpeakMessage(msg.id, speechContent)
                          : undefined}
                        queueActions={msg.role === 'user' && msg.original_message?.status === 'queued' && msg.original_message.queue_revision && msg.original_message.queue_mode &&
                          (!$activeTeamId || (msg.original_message.hashed_user_id && msg.original_message.hashed_user_id === currentUserHash)) &&
                          canAnnotate && onQueuedEdit && onQueuedSteer
                          ? {
                              mode: msg.original_message.queue_mode,
                              busy: queuedActionBusyMessageId === msg.id,
                              error: queuedActionErrors?.[msg.id] ?? null,
                              onEdit: () => onQueuedEdit(msg.original_message!),
                              onSteer: () => onQueuedSteer(msg.original_message!),
                            }
                          : undefined}
                    />
                    {/if}

                </div>
            {/each}

            {#if showPendingAssistantResponse && pendingAssistantResponse}
              <div class="message-wrapper assistant" data-testid="pending-assistant-response"
                data-message-id={pendingAssistantResponse.taskId} data-status="processing">
                <ChatMessage role="assistant" content="" status="processing"
                  category={pendingAssistantResponse.category || undefined}
                  model_name={pendingAssistantResponse.modelName || undefined}
                  server_region={pendingAssistantResponse.serverRegion}
                  messageId={pendingAssistantResponse.taskId}
                  userMessageId={pendingAssistantResponse.userMessageId}
                  loadedMemories={loadedMemoryAssociation.byAssistantId.get(pendingAssistantResponse.taskId) ?? []}
                  containerWidth={containerWidth} isTransientResponse={true} />
              </div>
            {/if}

            {#if virtualBottomSpacerHeight > 0}
              <div class="virtual-message-spacer" style="height: {virtualBottomSpacerHeight}px;" aria-hidden="true"></div>
            {/if}

            <!-- Admin debug panel: shown after the last assistant message when debug mode is active.
                 Must be OUTSIDE the {#each} loop — message-wrapper uses display:flex which would
                 place anything inside it beside the message, not below it. -->
            {#if $chatDebugStore.rawTextMode && lastAssistantMessageId}
              <div class="debug-history-output selectable">
                <div class="debug-history-header-row">
                  <div class="debug-history-title">window.debug.chat</div>
                  <button class="debug-history-copy-btn" onclick={copyDebugChatText} disabled={!$chatDebugStore.chatReport}>
                    {debugChatCopied ? 'Copied!' : 'Copy'}
                  </button>
                </div>
                {#if $chatDebugStore.chatReportLoading}
                  <div class="debug-history-loading">Loading debug chat report...</div>
                {:else if $chatDebugStore.chatReport}
                  <pre class="debug-history-pre selectable">{$chatDebugStore.chatReport}</pre>
                {:else}
                  <div class="debug-history-loading">No debug chat report available yet.</div>
                {/if}

                {#if isCurrentlyStreaming || $chatDebugStore.streamLogs.length > 0}
                  <div class="debug-history-title logs">Streaming warn/error logs</div>
                  <pre class="debug-history-pre selectable">{$chatDebugStore.streamLogs.join('\n')}</pre>
                {/if}
              </div>
            {/if}
            
            <!-- App settings/memories permission dialog (inline, scrolls with messages) -->
            <!-- Placed BEFORE the spacer so it appears right under the user message, not pushed below -->
            <!-- CRITICAL: Only show dialog if it belongs to the current chat (prevents showing in wrong chat) -->
            {#if shouldShowPermissionDialog}
                <div class="permission-dialog-wrapper" in:fade={{ duration: 200 }}>
                    <AppSettingsMemoriesPermissionDialog />
                </div>
            {/if}

            {#if shouldShowConnectedAccountPermissionDialog}
                <div class="permission-dialog-wrapper" in:fade={{ duration: 200 }}>
                    <ConnectedAccountPermissionDialog />
                </div>
            {/if}

            {#each $projectFileApprovals.filter((entry) => entry.request.chatId === currentChatId) as entry (entry.id)}
                <div class="permission-dialog-wrapper">
                    <ProjectFileApprovalCard {entry} onDecision={resolveProjectFileApproval} />
                </div>
            {/each}
            {#each $remoteCommandEntries.filter((entry) => entry.chatId === currentChatId) as entry (entry.id)}
                <div class="permission-dialog-wrapper">
                    <RemoteCommandReviewCard {entry} onDecision={resolveRemoteCommandApproval} onStop={requestRemoteCommandStop} />
                </div>
            {/each}

            
            <!-- Bottom spacer: fills remaining viewport space below messages during streaming.
                 Creates the ChatGPT-like effect where the user message sits near the top
                 with empty space below that gradually fills as the AI response streams in. -->
            {#if spacerHeight > 0}
                <div class="streaming-spacer" style="height: {spacerHeight}px;"></div>
            {/if}
            
            <!-- Follow-up suggestions shown after the last assistant message.
                 Visible without requiring the user to focus the message input first. -->
            {#if showQuickTipsInHistory && !timelineSection}
                <div class="quick-tips-wrapper" in:fade={{ duration: 200 }}>
                    <QuickTipsCard
                        slugs={effectiveQuickTipSlugs}
                        category={chatCategory}
                        on:action={(event) => handleQuickTipAction(event.detail)}
                    />
                </div>
            {/if}

            {#if showFollowUpSuggestionsInHistory && onSuggestionClick && !timelineSection}
                <div class="follow-up-suggestions-wrapper" transition:fade={{ duration: 120 }}>
                    <FollowUpSuggestions
                        suggestions={followUpSuggestions}
                        messageInputContent=""
                        onSuggestionClick={onSuggestionClick}
                    />
                </div>
            {/if}

            {#if showAssistantFeedback}
                <div class="assistant-response-feedback" data-testid="assistant-response-feedback" in:fade={{ duration: 200 }}>
                    {#if assistantFeedbackSubmitted && assistantFeedbackThanksState !== 'hidden'}
                        <p
                            class="assistant-feedback-thanks"
                            class:hiding={assistantFeedbackThanksState === 'hiding'}
                            data-testid="assistant-feedback-thanks"
                        >
                            {$text('chat.assistant_feedback.thanks')}
                        </p>
                    {:else if !assistantFeedbackSubmitted}
                        <div class="assistant-feedback-rating-row">
                            <span class="assistant-feedback-label">
                                {$text('chat.assistant_feedback.rate_label')}
                            </span>
                            <div class="assistant-feedback-stars" role="radiogroup" aria-label={$text('chat.assistant_feedback.rate_label')}>
                                {#each ASSISTANT_RATING_VALUES as rating}
                                    <button
                                        type="button"
                                        class="assistant-feedback-star"
                                        class:selected={selectedAssistantRating !== null && rating <= selectedAssistantRating}
                                        role="radio"
                                        aria-checked={selectedAssistantRating === rating}
                                        aria-label={$text('chat.assistant_feedback.star_label', { values: { count: rating } })}
                                        data-testid={`assistant-feedback-star-${rating}`}
                                        onclick={() => selectedAssistantRating = rating}
                                    >
                                        ★
                                    </button>
                                {/each}
                            </div>
                            {#if selectedAssistantRating !== null}
                                <button
                                    type="button"
                                    class="assistant-feedback-submit"
                                    data-testid="assistant-feedback-submit"
                                    onclick={handleAssistantFeedbackSubmit}
                                >
                                    {selectedAssistantRating <= 3
                                        ? $text('settings.report_issue')
                                        : $text('chat.assistant_feedback.submit')}
                                </button>
                            {/if}
                        </div>
                    {/if}
                    <button
                        type="button"
                        class="chat-history-feedback-link"
                        data-testid="chat-history-request-feature"
                        onclick={() => openReportIssue('feature_request')}
                    >
                        {$text('chat.request_feature')}
                    </button>
                </div>
            {/if}

        </div>
    {/if}
    
</div>

</div>

<style>
  /* Wrapper provides positioning context for the AI processing overlay.
     Takes the same absolute positioning the container previously had. */
  .chat-history-wrapper {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    container: chat-history / inline-size;
  }

  .chat-history-wrapper.disable-pointer-events {
    pointer-events: none;
  }

  .chat-history-container {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    overflow-y: auto;
    overflow-x: hidden; /* Prevent horizontal scrollbar from appearing at certain viewport widths */
    padding: var(--spacing-5);
    box-sizing: border-box;
    -webkit-overflow-scrolling: touch;
    /* Disable browser's automatic scroll anchoring.
       During streaming, content grows from the bottom which triggers the browser's
       scroll-anchoring algorithm. This fights with our manual scroll management
       and causes unpredictable jumps. We handle scroll position ourselves. */
    overflow-anchor: none;
    /* Fade the bottom edge — always visible to indicate more content below.
       Top fade is suppressed when at the top (.is-at-top) so the banner is not clipped. */
    mask-image: linear-gradient(to bottom, 
        rgba(0, 0, 0, 0) 0%, 
        rgba(0, 0, 0, 1) 30px, 
        rgba(0, 0, 0, 1) calc(100% - 30px), 
        rgba(0, 0, 0, 0) 100%
    );
  }

  .debug-history-header-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.35rem;
  }

  .debug-history-copy-btn {
    all: unset;
    cursor: pointer;
    font-size: 0.75rem;
    color: var(--color-primary);
    flex-shrink: 0;
  }

  .debug-history-copy-btn:disabled {
    opacity: 0.4;
    cursor: default;
  }

  .debug-history-output {
    margin-top: 0.5rem;
    margin-left: 2.25rem;
    margin-right: 0.75rem;
    padding: 0.75rem;
    border-radius: 0.75rem;
    border: 1px solid var(--color-grey-30);
    background: var(--color-grey-10);
  }

  .debug-history-title {
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--color-font-secondary);
  }

  .debug-history-title.logs {
    margin-top: 0.65rem;
  }

  .debug-history-loading {
    font-size: 0.8rem;
    color: var(--color-font-secondary);
  }

  .debug-history-pre {
    margin: 0;
    font-family: monospace;
    font-size: 0.78rem;
    line-height: 1.45;
    white-space: pre-wrap;
    word-break: break-word;
    color: var(--color-font-primary);
    overflow: visible;
    user-select: text;
    -webkit-user-select: text;
    -moz-user-select: text;
    -ms-user-select: text;
    -webkit-touch-callout: default;
  }

  /* When scrolled to the top, remove the top gradient so the banner edges aren't faded */
  .chat-history-container.is-at-top {
    mask-image: linear-gradient(to bottom, 
        rgba(0, 0, 0, 1) 0%, 
        rgba(0, 0, 0, 1) calc(100% - 30px), 
        rgba(0, 0, 0, 0) 100%
    );
  }

  .chat-history-container.has-call-strip {
    mask-image: linear-gradient(to bottom,
      rgba(0, 0, 0, 1) 0%, rgba(0, 0, 0, 1) calc(100% - 30px),
      rgba(0, 0, 0, 0) 100%);
  }

  .call-header-end { height: 1px; margin-top: -1px; pointer-events: none; }
  .voice-call-strip {
    position: sticky;
    top: 0;
    z-index: var(--z-index-dropdown-2);
    margin-inline: calc(-1 * var(--spacing-5));
    width: calc(100% + 2 * var(--spacing-5));
  }
  .voice-call-strip.stuck { top: calc(-1 * var(--spacing-5)); }

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
    max-width: var(--chat-content-max-width, 1000px);
    margin: 0 auto;
    box-sizing: border-box;
  }

  .message-wrapper[data-history-reveal='true'] {
    animation: loaded-history-reveal 180ms ease-out both;
  }

  @keyframes loaded-history-reveal {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  @media (prefers-reduced-motion: reduce) {
    .message-wrapper[data-history-reveal='true'] { animation: none; }
  }

  /* Only apply padding-top and min-height when there are messages */
  /* This prevents the first message from overlaying the button */
  .chat-history-content.has-messages {
    padding-top: calc(50px + var(--assistant-speech-overlay-reserve, 0px));
    /* ActiveChat's action buttons float over both inline edges. Reserve those
       lanes in the scrollable message column so auto-scroll cannot move a
       bubble underneath them after the sidebar narrows the canvas. */
    /* Gradually release the floating-control gutters as the pane narrows. */
    padding-inline: clamp(0px, calc((100cqw - 730px) / 3), 90px);
    /* Ensure minimum height for proper scrolling when messages exist */
    min-height: 100%;
  }

  .chat-history-content.has-messages.has-timeline {
    padding-inline-start: max(52px, clamp(0px, calc((100cqw - 730px) / 3), 90px));
  }

  /* When the header banner is showing, push messages below the banner.
     Banner height: 240px desktop / 190px mobile (matches ChatHeader.svelte dimensions).
     12px gap between banner bottom and first message.
     The banner itself is positioned in-flow (not absolute) so the content's padding-top
     stacks on top of it — we only need the extra padding-top offset removed since
     the banner already occupies the top space. */
  .chat-history-content.has-messages.has-header:not(.has-team-reminder) {
    padding-top: calc(var(--spacing-6) + var(--assistant-speech-overlay-reserve, 0px));
  }

  @container chat-history (max-width: 730px) {
    .chat-history-content.has-messages,
    .chat-history-content.has-messages.has-timeline {
      padding-top: calc(70px + var(--assistant-speech-overlay-reserve, 0px));
      padding-inline: 0;
    }

    .chat-history-content.has-messages.has-header:not(.has-team-reminder) {
      padding-top: calc(var(--spacing-6) + var(--assistant-speech-overlay-reserve, 0px));
    }
  }

  /* Permission dialog wrapper - renders as part of chat history */
  /* This allows users to scroll the chat while the dialog is visible */
  .permission-dialog-wrapper {
    width: 100%;
    display: flex;
    justify-content: center;
    padding: 20px 0;
    margin-top: var(--spacing-5);
  }


  /* Follow-up suggestions wrapper — shown inline below the chat history, aligned
     to the right as quick user-response actions rather than assistant content. */
  .quick-tips-wrapper,
  .follow-up-suggestions-wrapper {
    padding: 8px 0 14px;
    padding-inline-start: 20px;
    padding-inline-end: 20px;
    box-sizing: border-box;
    width: 100%;
  }

  .assistant-response-feedback {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-2);
    margin-top: var(--spacing-4);
    padding: 14px 20px 18px;
    box-sizing: border-box;
    width: 100%;
    text-align: center;
  }

  .assistant-feedback-rating-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-2);
  }

  .assistant-feedback-label,
  .assistant-feedback-thanks {
    margin: 0;
    color: var(--color-grey-60);
    font-size: var(--font-size-xs);
    font-weight: 600;
    line-height: 1.35;
  }

  .assistant-feedback-thanks {
    max-height: 2rem;
    overflow: hidden;
    opacity: 1;
    transform: translateY(0);
    transition:
      max-height 260ms var(--easing-default),
      opacity 220ms var(--easing-default),
      transform 220ms var(--easing-default);
  }

  .assistant-feedback-thanks.hiding {
    max-height: 0;
    opacity: 0;
    transform: translateY(-4px);
  }

  .assistant-feedback-stars {
    display: inline-flex;
    align-items: center;
    gap: 1px;
  }

  .assistant-feedback-star {
    all: unset;
    cursor: pointer;
    color: var(--color-grey-40);
    font-size: var(--font-size-small);
    line-height: 1;
    transition: color var(--duration-fast) var(--easing-default), transform var(--duration-fast) var(--easing-default);
  }

  .assistant-feedback-star.selected,
  .assistant-feedback-star:hover,
  .assistant-feedback-star:focus-visible {
    color: var(--color-orange-50, #f59e0b);
  }

  .assistant-feedback-star:hover {
    transform: translateY(-1px);
  }

  .assistant-feedback-star:focus-visible,
  .assistant-feedback-submit:focus-visible {
    outline: 2px solid var(--color-grey-70);
    outline-offset: 3px;
    border-radius: var(--radius-3);
  }

  .assistant-feedback-submit {
    all: unset;
    cursor: pointer;
    color: var(--color-grey-100);
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-6);
    padding: 4px 10px;
    font-size: var(--font-size-xs);
    font-weight: 700;
    line-height: 1.25;
    transition: background-color var(--duration-fast) var(--easing-default), border-color var(--duration-fast) var(--easing-default);
  }

  .assistant-feedback-submit:hover {
    background: var(--color-grey-20);
    border-color: var(--color-grey-40);
  }

  .chat-history-feedback-link {
    all: unset;
    cursor: pointer;
    color: var(--color-grey-60);
    font-size: var(--font-size-xs);
    font-weight: 600;
    line-height: 1.35;
    text-decoration: underline;
    text-underline-offset: 3px;
    transition: color var(--duration-fast) var(--easing-default);
  }

  .chat-history-feedback-link:hover,
  .chat-history-feedback-link:focus-visible {
    color: var(--color-grey-100);
  }

  .chat-history-feedback-link:focus-visible {
    outline: 2px solid var(--color-grey-70);
    outline-offset: 3px;
    border-radius: var(--radius-3);
  }

  @media (max-width: 500px) {
    .quick-tips-wrapper,
    .follow-up-suggestions-wrapper {
      padding-inline-start: 10px;
      padding-inline-end: 10px;
    }

    .assistant-response-feedback {
      padding-inline-start: 10px;
      padding-inline-end: 10px;
    }
  }

  /* Bottom spacer that fills remaining viewport space during AI streaming.
     Creates visual space below user message that fills as the response streams in. */
  .streaming-spacer {
    flex-shrink: 0;
    pointer-events: none;
    /* Smooth transition as spacer shrinks while AI response grows */
    transition: height var(--duration-fast);
  }

  .message-wrapper {
    margin: 5px 0;
    width: 100%;
    display: flex;
    flex-shrink: 0;
  }

  .virtual-message-spacer {
    width: 100%;
    flex-shrink: 0;
    pointer-events: none;
  }

  .message-wrapper.user {
    /* LTR default: user messages on the right */
    justify-content: flex-end;
  }

  /* RTL: user messages sit on the left (inline-start), assistant on the right */
  :global([dir="rtl"]) .message-wrapper.user {
    justify-content: flex-start;
  }

  .message-wrapper.assistant { /* Assistant messages aligned to the left */
    justify-content: flex-start;
  }

  :global([dir="rtl"]) .message-wrapper.assistant {
    justify-content: flex-end;
  }

  .message-wrapper.system { /* System messages (e.g., insufficient credits) centered */
    justify-content: center;
  }

  .message-wrapper.compression-boundary-wrapper {
    flex-direction: column;
    align-items: center;
  }

  .message-wrapper :global(.chat-message) {
    width: 100%;
  }

  .message-wrapper.target-message {
    outline: 2px solid var(--color-orange-50, #f59e0b);
    outline-offset: 4px;
    border-radius: var(--radius-8);
  }

  /* Forgotten-message controls for compressed chats.
     Appears above the message list when a compression summary exists. */
  .forgotten-messages-toggle {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-2);
    padding: 8px 0 4px;
  }

  .forgotten-messages-btn {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-2);
    padding: 6px 14px;
    font-size: var(--font-size-xxs);
    font-weight: 500;
    color: var(--color-grey-60, #888);
    background: var(--color-grey-10, rgba(255, 255, 255, 0.05));
    border: 1px solid var(--color-grey-20, rgba(255, 255, 255, 0.08));
    border-radius: var(--radius-8);
    cursor: pointer;
    transition: background-color var(--duration-fast) var(--easing-default), color var(--duration-fast) var(--easing-default);
  }

  .forgotten-messages-btn:hover {
    background: var(--color-grey-20, rgba(255, 255, 255, 0.08));
    color: var(--color-grey-80, #ccc);
  }

  .forgotten-messages-btn:disabled {
    cursor: wait;
    opacity: 0.6;
  }

  .forgotten-messages-note {
    margin: 0;
    max-width: min(520px, calc(100vw - 48px));
    color: var(--color-grey-60, #8a8a8a);
    font-size: var(--font-size-xxs);
    line-height: 1.35;
    text-align: center;
  }

  .forgotten-count {
    font-weight: 400;
    opacity: 0.7;
  }

  /* Wrapper for the ChatHeader banner at the top of new chats.
     Positioned in the normal flow of .chat-history-container (outside the max-width content),
     so it stretches edge-to-edge relative to the full scroll container width.
     The container has 10px padding on all sides — we cancel it on left/right/top
     with negative margins so the banner is flush with the scroll container edges. */
  .chat-header-wrapper {
    /* Cancel the container's 10px padding on all sides */
    margin-top: -10px;
    margin-inline-start: -10px;
    margin-inline-end: -10px;
    /* Full width including the cancelled side padding */
    width: calc(100% + 20px);
  }

</style>
