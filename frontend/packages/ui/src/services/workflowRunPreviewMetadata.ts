import { workflowApiRequest, type WorkflowDetail, type WorkflowRunDetail } from '../stores/workflowWorkspaceStore';
import type { WorkflowRunProvenance } from '../components/embeds/workflows/workflowRunProvenance';
import { workClient, workDecide } from './work/workRust';

// Flag-on builds decide which reads are needed and merge the metadata in the
// shared Rust core Worker (`work` op, web_work/workflows.rs); the constant folds
// to false otherwise, so flag-off keeps the original path.
const RUST_WORK = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';

type PreviewMetadata = Pick<WorkflowRunProvenance, 'title' | 'description' | 'startedAt'>;

/** Fetches owner-scoped display metadata without changing the selected workflow. */
export async function loadWorkflowRunPreviewMetadata(
  provenance: WorkflowRunProvenance,
): Promise<PreviewMetadata> {
  const work = RUST_WORK ? workClient() : null;
  if (work) {
    const paths = await workDecide<{ workflow: string | null; run: string | null }>(work, 'workflowRunPreviewPaths', { provenance });
    const [workflowResult, runResult] = await Promise.allSettled([
      paths.workflow === null ? Promise.resolve(null) : workflowApiRequest<{ workflow: WorkflowDetail }>(paths.workflow),
      paths.run === null ? Promise.resolve(null) : workflowApiRequest<{ run: WorkflowRunDetail }>(paths.run),
    ]);
    const merged = await workDecide<PreviewMetadata>(work, 'workflowRunPreviewMerge', {
      provenance,
      workflow: workflowResult.status === 'fulfilled' ? workflowResult.value?.workflow : undefined,
      run: runResult.status === 'fulfilled' ? runResult.value?.run : undefined,
    });
    return { title: merged.title, description: merged.description, startedAt: merged.startedAt };
  }
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
