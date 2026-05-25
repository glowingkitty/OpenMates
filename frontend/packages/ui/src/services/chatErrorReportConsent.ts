/**
 * Chat Error Report Consent
 *
 * Shows a privacy-preserving prompt after chat processing failures and, only
 * when the user agrees, opens the existing report issue flow with chat context
 * sharing preselected. Default diagnostics stay separate and content-free.
 */

import { get } from "svelte/store";
import { text } from "@repo/ui";
import { notificationStore } from "../stores/notificationStore";
import { panelState } from "../stores/panelStateStore";
import { activeChatStore } from "../stores/activeChatStore";
import { settingsDeepLink } from "../stores/settingsDeepLinkStore";
import { reportIssueStore } from "../stores/reportIssueStore";

type ChatErrorReportOptions = {
  chatId?: string | null;
  source: string;
  error: unknown;
};

const CONSENT_TOAST_DURATION_MS = 0;
const REPORT_DEEP_LINK_DELAY_MS = 100;

function translate(key: string): string {
  return get(text)(key);
}

function errorSummary(error: unknown): string {
  if (error instanceof Error) return error.message.slice(0, 300);
  if (typeof error === "string") return error.slice(0, 300);
  return "Unknown chat processing error";
}

export function promptChatErrorReportConsent(options: ChatErrorReportOptions): void {
  const dedupeKey = options.chatId
    ? `chat-error-report:${options.chatId}:${options.source}`
    : `chat-error-report:${options.source}`;
  let notificationId = "";

  notificationId = notificationStore.addNotificationWithOptions("error", {
    title: translate("chat.error_report_consent.title"),
    message: translate("chat.error_report_consent.message"),
    messageSecondary: translate("chat.error_report_consent.secondary"),
    actionLabel: translate("chat.error_report_consent.action"),
    secondaryActionLabel: translate("chat.error_report_consent.dismiss"),
    duration: CONSENT_TOAST_DURATION_MS,
    dismissible: true,
    dedupeKey,
    onAction: () => {
      if (notificationId) notificationStore.removeNotification(notificationId);
      if (options.chatId) activeChatStore.setActiveChat(options.chatId);
      reportIssueStore.set({
        title: translate("chat.error_report_consent.report_title"),
        description: `${translate("chat.error_report_consent.report_description")}\n\nSource: ${options.source}\nError: ${errorSummary(options.error)}`,
        url: typeof window !== "undefined" ? window.location.href : "",
        shareChat: true,
      });
      panelState.openSettings();
      setTimeout(() => settingsDeepLink.set("report_issue"), REPORT_DEEP_LINK_DELAY_MS);
    },
    onSecondaryAction: () => {
      if (notificationId) notificationStore.removeNotification(notificationId);
    },
  });
}
