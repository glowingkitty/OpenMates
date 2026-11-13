// contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../db', () => ({ chatDB: { getMessagesForChat: vi.fn() } }));
vi.mock('../ruleDocumentService', () => ({ listPersonalRuleDocuments: vi.fn() }));
vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));

import {
  NETWORK_RETRY_DELAY_MS, NEW_MEMORY_DRAFT_ID, RECOMMENDATION_DRAFT_WIRE, RecommendationDraftError, buildWorkflowInstruction,
  latestTurn, newMemoryDraft, parseCreateDraftResponse, parseUpdatePreviewResponse, previewMessageText, requestCreateMemoryDraft,
  latestTurnMessageId, loadRecommendationTurn, requestUpdatePreview, toPreviewMessages, updateMemoryDraft,
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
      request_id: expect.stringMatching(/\S/),
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

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.billing
  it('retries once when the request gets no response and then succeeds', async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(chatDB.getMessagesForChat).mockResolvedValue(turnMessages as never);
      const generated = serializeRuleDocument({ title: 'Conference preferences', when_to_use: 'events', body: 'Likes FOSDEM', load_mode: 'ask_first' });
      const fetchSpy = vi.spyOn(globalThis, 'fetch')
        .mockRejectedValueOnce(new TypeError('Load failed'))
        .mockResolvedValueOnce(new Response(JSON.stringify({ title: 'Conference preferences', when_to_use: 'events', body: generated }), { status: 200 }));
      const pending = requestCreateMemoryDraft('chat-1', { title: 'Conference preferences', summary: 'Open source events' });
      await vi.advanceTimersByTimeAsync(NETWORK_RETRY_DELAY_MS);
      await expect(pending).resolves.toMatchObject({ id: NEW_MEMORY_DRAFT_ID, is_new: true });
      expect(fetchSpy).toHaveBeenCalledTimes(2);
      // Same request_id on both attempts: the server bills one user action at most once.
      const ids = fetchSpy.mock.calls.map(call => JSON.parse(String((call[1] as RequestInit).body)).request_id);
      expect(ids[0]).toMatch(/\S/);
      expect(ids[1]).toBe(ids[0]);
    } finally {
      vi.useRealTimers();
    }
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.billing
  it('reports a connection problem after the single retry also gets no response', async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(chatDB.getMessagesForChat).mockResolvedValue([] as never);
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Load failed'));
      const pending = requestCreateMemoryDraft('c', { title: 't', summary: 's' });
      const outcome = expect(pending).rejects.toMatchObject({ code: 'network_unavailable' });
      await vi.advanceTimersByTimeAsync(NETWORK_RETRY_DELAY_MS);
      await outcome;
      expect(fetchSpy).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.billing
  it('reports a connection problem when the server refuses the retry as an already received request', async () => {
    vi.mocked(chatDB.getMessagesForChat).mockResolvedValue([] as never);
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"detail":"duplicate_request"}', { status: 409 }));
    await expect(requestCreateMemoryDraft('c', { title: 't', summary: 's' })).rejects.toMatchObject({ code: 'network_unavailable' });
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.billing
  it('never retries an HTTP error response, since the server may already have billed it', async () => {
    vi.mocked(chatDB.getMessagesForChat).mockResolvedValue([] as never);
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 502 }));
    await expect(requestCreateMemoryDraft('c', { title: 't', summary: 's' })).rejects.toMatchObject({ code: 'request_failed' });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
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
      request_id: expect.stringMatching(/\S/),
    });
    expect(parseUpdatePreviewResponse({ status: 'updated', body: 'new' })).toEqual({ status: 'updated', body: 'new' });
    expect(() => parseUpdatePreviewResponse({ status: 'updated' })).toThrow(RecommendationDraftError);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('puts the app chosen by the create-draft response into the draft and drops malformed ids', async () => {
    const generated = serializeRuleDocument({ title: 'Trips', when_to_use: 'travel', body: 'Window seat', load_mode: 'ask_first' });
    expect(parseCreateDraftResponse({ body: generated, app_id: 'travel' })).toEqual({ body: generated, app_id: 'travel' });
    expect(parseCreateDraftResponse({ body: generated, app_id: 'Not An App' })).toEqual({ body: generated });
    expect(parseCreateDraftResponse({ body: generated, app_id: null })).toEqual({ body: generated });
    vi.mocked(chatDB.getMessagesForChat).mockResolvedValue(turnMessages as never);
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ body: generated, app_id: 'travel' }), { status: 200 }));
    const draft = await requestCreateMemoryDraft('chat-1', { title: 'Trips', summary: 'seat' });
    expect(draft).toMatchObject({ id: NEW_MEMORY_DRAFT_ID, title: 'Trips', app_id: 'travel', is_new: true });
    expect(newMemoryDraft({ body: generated })).not.toHaveProperty('app_id');
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
  it('reports a missing memory as a typed error', async () => {
    vi.mocked(listPersonalRuleDocuments).mockResolvedValue([]);
    await expect(requestUpdatePreview('c', 'missing')).rejects.toMatchObject({ code: 'memory_not_found' });
  });
});

describe('recommendation turn billing link', () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  const linkedTurn = [
    { role: 'user', content: 'Find open source conferences', created_at: 1, message_id: 'chat1-u1' },
    { role: 'assistant', content: 'FOSDEM is in Brussels.', created_at: 2, message_id: 'chat1-a1', user_message_id: 'chat1-u1' },
    { role: 'user', content: 'Which ones are in Germany?', created_at: 4, message_id: 'chat1-u2' },
    { role: 'assistant', content: 'FrOSCon in Sankt Augustin.', created_at: 5, message_id: 'chat1-a2' },
  ];

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.billing
  it('picks the user message id of the latest turn, as a chat turn usage row does', async () => {
    expect(latestTurnMessageId(linkedTurn)).toBe('chat1-u2');
    expect(latestTurnMessageId([...linkedTurn.slice(0, 3), { ...linkedTurn[3], user_message_id: 'chat1-linked' }])).toBe('chat1-linked');
    expect(latestTurnMessageId([{ role: 'user', content: 'only a question', created_at: 1, message_id: 'u' }])).toBeUndefined();
    vi.mocked(chatDB.getMessagesForChat).mockResolvedValue(linkedTurn as never);
    expect(await loadRecommendationTurn('chat-1')).toEqual({
      userMessage: 'Which ones are in Germany?', assistantResponse: 'FrOSCon in Sankt Augustin.', messageId: 'chat1-u2',
    });
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.suggestions.billing
  it('sends message_id with both billed draft requests when the turn is known', async () => {
    vi.mocked(chatDB.getMessagesForChat).mockResolvedValue(linkedTurn as never);
    vi.mocked(listPersonalRuleDocuments).mockResolvedValue([{ id: 'personal:1', source: 'personal', document: memoryDocument }]);
    const generated = serializeRuleDocument({ title: 'Conferences', when_to_use: 'events', body: 'Likes FOSDEM', load_mode: 'ask_first' });
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ body: generated }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'unchanged' }), { status: 200 }));
    await requestCreateMemoryDraft('chat-1', { title: 'Conferences', summary: 'events' });
    await requestUpdatePreview('chat-1', '1');
    const bodies = fetchSpy.mock.calls.map(call => JSON.parse(String((call[1] as RequestInit).body)));
    expect(bodies.map(body => body.message_id)).toEqual(['chat1-u2', 'chat1-u2']);
  });
});
