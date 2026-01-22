import { writable } from 'svelte/store';

export interface ReportIssueTemplate {
    title?: string;
    description?: string;
    url?: string;
}

export const reportIssueStore = writable<ReportIssueTemplate | null>(null);
