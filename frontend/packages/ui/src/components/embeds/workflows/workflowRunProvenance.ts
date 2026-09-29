/** Recognize the provenance link in encrypted legacy and current deliveries. */
const RUN_LINK = /\[View workflow run\]\(\/workflows#workflow-id=([0-9a-f-]{36})&workflow-tab=runs&run-id=([0-9a-f-]{36})\)/i;

export function workflowRunProvenance(markdown: unknown): { workflowId: string; runId: string } | null {
  if (typeof markdown !== 'string') return null;
  const match = RUN_LINK.exec(markdown);
  return match ? { workflowId: match[1], runId: match[2] } : null;
}
