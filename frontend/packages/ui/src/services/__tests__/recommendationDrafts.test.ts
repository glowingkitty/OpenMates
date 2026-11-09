// contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../db', () => ({ chatDB: { getMessagesForChat: vi.fn() } }));
vi.mock('../ruleDocumentService', () => ({ listPersonalRuleDocuments: vi.fn() }));
vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));

import {
  NEW_MEMORY_DRAFT_ID, RECOMMENDATION_DRAFT_WIRE, RecommendationDraftError, buildWorkflowInstruction,
  latestTurn, newMemoryDraft, parseUpdatePreviewResponse, previewMessageText, requestCreateMemoryDraft,
  requestUpdatePreview, toPreviewMessages, updateMemoryDraft,
} from '../recommendationDrafts';
import { chatDB } from '../db';
import { listPersonalRuleDocuments } from '../ruleDocumentService';
import { serializeRuleDocument } from '../../utils/ruleDocuments';

const memoryDocument = serializeRuleDocument({ title: 'Staging API', when_to_use: 'deploys', body: 'port 8001', load_mode: 'auto_include' });
const turnMessages = [
  { role: 'user', content: 'Find open source conferences', created_at: 1 },
  { role: 'assistant', content: 'FOSDEM is in Brussels.', created_at: 2 },
  { role: 'system', content: '{"type":"context_entry"}', created_at: 3 },
  { role: 'user', content: 'Which ones are in Germany?', created_at: 4 },
  { role: 'assistant', content: 'FrOSCon in Sankt Augustin.', created_at: 5 },
];

describe('recommendation turn context', () => {
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
  it('picks the last assistant response and the user message before it', () => {
    expect(latestTurn(toPreviewMessages(turnMessages))).toEqual({
      userMessage: 'Which ones are in Germany?', assistantResponse: 'FrOSCon in Sankt Augustin.',
    });
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('builds the workflow instruction from title, summary and the latest turn', () => {
    const instruction = buildWorkflowInstruction(
      { action: 'create', title: 'Weekly conference digest', summary: 'Every Monday list new conferences.' },
      { userMessage: 'Which ones are in Germany?', assistantResponse: 'FrOSCon in Sankt Augustin.' },
    );
    expect(instruction).toContain('Create a workflow: Weekly conference digest');
    expect(instruction).toContain('Every Monday list new conferences.');
    expect(instruction).toContain('Which ones are in Germany?');
    expect(instruction).toContain('FrOSCon in Sankt Augustin.');
    expect(buildWorkflowInstruction({ action: 'update', title: 'Digest', summary: 's' }, { userMessage: '', assistantResponse: '' }))
      .toContain('Update this workflow: Digest');
  });
});

describe('recommendation memory drafts', () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor,app-memories.suggestions.billing
  it('requests a billed create draft with the latest turn and opens it unsaved', async () => {
    vi.mocked(chatDB.getMessagesForChat).mockResolvedValue(turnMessages as never);
    const generated = serializeRuleDocument({ title: 'Conference preferences', when_to_use: 'events', body: 'Likes FOSDEM', load_mode: 'ask_first' });
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      title: 'Conference preferences', when_to_use: 'events', body: generated,
    }), { status: 200 }));
    const draft = await requestCreateMemoryDraft('chat-1', { title: 'Conference preferences', summary: 'Open source events' });
    expect(draft).toMatchObject({
      id: NEW_MEMORY_DRAFT_ID, title: 'Conference preferences', memory: 'Likes FOSDEM', load_mode: 'ask_first', is_new: true,
    });
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe(`https://api.test${RECOMMENDATION_DRAFT_WIRE.createDraftPath}`);
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      chat_id: 'chat-1', title: 'Conference preferences', summary: 'Open source events',
      user_message: 'Which ones are in Germany?', assistant_response: 'FrOSCon in Sankt Augustin.',
    });
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.billing
  it('maps insufficient credits and malformed create drafts to typed errors', async () => {
    vi.mocked(chatDB.getMessagesForChat).mockResolvedValue([] as never);
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response('{}', { status: 402 }));
    await expect(requestCreateMemoryDraft('c', { title: 't', summary: 's' })).rejects.toMatchObject({ code: 'insufficient_credits' });
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response('{"body":""}', { status: 200 }));
    await expect(requestCreateMemoryDraft('c', { title: 't', summary: 's' })).rejects.toMatchObject({ code: 'request_failed' });
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('builds unsaved drafts and records the preview-time document as the update base', () => {
    const generated = serializeRuleDocument({ title: 'Tone', when_to_use: 'writing', body: 'Be brief', load_mode: 'ask_first' });
    expect(newMemoryDraft({ body: generated })).toMatchObject({ id: NEW_MEMORY_DRAFT_ID, title: 'Tone', is_new: true });
    const updated = serializeRuleDocument({ title: 'Staging API', when_to_use: 'deploys', body: 'port 8002', load_mode: 'auto_include' });
    const draft = updateMemoryDraft({ id: 'personal:1', source: 'personal', document: memoryDocument }, updated);
    expect(draft).toMatchObject({ id: 'personal:1', memory: 'port 8002', base_document: memoryDocument });
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor,app-memories.suggestions.billing
  it('sends the chat text to the update preview and validates its response', async () => {
    vi.mocked(listPersonalRuleDocuments).mockResolvedValue([{ id: 'personal:1', source: 'personal', document: memoryDocument }]);
    vi.mocked(chatDB.getMessagesForChat).mockResolvedValue([{ role: 'user', content: 'port is 8002', created_at: 1 }] as never);
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ status: 'unchanged' }), { status: 200 }));
    const { result } = await requestUpdatePreview('chat-1', '1');
    expect(result).toEqual({ status: 'unchanged' });
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe(`https://api.test${RECOMMENDATION_DRAFT_WIRE.updatePreviewPath}`);
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      chat_id: 'chat-1', memory_id: 'personal:1', memory_markdown: memoryDocument,
      messages: [{ role: 'user', text: 'port is 8002' }],
    });
    expect(parseUpdatePreviewResponse({ status: 'updated', body: 'new' })).toEqual({ status: 'updated', body: 'new' });
    expect(() => parseUpdatePreviewResponse({ status: 'updated' })).toThrow(RecommendationDraftError);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('reports a missing memory as a typed error', async () => {
    vi.mocked(listPersonalRuleDocuments).mockResolvedValue([]);
    await expect(requestUpdatePreview('c', 'missing')).rejects.toMatchObject({ code: 'memory_not_found' });
  });
});
