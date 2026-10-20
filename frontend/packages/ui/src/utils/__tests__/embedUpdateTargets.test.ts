import { describe, expect, it } from 'vitest';
import { embedUpdateTargetIds } from '../embedUpdateTargets';

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
describe('embed updates preserve unaffected assistant messages', () => {
  const messages = [
    { message_id: 'user-new', role: 'user', content: 'Find classes' },
    { message_id: 'old', role: 'assistant', user_message_id: 'user-old', content: 'Earlier answer' },
    { message_id: 'task-new', role: 'assistant', user_message_id: 'user-new', status: 'streaming', content: 'Working' },
  ];
  it('uses the user-to-assistant turn link rather than refreshing every answer', () => {
    expect([...embedUpdateTargetIds(messages, { message_id: 'user-new' })]).toEqual(['task-new']);
  });
  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it('accepts task IDs when an event does not carry the user message ID', () => {
    expect([...embedUpdateTargetIds(messages, { task_id: 'task-new' })]).toEqual(['task-new']);
  });
  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it('finds a saved structured reference without changing unrelated messages', () => {
    const saved = [...messages, { message_id: 'saved', role: 'assistant', content: {
      type: 'doc', content: [{ type: 'embed', attrs: { contentRef: 'embed:failed-call' } }],
    } }];
    expect([...embedUpdateTargetIds(saved, { embed_id: 'failed-call' })]).toEqual(['saved']);
    expect([...embedUpdateTargetIds(saved, { embed_id: 'another-chat' })]).toEqual([]);
  });
});
