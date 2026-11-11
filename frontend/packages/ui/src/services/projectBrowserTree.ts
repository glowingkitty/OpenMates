import type { ProjectItemViewModel } from "./projectService";

/** One direct child of a hosted folder, as listed on its card. */
export interface ProjectVirtualFolderChild {
  name: string;
  kind: "folder" | "file";
}

export interface ProjectVirtualFolder {
  name: string;
  path: string;
  /** Direct children (folders first, then files, by name); absent for breadcrumbs. */
  children?: ProjectVirtualFolderChild[];
}

function safePath(path: string): string | null {
  if (!path || path.length > 4096 || path.startsWith("/") || path.includes("\\")) return null;
  const parts = path.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) return null;
  return path;
}

/** Folder path of an adopted application item (`source: project_application`), else null. */
export function projectApplicationFolder(item: ProjectItemViewModel): string | null {
  if (item.metadata.source !== "project_application" || typeof item.metadata.path !== "string") return null;
  return safePath(item.metadata.path);
}

function hostedPath(item: ProjectItemViewModel): string | null {
  if (item.metadata.source !== "hosted_project_file" || typeof item.metadata.path !== "string") return null;
  return safePath(item.metadata.path);
}

/** Derive browsable virtual folders without exposing path segments to the server. */
export function projectVirtualBrowserView(
  items: readonly ProjectItemViewModel[],
  virtualPath: string | null,
): { folders: ProjectVirtualFolder[]; items: ProjectItemViewModel[] } {
  const prefix = virtualPath ? `${virtualPath}/` : "";
  const folders = new Map<string, ProjectVirtualFolder>();
  const visible: ProjectItemViewModel[] = [];
  const applications: ProjectItemViewModel[] = [];
  for (const item of items) {
    if (item.encrypted.hashed_folder_id) continue;
    const applicationFolder = projectApplicationFolder(item);
    if (applicationFolder) {
      // An application belongs to its folder: first entry inside it, never a loose root item.
      if (applicationFolder === virtualPath) applications.push(item);
      else if (applicationFolder.startsWith(prefix)) {
        const remainder = applicationFolder.slice(prefix.length);
        const name = remainder.split("/")[0]!;
        const folderPath = virtualPath ? `${virtualPath}/${name}` : name;
        const folder = folders.get(folderPath) ?? { name, path: folderPath, children: [] };
        folders.set(folderPath, folder);
        const nested = remainder.split("/")[1];
        if (nested && !folder.children!.some((entry) => entry.kind === "folder" && entry.name === nested)) {
          folder.children!.push({ name: nested, kind: "folder" });
        }
      }
      continue;
    }
    const path = hostedPath(item);
    if (!path) {
      if (!virtualPath) visible.push(item);
      continue;
    }
    if (!path.startsWith(prefix)) continue;
    const remainder = path.slice(prefix.length);
    const separator = remainder.indexOf("/");
    if (separator < 0) {
      visible.push(item);
      continue;
    }
    const name = remainder.slice(0, separator);
    const folderPath = virtualPath ? `${virtualPath}/${name}` : name;
    const folder = folders.get(folderPath) ?? { name, path: folderPath, children: [] };
    folders.set(folderPath, folder);
    // The card lists what is directly inside the folder, not the folder itself.
    const inner = remainder.slice(separator + 1);
    const innerSeparator = inner.indexOf("/");
    const child: ProjectVirtualFolderChild = innerSeparator < 0
      ? { name: inner, kind: "file" }
      : { name: inner.slice(0, innerSeparator), kind: "folder" };
    if (!folder.children!.some((entry) => entry.kind === child.kind && entry.name === child.name)) {
      folder.children!.push(child);
    }
  }
  for (const folder of folders.values()) {
    folder.children!.sort((left, right) => left.kind === right.kind
      ? left.name.localeCompare(right.name) : left.kind === "folder" ? -1 : 1);
  }
  return {
    folders: [...folders.values()].sort((left, right) => left.name.localeCompare(right.name)),
    items: [...applications, ...visible],
  };
}

export function projectBrowserItemName(item: ProjectItemViewModel): string {
  const path = hostedPath(item);
  return path?.split("/").at(-1) || item.displayName || item.target_id;
}

export function projectVirtualBreadcrumbs(path: string | null): ProjectVirtualFolder[] {
  if (!path) return [];
  const parts = path.split("/");
  return parts.map((name, index) => ({ name, path: parts.slice(0, index + 1).join("/") }));
}
