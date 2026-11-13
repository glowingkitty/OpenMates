<!--
  frontend/packages/ui/src/components/embeds/images/ImageModifyProgress.svelte

  Progress of images.modify while it runs: the computed draft picture (when one
  exists) with the current step text over it, or the step text alone. Shared by
  the generated-image card, its opened view and the skill-use group card.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import { imageDraftUrl, imageModifyStageKey, showsAttempt, type ImageModifyState } from './imageDraft';

  interface Props {
    state: ImageModifyState;
    title?: string;
    /** The card crops the draft to its media area; the opened view shows all of it. */
    fit?: 'cover' | 'contain';
    /** Fills the media area of the generated-image card. */
    card?: boolean;
  }

  let { state: progress, title = '', fit = 'cover', card = false }: Props = $props();
  let draftUrl = $derived(imageDraftUrl(progress.draft));
  let stageKey = $derived(imageModifyStageKey(progress.stage));
  let stepText = $derived(
    stageKey ? `${$text(stageKey)}${showsAttempt(progress.attempt) ? ` · ${$text('embeds.image_modify.attempt', { values: { n: progress.attempt } })}` : ''}` : '',
  );
</script>

<div class="modify-progress" class:card class:has-draft={!!draftUrl} data-testid={card ? 'image-modify-card' : undefined} data-stage={progress.stage} data-attempt={progress.attempt}>
  {#if draftUrl}
    <img class="modify-draft" class:contain={fit === 'contain'} src={draftUrl} alt={title} data-testid="image-modify-draft" />
  {/if}
  {#if stepText}
    <span class="modify-step" class:over-draft={!!draftUrl} data-testid="image-modify-step">{stepText}</span>
  {/if}
</div>

<style>
  .modify-progress {
    position: relative;
    width: 100%;
    height: 100%;
    min-height: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }

  .modify-progress.card {
    flex: 1;
  }

  .modify-draft {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .modify-draft.contain {
    object-fit: contain;
  }

  .modify-step {
    display: inline-block;
    padding: var(--spacing-1) var(--spacing-4);
    border-radius: var(--radius-2);
    background: rgba(0, 0, 0, 0.55);
    color: #fff;
    font-size: var(--font-size-tiny);
    line-height: 1.3;
  }

  .modify-step.over-draft {
    position: absolute;
    right: var(--spacing-4);
    top: var(--spacing-4);
    z-index: 1;
    font-size: var(--font-size-small);
    font-weight: 600;
    pointer-events: none;
  }
</style>
