// contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../db', () => ({ chatDB: { getMessagesForChat: vi.fn() } }));
vi.mock('../ruleDocumentService', () => ({ listPersonalRuleDocuments: vi.fn() }));
vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));

import {
  CONTEXT_SUGGESTION_WIRE, buildUpdatePreviewRequest, contextSuggestionKey, parseContextSuggestion,
  parseUpdatePreviewResponse,
} from '../contextSuggestionWire';
import {
  ContextSuggestionError, NEW_MEMORY_DRAFT_ID, newMemoryDraft, previewMessageText, requestUpdatePreview,
  toPreviewMessages, updateMemoryDraft,
} from '../contextSuggestionService';
import { chatDB } from '../db';
import { listPersonalRuleDocuments } from '../ruleDocumentService';
import { serializeRuleDocument } from '../../utils/ruleDocuments';

const wrap = (context_suggestion: unknown) => ({ [CONTEXT_SUGGESTION_WIRE.postProcessingField]: context_suggestion });
const memoryDocument = serializeRuleDocument({ title: 'Staging API', when_to_use: 'deploys', body: 'port 8001', load_mode: 'auto_include' });

describe('context suggestion wire adapter', () => {
  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('parses the three suggestion kinds', () => {
    expect(parseContextSuggestion(wrap({ kind: 'memory_update', memory_id: 'personal:1', title: 'Staging API' })))
      .toEqual({ kind: 'memory_update', memoryId: 'personal:1', title: 'Staging API' });
    expect(parseContextSuggestion(wrap({ kind: 'memory_create', title: 'Tone', body: 'Be brief' })))
      .toEqual({ kind: 'memory_create', title: 'Tone', body: 'Be brief' });
    expect(parseContextSuggestion(wrap({ kind: 'workflow_create', title: 'Weekly events', summary: 'Every Monday' })))
      .toEqual({ kind: 'workflow_create', title: 'Weekly events', summary: 'Every Monday' });
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('rejects missing, unknown or incomplete shapes', () => {
    expect(parseContextSuggestion({})).toBeNull();
    expect(parseContextSuggestion(wrap(null))).toBeNull();
    expect(parseContextSuggestion(wrap({ kind: 'memory_update', title: 'x' }))).toBeNull();
    expect(parseContextSuggestion(wrap({ kind: 'memory_create', title: 'x' }))).toBeNull();
    expect(parseContextSuggestion(wrap({ kind: 'workflow_create', title: 'x' }))).toBeNull();
    expect(parseContextSuggestion(wrap({ kind: 'other', title: 'x', body: 'y' }))).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('builds the update preview request and validates its response', () => {
    expect(buildUpdatePreviewRequest({ chatId: 'c', memoryId: 'm', memoryMarkdown: 'md', messages: [] }))
      .toEqual({ chat_id: 'c', memory_id: 'm', memory_markdown: 'md', messages: [] });
    expect(parseUpdatePreviewResponse({ status: 'updated', body: 'new' })).toEqual({ status: 'updated', body: 'new' });
    expect(parseUpdatePreviewResponse({ status: 'unchanged' })).toEqual({ status: 'unchanged' });
    expect(() => parseUpdatePreviewResponse({ status: 'updated' })).toThrow();
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('keys suggestions by kind, target and title', () => {
    const a = contextSuggestionKey({ kind: 'memory_update', memoryId: '1', title: 'T' });
    expect(a).not.toBe(contextSuggestionKey({ kind: 'memory_update', memoryId: '2', title: 'T' }));
  });
});

describe('context suggestion drafts and preview', () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('uses only user/assistant text and strips embed references', () => {
    const embed = '```json\n{"type":"app_skill_use","embed_id":"abc"}\n```';
    expect(previewMessageText(`Hello ${embed}`)).toBe('Hello');
    expect(toPreviewMessages([
      { role: 'assistant', content: 'b', created_at: 2 }, { role: 'user', content: 'a', created_at: 1 },
      { role: 'system', content: 'ctx', created_at: 3 }, { role: 'assistant', content: embed, created_at: 4 },
    ])).toEqual([{ role: 'user', text: 'a' }, { role: 'assistant', text: 'b' }]);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('builds an unsaved new-memory draft without any request', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const generated = serializeRuleDocument({ title: 'Tone', when_to_use: 'writing', body: 'Be brief', load_mode: 'ask_first' });
    expect(newMemoryDraft({ title: 'Tone', body: generated })).toMatchObject({
      id: NEW_MEMORY_DRAFT_ID, title: 'Tone', memory: 'Be brief', when_to_use: 'writing', load_mode: 'ask_first', is_new: true,
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('records the preview-time document as the draft base', () => {
    const updated = serializeRuleDocument({ title: 'Staging API', when_to_use: 'deploys', body: 'port 8002', load_mode: 'auto_include' });
    const draft = updateMemoryDraft({ id: 'personal:1', source: 'personal', document: memoryDocument }, updated);
    expect(draft).toMatchObject({ id: 'personal:1', title: 'Staging API', memory: 'port 8002', base_document: memoryDocument });
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('sends the originating chat text to the update preview and returns the draft source', async () => {
    vi.mocked(listPersonalRuleDocuments).mockResolvedValue([{ id: 'personal:1', source: 'personal', document: memoryDocument }]);
    vi.mocked(chatDB.getMessagesForChat).mockResolvedValue([{ role: 'user', content: 'port is 8002', created_at: 1 }] as never);
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ status: 'unchanged' }), { status: 200 }));
    const { result } = await requestUpdatePreview('chat-1', '1');
    expect(result).toEqual({ status: 'unchanged' });
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe(`https://api.test${CONTEXT_SUGGESTION_WIRE.updatePreviewPath}`);
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      chat_id: 'chat-1', memory_id: 'personal:1', memory_markdown: memoryDocument,
      messages: [{ role: 'user', text: 'port is 8002' }],
    });
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('maps insufficient credits and missing memories to typed errors', async () => {
    vi.mocked(listPersonalRuleDocuments).mockResolvedValue([{ id: 'personal:1', source: 'personal', document: memoryDocument }]);
    vi.mocked(chatDB.getMessagesForChat).mockResolvedValue([] as never);
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 402 }));
    await expect(requestUpdatePreview('c', '1')).rejects.toMatchObject({ code: 'insufficient_credits' });
    await expect(requestUpdatePreview('c', 'missing')).rejects.toBeInstanceOf(ContextSuggestionError);
  });
});
