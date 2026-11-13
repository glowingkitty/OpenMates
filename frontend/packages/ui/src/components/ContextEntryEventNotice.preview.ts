// Preview states for the context_entry chat history event:
// /dev/preview/ContextEntryEventNotice?chrome=0 (memory created), &variant=memory_updated,
// &variant=workflow_created, &variant=workflow_updated, &variant=missing,
// assistant-written Memories: &variant=assistant_created, &variant=assistant_updated,
// &variant=assistant_undone, &variant=assistant_undo_changed (Undo refused: edited since).
import type { ContextEntryHistoryEvent } from '../types/recommendations';

const event: ContextEntryHistoryEvent = {
  schema_version: 1, type: 'context_entry', kind: 'memory', action: 'created',
  entry_id: 'preview-memory', title: 'Conference day pacing', created_at: 1_793_000_000,
};

const props = {
  event,
  checkExists: async (_event: ContextEntryHistoryEvent) => true,
  onOpenMemory: (_event: ContextEntryHistoryEvent) => {},
  undone: false,
  onUndo: async (_event: ContextEntryHistoryEvent) => {},
};

const assistantEvent: ContextEntryHistoryEvent = {
  ...event, entry_id: 'personal:preview-assistant', title: 'Favourite test colour', source: 'assistant',
  undo: { job_id: 'memory-write-job-preview', action: 'create', written_document_sha256: '0'.repeat(64) },
};
const assistantUpdated: ContextEntryHistoryEvent = {
  ...assistantEvent, action: 'updated',
  undo: {
    job_id: 'memory-write-job-preview', action: 'update', written_document_sha256: '0'.repeat(64),
    encrypted_previous_document: 'sealed-preview',
  },
};

export default props;
export const variants = {
  memory_updated: { ...props, event: { ...event, action: 'updated' as const } },
  workflow_created: { ...props, event: { ...event, kind: 'workflow' as const, entry_id: 'preview-workflow', title: 'Weekly open source conference digest that summarises every talk, speaker announcement, schedule change and community discussion from the whole week' } },
  workflow_updated: { ...props, event: { ...event, kind: 'workflow' as const, action: 'updated' as const, entry_id: 'preview-workflow', title: 'Weekly open source conference digest' } },
  missing: { ...props, checkExists: async (_event: ContextEntryHistoryEvent) => false },
  assistant_created: { ...props, event: assistantEvent },
  assistant_updated: { ...props, event: assistantUpdated },
  assistant_undone: { ...props, event: assistantEvent, undone: true, checkExists: async (_event: ContextEntryHistoryEvent) => false },
  assistant_undo_changed: {
    ...props, event: assistantUpdated,
    onUndo: async (_event: ContextEntryHistoryEvent) => { throw new Error('rule_changed'); },
  },
};
