import type { ProjectMentionAccessMode } from "../extensions/GenericMentionNode";

export type ProjectMentionType = "project" | "project_folder" | "project_file";

export function buildProjectMentionSyntax(
  type: ProjectMentionType,
  projectId: string,
  accessMode: ProjectMentionAccessMode,
  path?: string,
  sourceId?: string,
): string {
  if (type === "project") {
    return `@project:${projectId}:${accessMode}`;
  }
  const encodedPath = encodeURIComponent(path ?? "/");
  const sourceSegment = sourceId ? `:${sourceId}` : "";
  return type === "project_folder"
    ? `@project-folder:${projectId}${sourceSegment}:${encodedPath}:${accessMode}`
    : `@project-file:${projectId}${sourceSegment}:${encodedPath}:${accessMode}`;
}
