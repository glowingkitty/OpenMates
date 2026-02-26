import { writable } from "svelte/store";

export interface ReportIssueTemplate {
  title?: string;
  description?: string;
  url?: string;
  /** When true, the report issue form will default the "share chat" toggle to ON */
  shareChat?: boolean;
}

export const reportIssueStore = writable<ReportIssueTemplate | null>(null);

/**
 * Holds the issue ID of the most recently submitted issue report.
 * Set by SettingsReportIssue on successful submission; read by
 * SettingsReportIssueConfirmation to display the ID to the user.
 * Cleared when the confirmation page unmounts.
 */
export const submittedIssueIdStore = writable<string>("");
