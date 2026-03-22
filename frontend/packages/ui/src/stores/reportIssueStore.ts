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

/**
 * In-progress draft of the Report Issue form.
 *
 * Because CurrentSettingsPage.svelte destroys and re-creates the
 * SettingsReportIssue component every time the user navigates away (e.g. when
 * the DOM Element Picker closes the settings panel), all local $state variables
 * are wiped on each remount.  This store survives the unmount/remount cycle and
 * is used to restore the form exactly as the user left it.
 *
 * Lifecycle:
 *  - Written just before startElementPicker() fires (settings panel closes).
 *  - Read in onMount to restore all fields after remount.
 *  - Cleared on successful form submission.
 *
 * Fields mirror the $state variables in SettingsReportIssue.svelte that a user
 * can fill before triggering the picker.
 */
export interface ReportIssueFormDraft {
  issueTitle: string;
  userFlow: string;
  expectedBehaviour: string;
  actualBehaviour: string;
  shareChatEnabled: boolean;
  chatOrEmbedUrl: string;
  contactEmail: string;
  includeEmailToggle: boolean;
  pickedElementHtml: string | null;
  screenshotDataUrl: string | null;
}

export const reportIssueFormDraftStore = writable<ReportIssueFormDraft | null>(
  null,
);
