/**
 * Pure replay eligibility of a deferred draft deletion. A queued deletion may
 * replay only while the editor has no unsaved edit for the chat and the local
 * row exists with no draft text, no preview and version 0, so an older delete
 * never overwrites a newer draft. Mirrored by
 * packages/openmates-rust/src/web_send_prep/deferred_delete.rs (parity vectors).
 */
export interface DeferredDeleteFacts {
  editorOnChat: boolean;
  editorUnsaved: boolean;
  localExists: boolean;
  hasDraft: boolean;
  hasPreview: boolean;
  draftVersion: number | null | undefined;
}

export function isDeferredDeleteReplayable(facts: DeferredDeleteFacts): boolean {
  if (facts.editorOnChat && facts.editorUnsaved) return false;
  return facts.localExists && !facts.hasDraft && !facts.hasPreview && (facts.draftVersion ?? 0) === 0;
}
