import { workflowApiRequest, type WorkflowDetail, type WorkflowRunDetail } from '../stores/workflowWorkspaceStore';
import type { WorkflowRunProvenance } from '../components/embeds/workflows/workflowRunProvenance';

/** Fetches owner-scoped display metadata without changing the selected workflow. */
export async function loadWorkflowRunPreviewMetadata(
  provenance: WorkflowRunProvenance,
): Promise<Pick<WorkflowRunProvenance, 'title' | 'description' | 'startedAt'>> {
  const path = `/v1/workflows/${encodeURIComponent(provenance.workflowId)}`;
  const [workflowResult, runResult] = await Promise.allSettled([
    provenance.title
      ? Promise.resolve(null)
      : workflowApiRequest<{ workflow: WorkflowDetail }>(path),
    provenance.startedAt
      ? Promise.resolve(null)
      : workflowApiRequest<{ run: WorkflowRunDetail }>(`${path}/runs/${encodeURIComponent(provenance.runId)}`),
  ]);
  const workflow = workflowResult.status === 'fulfilled' ? workflowResult.value?.workflow : undefined;
  const run = runResult.status === 'fulfilled' ? runResult.value?.run : undefined;
  return {
    title: provenance.title ?? workflow?.title,
    description: provenance.description ?? workflow?.description ?? undefined,
    startedAt: provenance.startedAt ?? run?.started_at ?? undefined,
  };
}
