/** Metadata travels in the encrypted delivered message, so shared history needs no owner API. */
export type WorkflowRunProvenance = {
  workflowId: string;
  runId: string;
  title?: string;
  description?: string;
  startedAt?: number;
};

const RUN_LINK = /\[View workflow run\]\((\/workflows#[^\s)]*)\)/i;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function boundedText(value: string | null, limit: number, multiline = false): string | undefined {
  if (!value || value.length > limit || Array.from(value).some(char => { const code = char.charCodeAt(0); return (code < 32 && !(multiline && [9, 10, 13].includes(code))) || code === 127; })) return undefined;
  return value.trim() || undefined;
}

export function workflowRunProvenance(markdown: unknown): WorkflowRunProvenance | null {
  if (typeof markdown !== 'string') return null;
  const match = RUN_LINK.exec(markdown);
  if (!match) return null;
  const params = new URLSearchParams(match[1].split('#', 2)[1]);
  const workflowId = params.get('workflow-id');
  const runId = params.get('run-id');
  if (!workflowId || !runId || !UUID.test(workflowId) || !UUID.test(runId) || params.get('workflow-tab') !== 'runs') return null;
  const started = params.get('run-started');
  const startedAt = started && /^\d{1,11}$/.test(started) ? Number(started) : undefined;
  return {
    workflowId,
    runId,
    title: boundedText(params.get('workflow-name'), 200),
    description: boundedText(params.get('workflow-description'), 2000, true),
    startedAt: startedAt && Number.isSafeInteger(startedAt) ? startedAt : undefined,
  };
}
