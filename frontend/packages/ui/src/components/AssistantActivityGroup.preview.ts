// Fictional local state only; no authenticated network requests or inference.
import { embedStore } from '../services/embedStore';
import { chatDB } from '../services/db';
import { activeChatStore } from '../stores/activeChatStore';
import { activeChatFocusStore } from '../stores/activeChatFocusStore';
import { pendingFocusActivationStore } from '../stores/pendingFocusActivationStore';
import type { AssistantDocument } from '../message_parsing/assistantActivityRuns';
import { mount, unmount } from 'svelte';
import FocusModeActivationEmbed from './embeds/focus_mode/FocusModeActivationEmbed.svelte';
import { embedRenderers } from './enter_message/extensions/embed_renderers';
import type { EmbedRenderer } from './enter_message/extensions/embed_renderers/types';

const embed = (attrs: Record<string, unknown>) => ({ type: 'paragraph', content: [{ type: 'embed', attrs }] });
const doc = (...attrs: Record<string, unknown>[]): AssistantDocument => ({ type: 'doc', content: attrs.map(embed) });
const skill = (app: string) => {
  const id = `preview-activity-${app}`;
  embedStore.registerStaticEmbed({ embedId: id, type: 'app-skill-use', appId: app,
    content: JSON.stringify({ type: 'app_skill_use', title: 'Local result', status: 'finished' }) });
  return { type: 'app-skill-use', id, app_id: app, skill_id: app === 'code' ? 'get_docs' : app === 'ai' ? 'ask' : 'search', contentRef: `embed:${id}`, status: 'finished' };
};
const focus = { type: 'focus-mode-activation', id: 'preview-completed-focus', app_id: 'web', focus_id: 'web-research', focus_mode_name: 'Deep research', status: 'finished' };
const batch = { type: 'sub-chat-batch', id: 'preview-completed-batch', parentChatId: 'example-us-egg-prices-deep', status: 'finished',
  subChatIds: [1, 2, 3].map((n) => `example-us-egg-prices-deep-sub-chat-${n}`) };
const liveChatId = 'preview-live-activity-parent';
const liveFocus = { ...focus, id: 'preview-live-focus' };
const projectFocus = { ...focus, id: 'preview-project-focus-activation', focus_id: 'project-preview-activity',
  focus_mode_name: 'Preview project', status: 'finished' };
const projectFocusId = String(projectFocus.id);
const projectFocusModeId = String(projectFocus.focus_id);
let remountProjectCard: (() => void) | undefined;

// The exact fictional ID uses the real card with a local accept callback. Other
// focus embeds still use the production renderer; this preview never calls Project APIs.
if (typeof window !== 'undefined') {
  const original = embedRenderers['focus-mode-activation'];
  const mounted = new WeakMap<HTMLElement, ReturnType<typeof mount>>();
  const previewRenderer: EmbedRenderer = {
    type: 'focus-mode-activation',
    render(context) {
      if (context.attrs.id !== projectFocusId) return original.render(context);
      const previous = mounted.get(context.content);
      if (previous) void unmount(previous);
      context.content.replaceChildren();
      const component = mount(FocusModeActivationEmbed, { target: context.content, props: {
        id: projectFocusId, focusId: projectFocusModeId, appId: 'web', focusModeName: 'Preview project',
        chatId: liveChatId, alreadyActive: false,
        onAcceptProject: async () => {
          document.body.dataset.projectAcceptCount = String(Number(document.body.dataset.projectAcceptCount ?? 0) + 1);
          activeChatFocusStore.setActiveFocus(liveChatId, projectFocusModeId);
        },
      } });
      mounted.set(context.content, component);
      remountProjectCard = () => { void previewRenderer.render(context); };
    },
    toMarkdown: (attrs) => original.toMarkdown(attrs),
    update: (context) => context.attrs.id === projectFocusId ? false : original.update?.(context) ?? false,
    destroy(context) {
      if (context.attrs.id !== projectFocusId) return original.destroy?.(context);
      const component = mounted.get(context.content);
      if (component) void unmount(component);
      mounted.delete(context.content);
    },
  };
  embedRenderers['focus-mode-activation'] = previewRenderer;
}
// Live lifecycle setup belongs only to live variants, not label/gradient previews.
if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('variant')?.startsWith('live')) {
  activeChatStore.setActiveChat(liveChatId);
  pendingFocusActivationStore.set(String(liveFocus.id), { chatId: liveChatId, focusId: 'web-research', expiresAt: Date.now() + 4000 });
  if (new URLSearchParams(window.location.search).get('variant') === 'liveProjectFocus') {
    pendingFocusActivationStore.set(projectFocusId, { chatId: liveChatId, focusId: projectFocusModeId,
      expiresAt: Date.now() + 60_000, activationPolicy: 'approval' });
  }
}
if (typeof window !== 'undefined') {
  window.document.addEventListener('preview:start-focus-countdown', () => {
    pendingFocusActivationStore.set(String(liveFocus.id), { chatId: liveChatId, focusId: 'web-research', expiresAt: Date.now() + 4000 });
  });
  window.document.addEventListener('preview:activate-focus', () => {
    // Match catalog WebSocket activation: confirmation updates active focus;
    // its transient countdown entry can remain in the pending store.
    activeChatFocusStore.setActiveFocus(liveChatId, 'web-research');
  });
  window.document.addEventListener('preview:deactivate-focus', () => {
    activeChatFocusStore.clearActiveFocus(liveChatId);
  });
  window.document.addEventListener('preview:start-project-countdown', () => {
    pendingFocusActivationStore.clear(projectFocusId);
    pendingFocusActivationStore.set(projectFocusId, { chatId: liveChatId, focusId: projectFocusModeId,
      expiresAt: Date.now() + 4000, activationPolicy: 'delayed' });
    // Install the card's client timer after the test clock has frozen.
    remountProjectCard?.();
  });
}
// Actual IndexedDB child records let the real batch renderer show in-progress cards.
// Public demo IDs use the repository's account-free storage path. Ordinary chat
// creation requires a logged-in account's master key, absent in bare previews.
const liveIds = ['demo-activity-child-1', 'demo-activity-child-2'];
if (typeof window !== 'undefined') {
  window.document.addEventListener('preview:seed-sub-chats', (event) => {
    const detail = (event as CustomEvent<{ completion?: Promise<void> }>).detail;
    const completion = Promise.all(liveIds.map((chatId, index) => chatDB.addChat({
      chat_id: chatId, encrypted_title: null, title: `Research source ${index + 1}`, parent_id: liveChatId,
      is_sub_chat: true, category: 'finance', icon: 'search', messages_v: 1, title_v: 1,
      last_edited_overall_timestamp: 1, unread_count: 0, created_at: 1, updated_at: 1,
    }))).then(() => window.dispatchEvent(new CustomEvent('subChatProgress', { detail: {
      type: 'sub_chat_progress', chat_id: liveChatId, task_id: 'preview-live-task', status: 'running',
    } }))).then(() => undefined);
    if (detail) detail.completion = completion;
    else void completion.catch((error) => console.error('[Activity preview] Failed to seed sub-chats:', error));
  });
}
const liveBatch = { type: 'sub-chat-batch', id: 'preview-live-batch', parentChatId: liveChatId,
  batchId: 'preview-live-batch', contentRef: 'sub-chat-batch:preview-live-batch',
  parentMessageId: 'preview-live-task', taskId: 'preview-live-task', status: 'processing', subChatIds: liveIds };

export default { document: doc(skill('code')), appIds: ['code'] };
export const variants = {
  thinking: { document: doc({ type: 'app-skill-use-group', id: 'preview-thinking-skills', groupedItems: [skill('web'), skill('news'), skill('images')] }), appIds: ['web', 'news', 'images'], thinkingContent: Array.from({ length: 18 }, (_, i) => `Reasoning line ${i + 1}.`).join('\n\n') },
  streamingThinking: { document: doc({ type: 'app-skill-use-group', id: 'preview-thinking-skills', groupedItems: [skill('web'), skill('news'), skill('images')] }), appIds: ['web', 'news', 'images'], thinkingContent: Array.from({ length: 18 }, (_, i) => `Reasoning line ${i + 1}.`).join('\n\n'), thinkingStreaming: true, active: true },
  multiple: { document: doc(skill('web'), skill('news'), skill('images')), appIds: ['web', 'news', 'images'] },
  gradients: { document: doc(skill('code'), skill('events'), skill('ai')), appIds: ['code', 'events', 'ai'] },
  focusSubChats: { document: doc(focus, batch), appIds: [], chatId: 'example-us-egg-prices-deep' },
  liveFocus: { document: doc(liveFocus), appIds: [], chatId: liveChatId, active: true },
  liveProjectFocus: { document: doc(projectFocus), appIds: [], chatId: liveChatId, active: true },
  liveSubChats: { document: doc(liveBatch), appIds: [], chatId: liveChatId, active: true },
  liveFocusAndSubChats: { document: doc(liveFocus, liveBatch), appIds: [], chatId: liveChatId, active: true },
};
