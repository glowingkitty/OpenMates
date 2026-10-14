import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getRawEntry: vi.fn(),
  get: vi.fn(),
  decodeToonContent: vi.fn(),
}));

vi.mock('../embedStore', () => ({
  embedStore: { getRawEntry: mocks.getRawEntry, get: mocks.get },
}));
vi.mock('../embedResolver', () => ({ decodeToonContent: mocks.decodeToonContent }));
vi.mock('../../message_parsing/utils', () => ({ computeSHA256: async (value: string) => `hash:${value}` }));

import { projectAnonymousChatHistory } from '../anonymousChatHistory';

const CHAT_ID = 'anonymous-current';
const CODE_ID = 'cbb473d9-7c70-43be-9674-ab59672e0fa9';
const PLOT_ID = 'ead63d25-833d-45a1-9607-6dd8ac03346a';

function reference(type: string, embedId: string): string {
  return `\x60\x60\x60json\n${JSON.stringify({ type, embed_id: embedId })}\n\x60\x60\x60`;
}

function storeEmbed(embedId: string, type: string, content: Record<string, unknown>, chatId = CHAT_ID): void {
  const contentRef = `embed:${embedId}`;
  mocks.getRawEntry.mockImplementation(async (key: string) => key === contentRef
    ? { embed_id: embedId, hashed_chat_id: `hash:${chatId}`, status: 'finished' }
    : null);
  mocks.get.mockImplementation(async (key: string) => key === contentRef
    ? { embed_id: embedId, hashed_chat_id: `hash:${chatId}`, content: JSON.stringify({ type, ...content }) }
    : undefined);
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.getRawEntry.mockResolvedValue(null);
  mocks.get.mockResolvedValue(undefined);
  mocks.decodeToonContent.mockImplementation(async (value: string) => JSON.parse(value));
});

describe('projectAnonymousChatHistory', () => {
  // contract-test: supporting surface=gui.web assertions=billing.anonymous.local-only-content,chats.surface.semantic-parity
  it('restores exact Bash source and repeated refs from one same-chat local embed read', async () => {
    const source = 'echo "${VM_NAME}"\nprintf "%s\\n" "$HOME"';
    storeEmbed(CODE_ID, 'code', { language: 'bash', filename: 'deploy.sh', code: source });
    const ref = reference('code', CODE_ID);

    const projected = await projectAnonymousChatHistory(`Before\n${ref}\nAfter\n${ref}`, CHAT_ID);

    expect(projected).toBe(`Before\n\x60\x60\x60bash:deploy.sh\n${source}\n\x60\x60\x60\nAfter\n\x60\x60\x60bash:deploy.sh\n${source}\n\x60\x60\x60`);
    expect(mocks.getRawEntry).toHaveBeenCalledTimes(1);
    expect(mocks.get).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=billing.anonymous.local-only-content,chats.surface.semantic-parity
  it('uses a longer fence when code itself contains backticks', async () => {
    storeEmbed(CODE_ID, 'code', { language: 'markdown', code: 'show \x60\x60\x60 inline' });

    expect(await projectAnonymousChatHistory(reference('code', CODE_ID), CHAT_ID))
      .toBe('\x60\x60\x60\x60markdown\nshow \x60\x60\x60 inline\n\x60\x60\x60\x60');
  });

  // contract-test: supporting surface=gui.web assertions=billing.anonymous.local-only-content,chats.surface.semantic-parity
  it('restores a plot specification without turning it into code', async () => {
    storeEmbed(PLOT_ID, 'math-plot', { plot_spec: 'f(x)=sin(x)' });

    expect(await projectAnonymousChatHistory(reference('math-plot', PLOT_ID), CHAT_ID))
      .toBe('\x60\x60\x60plot\nf(x)=sin(x)\n\x60\x60\x60');
  });

  // contract-test: supporting surface=gui.web assertions=billing.anonymous.local-only-content,chats.surface.semantic-parity
  it('leaves malformed, foreign-chat, and missing references for the server to strip', async () => {
    const malformed = '\x60\x60\x60json\n{"type":"code","embed_id":"bad","extra":"x"}\n\x60\x60\x60';
    const foreign = reference('code', CODE_ID);
    const missing = reference('math-plot', PLOT_ID);
    storeEmbed(CODE_ID, 'code', { code: 'private foreign content' }, 'anonymous-other');

    const markdown = `${malformed}\n${foreign}\n${missing}`;
    expect(await projectAnonymousChatHistory(markdown, CHAT_ID)).toBe(markdown);
    expect(mocks.get).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=billing.anonymous.local-only-content,chats.surface.semantic-parity
  it('limits reconstruction to twelve references and the API history size', async () => {
    storeEmbed(CODE_ID, 'code', { language: 'txt', code: 'x'.repeat(2_000) });
    const ref = reference('code', CODE_ID);
    const projected = await projectAnonymousChatHistory(Array(13).fill(ref).join('\n'), CHAT_ID);

    expect(projected.length).toBeLessThanOrEqual(20_000);
    expect(projected).toContain(ref);
    expect(projected.match(/\x60\x60\x60txt/g)?.length).toBeLessThanOrEqual(9);
  });
});
