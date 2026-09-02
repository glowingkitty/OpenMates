<!-- frontend/packages/ui/src/components/AssistantSpeechPlayer.svelte -->
<!--
  Responsive Figma-defined player for one assistant response at a time.
  Renders local chapter metadata and waveform samples without exposing audio URLs.
  The active-chat container places it over history below its action buttons.
  An injected controller keeps the deployed component preview deterministic.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import Icon from './Icon.svelte';
  import {
    assistantSpeechController,
    type AssistantSpeechPlaybackController,
  } from '../services/assistantSpeechController';
  import type { AssistantSpeechChapter, AssistantSpeechWaveformRegion } from '../services/assistantSpeechQueue';

  interface Props {
    controller?: AssistantSpeechPlaybackController;
    onHeightChange?: (height: number) => void;
  }

  let {
    controller = assistantSpeechController,
    onHeightChange = (_height: number) => {},
  }: Props = $props();

  let player = $derived(controller.player);
  const placeholderBars = [4, 4, 4, 4, 4, 4, 4, 4];
  let isPlaying = $derived($player.status === 'playing');
  let isPaused = $derived($player.status === 'paused');
  let isLoading = $derived(
    ['waiting_for_segment', 'waiting_for_more'].includes($player.status) ||
    $player.presentationMode === 'passive_clip',
  );
  let isVisible = $derived(
    $player.responseId !== null && !['idle', 'stopped'].includes($player.status),
  );
  let activeIndex = $derived($player.regions.findIndex((region) => region.active));
  let activeRegion = $derived(activeIndex >= 0 ? $player.regions[activeIndex] : null);
  let previousRegion = $derived(previousReplayableRegion($player.regions, activeIndex));
  let nextRegion = $derived(nextReplayableRegion($player.regions, activeIndex));
  let hasPlaceholder = $derived(Boolean(activeRegion && activeRegion.waveform.length === 0));

  function observeHeight(node: HTMLElement) {
    const reportHeight = () => onHeightChange(node.getBoundingClientRect().height);
    const observer = new ResizeObserver(reportHeight);
    observer.observe(node);
    reportHeight();
    return {
      destroy() {
        observer.disconnect();
        onHeightChange(0);
      },
    };
  }

  function chapterLabel(chapter: AssistantSpeechChapter): string {
    if (chapter.kind === 'heading') return chapter.text;
    if (chapter.kind === 'part') return $text('chat.assistant_speech.part', { values: { number: chapter.number } });
    if (chapter.kind === 'semantic') return $text(`chat.assistant_speech.${chapter.type}`);
    return $text(`chat.assistant_speech.${chapter.type}`);
  }

  function previousReplayableRegion(
    regions: AssistantSpeechWaveformRegion[],
    currentIndex: number,
  ): AssistantSpeechWaveformRegion | null {
    if (currentIndex <= 0) return null;
    return regions[currentIndex - 1] ?? null;
  }

  function nextReplayableRegion(
    regions: AssistantSpeechWaveformRegion[],
    currentIndex: number,
  ): AssistantSpeechWaveformRegion | null {
    if (currentIndex < 0) return regions[0] ?? null;
    return regions[currentIndex + 1] ?? null;
  }
</script>

{#if isVisible}
  <section
    use:observeHeight
    class="assistant-speech-player"
    data-testid="assistant-speech-player"
    data-presentation={$player.presentationMode}
    data-status={$player.status}
    aria-label="Voice response player"
  >
    <div
      class="assistant-speech-mate mate-profile {$player.mateCategory}"
      data-testid="assistant-speech-mate"
      role="img"
      aria-label={$player.mateName}
    >
      <span class="assistant-speech-mate-badge" aria-hidden="true"><Icon name="ai" size="10px" noMargin={true} /></span>
    </div>

    <div
      class="assistant-speech-waveform"
      data-testid="assistant-speech-waveform"
      data-placeholder={hasPlaceholder}
      aria-label="Response waveform"
    >
      {#each $player.regions as region (region.segmentId)}
        <button
          type="button"
          class="assistant-speech-region"
          data-testid="assistant-speech-region"
          data-status={region.status}
          data-active={region.active}
          class:active={region.active}
          class:pending={region.waveform.length === 0}
          style:flex-grow={Math.max(0.04, region.end - region.start)}
          aria-label={chapterLabel(region.chapter)}
          disabled={$player.presentationMode === 'passive_clip'}
          onclick={() => $player.presentationMode === 'replayable_track_queue' && void controller.selectSegment(region.segmentId)}
        >
          {#each region.waveform.length > 0 ? region.waveform : placeholderBars as height, index (`${region.segmentId}:${index}`)}
            <span
              class="assistant-speech-waveform-bar"
              data-testid="assistant-speech-waveform-bar"
              style:height={`${Math.max(4, height)}%`}
            ></span>
          {/each}
        </button>
      {/each}
    </div>

    <div class="assistant-speech-primary-controls" class:paused={isPaused}>
      <button
        type="button"
        class="assistant-speech-primary-control"
        data-testid="assistant-speech-primary-control"
        aria-label={isPlaying ? 'Pause voice response' : 'Play voice response'}
        onclick={() => isPlaying ? controller.pause() : void controller.play()}
      >
        <Icon name={isPlaying ? 'pause' : 'play'} size="18px" noMargin={true} />
      </button>
      {#if isPaused}
        <button
          type="button"
          class="assistant-speech-primary-control"
          data-testid="assistant-speech-close"
          aria-label={$text('common.close')}
          onclick={() => void controller.close()}
        >
          <Icon name="close" size="18px" noMargin={true} />
        </button>
      {/if}
    </div>

    <div class="assistant-speech-chapters">
      {#if $player.presentationMode === 'replayable_track_queue' && previousRegion}
        <button
          type="button"
          class="assistant-speech-adjacent previous"
          data-testid="assistant-speech-previous-chapter"
          aria-label={`Previous chapter: ${chapterLabel(previousRegion.chapter)}`}
          onclick={() => void controller.previous()}
        >
          <span>{chapterLabel(previousRegion.chapter)}</span><Icon name="back" size="12px" noMargin={true} />
        </button>
      {/if}
      <strong data-testid="assistant-speech-current-chapter">
        {activeRegion ? chapterLabel(activeRegion.chapter) : $text('common.loading')}
      </strong>
      {#if $player.presentationMode === 'replayable_track_queue' && nextRegion}
        <button
          type="button"
          class="assistant-speech-adjacent next"
          data-testid="assistant-speech-next-chapter"
          aria-label={`Next chapter: ${chapterLabel(nextRegion.chapter)}`}
          onclick={() => void controller.next()}
        >
          <Icon name="back" size="12px" noMargin={true} /><span>{chapterLabel(nextRegion.chapter)}</span>
        </button>
      {/if}
      {#if isLoading}
        <span class="assistant-speech-loading" data-testid="assistant-speech-loading">
          <Icon name="back" size="12px" noMargin={true} />{$text('common.loading')}
        </span>
      {/if}
    </div>
  </section>
{/if}

<style>
  .assistant-speech-player {
    position: absolute;
    z-index: var(--z-index-raised);
    inset: 0 0 auto;
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: 46px 22px;
    width: 100%;
    height: 82px;
    box-sizing: border-box;
    padding: 8px 120px 6px;
    overflow: hidden;
    border-radius: var(--radius-8);
    color: var(--color-grey-0);
    background: var(--gradient-primary);
    box-shadow: var(--shadow-sm);
  }

  .assistant-speech-mate {
    position: absolute;
    z-index: 2;
    top: 13px;
    left: calc(50% - 185px);
    width: 34px;
    height: 34px;
    border-radius: var(--radius-full);
    box-shadow: var(--shadow-xs);
  }

  .assistant-speech-mate-badge {
    position: absolute;
    right: -3px;
    bottom: -3px;
    display: grid;
    place-items: center;
    width: 15px;
    height: 15px;
    border-radius: var(--radius-full);
    color: var(--color-primary);
    background: var(--color-grey-0);
  }

  .assistant-speech-waveform {
    display: flex;
    align-items: center;
    justify-self: center;
    width: min(100%, 330px);
    height: 38px;
    gap: 2px;
    transition: width var(--duration-slow) var(--easing-default);
  }

  .assistant-speech-region {
    all: unset;
    display: flex;
    align-items: center;
    height: 100%;
    min-width: 24px;
    gap: 2px;
    cursor: pointer;
    opacity: 0.34;
    transition: opacity var(--duration-normal) var(--easing-default);
  }

  .assistant-speech-region.active { opacity: 1; }
  .assistant-speech-region:disabled { cursor: default; }

  .assistant-speech-waveform-bar {
    display: block;
    flex: 1 1 2px;
    min-width: 1px;
    max-width: 3px;
    border-radius: var(--radius-full);
    background: currentColor;
    transition: height var(--duration-slow) var(--easing-default);
  }

  .assistant-speech-primary-controls {
    position: absolute;
    z-index: 3;
    top: 12px;
    left: 50%;
    display: flex;
    gap: var(--spacing-2);
    transform: translateX(-50%);
  }

  .assistant-speech-primary-controls.paused { transform: translateX(-50%); }

  .assistant-speech-primary-control {
    all: unset;
    display: grid;
    place-items: center;
    width: 40px;
    height: 40px;
    border-radius: var(--radius-full);
    color: var(--color-primary);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-xs);
    cursor: pointer;
    transition: transform var(--duration-fast) var(--easing-default);
  }

  .assistant-speech-primary-control:hover { transform: scale(1.06); }
  .assistant-speech-primary-control:active { transform: scale(0.95); }
  .assistant-speech-primary-control:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }

  .assistant-speech-chapters {
    grid-row: 2;
    display: flex;
    align-items: center;
    justify-content: center;
    min-width: 0;
    gap: var(--spacing-4);
    font-size: var(--font-size-xxs);
    line-height: 1;
  }

  .assistant-speech-chapters strong {
    max-width: 210px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .assistant-speech-adjacent {
    all: unset;
    display: inline-flex;
    align-items: center;
    min-width: 0;
    gap: 3px;
    opacity: 0.54;
    cursor: pointer;
    transition: opacity var(--duration-fast) var(--easing-default);
  }

  .assistant-speech-adjacent:hover,
  .assistant-speech-adjacent:focus-visible { opacity: 1; }
  .assistant-speech-adjacent span { max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .assistant-speech-adjacent.next :global(.icon) { transform: rotate(180deg); }

  .assistant-speech-loading {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    opacity: 0.54;
    white-space: nowrap;
  }

  @media (max-width: 730px) {
    .assistant-speech-player {
      grid-template-rows: 54px 24px;
      height: 92px;
      padding: 8px 72px 6px;
    }

    .assistant-speech-mate { display: none; }
    .assistant-speech-waveform { width: min(100%, 190px); height: 42px; }
    .assistant-speech-primary-controls { top: 14px; }
    .assistant-speech-chapters { gap: var(--spacing-2); }
    .assistant-speech-adjacent span { display: none; }
    .assistant-speech-chapters strong { max-width: 170px; }
  }

  @media (prefers-reduced-motion: reduce) {
    .assistant-speech-waveform,
    .assistant-speech-waveform-bar,
    .assistant-speech-primary-control,
    .assistant-speech-region { transition: none; }
  }
</style>
