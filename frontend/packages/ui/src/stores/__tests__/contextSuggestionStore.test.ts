// contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
import { beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import {
  clearContextSuggestions, contextSuggestions, dismissContextSuggestion, isContextSuggestionDismissed,
  setContextSuggestion,
} from '../contextSuggestionStore';
import type { ContextSuggestion } from '../../services/contextSuggestionWire';

const update: ContextSuggestion = { kind: 'memory_update', memoryId: 'personal:1', title: 'Staging API' };

describe('context suggestion store', () => {
  beforeEach(() => { localStorage.clear(); clearContextSuggestions(); });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('keeps one suggestion per chat; a new turn replaces it', () => {
    setContextSuggestion('c1', update);
    setContextSuggestion('c1', { kind: 'workflow_create', title: 'W', summary: 'S' });
    expect(get(contextSuggestions).c1).toMatchObject({ kind: 'workflow_create' });
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('remembers dismissals locally per chat and suggestion', () => {
    setContextSuggestion('c1', update);
    dismissContextSuggestion('c1', update);
    expect(get(contextSuggestions).c1).toBeNull();
    expect(isContextSuggestionDismissed('c1', update)).toBe(true);
    expect(isContextSuggestionDismissed('c2', update)).toBe(false);
    expect(isContextSuggestionDismissed('c1', { ...update, memoryId: 'personal:2' })).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('tolerates corrupt storage', () => {
    localStorage.setItem('openmates.contextSuggestionDismissals.v1', '{not json');
    expect(isContextSuggestionDismissed('c1', update)).toBe(false);
  });
});
