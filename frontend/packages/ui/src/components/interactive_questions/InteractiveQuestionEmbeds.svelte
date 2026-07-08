<!--
  frontend/packages/ui/src/components/interactive_questions/InteractiveQuestionEmbeds.svelte

  Renders OpenMates embed references that are attached to choice options or swipe cards.
  Uses the same large embed preview pipeline as chat messages, while preventing preview
  clicks from toggling the surrounding question control.

  Architecture: Svelte 5 / InteractiveQuestions + Unified embed previews
-->

<script lang="ts">
  import EmbedPreviewLarge from '../embeds/EmbedPreviewLarge.svelte';

  let { embedIds = [] }: { embedIds?: string[] } = $props();
  let normalizedEmbedIds = $derived(embedIds.filter((embedId) => embedId.trim().length > 0));
</script>

{#if normalizedEmbedIds.length > 0}
  <div
    class="interactive-question-embeds"
    data-testid="interactive-question-embeds"
  >
    {#each normalizedEmbedIds as embedId (embedId)}
      <div class="interactive-question-embed" data-testid="interactive-question-embed">
        <EmbedPreviewLarge
          embedRef={embedId}
          {embedId}
          carouselIndex={0}
          carouselTotal={1}
          runRef={`interactive-question-${embedId}`}
        />
      </div>
    {/each}
  </div>
{/if}

<style>
  .interactive-question-embeds {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-8, 8px);
    width: 100%;
    margin-top: var(--spacing-8, 8px);
  }

  .interactive-question-embed {
    width: 100%;
    min-width: 0;
  }

  :global(.interactive-question-embed .embed-preview-large-wrapper) {
    max-width: 100%;
  }
</style>
