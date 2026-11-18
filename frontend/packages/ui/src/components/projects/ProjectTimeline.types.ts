export type ProjectTimelineAuthor = 'user' | 'assistant';

export interface ProjectTimelineCommitFile {
  path: string;
  version: number;
  /** Absent when the commit does not record a per-file change kind. */
  change?: 'added' | 'modified' | 'deleted' | 'unchanged';
}

export interface ProjectTimelineCommit {
  id: string;
  message: string;
  author: ProjectTimelineAuthor;
  restoredFrom: string | null;
  files: ProjectTimelineCommitFile[];
}

export interface ProjectTimelineEntry {
  kind: 'commit' | 'file_version' | 'file_operation';
  id: string;
  /** Unix seconds. */
  createdAt: number;
  author: ProjectTimelineAuthor;
  path: string | null;
  pathSource: 'live' | 'commit' | 'unknown';
  version: number | null;
  action: string | null;
  restoredFromVersion: number | null;
  commit: ProjectTimelineCommit | null;
}
