import type { Message } from '../types/chat';
import type { TimelineEntry } from '../utils/chatTimeline';
import { piiVisibilityStore } from '../stores/piiVisibilityStore';

export const layout = 'fill';
const entries: TimelineEntry[] = Array.from({ length: 24 }, (_, index) => ({
  message_id: `timeline-user-${index}`, created_at: 1788870532 + index * 10, role: 'user',
}));
const message = (entry: TimelineEntry, assistant: boolean): Message => ({
  ...entry, chat_id: 'preview-timeline', status: 'synced', role: assistant ? 'assistant' : 'user',
  message_id: assistant ? entry.message_id.replace('user', 'assistant') : entry.message_id,
  content: assistant
    ? `Here is the answer to question ${entry.message_id.split('-').pop()}.\n\nThe plan keeps the budget clear and leaves time for the train journey.\n\nThis fourth line should stay clipped.`
    : `Question ${entry.message_id.split('-').pop()}: help me plan the project budget.\n\nInclude the venue, train tickets and preparation.\n\nThis fourth line should stay clipped.`,
});
const onActivate = async (entry: TimelineEntry) => {
  window.dispatchEvent(new CustomEvent('timeline-preview-activated', { detail: entry.message_id }));
};
if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('variant') === 'piiRevealed') {
  piiVisibilityStore.setRevealed('preview-timeline', true);
}
const piiPreview = async (entry: TimelineEntry) => ({
  user: { ...message(entry, false), content: 'Please contact [EMAIL_1_com].',
    pii_mappings: [{ placeholder: '[EMAIL_1_com]', original: 'alex@example.test', type: 'EMAIL' }] },
  assistant: null, pending: false,
});
const props = { entries, contextKey: 'preview-timeline', compressionBoundary: entries[11].created_at,
  currentId: entries[18].message_id, catalogueLoading: false, catalogueIncomplete: false, historical: false,
  onPreview: async (entry: TimelineEntry) => ({ user: message(entry, false), assistant: message(entry, true), pending: false }),
  onActivate, onLoadEarlier: () => {}, onLatest: () => {},
};
export default props;
export const variants = {
  piiHidden: { ...props, onPreview: piiPreview },
  piiRevealed: { ...props, onPreview: piiPreview },
  empty: { ...props, entries: [] },
  dense: { ...props, entries: Array.from({ length: 10000 }, (_, index) => ({
    message_id: `timeline-user-${index}`, created_at: 1788870532 + index * 10, role: 'user',
  })) },
  pending: { ...props, onPreview: async (entry: TimelineEntry) => ({ user: message(entry, false), assistant: null, pending: true }) },
  unavailable: { ...props, onPreview: async () => { throw new Error('Fictional offline section'); },
    onActivate: async () => { throw new Error('Fictional offline section'); } },
};
