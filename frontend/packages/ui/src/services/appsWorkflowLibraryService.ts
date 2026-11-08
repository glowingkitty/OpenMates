import { workflowApiRequest } from "../stores/workflowWorkspaceStore";
import { workClient, workDecide } from "./work/workRust";

// Flag-on builds decide the query path and the page projection in the shared
// Rust core Worker (`work` op, web_work/workflows.rs); the constant folds to
// false otherwise, so flag-off keeps the original path.
const RUST_WORK = import.meta.env.VITE_OPENMATES_RUST_CORE === "1";

export type AppsWorkflowLibraryItem = { id: string; title: string };
export type AppsWorkflowLibraryPage = {
  items: AppsWorkflowLibraryItem[];
  hasMore: boolean;
  offset: number;
  limit: number;
};

type AppsWorkflowLibraryReply = {
  workflows: AppsWorkflowLibraryItem[];
  has_more: boolean;
  offset: number;
  limit: number;
};

/** Load only saved workflows related to this app in the selected account. */
export async function listAppsWorkflows(
  appId: string,
  teamId?: string,
  offset = 0,
  limit = 20,
): Promise<AppsWorkflowLibraryPage> {
  const work = RUST_WORK ? workClient() : null;
  if (work) {
    const path = await workDecide<string>(work, "workflowAppsLibraryPath", { app_id: appId, team_id: teamId, offset, limit });
    const reply = await workflowApiRequest<AppsWorkflowLibraryReply>(path);
    const page = await workDecide<AppsWorkflowLibraryPage>(work, "workflowAppsLibraryPage", { result: reply });
    return { items: page.items, hasMore: page.hasMore, offset: page.offset, limit: page.limit };
  }
  const params = new URLSearchParams({ app_id: appId, offset: String(offset), limit: String(limit) });
  if (teamId) params.set("team_id", teamId);
  const result = await workflowApiRequest<AppsWorkflowLibraryReply>(`/v1/workflows?${params.toString()}`);
  return {
    items: result.workflows.map(({ id, title }) => ({ id, title })),
    hasMore: result.has_more,
    offset: result.offset,
    limit: result.limit,
  };
}
