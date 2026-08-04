<script lang="ts">
  /**
   * LandingMatesFocusDemo.svelte
   *
   * Deterministic explanation of metadata-backed OpenMates experts and real
   * focus-mode identities. The component is decorative and store-independent.
   */

  import { onMount } from 'svelte';
  import { text } from '@repo/ui';
  import { matesMetadata } from '../../data/matesMetadata';
  import { getLucideIcon } from '../../utils/categoryUtils';
  import {
    MATES_FOCUS_STORY_DURATION_MS,
    MATES_FOCUS_STORY_STAGES,
    type MatesFocusStoryStage,
  } from './landingProductStoryTimelines';

  interface Props { playing: boolean; reducedMotion: boolean; onComplete: () => void; }
  let { playing, reducedMotion, onComplete }: Props = $props();
  let activeStageIndex = $state(0);
  let activeItemIndex = $state(0);
  let mounted = $state(false);

  const SparklesIcon = getLucideIcon('sparkles');
  const CheckIcon = getLucideIcon('check');
  const selectedMateIds = ['software_development', 'marketing_sales', 'general_knowledge', 'medical_health'];
  const selectedMates = matesMetadata.filter((mate) => selectedMateIds.includes(mate.id));
  const focusModes = [
    { id: 'project-planner', labelKey: 'app_focus_modes.code.project_planner', icon: 'list-check' },
    { id: 'research-solutions', labelKey: 'app_focus_modes.code.research_solutions', icon: 'search' },
    { id: 'learn-by-building', labelKey: 'app_focus_modes.code.learn_by_building', icon: 'graduation-cap' },
  ];
  let activeStage = $derived<MatesFocusStoryStage>(MATES_FOCUS_STORY_STAGES[activeStageIndex]?.id ?? 'mates');

  onMount(() => { mounted = true; });

  $effect(() => {
    if (!mounted || reducedMotion || !playing) { activeStageIndex = 0; activeItemIndex = 0; return; }
    activeStageIndex = 0;
    activeItemIndex = 0;
    const timeouts: number[] = [];
    [1, 2, 3].forEach((index) => timeouts.push(window.setTimeout(() => { activeItemIndex = index; }, 900 + index * 1100)));
    const focusStartMs = MATES_FOCUS_STORY_STAGES[0].durationMs;
    timeouts.push(window.setTimeout(() => { activeStageIndex = 1; activeItemIndex = 0; }, focusStartMs));
    [1, 2].forEach((index) => timeouts.push(window.setTimeout(() => { activeItemIndex = index; }, focusStartMs + 900 + index * 1400)));
    timeouts.push(window.setTimeout(onComplete, MATES_FOCUS_STORY_DURATION_MS));
    return () => timeouts.forEach((timeout) => window.clearTimeout(timeout));
  });
</script>

<div class="mates-focus-demo" data-testid="landing-mates-focus-demo" data-active-stage={activeStage} data-reduced-motion={reducedMotion ? 'true' : 'false'} data-playing={playing ? 'true' : 'false'} aria-hidden="true">
  {#if activeStage === 'mates' || reducedMotion}
    <div class="story-copy"><SparklesIcon size={18} /> {$text('demo_chats.for_everyone.landing_mates_experts')}</div>
    <div class="scroll-list mates-list">
      {#each selectedMates as mate, index}
        <div class:active={reducedMotion || index === activeItemIndex} class="story-row" data-testid="landing-mate-profile" data-mate-id={mate.id}>
          <span class="mate-profile {mate.profile_class}"></span>
          <span><strong>{$text(mate.name_translation_key)}</strong><small>{$text(mate.description_translation_key)}</small></span>
        </div>
      {/each}
    </div>
  {/if}
  {#if activeStage === 'focus' || reducedMotion}
    <div class="story-copy"><SparklesIcon size={18} /> {$text('demo_chats.for_everyone.landing_mates_focus_modes')}</div>
    <div class="scroll-list focus-list">
      {#each focusModes as mode, index}
        {@const ModeIcon = getLucideIcon(mode.icon)}
        <div class:active={index === activeItemIndex} class="story-row focus-row" data-testid="landing-focus-mode" data-focus-id={mode.id}>
          <span class="focus-icon"><ModeIcon size={20} /></span>
          <strong>{$text(mode.labelKey)}</strong>
          {#if index === activeItemIndex}<span class="active-check"><CheckIcon size={16} /></span>{/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .mates-focus-demo { display: grid; grid-template-columns: minmax(150px,.8fr) minmax(250px,1.2fr); align-items: center; gap: 22px; width: min(100%,680px); height: 100%; color: var(--color-font-button); pointer-events: none; }
  .story-copy { display: flex; align-items: center; justify-content: center; gap: 8px; font-size: clamp(.8rem,2cqi,1rem); font-weight: 800; text-align: center; }
  .scroll-list { display: grid; gap: 7px; max-height: 150px; overflow: hidden; padding: 5px; mask-image: linear-gradient(transparent, black 12%, black 88%, transparent); }
  .story-row { display: grid; grid-template-columns: 38px 1fr auto; align-items: center; gap: 9px; min-height: 46px; padding: 6px 10px; border: 1px solid rgba(255,255,255,.16); border-radius: 14px; background: rgba(255,255,255,.12); opacity: .42; transform: scale(.96); transition: opacity 260ms ease, transform 260ms ease, background 260ms ease; }
  .story-row.active { background: rgba(255,255,255,.23); opacity: 1; transform: scale(1); box-shadow: var(--shadow-md); }
  .story-row strong { display: block; font-size: .76rem; }
  .story-row small { display: block; max-width: 280px; overflow: hidden; font-size: .61rem; opacity: .7; text-overflow: ellipsis; white-space: nowrap; }
  .mate-profile { display: block; width: 34px !important; height: 34px !important; }
  .focus-icon { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: rgba(255,255,255,.16); }
  .active-check { display: grid; place-items: center; color: var(--color-font-button); }

  @container chat-side (max-width: 560px) {
    .mates-focus-demo { grid-template-columns: 1fr; gap: 7px; }
    .story-copy { font-size: .72rem; }
    .scroll-list { width: min(100%,360px); max-height: 112px; margin: auto; gap: 4px; }
    .story-row { min-height: 34px; padding: 3px 8px; grid-template-columns: 28px 1fr auto; }
    .mate-profile, .focus-icon { width: 26px !important; height: 26px !important; }
    .story-row small { display: none; }
  }

  @media (prefers-reduced-motion: reduce) { .story-row { transition: none; } }
  @media (prefers-reduced-motion: reduce) {
    .mates-focus-demo { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .story-copy { display: none; }
    .scroll-list { max-height: 138px; }
    .story-row { min-height: 34px; padding: 3px 7px; }
    .story-row small { display: none; }
  }
</style>
