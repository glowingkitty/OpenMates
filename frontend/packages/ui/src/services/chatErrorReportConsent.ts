/**
 * Chat Error Report Consent
 *
 * Shows a privacy-preserving prompt after chat processing failures and submits
 * an issue report only when the user presses the report action. Default
 * diagnostics stay separate and content-free.
 */

import { get } from "svelte/store";
import { text } from "@repo/ui";
import { notificationStore } from "../stores/notificationStore";
import { activeChatStore } from "../stores/activeChatStore";
import { submitIssueReport } from "./issueReportSubmission";

type ChatErrorReportOptions = {
  chatId?: string | null;
  source: string;
  error: unknown;
};

const CONSENT_TOAST_DURATION_MS = 0;

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
    onAction: async () => {
      if (options.chatId) activeChatStore.setActiveChat(options.chatId);
      notificationStore.updateNotification(notificationId, {
        message: translate("chat.error_report_consent.submitting"),
        messageSecondary: undefined,
        actionLabel: undefined,
        secondaryActionLabel: undefined,
      });

      const result = await submitIssueReport({
        title: translate("chat.error_report_consent.report_title"),
        description: `${translate("chat.error_report_consent.report_description")}\n\nSource: ${options.source}\nError: ${errorSummary(options.error)}`,
        shareCurrentChat: true,
        source: options.source,
      });

      if (notificationId) notificationStore.removeNotification(notificationId);
      if (result.success) {
        notificationStore.success(
          result.issueId
            ? `${translate("settings.report_issue_success")} (${result.issueId})`
            : translate("settings.report_issue_success"),
          7000,
        );
      } else {
        notificationStore.error(result.message || translate("settings.report_issue_error"), 10000);
      }
    },
    onSecondaryAction: () => {
      if (notificationId) notificationStore.removeNotification(notificationId);
    },
  });
}
