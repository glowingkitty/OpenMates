import type { ProjectTimelineEntry } from './ProjectTimeline.types';

const now = Math.floor(Date.now() / 1000);
const wait = () => new Promise<void>((resolve) => setTimeout(resolve, 300));

function version(
  id: string, ago: number, author: 'user' | 'assistant', path: string | null, v: number,
  action: string, extra: Partial<ProjectTimelineEntry> = {},
): ProjectTimelineEntry {
  return {
    kind: 'file_version', id, createdAt: now - ago, author, path,
    pathSource: path ? 'live' : 'unknown', version: v, action,
    restoredFromVersion: null, commit: null, ...extra,
  };
}

function commit(
  id: string, ago: number, author: 'user' | 'assistant', message: string,
  files: { path: string; version: number; change: 'added' | 'modified' | 'deleted' | 'unchanged' }[],
  restoredFrom: string | null = null,
): ProjectTimelineEntry {
  return {
    kind: 'commit', id, createdAt: now - ago, author, path: null, pathSource: 'commit',
    version: null, action: null, restoredFromVersion: null,
    commit: { id, message, author, restoredFrom, files },
  };
}

export const entries: ProjectTimelineEntry[] = [
  commit('c4e1f9a2b3', 600, 'user', 'Restore "Add recipe list"', [
    { path: 'web-app/index.html', version: 3, change: 'modified' },
    { path: 'web-app/app.js', version: 3, change: 'modified' },
  ], 'a91b2c3d4e'),
  {
    kind: 'file_operation', id: 'op-removed', createdAt: now - 3600, author: 'assistant', path: null,
    pathSource: 'unknown', version: null, action: 'deleted', restoredFromVersion: null, commit: null,
  },
  commit('b7d2e8f1a0', 7200, 'assistant', 'Fix ingredient scaling', [
    { path: 'web-app/app.js', version: 2, change: 'modified' },
    { path: 'web-app/index.html', version: 1, change: 'unchanged' },
  ]),
  {
    kind: 'file_operation', id: 'op-rename', createdAt: now - 10800, author: 'user', path: 'web-app/recipes.js',
    pathSource: 'live', version: 2, action: 'renamed', restoredFromVersion: null, commit: null,
  },
  version('v-styles', 14400, 'user', 'web-app/styles.css', 2, 'edited'),
  commit('a91b2c3d4e', 90000, 'assistant', 'Add recipe list', [
    { path: 'web-app/index.html', version: 1, change: 'added' },
    { path: 'web-app/app.js', version: 1, change: 'added' },
    { path: 'web-app/styles.css', version: 1, change: 'added' },
  ]),
  version('v-app', 90100, 'assistant', 'web-app/app.js', 1, 'created'),
  version('v-index', 90200, 'assistant', 'web-app/index.html', 1, 'created'),
];

const callbacks = {
  onLoadMore: () => { window.dispatchEvent(new CustomEvent('project-timeline-action', { detail: 'load-more' })); },
  onRestoreCommit: wait,
  onOpenFile: (path: string) => { window.dispatchEvent(new CustomEvent('project-timeline-action', { detail: path })); },
};

export default { entries, loading: false, error: null, hasMore: true, ...callbacks };

export const variants = {
  empty: { ...callbacks, entries: [], loading: false, error: null, hasMore: false },
  error: { ...callbacks, entries: [], loading: false, error: 'The history service did not answer.', hasMore: false },
  loading: { ...callbacks, entries: [], loading: true, error: null, hasMore: false },
  restoreFails: {
    ...callbacks, entries, loading: false, error: null, hasMore: false,
    onRestoreCommit: async () => { await wait(); throw new Error('restore failed'); },
  },
};
