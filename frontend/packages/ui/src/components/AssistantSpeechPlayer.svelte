<!-- frontend/packages/ui/src/components/AssistantSpeechPlayer.svelte -->
<!--
  Responsive Figma-defined player for one assistant response at a time.
  Renders local chapter metadata and waveform samples without exposing audio URLs.
  The active-chat container places it over history below its action buttons.
  An injected controller keeps the deployed component preview deterministic.
  -->
<script lang="ts">
  import { text } from '@repo/ui';
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
  const WAVEFORM_BAR_COUNT = 96;
  const placeholderBars = Array.from({ length: WAVEFORM_BAR_COUNT }, () => 8);
  const mateImages = import.meta.glob('../../static/images/mates/*.jpeg', {
    eager: true,
    query: '?url',
    import: 'default',
  }) as Record<string, string>;
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
  let activeWaveform = $derived(waveformBars(activeRegion?.waveform ?? []));
  let mateImageUrl = $derived(
    Object.entries(mateImages).find(([path]) => path.endsWith(`/${$player.mateCategory}.jpeg`))?.[1] ?? '',
  );

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

  function waveformBars(samples: number[]): number[] {
    if (samples.length === 0) return placeholderBars;
    if (samples.length === WAVEFORM_BAR_COUNT) return samples;
    return Array.from({ length: WAVEFORM_BAR_COUNT }, (_, index) => {
      const sampleIndex = Math.round((index / (WAVEFORM_BAR_COUNT - 1)) * (samples.length - 1));
      return samples[sampleIndex] ?? 8;
    });
  }

  function previousReplayableRegion(
    regions: AssistantSpeechWaveformRegion[],
    currentIndex: number,
  ): AssistantSpeechWaveformRegion | null {
    if (currentIndex <= 0) return null;
    return regions.slice(0, currentIndex).reverse().find((region) => region.sequence >= 0) ?? null;
  }

  function nextReplayableRegion(
    regions: AssistantSpeechWaveformRegion[],
    currentIndex: number,
  ): AssistantSpeechWaveformRegion | null {
    if (currentIndex < 0) return regions.find((region) => region.sequence >= 0) ?? null;
    return regions.slice(currentIndex + 1).find((region) => region.sequence >= 0) ?? null;
  }
</script>

{#if isVisible}
  <section
    use:observeHeight
    class="assistant-speech-player"
    class:expanded={Boolean(previousRegion)}
    data-testid="assistant-speech-player"
    data-presentation={$player.presentationMode}
    data-status={$player.status}
    aria-label="Voice response player"
  >
    <div
      class="assistant-speech-mate"
      data-testid="assistant-speech-mate"
      role="img"
      aria-label={$player.mateName}
      style:background-image={mateImageUrl ? `url(${mateImageUrl})` : undefined}
    >
      <span class="assistant-speech-mate-badge" aria-hidden="true"><span class="assistant-speech-icon ai"></span></span>
    </div>

    <div
      class="assistant-speech-waveform"
      class:pending={hasPlaceholder}
      data-testid="assistant-speech-waveform"
      data-placeholder={hasPlaceholder}
      data-segment-id={activeRegion?.segmentId ?? ''}
      aria-label="Response waveform"
    >
      {#each activeWaveform as height, index (index)}
        <span
          class="assistant-speech-waveform-bar"
          data-testid="assistant-speech-waveform-bar"
          style:height={`${Math.max(4, height)}%`}
          style:transition-delay={`${index * 5}ms`}
        ></span>
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
        <span
          class="assistant-speech-icon"
          class:pause={isPlaying}
          class:play={!isPlaying}
          data-testid="assistant-speech-primary-icon"
          data-icon={isPlaying ? 'pause' : 'play'}
        ></span>
      </button>
      {#if isPaused}
        <button
          type="button"
          class="assistant-speech-primary-control"
          data-testid="assistant-speech-close"
          aria-label={$text('common.close')}
          onclick={() => void controller.close()}
        >
          <span class="assistant-speech-icon close" data-testid="assistant-speech-close-icon"></span>
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
          <span>{chapterLabel(previousRegion.chapter)}</span><span class="assistant-speech-icon chevron previous"></span>
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
          <span class="assistant-speech-icon chevron next"></span><span>{chapterLabel(nextRegion.chapter)}</span>
        </button>
      {/if}
      {#if isLoading && !nextRegion}
        <span class="assistant-speech-loading" data-testid="assistant-speech-loading">
          {$text('common.loading')}
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
    padding: 8px 24px 6px;
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
    left: calc(50% - 148px);
    width: 34px;
    height: 34px;
    border-radius: var(--radius-full);
    background-position: center;
    background-repeat: no-repeat;
    background-size: cover;
    box-shadow: var(--shadow-xs);
    transition: left var(--duration-slow) var(--easing-default);
  }

  .assistant-speech-player.expanded .assistant-speech-mate { left: calc(50% - 190px); }

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
    width: min(100%, 220px);
    height: 38px;
    gap: 1px;
    transition: width var(--duration-slow) var(--easing-default);
  }

  .assistant-speech-player.expanded .assistant-speech-waveform { width: min(100%, 300px); }
  .assistant-speech-waveform.pending { opacity: 0.55; }

  .assistant-speech-waveform-bar {
    display: block;
    flex: 1 1 1px;
    min-width: 1px;
    max-width: 2px;
    border-radius: var(--radius-full);
    background: currentColor;
    transition: height var(--duration-normal) var(--easing-default), opacity var(--duration-fast) var(--easing-default);
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

  .assistant-speech-icon {
    display: block;
    width: 18px;
    height: 18px;
    background: currentColor;
    -webkit-mask-position: center;
    -webkit-mask-repeat: no-repeat;
    -webkit-mask-size: contain;
    mask-position: center;
    mask-repeat: no-repeat;
    mask-size: contain;
  }

  .assistant-speech-icon.play { -webkit-mask-image: var(--icon-url-play); mask-image: var(--icon-url-play); }
  .assistant-speech-icon.pause { -webkit-mask-image: var(--icon-url-pause); mask-image: var(--icon-url-pause); }
  .assistant-speech-icon.close { -webkit-mask-image: var(--icon-url-close); mask-image: var(--icon-url-close); }
  .assistant-speech-icon.ai { width: 9px; height: 9px; -webkit-mask-image: var(--icon-url-ai); mask-image: var(--icon-url-ai); }
  .assistant-speech-icon.chevron { width: 11px; height: 11px; -webkit-mask-image: var(--icon-url-back); mask-image: var(--icon-url-back); }
  .assistant-speech-icon.chevron.next { transform: rotate(180deg); }

  .assistant-speech-primary-control:hover { transform: scale(1.06); }
  .assistant-speech-primary-control:active { transform: scale(0.95); }
  .assistant-speech-primary-control:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }

  .assistant-speech-chapters {
    position: relative;
    grid-row: 2;
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    align-items: center;
    min-width: 0;
    column-gap: var(--spacing-4);
    font-size: var(--font-size-xxs);
    line-height: 1;
  }

  .assistant-speech-chapters strong {
    grid-column: 2;
    justify-self: center;
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

  .assistant-speech-adjacent.previous { grid-column: 1; justify-self: end; }
  .assistant-speech-adjacent.next { grid-column: 3; justify-self: start; }

  .assistant-speech-adjacent:hover,
  .assistant-speech-adjacent:focus-visible { opacity: 1; }
  .assistant-speech-adjacent span { max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .assistant-speech-loading {
    grid-column: 3;
    justify-self: start;
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
      padding: 8px 16px 6px;
    }

    .assistant-speech-mate { display: none; }
    .assistant-speech-waveform,
    .assistant-speech-player.expanded .assistant-speech-waveform { width: min(100%, 185px); height: 42px; }
    .assistant-speech-primary-controls { top: 14px; }
    .assistant-speech-chapters { column-gap: var(--spacing-2); }
    .assistant-speech-adjacent span { display: none; }
    .assistant-speech-chapters strong { max-width: 170px; }
  }

  @media (prefers-reduced-motion: reduce) {
    .assistant-speech-waveform,
    .assistant-speech-waveform-bar,
    .assistant-speech-primary-control,
    .assistant-speech-mate { transition: none; }
  }
</style>
