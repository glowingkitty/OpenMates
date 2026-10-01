import { workflowApiRequest } from "../stores/workflowWorkspaceStore";

export type AppsWorkflowLibraryItem = { id: string; title: string };
export type AppsWorkflowLibraryPage = {
  items: AppsWorkflowLibraryItem[];
  hasMore: boolean;
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
  const params = new URLSearchParams({ app_id: appId, offset: String(offset), limit: String(limit) });
  if (teamId) params.set("team_id", teamId);
  const result = await workflowApiRequest<{
    workflows: AppsWorkflowLibraryItem[];
    has_more: boolean;
    offset: number;
    limit: number;
  }>(`/v1/workflows?${params.toString()}`);
  return {
    items: result.workflows.map(({ id, title }) => ({ id, title })),
    hasMore: result.has_more,
    offset: result.offset,
    limit: result.limit,
  };
}
