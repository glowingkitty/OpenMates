import { test, vi } from 'vitest';
import assert from 'node:assert/strict';

vi.mock('../ruleDocumentService', () => ({ listPersonalRuleDocuments: vi.fn() }));
vi.mock('../../stores/workflowWorkspaceStore', () => ({ workflowWorkspaceStore: {} }));
vi.mock('../../components/workflows/workflowMemorySnapshots', () => ({ syncGraphMemorySnapshots: vi.fn() }));

const { sortMemoriesByRecency } = await import('../workflowMemorySnapshotService');

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.ask-ai
test('dated memories come first newest first, undated follow in reversed stored order', () => {
  const input = [
    { id: 'a' }, { id: 'b', updatedAt: 100 }, { id: 'c' }, { id: 'd', updatedAt: 300 }, { id: 'e', updatedAt: 200 },
  ];
  assert.deepEqual(sortMemoriesByRecency(input).map(item => item.id), ['d', 'e', 'b', 'c', 'a']);
  assert.deepEqual(input.map(item => item.id), ['a', 'b', 'c', 'd', 'e']);
});
