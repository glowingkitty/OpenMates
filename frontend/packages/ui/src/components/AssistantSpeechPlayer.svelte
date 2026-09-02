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
  import playIconUrl from '../../static/icons/play.svg?url';
  import pauseIconUrl from '../../static/icons/pause.svg?url';
  import closeIconUrl from '../../static/icons/close.svg?url';
  import backIconUrl from '../../static/icons/back.svg?url';
  import aiIconUrl from '../../static/icons/ai.svg?url';
  import softwareDevelopmentMateUrl from '../../static/images/mates/software_development.jpeg?url';
  import businessDevelopmentMateUrl from '../../static/images/mates/business_development.jpeg?url';
  import medicalHealthMateUrl from '../../static/images/mates/medical_health.jpeg?url';
  import legalLawMateUrl from '../../static/images/mates/legal_law.jpeg?url';
  import makerPrototypingMateUrl from '../../static/images/mates/maker_prototyping.jpeg?url';
  import marketingSalesMateUrl from '../../static/images/mates/marketing_sales.jpeg?url';
  import financeMateUrl from '../../static/images/mates/finance.jpeg?url';
  import designMateUrl from '../../static/images/mates/design.jpeg?url';
  import electricalEngineeringMateUrl from '../../static/images/mates/electrical_engineering.jpeg?url';
  import moviesTvMateUrl from '../../static/images/mates/movies_tv.jpeg?url';
  import historyMateUrl from '../../static/images/mates/history.jpeg?url';
  import scienceMateUrl from '../../static/images/mates/science.jpeg?url';
  import lifeCoachPsychologyMateUrl from '../../static/images/mates/life_coach_psychology.jpeg?url';
  import cookingFoodMateUrl from '../../static/images/mates/cooking_food.jpeg?url';
  import activismMateUrl from '../../static/images/mates/activism.jpeg?url';
  import generalKnowledgeMateUrl from '../../static/images/mates/general_knowledge.jpeg?url';
  import onboardingSupportMateUrl from '../../static/images/mates/onboarding_support.jpeg?url';

  interface Props {
    controller?: AssistantSpeechPlaybackController;
    onHeightChange?: (height: number) => void;
  }

  let {
    controller = assistantSpeechController,
    onHeightChange = (_height: number) => {},
  }: Props = $props();

  let player = $derived(controller.player);
  const WAVEFORM_BARS_PER_SLOT = 32;
  const placeholderBars = Array.from({ length: WAVEFORM_BARS_PER_SLOT }, () => 8);
  const mateImages: Record<string, string> = {
    software_development: softwareDevelopmentMateUrl,
    business_development: businessDevelopmentMateUrl,
    medical_health: medicalHealthMateUrl,
    legal_law: legalLawMateUrl,
    maker_prototyping: makerPrototypingMateUrl,
    marketing_sales: marketingSalesMateUrl,
    finance: financeMateUrl,
    design: designMateUrl,
    electrical_engineering: electricalEngineeringMateUrl,
    movies_tv: moviesTvMateUrl,
    history: historyMateUrl,
    science: scienceMateUrl,
    life_coach_psychology: lifeCoachPsychologyMateUrl,
    cooking_food: cookingFoodMateUrl,
    activism: activismMateUrl,
    general_knowledge: generalKnowledgeMateUrl,
    onboarding_support: onboardingSupportMateUrl,
  };
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
  let waveformWindow = $derived([
    previousRegion ? { position: 'previous', region: previousRegion } : null,
    activeRegion ? { position: 'current', region: activeRegion } : null,
    nextRegion ? { position: 'next', region: nextRegion } : null,
  ].filter(Boolean) as Array<{ position: 'previous' | 'current' | 'next'; region: AssistantSpeechWaveformRegion }>);
  let mateImageUrl = $derived(mateImages[$player.mateCategory] ?? generalKnowledgeMateUrl);

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
    if (samples.length === WAVEFORM_BARS_PER_SLOT) return samples;
    return Array.from({ length: WAVEFORM_BARS_PER_SLOT }, (_, index) => {
      const sampleIndex = Math.round((index / (WAVEFORM_BARS_PER_SLOT - 1)) * (samples.length - 1));
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
      data-mate-category={$player.mateCategory}
      style:background-image={`url(${mateImageUrl})`}
    >
      <span class="assistant-speech-mate-badge" aria-hidden="true"><span class="assistant-speech-icon ai" style={`--speech-icon-url: url(${aiIconUrl})`}></span></span>
    </div>

    <div
      class="assistant-speech-waveform"
      class:pending={hasPlaceholder}
      data-testid="assistant-speech-waveform"
      data-placeholder={hasPlaceholder}
      data-segment-id={activeRegion?.segmentId ?? ''}
      data-window={waveformWindow.map(({ region }) => region.segmentId).join(',')}
      aria-label="Response waveform"
    >
      {#each waveformWindow as slot (slot.position)}
        <div
          class="assistant-speech-waveform-region {slot.position}"
          data-testid="assistant-speech-waveform-region"
          data-position={slot.position}
          data-segment-id={slot.region.segmentId}
          data-placeholder={slot.region.waveform.length === 0}
        >
          {#each waveformBars(slot.region.waveform) as height, index (index)}
            <span
              class="assistant-speech-waveform-bar"
              data-testid="assistant-speech-waveform-bar"
              style:height={`${Math.max(4, height)}%`}
              style:transition-delay={`${index * 7}ms`}
            ></span>
          {/each}
        </div>
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
          style={`--speech-icon-url: url(${isPlaying ? pauseIconUrl : playIconUrl})`}
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
          <span class="assistant-speech-icon close" data-testid="assistant-speech-close-icon" style={`--speech-icon-url: url(${closeIconUrl})`}></span>
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
          <span>{chapterLabel(previousRegion.chapter)}</span><span class="assistant-speech-icon chevron previous" style={`--speech-icon-url: url(${backIconUrl})`}></span>
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
          <span class="assistant-speech-icon chevron next" style={`--speech-icon-url: url(${backIconUrl})`}></span><span>{chapterLabel(nextRegion.chapter)}</span>
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
    left: calc(50% - 95px);
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
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    align-items: center;
    justify-self: center;
    width: min(100%, 220px);
    height: 38px;
    gap: 1px;
    transition: width var(--duration-slow) var(--easing-default);
  }

  .assistant-speech-player.expanded .assistant-speech-waveform { width: min(100%, 300px); }

  .assistant-speech-waveform-region {
    display: flex;
    align-items: center;
    align-self: stretch;
    min-width: 0;
    gap: 1px;
    overflow: hidden;
    opacity: 0.42;
    transition: opacity var(--duration-normal) var(--easing-default);
  }

  .assistant-speech-waveform-region.previous { grid-column: 1; }
  .assistant-speech-waveform-region.current { grid-column: 2; opacity: 1; }
  .assistant-speech-waveform-region.next { grid-column: 3; }
  .assistant-speech-waveform-region.current[data-placeholder='true'] { opacity: 0.55; }

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
    -webkit-mask-image: var(--speech-icon-url);
    mask-image: var(--speech-icon-url);
  }

  .assistant-speech-icon.ai { width: 9px; height: 9px; }
  .assistant-speech-icon.chevron { width: 11px; height: 11px; }
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
