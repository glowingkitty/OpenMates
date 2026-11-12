<!--
  frontend/packages/ui/src/components/embeds/videos/VideoEditInspector.svelte

  Edit-mode inspector for the part selected on the timeline: one field per
  editable text, shorten from start / end in half-second steps (never below half
  a second remaining) and remove part (composed videos). Changes only update the
  pending-edit model; nothing is rendered or sent until Apply.
-->
<script lang="ts">
  import { text } from '../../../i18n/translations';
  import {
    canRemovePart, canShorten, formatSeconds, isRemoved, remainingFrames, textValue, toggleRemoved, trimOf,
    withText, withTrimStep, type PendingEdits, type VideoPart, type VideoTimelineModel,
  } from './videoTimelineModel';

  interface Props {
    timeline: VideoTimelineModel;
    part: VideoPart;
    edits: PendingEdits;
    onChange: (edits: PendingEdits) => void;
  }

  let { timeline, part, edits, onChange }: Props = $props();
  const composed = $derived(timeline.madeBy === 'composed');
  const removed = $derived(isRemoved(edits, part.id));
  const trim = $derived(trimOf(edits, part.id));
  const seconds = (frames: number) => formatSeconds(frames / timeline.fps);
  const sides = ['start', 'end'] as const;
</script>

<section class="inspector" data-testid="video-edit-inspector" data-part-id={part.id} aria-label={$text('embeds.video_generate.edit_part', { values: { label: part.label } })}>
  <header>
    <h3>{composed ? part.label : $text('embeds.video_generate.trim_video')}</h3>
    <span class="length" data-testid="video-edit-part-length">{seconds(remainingFrames(part, edits))}</span>
  </header>

  {#if composed && !removed}
    {#each part.texts as item (item.id)}
      <label class="field">
        <span>{item.id}</span>
        <input type="text" value={textValue(edits, part.id, item.id, item.value)} data-testid="video-edit-text-{item.id}"
          oninput={(event) => onChange(withText(edits, timeline, part.id, item.id, event.currentTarget.value))} />
      </label>
    {/each}
  {/if}

  {#if !removed}
    <div class="steppers">
      {#each sides as side (side)}
        {@const frames = side === 'start' ? trim.fromStartFrames : trim.fromEndFrames}
        <div class="stepper" role="group" aria-label={$text(side === 'start' ? 'embeds.video_generate.shorten_start' : 'embeds.video_generate.shorten_end')}>
          <span class="stepper-label">{$text(side === 'start' ? 'embeds.video_generate.shorten_start' : 'embeds.video_generate.shorten_end')}</span>
          <div class="stepper-controls">
            <button type="button" data-testid="video-edit-shorten-{side}-less" disabled={frames === 0}
              aria-label={$text('embeds.video_generate.shorten_less')} onclick={() => onChange(withTrimStep(edits, timeline, part.id, side, -1))}>−</button>
            <output data-testid="video-edit-shorten-{side}-value">{seconds(frames)}</output>
            <button type="button" data-testid="video-edit-shorten-{side}-more" disabled={!canShorten(edits, timeline, part.id, side)}
              aria-label={$text('embeds.video_generate.shorten_more')} onclick={() => onChange(withTrimStep(edits, timeline, part.id, side, 1))}>+</button>
          </div>
        </div>
      {/each}
    </div>
  {/if}

  {#if composed}
    <div class="remove">
      <button type="button" class="remove-btn" data-testid="video-edit-remove" disabled={!removed && !canRemovePart(edits, timeline, part.id)}
        onclick={() => onChange(toggleRemoved(edits, timeline, part.id))}>
        {$text(removed ? 'embeds.video_generate.restore_part' : 'embeds.video_generate.remove_part')}
      </button>
      {#if !removed && !canRemovePart(edits, timeline, part.id)}
        <span class="hint" data-testid="video-edit-remove-hint">{$text('embeds.video_generate.remove_last_hint')}</span>
      {/if}
    </div>
  {/if}
</section>

<style>
  .inspector {
    width: 100%; box-sizing: border-box; display: grid; gap: var(--spacing-5); padding: var(--spacing-6);
    background: var(--color-grey-0); border: 1px solid var(--color-grey-25); border-radius: var(--radius-4);
  }
  header { display: flex; align-items: baseline; justify-content: space-between; gap: var(--spacing-4); min-width: 0; }
  h3 { margin: 0; font-size: var(--font-size-p); font-weight: 700; min-width: 0; overflow-wrap: anywhere; }
  .length { flex: none; font-size: var(--font-size-small); color: var(--color-font-secondary); font-variant-numeric: tabular-nums; }
  .field { display: grid; gap: var(--spacing-2); font-size: var(--font-size-small); color: var(--color-font-secondary); }
  .field input {
    width: 100%; box-sizing: border-box; padding: var(--spacing-3) var(--spacing-4); font: inherit; color: var(--color-font-primary);
    background: var(--color-grey-10); border: 1px solid var(--color-grey-30); border-radius: var(--radius-3);
  }
  .field input:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 1px; }
  .steppers { display: flex; flex-wrap: wrap; gap: var(--spacing-5) var(--spacing-8); }
  .stepper { display: grid; gap: var(--spacing-2); }
  .stepper-label { font-size: var(--font-size-small); color: var(--color-font-secondary); }
  .stepper-controls { display: inline-flex; align-items: center; gap: var(--spacing-3); }
  output { min-width: 3.5rem; text-align: center; font-variant-numeric: tabular-nums; font-size: var(--font-size-small); }
  .stepper-controls button {
    width: 2rem; min-width: 0; height: 2rem; padding: 0; margin: 0; filter: none; border-radius: 50%; border: 1px solid var(--color-grey-30);
    background: var(--color-grey-10); color: var(--color-font-primary); font-size: var(--font-size-h3); line-height: 1; cursor: pointer;
  }
  .stepper-controls button:disabled { opacity: 0.4; cursor: default; }
  .stepper-controls button:focus-visible, .remove-btn:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  .remove { display: flex; flex-wrap: wrap; align-items: center; gap: var(--spacing-4); }
  .remove-btn {
    font: inherit; font-size: var(--font-size-small); font-weight: 600; padding: var(--spacing-3) var(--spacing-6); cursor: pointer;
    min-width: 0; height: auto; margin: 0; filter: none;
    border-radius: var(--radius-8); border: 1px solid var(--color-error); background: transparent; color: var(--color-error);
  }
  .remove-btn:disabled { opacity: 0.45; cursor: default; }
  .hint { font-size: var(--font-size-small); color: var(--color-font-secondary); }
</style>
