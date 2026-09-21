/**
 * Issue Report Submission Service
 *
 * Shared client-side issue submission helper for reports that should be sent
 * without opening the Settings report form. It mirrors the core report payload
 * while keeping screenshot/element-picker collection exclusive to the full UI.
 */

import { get } from "svelte/store";
import { getApiEndpoint, apiEndpoints } from "../config/api";
import { activeChatStore } from "../stores/activeChatStore";
import { activeEmbedStore } from "../stores/activeEmbedStore";
import { authStore } from "../stores/authStore";
import { isOnline } from "../stores/networkStatusStore";
import { websocketStatus } from "../stores/websocketStatusStore";
import { phasedSyncState } from "../stores/phasedSyncStateStore";
import { aiTypingStore } from "../stores/aiTypingStore";
import { hasPendingSends } from "../stores/pendingUploadStore";
import { logCollector } from "./logCollector";
import { userActionTracker } from "./userActionTracker";
import { isPublicChat } from "../demo_chats/convertToChat";
import { uint8ArrayToBase64 } from "./cryptoService";
import { getWebSocketToken } from "../utils/cookies";

type SubmitIssueReportOptions = {
  title: string;
  description?: string;
  issueType?: "bug_report" | "feature_request";
  shareCurrentChat?: boolean;
  source?: string;
};

type SubmitIssueReportResult = {
  success: boolean;
  issueId?: string;
  shortIssueId?: string;
  message?: string;
};

function collectDeviceInfo() {
  return {
    userAgent: navigator.userAgent,
    viewportWidth: window.innerWidth,
    viewportHeight: window.innerHeight,
    isTouchEnabled: "ontouchstart" in window || navigator.maxTouchPoints > 0,
  };
}

function collectRuntimeDebugState(activeChatId: string | null) {
  const syncState = get(phasedSyncState);
  return {
    websocket_status: get(websocketStatus),
    is_online: get(isOnline),
    ai_typing_status: get(aiTypingStore),
    has_pending_sends: activeChatId ? hasPendingSends(activeChatId) : false,
    phased_sync_state: {
      initialSyncCompleted: syncState.initialSyncCompleted,
      currentActiveChatId: syncState.currentActiveChatId,
      initialChatLoaded: syncState.initialChatLoaded,
    },
  };
}

function collectVisibleChatMessageTexts(): string[] {
  return Array.from(document.querySelectorAll('[data-message-id]'))
    .flatMap((message) => {
      const renderedBodies = Array.from(
        message.querySelectorAll('.read-only-message .ProseMirror, .chat-message-text .ProseMirror'),
      )
        .map((body) => body.textContent?.trim() ?? '')
        .filter(Boolean);
      return renderedBodies.length > 0
        ? renderedBodies
        : [message.textContent?.trim() ?? ''];
    })
    .filter((message) => message.length >= 3);
}

export async function generateCurrentContextUrl(): Promise<string | null> {
  const baseUrl = window.location.origin;
  const activeEmbedId = get(activeEmbedStore);
  if (activeEmbedId) {
    try {
      const { generateEmbedShareKeyBlob } = await import("./embedShareEncryption");
      const encryptedBlob = await generateEmbedShareKeyBlob(activeEmbedId, 0, undefined);
      return `${baseUrl}/share/embed/${activeEmbedId}#key=${encryptedBlob}`;
    } catch (error) {
      console.warn("[IssueReportSubmission] Failed to generate embed share URL:", error);
    }
  }

  const activeChatId = get(activeChatStore);
  if (!activeChatId) return null;
  if (isPublicChat(activeChatId)) return `${baseUrl}/#chat-id=${activeChatId}`;

  try {
    const { chatKeyManager } = await import("./encryption/ChatKeyManager");
    let chatKey = chatKeyManager.getKeySync(activeChatId);
    if (!chatKey) chatKey = await chatKeyManager.getKey(activeChatId);
    if (!chatKey) return null;

    const chatKeyBase64 = uint8ArrayToBase64(chatKey);
    const { generateShareKeyBlob } = await import("./shareEncryption");
    const encryptedBlob = await generateShareKeyBlob(activeChatId, chatKeyBase64, 0, undefined);
    return `${baseUrl}/share/chat/${activeChatId}#key=${encryptedBlob}`;
  } catch (error) {
    console.warn("[IssueReportSubmission] Failed to generate chat share URL:", error);
    return null;
  }
}

/**
 * Make the context referenced by an issue-report share URL available to a
 * fresh viewer before the report itself is submitted. The fragment key is
 * deliberately never sent to the metadata endpoint.
 */
export async function ensureIssueReportContextIsShared(
  shareUrl: string,
): Promise<void> {
  const parsed = new URL(shareUrl, window.location.origin);
  const chatMatch = parsed.pathname.match(/^\/share\/chat\/([^/]+)$/);
  const embedMatch = parsed.pathname.match(/^\/share\/embed\/([^/]+)$/);

  if (!chatMatch && !embedMatch) return;

  const isChat = Boolean(chatMatch);
  const contentId = decodeURIComponent((chatMatch ?? embedMatch)![1]);
  const endpoint = isChat
    ? "/v1/share/chat/metadata"
    : "/v1/share/embed/metadata";
  const body = isChat
    ? {
        chat_id: contentId,
        title: null,
        summary: null,
        is_shared: true,
        share_pii: false,
        share_highlights: false,
      }
    : {
        embed_id: contentId,
        title: null,
        description: null,
        is_shared: true,
      };

  const response = await fetch(getApiEndpoint(endpoint), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      Origin: window.location.origin,
    },
    credentials: "include",
    body: JSON.stringify(body),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result.success !== true) {
    throw new Error("Failed to make the issue-report context shareable");
  }

  if (isChat) {
    const { chatDB } = await import("./db");
    const chat = await chatDB.getChat(contentId);
    if (chat) {
      await chatDB.updateChat({
        ...chat,
        is_shared: true,
        is_private: false,
        share_pii: false,
        share_highlights: false,
      });
      window.dispatchEvent(
        new CustomEvent("chatShared", { detail: { chat_id: contentId } }),
      );
    }
  }
}

export async function submitIssueReport(options: SubmitIssueReportOptions): Promise<SubmitIssueReportResult> {
  const activeChatId = get(activeChatStore);
  const visibleChatMessages = collectVisibleChatMessageTexts();
  const currentLanguage = localStorage.getItem("preferredLanguage")
    || navigator.language.split("-")[0]
    || "en";
  let recentTraceIds: string[] = [];
  try {
    const { getRecentTraceIds } = await import("./tracing/wsSpans");
    recentTraceIds = getRecentTraceIds();
  } catch {
    recentTraceIds = [];
  }

  const chatOrEmbedUrl = options.shareCurrentChat ? await generateCurrentContextUrl() : null;
  if (chatOrEmbedUrl) {
    await ensureIssueReportContextIsShared(chatOrEmbedUrl);
  }
  const response = await fetch(getApiEndpoint("/v1/settings/issues"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "application/json",
      "Origin": window.location.origin,
    },
    credentials: "include",
    body: JSON.stringify({
      title: options.title,
      description: options.description ?? null,
      issue_type: options.issueType ?? "bug_report",
      chat_or_embed_url: chatOrEmbedUrl,
      contact_email: null,
      language: currentLanguage,
      device_info: collectDeviceInfo(),
      console_logs: logCollector.getIssueReportLogsAsText(100, visibleChatMessages),
      indexeddb_report: null,
      last_messages_html: null,
      active_chat_sidebar_html: null,
      runtime_debug_state: collectRuntimeDebugState(activeChatId),
      action_history: userActionTracker.getActionHistoryAsText(),
      screenshot_png_base64: null,
      picked_element_html: null,
      trace_ids: recentTraceIds,
      send_email_notification: true,
      ephemeral_session_id: sessionStorage.getItem("ephemeral_session_id") ?? null,
    }),
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.success !== true) {
    return {
      success: false,
      message: data.message || data.detail || "Issue report failed",
    };
  }

  const issueId = data.issue_id || "";
  const shortIssueId = data.short_issue_id || "";
  if (issueId && get(authStore).isAuthenticated) {
    const wsToken = getWebSocketToken();
    void fetch(getApiEndpoint(apiEndpoints.settings.issueLogs), {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(wsToken ? { "X-WS-Token": wsToken } : {}),
      },
      body: JSON.stringify({
        issue_id: issueId,
        logs_text: logCollector.getIssueReportLogsAsText(150, visibleChatMessages),
        page_url: window.location.pathname,
        user_agent: navigator.userAgent,
      }),
    }).catch(() => { /* non-critical */ });
  }

  return { success: true, issueId, shortIssueId: shortIssueId || issueId };
}
