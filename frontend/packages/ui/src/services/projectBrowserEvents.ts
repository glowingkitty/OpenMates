export const PROJECTS_CHANGED_EVENT = "openmates-projects-changed";

export function broadcastProjectFilesChanged(projectId?: string): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(PROJECTS_CHANGED_EVENT, {
    detail: projectId ? { projectId } : undefined,
  }));
}
