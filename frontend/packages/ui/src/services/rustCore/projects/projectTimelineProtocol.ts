/**
 * `projectTimeline` unit protocol of the shared Rust core Worker (Project
 * Timeline tab; VITE_OPENMATES_RUST_CORE builds only). The core
 * (browser_project_timeline.rs) reads the page and builds the presentation
 * JSON; these types only carry it across the unit port. Failures arrive as the
 * core's stable codes.
 */
import type { ProjectTimelineEntry } from '../../../components/projects/ProjectTimeline.types';

export interface ProjectTimelinePageResult {
	entries: ProjectTimelineEntry[];
	nextCursor: string | null;
}

/** One file of a restore: what the core did with it (`reason` is a stable refusal code). */
export interface ProjectCommitRestoreFileResult {
	path: string | null;
	outcome: 'restored' | 'unchanged' | 'relinked' | 'refused';
	version?: number;
	reason?: string;
}

export interface ProjectCommitRestoreResult {
	/** The new restore commit. */
	commitId: string;
	files: ProjectCommitRestoreFileResult[];
}

export type ProjectTimelineProtocol = {
	/** One newest-first page; `before` is the previous page's `nextCursor`. */
	timeline: {
		request: { selector: string; limit?: number; before?: string; teamId?: string | null };
		response: ProjectTimelinePageResult;
	};
	/** Restore a whole commit as the signed-in user; records a new commit. */
	restoreCommit: {
		request: { selector: string; commitId: string; teamId?: string | null; message?: string };
		response: ProjectCommitRestoreResult;
	};
};

export const PROJECT_TIMELINE_UNIT_CLOSE = Object.freeze({ v: 1, type: 'project_timeline_close' });
export function isProjectTimelineUnitClose(value: unknown): boolean {
	const data = value as { v?: unknown; type?: unknown } | null;
	return data?.v === 1 && data.type === 'project_timeline_close';
}
