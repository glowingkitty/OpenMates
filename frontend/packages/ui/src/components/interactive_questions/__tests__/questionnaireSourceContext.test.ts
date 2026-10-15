import { describe, expect, it, vi } from 'vitest';
import { mount, unmount } from 'svelte';
import { EMBED_SOURCE_CHAT_CONTEXT } from '../../../types/embedFullscreen';
import InteractiveQuestionContainer from '../InteractiveQuestionContainer.svelte';

vi.mock('../renderers/ChoiceQuestion.svelte', async () => import('./QuestionSourceProbe.svelte'));
vi.mock('../renderers/InputQuestion.svelte', async () => import('./QuestionSourceProbe.svelte'));
vi.mock('../renderers/SliderQuestion.svelte', async () => import('./QuestionSourceProbe.svelte'));
vi.mock('../renderers/SwipeQuestion.svelte', async () => import('./QuestionSourceProbe.svelte'));
vi.mock('../renderers/RatingQuestion.svelte', async () => import('./QuestionSourceProbe.svelte'));
vi.mock('../../../services/db', () => ({ chatDB: { getMessagesForChat: vi.fn(async () => []) } }));
vi.mock('../../../services/chatSyncService', () => ({ chatSyncService: { addEventListener: vi.fn(), removeEventListener: vi.fn() } }));
vi.mock('../../../stores/activeChatStore', () => ({ activeChatStore: { get: () => 'unrelated-active-chat' } }));

// contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
describe('questionnaire option preview source', () => {
  it.each([
    ['example-vegetarian-recipes-from-fridge', 'different-source', 'example-vegetarian-recipes-from-fridge'],
    ['private-chat-source', 'different-source', 'private-chat-source'],
    ['', 'inherited-source', 'inherited-source'],
    ['', null, 'none'],
  ])('keeps supplied %s and inherited %s source scoped', async (chatId, inherited, expected) => {
    const target = document.createElement('div');
    document.body.append(target);
    const component = mount(InteractiveQuestionContainer, {
      target,
      props: { chatId, payload: { id: 'recipe', type: 'choice', question: 'Pick', options: [{ id: 'salad', text: 'Salad' }] } },
      context: new Map([[EMBED_SOURCE_CHAT_CONTEXT, { chatId: inherited }]]),
    });
    await vi.waitFor(() => expect(target.querySelector('[data-testid="source-chat"]')?.textContent).toBe(expected));
    await unmount(component);
    target.remove();
  });
});
