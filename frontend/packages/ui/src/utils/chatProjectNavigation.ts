// Sidebar navigation models retain decrypted names only in memory.
// Folder parent and item membership links use the server SHA-256 IDs.
// A folder view exposes immediate children; activity aggregates descendants.
// Breadcrumbs retain every ancestor while the UI compresses the middle.
// Missing destinations and corrupt cycles never expand to the project root.
export interface ChatProjectLocation { projectId: string; folderId: string | null }
export interface SidebarFolder { id: string; hash: string; parentHash: string | null; name: string }
export interface SidebarProjectItem { id: string; chatId: string; folderHash: string | null }
export interface SidebarProject {
  id: string; name: string; folders: SidebarFolder[]; chats: SidebarProjectItem[];
}
export interface ProjectBreadcrumb { id: string | null; name: string }

export function projectBreadcrumbs(project: SidebarProject, folderId: string | null): ProjectBreadcrumb[] {
  const ancestors: ProjectBreadcrumb[] = [];
  const visited = new Set<string>();
  let folder = project.folders.find(folder => folder.id === folderId);
  while (folder && !visited.has(folder.id)) {
    visited.add(folder.id);
    ancestors.unshift({ id: folder.id, name: folder.name });
    folder = project.folders.find(candidate => candidate.hash === folder!.parentHash);
  }
  return [{ id: null, name: project.name }, ...ancestors];
}

export function projectFolderChatIds(project: SidebarProject, folderId: string | null, recursive = false): Set<string> {
  const folder = project.folders.find(folder => folder.id === folderId);
  if (folderId !== null && !folder) return new Set();
  const hashes = new Set<string | null>([folder?.hash ?? null]);
  if (recursive) {
    let previous = -1;
    while (previous !== hashes.size) {
      previous = hashes.size;
      for (const candidate of project.folders) if (hashes.has(candidate.parentHash)) hashes.add(candidate.hash);
    }
  }
  return new Set(project.chats.filter(chat => hashes.has(chat.folderHash)).map(chat => chat.chatId));
}

export function locationHasRunningChats(project: SidebarProject, folderId: string | null, runningIds: ReadonlySet<string>): boolean {
  return [...projectFolderChatIds(project, folderId, true)].some(id => runningIds.has(id));
}
