import { describe, expect, it } from 'vitest';
import { workflowRunProvenance } from './workflowRunProvenance';

const workflowId = '998a335e-741f-582c-885c-bf61d12ace93';
const runId = '118a335e-741f-582c-885c-bf61d12ace93';

describe('workflow run provenance', () => {
  // contract-test: supporting surface=gui.web assertions=workflows.chat-delivery.run-provenance
  it('keeps legacy links readable and decodes a bounded encrypted snapshot', () => {
    const base = `/workflows#workflow-id=${workflowId}&workflow-tab=runs&run-id=${runId}`;
    expect(workflowRunProvenance(`[View workflow run](${base})`)).toEqual({ workflowId, runId, title: undefined, description: undefined, startedAt: undefined });
    expect(workflowRunProvenance(`[View workflow run](${base}&workflow-name=Meetings+%26+events&workflow-description=Today%27s+brief&run-started=1791764400)`)).toEqual({
      workflowId, runId, title: 'Meetings & events', description: "Today's brief", startedAt: 1791764400,
    });
    const title = 'A'.repeat(200);
    const description = 'First line\nSecond line';
    const multiline = workflowRunProvenance(`[View workflow run](${base}&workflow-name=${title}&workflow-description=${encodeURIComponent(description)})`);
    expect(multiline?.title).toBe(title);
    expect(multiline?.description).toBe(description);
  });

  // contract-test: supporting surface=gui.web assertions=workflows.chat-delivery.run-provenance
  it('rejects malformed IDs and ignores invalid optional fields', () => {
    expect(workflowRunProvenance('[View workflow run](/workflows#workflow-id=bad&workflow-tab=runs&run-id=bad)')).toBeNull();
    const parsed = workflowRunProvenance(`[View workflow run](/workflows#workflow-id=${workflowId}&workflow-tab=runs&run-id=${runId}&workflow-name=%0Aevil&run-started=-5)`);
    expect(parsed?.title).toBeUndefined();
    expect(parsed?.startedAt).toBeUndefined();
  });
});
