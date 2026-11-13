<!--
  frontend/packages/ui/src/components/embeds/videos/VideoExtendField.svelte

  Inline field that asks what should happen in the clip added at the start or end
  of a generated video. Focus moves into the field when it opens, Escape closes it,
  and an empty description is not sent (a hint is shown instead). The caller sends
  the text as an ordinary follow-up about the video.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '../../../i18n/translations';

  interface Props {
    side: 'start' | 'end';
    submitting?: boolean;
    onSend: (description: string) => void;
    onClose: () => void;
  }

  let { side, submitting = false, onSend, onClose }: Props = $props();
  let value = $state('');
  let showHint = $state(false);
  let input: HTMLTextAreaElement | undefined = $state();

  onMount(() => input?.focus());

  function send() {
    if (!value.trim()) {
      showHint = true;
      input?.focus();
      return;
    }
    onSend(value.trim());
  }
  function onKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      onClose();
    } else if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      send();
    }
  }
</script>

<div class="extend-field" data-testid="video-extend-field" data-side={side} role="group"
  aria-label={$text(side === 'end' ? 'embeds.video_generate.extend_end' : 'embeds.video_generate.extend_start')}>
  <textarea bind:this={input} bind:value rows="2" data-testid="video-extend-input"
    placeholder={$text(side === 'end' ? 'embeds.video_generate.extend_placeholder_end' : 'embeds.video_generate.extend_placeholder_start')}
    aria-describedby={showHint ? 'video-extend-hint' : undefined} aria-invalid={showHint && !value.trim()}
    oninput={() => { if (value.trim()) showHint = false; }} onkeydown={onKeydown}></textarea>
  {#if showHint}
    <p class="hint" id="video-extend-hint" role="alert" data-testid="video-extend-hint">{$text('embeds.video_generate.extend_empty')}</p>
  {/if}
  <div class="actions">
    <button type="button" class="secondary" data-testid="video-extend-cancel" onclick={onClose}>{$text('embeds.video_generate.cancel')}</button>
    <button type="button" class="primary" data-testid="video-extend-send" disabled={submitting} onclick={send}>{$text('embeds.video_generate.send')}</button>
  </div>
</div>

<style>
  .extend-field {
    width: 100%; box-sizing: border-box; display: grid; gap: var(--spacing-3); padding: var(--spacing-5);
    background: var(--color-grey-0); border: 1px solid var(--color-grey-25); border-radius: var(--radius-4);
  }
  textarea {
    width: 100%; box-sizing: border-box; resize: vertical; min-height: 3.5rem; padding: var(--spacing-3) var(--spacing-4);
    font: inherit; font-size: var(--font-size-small); color: var(--color-font-primary);
    background: var(--color-grey-10); border: 1px solid var(--color-grey-30); border-radius: var(--radius-3);
  }
  textarea:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 1px; }
  textarea[aria-invalid='true'] { border-color: var(--color-error); }
  .hint { margin: 0; font-size: var(--font-size-small); color: var(--color-error); }
  .actions { display: flex; justify-content: flex-end; gap: var(--spacing-3); }
  button {
    font: inherit; font-size: var(--font-size-small); font-weight: 600; padding: var(--spacing-3) var(--spacing-6);
    border-radius: var(--radius-8); border: 1px solid transparent; cursor: pointer;
    min-width: 0; height: auto; margin: 0; filter: none;
  }
  .primary { background: var(--color-button-primary); color: var(--color-font-button); }
  .secondary { background: var(--color-grey-10); color: var(--color-font-primary); border-color: var(--color-grey-30); }
  button:disabled { opacity: 0.5; cursor: default; }
  button:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
</style>
