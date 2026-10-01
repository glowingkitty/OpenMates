<!-- A workflow test response uses the same read-only Markdown and embed renderer as chat. -->
<script lang="ts">
  import { onDestroy } from 'svelte';
  import ReadOnlyMessage from '../ReadOnlyMessage.svelte';
  import { embedStore } from '../../services/embedStore';
  import type { WorkflowPreviewEmbed } from '../../services/workflowStepTestStream';

  let { content, processing, error = '', embeds = [] }: {
    content: string;
    processing: boolean;
    error?: string;
    embeds?: WorkflowPreviewEmbed[];
  } = $props();

  const registeredIds = new Set<string>();
  let seededEmbeds = $state.raw<WorkflowPreviewEmbed[] | null>(null);
  let hydrationTimestamp = $state(0);
  $effect(() => {
    const nextIds = new Set(embeds.map(embed => embed.embed_id));
    for (const id of registeredIds) {
      if (!nextIds.has(id)) { embedStore.removeFromMemoryCache(`embed:${id}`); registeredIds.delete(id); }
    }
    for (const embed of embeds) {
      embedStore.setInMemoryOnly(`embed:${embed.embed_id}`, {
        embed_id: embed.embed_id, type: embed.content_type, status: 'finished',
        content: JSON.stringify({ ...embed.content, embed_id: embed.embed_id, embed_ref: embed.embed_id, app_id: embed.app_id, skill_id: embed.skill_id }),
      });
      embedStore.registerEmbedRef(embed.embed_id, embed.embed_id, embed.app_id, embed.content_type, embed.skill_id);
      registeredIds.add(embed.embed_id);
    }
    // Mount the renderer only after its refs are resolvable; preview data stays in memory.
    seededEmbeds = embeds;
    hydrationTimestamp = embeds.length ? Date.now() : 0;
  });
  onDestroy(() => { for (const id of registeredIds) embedStore.removeFromMemoryCache(`embed:${id}`); });
</script>

{#if content || error}
  <section
    class="workflow-ask-ai-test-preview"
    data-testid="workflow-ask-ai-test-preview"
    aria-label="OpenMates test response"
    aria-busy={processing}
  >
    {#if content && (embeds.length === 0 || seededEmbeds === embeds)}
      <div class="chat-message assistant" data-testid="workflow-ask-ai-test-message">
        <div class="mate-profile openmates_official" data-testid="workflow-ask-ai-test-avatar" role="img" aria-label="OpenMates"></div>
        <div class="message-align-left">
          <div class="mate-message-content" role="article">
            <div class="assistant-identity-row">
              <div class="chat-mate-name" data-testid="workflow-ask-ai-test-sender">OpenMates</div>
            </div>
            <div class="chat-message-body" data-testid="workflow-ask-ai-test-body">
              <ReadOnlyMessage {content} isStreaming={processing} role="assistant" _embedUpdateTimestamp={hydrationTimestamp}/>
            </div>
          </div>
        </div>
      </div>
    {/if}
    {#if error}
      <p class="error" role="alert" data-testid="workflow-ask-ai-test-error">{error}</p>
    {/if}
  </section>
{/if}

<style>
  .workflow-ask-ai-test-preview { width: 100%; min-width: 0; color: var(--color-font-primary); text-align: left; }
  .workflow-ask-ai-test-preview :global(.chat-message) { justify-content: flex-start; }
  .workflow-ask-ai-test-preview :global(.message-align-left) { flex: 1; max-width: calc(100% - 5rem); }
  .workflow-ask-ai-test-preview :global(.mate-message-content) { overflow-wrap: anywhere; }
  .workflow-ask-ai-test-preview :global(.chat-message-body) { min-width: 0; }
  .assistant-identity-row { display: flex; align-items: center; gap: var(--spacing-2); }
  .error { margin: var(--spacing-2) 0 0; color: var(--color-error); font-size: var(--font-size-small); }
  @media (max-width: 500px) {
    .workflow-ask-ai-test-preview :global(.chat-message) { flex-direction: column; align-items: flex-start; }
    .workflow-ask-ai-test-preview :global(.mate-profile) { width: 25px; height: 25px; margin: 0 0 var(--spacing-4); }
    .workflow-ask-ai-test-preview :global(.message-align-left) { max-width: 100%; width: 100%; padding-inline-end: 0; }
    .workflow-ask-ai-test-preview :global(.mate-message-content) { margin: 0; }
    .workflow-ask-ai-test-preview :global(.mate-message-content)::before { transform: rotate(90deg); inset-inline-start: 20px; top: -12px; }
  }
</style>
