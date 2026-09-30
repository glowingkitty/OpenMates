import { test } from 'vitest';
import assert from 'node:assert/strict';
import { consumeWorkflowTestStream, type WorkflowTestStreamEvent } from '../workflowStepTestStream';
import type { WorkflowRunDetail } from '../../stores/workflowWorkspaceStore';

function stream(text: string): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(text);
  let offset = 0;
  return new ReadableStream({
    pull(controller) {
      // A single-byte boundary also splits multibyte Unicode and CRLF frames.
      if (offset === bytes.length) controller.close();
      else controller.enqueue(bytes.slice(offset, ++offset));
    },
  });
}

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.ask-ai
test('streamed preview keeps cumulative Unicode text and returns the saved terminal run', async () => {
  const run = { run_id: 'test-run', status: 'completed' } as WorkflowRunDetail;
  const events: WorkflowTestStreamEvent[] = [];
  const frames = [
    { type: 'processing', run_id: 'test-run' },
    { type: 'chunk', content: '**Café**' },
    { type: 'chunk', content: '**Café** ☀️\n\nA rendered answer.' },
    { type: 'completed', run },
  ].map(event => `data: ${JSON.stringify(event)}\r\n\r\n`).join('');
  assert.deepEqual(await consumeWorkflowTestStream(stream(frames), event => events.push(event)), run);
  assert.deepEqual(events.map(event => event.type), ['processing', 'chunk', 'chunk', 'completed']);
  assert.equal(events[2].type === 'chunk' && events[2].content, '**Café** ☀️\n\nA rendered answer.');
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.ask-ai
test('failed or interrupted streams cannot become a successful workflow preview', async () => {
  const run = { run_id: 'failed-run', status: 'failed' } as WorkflowRunDetail;
  const events: WorkflowTestStreamEvent[] = [];
  const failure = { type: 'error', message: 'Inference failed', run };
  await assert.rejects(consumeWorkflowTestStream(stream(`data: ${JSON.stringify(failure)}\n\n`), event => events.push(event)), /Inference failed/);
  assert.deepEqual(events, [failure]);
  await assert.rejects(consumeWorkflowTestStream(stream('data: {"type":"chunk","content":"partial"}\n\n'), () => {}), /before completion/);
});
