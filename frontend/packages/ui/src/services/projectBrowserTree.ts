import type { ProjectItemViewModel } from "./projectService";

export interface ProjectVirtualFolder {
  name: string;
  path: string;
}

function hostedPath(item: ProjectItemViewModel): string | null {
  if (item.metadata.source !== "hosted_project_file" || typeof item.metadata.path !== "string") return null;
  const path = item.metadata.path;
  if (!path || path.length > 4096 || path.startsWith("/") || path.includes("\\")) return null;
  const parts = path.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) return null;
  return path;
}

/** Derive browsable virtual folders without exposing path segments to the server. */
export function projectVirtualBrowserView(
  items: readonly ProjectItemViewModel[],
  virtualPath: string | null,
): { folders: ProjectVirtualFolder[]; items: ProjectItemViewModel[] } {
  const prefix = virtualPath ? `${virtualPath}/` : "";
  const folders = new Map<string, ProjectVirtualFolder>();
  const visible: ProjectItemViewModel[] = [];
  for (const item of items) {
    if (item.encrypted.hashed_folder_id) continue;
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
    folders.set(folderPath, { name, path: folderPath });
  }
  return {
    folders: [...folders.values()].sort((left, right) => left.name.localeCompare(right.name)),
    items: visible,
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
