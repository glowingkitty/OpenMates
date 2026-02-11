import { writable } from "svelte/store";

export interface ReportIssueTemplate {
  title?: string;
  description?: string;
  url?: string;
  /** When true, the report issue form will default the "share chat" toggle to ON */
  shareChat?: boolean;
}

export const reportIssueStore = writable<ReportIssueTemplate | null>(null);
