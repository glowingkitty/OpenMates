import type { ProjectFolderViewModel, ProjectItemViewModel, ProjectRemoteDirectoryEntry } from './projectService';
import { projectBrowserItemName } from './projectBrowserTree';

export type ProjectRemoteBrowserRow =
  | { kind: 'remote'; key: string; name: string; entry: ProjectRemoteDirectoryEntry }
  | { kind: 'chat'; key: string; name: string; item: ProjectItemViewModel }
  | { kind: 'chat-folder'; key: string; name: string; path: string };

/** Match the connected CLI's basename cursor ordering, including equal locale keys. */
export function compareProjectNames(left: string, right: string): number {
  return left.localeCompare(right) || (left < right ? -1 : left > right ? 1 : 0);
}

function folderPath(value: unknown): string | null {
  if (value === '.' || value === '' || value === null || value === undefined) return '.';
  if (typeof value !== 'string' || value.length > 4096 || value.startsWith('/') || value.includes('\\')) return null;
  const path = value.startsWith('./') ? value.slice(2) : value;
  return path.split('/').some((part) => !part || part === '.' || part === '..') ? null : path;
}

/** Project links are encrypted OpenMates metadata, never connected-device files. */
export function projectChatFolderPath(
  item: ProjectItemViewModel,
  sourceId: string,
  folders: readonly ProjectFolderViewModel[],
  hashes: ReadonlyMap<string, string>,
): string | null {
  if (item.item_type !== 'chat') return null;
  if (item.metadata.source_id !== undefined && item.metadata.source_id !== sourceId) return null;
  let hash = item.encrypted.hashed_folder_id;
  if (!hash) return folderPath(item.metadata.folder_path ?? item.metadata.path);
  const byHash = new Map(folders.flatMap((folder) => {
    const key = hashes.get(folder.folder_id);
    return key ? [[key, folder] as const] : [];
  }));
  const seen = new Set<string>();
  const parts: string[] = [];
  while (hash) {
    if (seen.has(hash)) return null;
    seen.add(hash);
    const folder = byHash.get(hash);
    if (!folder || !folder.name || folder.name.includes('/')) return null;
    parts.unshift(folder.name);
    hash = folder.parentHash;
  }
  return folderPath(parts.join('/'));
}

/** Merge direct chat links and their reachable ancestors with the live file prefix. */
export function projectRemoteBrowserRows(
  items: readonly ProjectItemViewModel[],
  folders: readonly ProjectFolderViewModel[],
  hashes: ReadonlyMap<string, string>,
  sourceId: string,
  path: string,
  entries: readonly ProjectRemoteDirectoryEntry[],
): ProjectRemoteBrowserRow[] {
  const remotePaths = new Set(entries.filter((entry) => entry.kind === 'directory').map((entry) => entry.path));
  const childFolders = new Map<string, ProjectRemoteBrowserRow>();
  const rows: ProjectRemoteBrowserRow[] = entries.map((entry) => ({
    kind: 'remote', key: `remote:${entry.path}`, name: entry.path.split('/').at(-1) || entry.path, entry,
  }));
  const prefix = path === '.' ? '' : `${path}/`;
  for (const item of items) {
    const location = projectChatFolderPath(item, sourceId, folders, hashes);
    if (location === path) {
      rows.push({ kind: 'chat', key: `chat:${item.project_item_id}`, name: projectBrowserItemName(item), item });
    } else if (location && location !== '.' && location.startsWith(prefix)) {
      const name = location.slice(prefix.length).split('/')[0];
      const childPath = `${prefix}${name}`;
      if (!remotePaths.has(childPath)) childFolders.set(childPath, { kind: 'chat-folder', key: `chat-folder:${childPath}`, name, path: childPath });
    }
  }
  rows.push(...childFolders.values());
  return rows.sort((left, right) => compareProjectNames(left.name, right.name) || compareProjectNames(left.key, right.key));
}

/** Unfetched remote names must sort after the last fetched basename cursor. */
export function projectRemotePageReady(
  rows: readonly ProjectRemoteBrowserRow[],
  pageIndex: number,
  pageSize: number,
  nextCursor: string | null,
): boolean {
  if (!nextCursor) return true;
  const last = rows[(pageIndex + 1) * pageSize - 1];
  return !!last && compareProjectNames(last.name, nextCursor) <= 0;
}
