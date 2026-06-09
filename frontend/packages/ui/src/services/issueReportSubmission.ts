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

type SubmitIssueReportOptions = {
  title: string;
  description?: string;
  shareCurrentChat?: boolean;
  source?: string;
};

type SubmitIssueReportResult = {
  success: boolean;
  issueId?: string;
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

async function generateCurrentContextUrl(): Promise<string | null> {
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

    let chatKeyBase64: string;
    if (chatKey instanceof Uint8Array) {
      let binary = "";
      chatKey.forEach((byte) => { binary += String.fromCharCode(byte); });
      chatKeyBase64 = btoa(binary);
    } else {
      chatKeyBase64 = chatKey;
    }
    const { generateShareKeyBlob } = await import("./shareEncryption");
    const encryptedBlob = await generateShareKeyBlob(activeChatId, chatKeyBase64, 0, undefined);
    return `${baseUrl}/share/chat/${activeChatId}#key=${encryptedBlob}`;
  } catch (error) {
    console.warn("[IssueReportSubmission] Failed to generate chat share URL:", error);
    return null;
  }
}

export async function submitIssueReport(options: SubmitIssueReportOptions): Promise<SubmitIssueReportResult> {
  const activeChatId = get(activeChatStore);
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
      chat_or_embed_url: chatOrEmbedUrl,
      contact_email: null,
      language: currentLanguage,
      device_info: collectDeviceInfo(),
      console_logs: logCollector.getLogsAsText(100),
      indexeddb_report: null,
      last_messages_html: null,
      active_chat_sidebar_html: null,
      runtime_debug_state: collectRuntimeDebugState(activeChatId),
      action_history: userActionTracker.getActionHistoryAsText(),
      screenshot_png_base64: null,
      picked_element_html: null,
      trace_ids: recentTraceIds,
      add_to_linear: true,
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
  if (issueId && get(authStore).isAuthenticated) {
    void fetch(getApiEndpoint(apiEndpoints.settings.issueLogs), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        issue_id: issueId,
        logs_text: logCollector.getLogsAsText(150),
        page_url: window.location.pathname,
        user_agent: navigator.userAgent,
      }),
    }).catch(() => { /* non-critical */ });
  }

  return { success: true, issueId };
}
