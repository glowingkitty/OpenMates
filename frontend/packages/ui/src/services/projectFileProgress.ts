/** Safe, client-visible state for one Project file operation. */
export type ProjectFileProgressPhase =
  | "available" | "running" | "completed" | "awaiting_approval"
  | "waiting_for_executor" | "conflict" | "failed";

export interface ProjectFileProgress {
  chatId: string;
  operationId: string;
  operation: string;
  searchTarget: string;
  phase: ProjectFileProgressPhase;
}

/** A landing page has neither a chat nor progress; absent IDs must never match. */
export function projectFileProgressMatchesChat(
  progress: ProjectFileProgress | null,
  chatId: string | null | undefined,
): progress is ProjectFileProgress {
  return Boolean(progress && chatId && progress.chatId === chatId);
}

export function phaseFromProjectFileResult(status: unknown): ProjectFileProgressPhase {
  switch (status) {
    case "completed":
    case "awaiting_approval":
    case "waiting_for_executor":
    case "conflict":
      return status;
    default:
      return "failed";
  }
}

export function projectFileProgressKey(progress: ProjectFileProgress): string {
  if (progress.phase === "completed") return "ready";
  if (progress.phase === "awaiting_approval") return "approval";
  if (progress.phase === "waiting_for_executor") return "waiting_source";
  if (progress.phase === "conflict") return "conflict";
  if (progress.phase === "available") return "preparing";
  if (progress.operation === "search" && progress.searchTarget === "files") return "search_files";
  if (progress.operation === "search" && progress.searchTarget === "content") return "search_text";
  if (progress.operation === "read_text") return "read";
  if (progress.operation === "list") return "list";
  return "working";
}
