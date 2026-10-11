<!--
  AssistantActivityGroup.svelte
  Shows one source-position run of assistant skill calls and, at most once,
  the response-wide visible thinking stream when no per-cycle anchors exist.
  Active work remains open; completed work collapses into an accessible summary.
  The expandable body keeps real embed nodes, links, and fullscreen actions alive.
  No elapsed time is shown without a measured duration supplied by the response.
-->
<script lang="ts">
  import ReadOnlyMessage from './ReadOnlyMessage.svelte';
  import Icon from './Icon.svelte';
  import { parse_message } from '../message_parsing/parse_message';
  import { appSkillsStore } from '../stores/appSkillsStore';
  import { embedAvailabilityVersion, embedStore } from '../services/embedStore';
  import { areAssistantSkillsTerminal, assistantSkillRefs } from '../message_parsing/assistantActivityCompletion';
  import { text } from '@repo/ui';
  import type { AssistantDocument } from '../message_parsing/assistantActivityRuns';
  import type { PIIMapping } from '../types/chat';

  let {
    document, appIds = [], thinkingContent = '', active = false,
    chatId = undefined, embedUpdateTimestamp = 0, piiMappings = undefined,
    piiRevealed = false, onEmbedClick = undefined,
  }: {
    document?: AssistantDocument;
    appIds?: string[];
    thinkingContent?: string;
    active?: boolean;
    chatId?: string;
    embedUpdateTimestamp?: number;
    piiMappings?: PIIMapping[];
    piiRevealed?: boolean;
    onEmbedClick?: (event: CustomEvent) => void;
  } = $props();

  let expanded = $state(false);
  let userToggled = $state(false);
  let skillsComplete = $state(false);
  let checkedRunSignature = '';
  const groupActive = $derived(active && !skillsComplete);
  const skillRefSignature = $derived(JSON.stringify(assistantSkillRefs(document)));
  $effect(() => {
    if (!active) {
      skillsComplete = false;
      checkedRunSignature = '';
      return;
    }
    const refs = JSON.parse(skillRefSignature) as string[];
    // Only the active run checks storage. Prose changes keep this signature stable.
    void $embedAvailabilityVersion;
    const runSignature = JSON.stringify([chatId, refs]);
    if (runSignature !== checkedRunSignature) {
      skillsComplete = false;
      checkedRunSignature = runSignature;
    }
    let current = true;
    void areAssistantSkillsTerminal(refs, (ref) => embedStore.getRawEntry(ref)).then((complete) => {
      if (current) skillsComplete = complete;
    }).catch(() => { if (current) skillsComplete = false; });
    return () => { current = false; };
  });
  $effect(() => {
    if (userToggled) return;
    expanded = groupActive;
  });
  const thinkingDoc = $derived(thinkingContent
    ? parse_message(thinkingContent, 'read', { unifiedParsingEnabled: true })
    : null);
  const appNames = $derived(appIds.map((id) => {
    const app = appSkillsStore.getApp(id);
    const translated = app?.name_translation_key ? $text(app.name_translation_key) : '';
    return translated && translated !== app?.name_translation_key
      ? translated : (app?.name || id.replace(/_/g, ' ').replace(/^./, (letter) => letter.toUpperCase()));
  }));
  const appList = $derived(appNames.join(', '));
  const appIcons = $derived(appIds.map((id) => ({
    id, name: appSkillsStore.getApp(id)?.icon_image?.replace(/\.svg$/i, '') || id,
  })));
  const summary = $derived(appNames.length
    ? $text(thinkingContent ? 'chat.response_activity.thinking_using' : 'chat.response_activity.using', { values: { apps: appList } })
    : $text(groupActive ? 'chat.thinking.header_streaming' : 'chat.thinking.header_done'));
</script>

<div class="assistant-activity-group" data-testid="assistant-activity-group" class:active={groupActive}>
  <button type="button" class="activity-summary" data-testid="assistant-activity-toggle"
    aria-expanded={expanded} onclick={() => { expanded = !expanded; userToggled = true; }}>
    <span class="activity-icons" aria-hidden="true" data-testid="assistant-activity-icons">
      {#if thinkingContent}
        <span class="activity-app-icon activity-ai-icon" data-testid="assistant-thinking-app-icon"><Icon name="ai" type="app" size="18px" noAnimation noMargin ariaHidden /></span>
      {/if}
      {#if appIcons.length}
        {#each appIcons.slice(0, 4) as app (app.id)}
          <span class="activity-app-icon" data-testid="assistant-skill-app-icon"><Icon name={app.name} type="app" size="18px" noAnimation noMargin ariaHidden /></span>
        {/each}
      {:else if !thinkingContent}
        <Icon name="reasoning" size="16px" noAnimation noMargin ariaHidden />
      {/if}
    </span>
    <span>{summary}</span>
    <span class="activity-arrow" class:expanded aria-hidden="true"></span>
  </button>
  {#if expanded}
    <div class="activity-body" data-testid="assistant-activity-body">
      {#if thinkingDoc}
        <div class="response-thinking" data-testid="assistant-response-thinking">
          <div class="response-thinking-label">{$text('chat.response_activity.response_thinking')}</div>
          <ReadOnlyMessage content={thinkingDoc} role="assistant" {chatId} isStreaming={groupActive}
            {piiMappings} {piiRevealed} />
        </div>
      {/if}
      {#if document?.content.length}
        <ReadOnlyMessage content={document} role="assistant" {chatId} isStreaming={groupActive}
          _embedUpdateTimestamp={embedUpdateTimestamp} {piiMappings} {piiRevealed}
          on:message-embed-click={onEmbedClick} />
      {/if}
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
  .activity-arrow { width: 8px; height: 8px; border-inline-end: 2px solid currentColor; border-block-end: 2px solid currentColor; transform: rotate(-45deg); margin-inline-start: auto; flex: 0 0 auto; transition: transform var(--duration-fast) var(--easing-default); }
  .activity-arrow.expanded { transform: rotate(45deg); }
  .activity-body { padding: var(--spacing-2) var(--spacing-4) var(--spacing-4); background: var(--color-grey-10); }
  .response-thinking { margin-block-end: var(--spacing-3); color: var(--color-grey-70); }
  .response-thinking-label { font-size: var(--font-size-small); font-weight: 600; margin-block-end: var(--spacing-2); }
  @media (prefers-reduced-motion: reduce) { .activity-arrow { transition: none; } }
</style>
