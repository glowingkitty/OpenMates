<!--
  AssistantActivityGroup.svelte
  Shows one source-position run of assistant skill calls and, at most once,
  the response-wide visible thinking stream when no per-cycle anchors exist.
  Active work remains open; completed work collapses into an accessible summary.
  The expandable body keeps real embed nodes, links, and fullscreen actions alive.
  No elapsed time is shown without a measured duration supplied by the response.
-->
<script lang="ts">
  import { onMount, onDestroy, type Snippet } from 'svelte';
  import ReadOnlyMessage from './ReadOnlyMessage.svelte';
  import Icon from './Icon.svelte';
  import ThinkingSection from './ThinkingSection.svelte';
  import { appSkillsStore } from '../stores/appSkillsStore';
  import { pendingFocusActivationStore } from '../stores/pendingFocusActivationStore';
  import { activeChatFocusStore } from '../stores/activeChatFocusStore';
  import { chatDB } from '../services/db';
  import { LOCAL_CHAT_LIST_CHANGED_EVENT } from '../services/drafts/draftConstants';
  import { loadSubChatPreviews } from '../services/subChatPreviewService';
  import { embedAvailabilityVersion, embedStore } from '../services/embedStore';
  import { areAssistantSkillsTerminal, assistantSkillRefs } from '../message_parsing/assistantActivityCompletion';
  import { text } from '@repo/ui';
  import { assistantActivityItems, type AssistantDocument } from '../message_parsing/assistantActivityRuns';
  import type { PIIMapping } from '../types/chat';

  let {
    document, appIds = [], thinkingContent = '', thinkingStreaming = false, active = false,
    chatId = undefined, embedUpdateTimestamp = 0, piiMappings = undefined,
    piiRevealed = false, onEmbedClick = undefined,
    workedInSubChats = false, subChatsActive = false, children,
  }: {
    document?: AssistantDocument; appIds?: string[]; thinkingContent?: string; thinkingStreaming?: boolean; active?: boolean;
    chatId?: string; embedUpdateTimestamp?: number; piiMappings?: PIIMapping[];
    piiRevealed?: boolean; onEmbedClick?: (event: CustomEvent) => void;
    workedInSubChats?: boolean; subChatsActive?: boolean; children?: Snippet;
  } = $props();

  let expanded = $state(false);
  let userToggled = $state(false);
  let skillsComplete = $state(false);
  let checkedRunSignature = '';
  const items = $derived(assistantActivityItems(document));
  const focuses = $derived(items.filter((item) => item.type === 'focus-mode-activation'));
  const batches = $derived(items.filter((item) => item.type === 'sub-chat-batch'));
  const skillRefSignature = $derived(JSON.stringify(assistantSkillRefs(document)));
  const hasSkills = $derived(JSON.parse(skillRefSignature).length > 0);
  let batchRefresh = $state(0);
  let batchStatuses = $state<Record<string, string>>({});
  let lingeringFocusIds = $state<string[]>([]);
  let rejectedFocusIds = $state<string[]>([]);
  const observedActivations = new Set<string>();
  const liveFocusIds = new Set<string>();
  const terminalChildIds = new Set<string>();
  const activationTimers = new Set<ReturnType<typeof setTimeout>>();

  function pendingForFocus(item: Record<string, unknown>) {
    const pending = $pendingFocusActivationStore[String(item.id)];
    return pending?.chatId === chatId && pending.focusId === item.focus_id ? pending : undefined;
  }
  function focusPending(item: Record<string, unknown>): boolean {
    const pending = pendingForFocus(item);
    const focusId = String(item.focus_id);
    // Project acceptance runs in the mounted card at the deadline. Keep a live
    // request mounted until confirmation, without replaying expired history.
    const liveProjectRequest = focusId.startsWith('project-') && !focusId.startsWith('project-focus:') &&
      (pending?.activationPolicy ?? 'delayed') === 'delayed' && liveFocusIds.has(String(item.id));
    return !!pending && !pending.confirmed &&
      (liveProjectRequest || (!pending.expired && pending.expiresAt > Date.now()));
  }
  function focusOpen(item: Record<string, unknown>): boolean {
    if (rejectedFocusIds.includes(String(item.id))) return false;
    const pending = pendingForFocus(item);
    return focusPending(item) || lingeringFocusIds.includes(String(item.id)) ||
      (active && !pending?.confirmed && !pending?.expired && !observedActivations.has(String(item.id)) &&
        $activeChatFocusStore[chatId ?? ''] !== item.focus_id);
  }
  function batchOpen(item: Record<string, unknown>): boolean {
    const status = batchStatuses[String(item.id)] ?? item.status;
    return !['finished', 'completed', 'error', 'failed', 'cancelled', 'stopped'].includes(String(status));
  }

  $effect(() => {
    // Only a live activation gets the one-second acknowledgement. History never replays it.
    for (const item of focuses) {
      const id = String(item.id);
      const confirmed = pendingForFocus(item)?.confirmed || (!!chatId && $activeChatFocusStore[chatId] === item.focus_id);
      // A remounted history row already knows this activation was settled.
      if (confirmed && !liveFocusIds.has(id)) { observedActivations.add(id); continue; }
      if (active || focusPending(item)) liveFocusIds.add(id);
      if (!confirmed || !liveFocusIds.has(id) || observedActivations.has(id)) continue;
      observedActivations.add(id);
      lingeringFocusIds = [...lingeringFocusIds, id];
      const timer = setTimeout(() => {
        lingeringFocusIds = lingeringFocusIds.filter((value) => value !== id);
        activationTimers.delete(timer);
      }, 1000);
      activationTimers.add(timer);
    }
  });
  onDestroy(() => { activationTimers.forEach(clearTimeout); });

  const batchSignature = $derived(JSON.stringify(batches));
  $effect(() => {
    void batchRefresh;
    const currentBatches = JSON.parse(batchSignature) as Array<Record<string, unknown>>;
    const parentId = chatId;
    if (!parentId) return;
    let current = true;
    for (const item of currentBatches) {
      const ids = Array.isArray(item.subChatIds) ? item.subChatIds as string[] : [];
      if (!ids.length || !batchOpen(item)) continue;
      void loadSubChatPreviews(parentId, { subChatIds: ids, forceRefresh: true }).then(async (children) => {
        if (children.length !== ids.length) return;
        const terminal = await Promise.all(children.map(async (child) => {
          if (child.previewSummary || terminalChildIds.has(child.chat_id)) return true;
          // A failed or empty completed response may have no display summary.
          const messages = await chatDB.getMessagesForChat(child.chat_id);
          const last = messages.at(-1);
          return last?.role === 'assistant' && ['synced', 'failed'].includes(last.status);
        }));
        if (current && terminal.every(Boolean)) batchStatuses = { ...batchStatuses, [String(item.id)]: 'completed' };
      }).catch((error) => { console.error('[AssistantActivityGroup] Failed to resolve sub-chat completion:', error); });
    }
    return () => { current = false; };
  });
  onMount(() => {
    const handleListChange = (event: Event) => {
      const detail = (event as CustomEvent<{ chat_id?: string; parent_id?: string }>).detail;
      const childIds = batches.flatMap((item) => Array.isArray(item.subChatIds) ? item.subChatIds as string[] : []);
      if (!detail || detail.chat_id === chatId || detail.parent_id === chatId || childIds.includes(detail.chat_id ?? '')) batchRefresh += 1;
    };
    const handleChildCompleted = (event: Event) => {
      const detail = (event as CustomEvent<{ parent_id?: string; chat_id?: string }>).detail;
      if (detail?.parent_id !== chatId || !detail.chat_id) return;
      terminalChildIds.add(detail.chat_id);
      for (const item of batches) {
        const ids = Array.isArray(item.subChatIds) ? item.subChatIds as string[] : [];
        if (ids.length && ids.every((id) => terminalChildIds.has(id))) batchStatuses = { ...batchStatuses, [String(item.id)]: 'completed' };
      }
    };
    const handleProgress = (event: Event) => {
      const detail = (event as CustomEvent<Record<string, unknown>>).detail;
      if (!detail || detail.chat_id !== chatId || typeof detail.status !== 'string') return;
      const matching = batches.filter((item) => detail.batch_id
        ? detail.batch_id === item.id
        : (detail.task_id && detail.task_id === item.taskId) || (detail.message_id && detail.message_id === item.parentMessageId));
      // Legacy task-level progress cannot identify one of several batches.
      if (matching.length === 1) batchStatuses = { ...batchStatuses, [String(matching[0].id)]: detail.status };
      batchRefresh += 1;
    };
    const handleRejected = (event: Event) => {
      const detail = (event as CustomEvent<{ embedId?: string; chatId?: string }>).detail;
      if (detail?.chatId === chatId && detail.embedId) rejectedFocusIds = [...rejectedFocusIds, detail.embedId];
    };
    window.addEventListener(LOCAL_CHAT_LIST_CHANGED_EVENT, handleListChange);
    window.addEventListener('subChatProgress', handleProgress);
    window.addEventListener('subChatCompleted', handleChildCompleted);
    window.document.addEventListener('focusModeRejected', handleRejected);
    return () => {
      window.removeEventListener(LOCAL_CHAT_LIST_CHANGED_EVENT, handleListChange);
      window.removeEventListener('subChatProgress', handleProgress);
      window.removeEventListener('subChatCompleted', handleChildCompleted);
      window.document.removeEventListener('focusModeRejected', handleRejected);
    };
  });

  $effect(() => {
    if (!active || !hasSkills) { skillsComplete = false; checkedRunSignature = ''; return; }
    const refs = JSON.parse(skillRefSignature) as string[];
    void $embedAvailabilityVersion;
    void embedUpdateTimestamp;
    const runSignature = JSON.stringify([chatId, refs]);
    if (runSignature !== checkedRunSignature) { skillsComplete = false; checkedRunSignature = runSignature; }
    let current = true;
    void areAssistantSkillsTerminal(refs, (ref) => embedStore.getRawEntry(ref)).then((complete) => {
      if (current) skillsComplete = complete;
    }).catch(() => { if (current) skillsComplete = false; });
    return () => { current = false; };
  });
  const groupActive = $derived(thinkingStreaming || (active && hasSkills && !skillsComplete) || focuses.some(focusOpen) ||
    batches.some(batchOpen) || subChatsActive || (active && !items.length && !workedInSubChats));
  $effect(() => { if (!userToggled) expanded = groupActive; });
  const updatedDocument = $derived(document ? { ...document, content: document.content.map((node) => {
    const item = assistantActivityItems({ type: 'doc', content: [node] })[0];
    const status = item && batchStatuses[String(item.id)];
    if (item?.type !== 'sub-chat-batch' || !status || !Array.isArray(node.content)) return node;
    const terminalStatus = ['completed', 'finished'].includes(status) ? 'finished'
      : ['failed', 'error'].includes(status) ? 'error' : ['cancelled', 'stopped'].includes(status) ? 'cancelled' : 'processing';
    return { ...node, content: [{ ...(node.content[0] as Record<string, unknown>), attrs: { ...item, status: terminalStatus } }] };
  }) } : document);
  // While other work is active, settled focus acknowledgements already leave the full-size area.
  const visibleDocument = $derived(groupActive && !userToggled && updatedDocument ? {
    ...updatedDocument, content: updatedDocument.content.filter((node) => {
      const first = assistantActivityItems({ type: 'doc', content: [node] })[0];
      if (first?.type === 'focus-mode-activation') return focusOpen(first);
      if (first?.type === 'sub-chat-batch') return batchOpen(first);
      return true;
    }),
  } : updatedDocument);
  function displayName(key: string, fallback: string): string {
    if (!key || !key.includes('.')) return fallback;
    const translated = $text(key);
    return translated && !translated.startsWith('[T:') && translated !== key ? translated : fallback;
  }
  const appNames = $derived(appIds.map((id) => {
    const app = appSkillsStore.getApp(id);
    return displayName(app?.name_translation_key || '', app?.name || id.replace(/_/g, ' ').replace(/^./, (letter) => letter.toUpperCase()));
  }));
  const appList = $derived(appNames.length > 1
    ? $text('chat.response_activity.list_last', { values: { items: appNames.slice(0, -1).join(', '), last: appNames.at(-1)! } })
    : appNames[0] ?? '');
  const appIcons = $derived(appIds.map((id) => ({ id, name: appSkillsStore.getApp(id)?.icon_image?.replace(/\.svg$/i, '') || id })));
  const cancelledFocusIds = $derived(focuses.filter((item) => {
    const pending = pendingForFocus(item);
    return rejectedFocusIds.includes(String(item.id)) || (pending?.activationPolicy === 'approval' && pending.expired && !pending.confirmed);
  }).map((item) => String(item.id)));
  const focusNames = $derived(focuses.filter((item) => !cancelledFocusIds.includes(String(item.id))).map((item) => {
    const fallback = String(item.focus_id ?? '').split('-').slice(1).join(' ').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
    const key = String(item.focus_mode_name ?? fallback);
    return displayName(key, key.includes('.') ? fallback : key);
  }));
  const hasSubChats = $derived(workedInSubChats || batches.length > 0);
  const summary = $derived.by(() => {
    const clauses: string[] = [];
    if (groupActive) {
      if (appNames.length) clauses.push($text(active && !skillsComplete ? (thinkingStreaming ? 'chat.response_activity.thinking_using' : 'chat.response_activity.using')
        : `chat.response_activity.used_${appNames.length === 1 ? 'single' : 'multiple'}`, { values: { apps: appList } }));
      if (focusNames.length) clauses.push($text(focuses.some((item) => focusOpen(item) && $activeChatFocusStore[chatId ?? ''] !== item.focus_id)
        ? 'chat.response_activity.focus_activating' : 'chat.response_activity.focus_activated', { values: { focus: focusNames.join("', '") } }));
      if (hasSubChats) clauses.push($text(subChatsActive || batches.some(batchOpen) ? 'chat.response_activity.sub_chats_working' : 'chat.response_activity.sub_chats'));
      if (clauses.length) return clauses.join('. ');
    }
    if (appNames.length) clauses.push($text(`chat.response_activity.${thinkingContent ? 'thought_used' : 'used'}_${appNames.length === 1 ? 'single' : 'multiple'}`, { values: { apps: appList } }));
    if (focusNames.length) clauses.push($text(hasSubChats ? 'chat.response_activity.focus_sub_chats' : 'chat.response_activity.focus_activated', { values: { focus: focusNames.join("', '") } }));
    else if (hasSubChats) clauses.push($text('chat.response_activity.sub_chats'));
    if (clauses.length) return clauses.join('. ');
    if (cancelledFocusIds.length) return $text('chat.response_activity.focus_cancelled');
    return $text(groupActive ? 'chat.thinking.header_streaming' : 'chat.thinking.header_done');
  });
</script>

<div class="assistant-activity-group" data-testid="assistant-activity-group" class:active={groupActive}>
  <button type="button" class="activity-summary" data-testid="assistant-activity-toggle"
    aria-expanded={expanded} onclick={() => { expanded = !expanded; userToggled = true; }}>
    <span class="activity-icons" aria-hidden="true" data-testid="assistant-activity-icons">
      {#if thinkingContent}
        <span class="activity-app-icon activity-ai-icon" data-testid="assistant-thinking-app-icon"><Icon name="ai" type="app" appId="ai" size="18px" noAnimation noMargin ariaHidden /></span>
      {/if}
      {#if appIcons.length}
        {#each appIcons.slice(0, 4) as app (app.id)}
          <span class="activity-app-icon" data-testid="assistant-skill-app-icon"><Icon name={app.name} type="app" appId={app.id} size="18px" noAnimation noMargin ariaHidden /></span>
        {/each}
      {:else if !thinkingContent && !focuses.length && !hasSubChats}
        <Icon name="reasoning" size="16px" noAnimation noMargin ariaHidden />
      {/if}
      {#each focuses as focus (String(focus.id))}
        <span class="activity-app-icon" data-testid="assistant-focus-app-icon"><Icon name={appSkillsStore.getApp(String(focus.app_id))?.icon_image?.replace(/\.svg$/i, '') || String(focus.app_id)} type="app" appId={String(focus.app_id)} size="18px" noAnimation noMargin ariaHidden /></span>
      {/each}
      {#if hasSubChats}
        <span class="activity-app-icon" data-testid="assistant-sub-chats-icon"><Icon name="chat" type="app" appId="ai" size="18px" noAnimation noMargin ariaHidden /></span>
      {/if}
    </span>
    <span class="summary-text">{summary}</span>
    <span class="activity-arrow" class:expanded aria-hidden="true"></span>
  </button>
  {#if expanded}
    <div class="activity-body" data-testid="assistant-activity-body">
      {#if thinkingContent || thinkingStreaming}
        <div class="response-thinking" data-testid="assistant-response-thinking">
          <div class="response-thinking-label">{$text('chat.response_activity.response_thinking')}</div>
          <ThinkingSection {thinkingContent} isStreaming={thinkingStreaming} {chatId} {piiMappings} {piiRevealed} />
        </div>
      {/if}
      {#if visibleDocument?.content.length}
        <ReadOnlyMessage content={visibleDocument} role="assistant" {chatId} isStreaming={groupActive}
          _embedUpdateTimestamp={embedUpdateTimestamp} {piiMappings} {piiRevealed}
          on:message-embed-click={onEmbedClick} />
      {/if}
      {@render children?.()}
    </div>
  {/if}
</div>

<style>
  .assistant-activity-group { margin-block: var(--spacing-2); border-radius: var(--radius-4); overflow: hidden; }
  .activity-summary { display: flex; align-items: center; gap: var(--spacing-2); width: 100%; min-height: 30px; padding: var(--spacing-1) var(--spacing-3); border: 0; border-radius: var(--radius-4); background: var(--color-grey-10); color: var(--color-font-primary); font: inherit; font-size: var(--font-size-small); text-align: start; cursor: pointer; }
  .activity-summary:hover { background: var(--color-grey-20); }
  .activity-summary:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: -2px; }
  .activity-icons { display: inline-flex; align-items: center; flex: 0 0 auto; min-width: 16px; }
  .activity-app-icon { display: inline-flex; align-items: center; justify-content: center; flex: 0 0 22px; box-sizing: border-box; width: 22px; height: 22px; aspect-ratio: 1; border: 2px solid var(--color-grey-0); border-radius: 50%; overflow: hidden; }
  .activity-app-icon :global(.icon) { box-sizing: border-box; border-radius: 50% !important; }
  .activity-app-icon + .activity-app-icon { margin-inline-start: -6px; }
  .summary-text { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .activity-arrow { width: 8px; height: 8px; border-right: 2px solid currentColor; border-bottom: 2px solid currentColor; transform: rotate(45deg); margin-inline-start: auto; flex: 0 0 auto; transition: transform var(--duration-fast) var(--easing-default); }
  .activity-arrow.expanded { transform: rotate(225deg); }
  .activity-body { padding: var(--spacing-2) var(--spacing-4) var(--spacing-4); background: var(--color-grey-10); }
  .response-thinking { margin-block-end: var(--spacing-3); color: var(--color-grey-70); }
  .response-thinking-label { font-size: var(--font-size-small); font-weight: 600; margin-block-end: var(--spacing-2); }
  @media (prefers-reduced-motion: reduce) { .activity-arrow { transition: none; } }
</style>
