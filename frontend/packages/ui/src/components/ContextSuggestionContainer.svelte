<!-- frontend/packages/ui/src/components/ContextSuggestionContainer.svelte
     Container between the chat history and the follow-up suggestions. Shows at most one
     post-processor suggestion for the chat: a Memory update/create (title + Preview) or a
     Workflow (title + summary + Create). Nothing is saved or generated before the user acts.
     Spec: app-memories.suggestions.post-processor, app-memories.suggestions.billing.
-->
<script lang="ts">
  import { text } from '../i18n/translations';
  import { contextSuggestions, dismissContextSuggestion, isContextSuggestionDismissed } from '../stores/contextSuggestionStore';
  import { memoryDraftSuggestion } from '../stores/memoryDraftSuggestionStore';
  import { settingsDeepLink } from '../stores/settingsDeepLinkStore';
  import { panelState } from '../stores/panelStateStore';
  import { notificationStore } from '../stores/notificationStore';
  import { settingsMenuVisible } from './Settings.svelte';
  import { queueAppsWorkspaceWorkflowHandoff } from '../services/appsWorkspaceChatHandoffService';
  import {
    ContextSuggestionError, newMemoryDraft, requestUpdatePreview, updateMemoryDraft,
  } from '../services/contextSuggestionService';
  import type { ContextSuggestion } from '../services/contextSuggestionWire';

  interface Props { chatId: string }
  let { chatId }: Props = $props();

  let busy = $state(false);
  let upToDateKey = $state<string | null>(null);
  // Bumped on dismissal so the localStorage-backed check re-evaluates.
  let dismissals = $state(0);

  let suggestion = $derived.by((): ContextSuggestion | null => {
    void dismissals;
    const current = $contextSuggestions[chatId] ?? null;
    return current && !isContextSuggestionDismissed(chatId, current) ? current : null;
  });
  let isUpToDate = $derived(suggestion?.kind === 'memory_update' && upToDateKey === `${chatId}:${suggestion.memoryId}`);

  function openMemoryDraft(draft: Parameters<typeof memoryDraftSuggestion.set>[0]): void {
    if (!draft) return;
    memoryDraftSuggestion.set(draft);
    settingsMenuVisible.set(true);
    panelState.openSettings();
    settingsDeepLink.set(`memories/${encodeURIComponent(draft.id)}`);
  }

  function failureMessage(error: unknown): string {
    const code = error instanceof ContextSuggestionError ? error.code : 'request_failed';
    if (code === 'insufficient_credits') return $text('memories.suggestion_insufficient_credits');
    if (code === 'memory_not_found') return $text('memories.suggestion_not_found');
    return $text('memories.suggestion_failed');
  }

  async function preview(): Promise<void> {
    if (!suggestion || busy) return;
    if (suggestion.kind === 'memory_create') {
      // No network call: the body was already generated.
      openMemoryDraft(newMemoryDraft({ title: suggestion.title, body: suggestion.body }));
      return;
    }
    if (suggestion.kind !== 'memory_update') return;
    const { memoryId } = suggestion;
    busy = true;
    try {
      const { document, result } = await requestUpdatePreview(chatId, memoryId);
      if (result.status === 'unchanged') { upToDateKey = `${chatId}:${memoryId}`; return; }
      openMemoryDraft(updateMemoryDraft(document, result.body));
    } catch (error) {
      notificationStore.error(failureMessage(error), 5000);
    } finally { busy = false; }
  }

  async function createWorkflow(): Promise<void> {
    if (!suggestion || suggestion.kind !== 'workflow_create' || busy) return;
    busy = true;
    try {
      // Same path as asking AI to create a workflow from the workspace: the Workflows page consumes it
      // and builds the workflow visibly in the full-screen view.
      await queueAppsWorkspaceWorkflowHandoff({
        text: $text('memories.suggestion_workflow_prompt', { values: { title: suggestion.title, summary: suggestion.summary } }),
      });
    } catch {
      notificationStore.error($text('memories.suggestion_failed'), 5000);
    } finally { busy = false; }
  }

  function dismiss(): void {
    if (!suggestion) return;
    dismissContextSuggestion(chatId, suggestion);
    dismissals++;
  }
</script>

{#if suggestion}
  <div class="context-suggestion" data-testid="context-suggestion" data-kind={suggestion.kind} role="region"
    aria-label={suggestion.title}>
    <div class="text">
      <p class="title" data-testid="context-suggestion-title">
        {#if suggestion.kind === 'memory_update'}
          {$text('memories.suggestion_update', { values: { title: suggestion.title } })}
        {:else if suggestion.kind === 'memory_create'}
          {$text('memories.suggestion_create', { values: { title: suggestion.title } })}
        {:else}
          {suggestion.title}
        {/if}
      </p>
      {#if suggestion.kind === 'workflow_create'}
        <p class="summary" data-testid="context-suggestion-summary">{suggestion.summary}</p>
      {/if}
      {#if busy && suggestion.kind === 'memory_update'}
        <p class="status" role="status" data-testid="context-suggestion-loading">{$text('memories.suggestion_previewing')}</p>
      {:else if isUpToDate}
        <p class="status" role="status" data-testid="context-suggestion-up-to-date">{$text('memories.suggestion_up_to_date')}</p>
      {/if}
    </div>
    <div class="actions">
      {#if suggestion.kind === 'workflow_create'}
        <button type="button" class="primary" data-testid="context-suggestion-create" disabled={busy} onclick={() => void createWorkflow()}>
          {$text('memories.suggestion_workflow_create')}
        </button>
      {:else}
        <button type="button" class="primary" data-testid="context-suggestion-preview" disabled={busy} onclick={() => void preview()}>
          {$text('memories.suggestion_preview')}
        </button>
      {/if}
      <button type="button" class="dismiss" data-testid="context-suggestion-dismiss" aria-label={$text('memories.suggestion_dismiss')} onclick={dismiss}>
        <span class="clickable-icon icon_close" aria-hidden="true"></span>
      </button>
    </div>
  </div>
{/if}

<style>
  .context-suggestion {
    display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-5);
    width: calc(100% - 40px); margin: var(--spacing-4) 20px; box-sizing: border-box;
    padding: var(--spacing-5); border: 1px solid var(--color-grey-25); border-radius: var(--radius-4);
    background: var(--color-grey-10); color: var(--color-font-primary);
  }
  .text { min-width: 0; display: grid; gap: var(--spacing-2); }
  p { margin: 0; overflow-wrap: anywhere; }
  .title { font-weight: 600; }
  .summary, .status { color: var(--color-font-secondary); font-size: var(--font-size-small); }
  .actions { display: flex; align-items: center; gap: var(--spacing-3); flex-shrink: 0; }
  button { min-height: 2.75rem; border-radius: var(--radius-4); cursor: pointer; font: inherit; }
  button:disabled { cursor: default; opacity: 0.65; }
  button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }
  .primary { padding: var(--spacing-3) var(--spacing-6); border: 1px solid var(--color-grey-30); background: var(--color-grey-0); color: var(--color-font-primary); }
  .dismiss { min-width: 2.75rem; border: 0; background: transparent; color: var(--color-font-secondary); display: inline-flex; align-items: center; justify-content: center; }
  @media (max-width: 560px) {
    .context-suggestion { flex-direction: column; align-items: stretch; }
    .actions { justify-content: space-between; }
  }
</style>
