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
  import LandingSubslideMotion from './LandingSubslideMotion.svelte';
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

  const selectedMateIds = ['software_development', 'medical_health', 'marketing_sales', 'general_knowledge'];
  const selectedMates = matesMetadata.filter((mate) => selectedMateIds.includes(mate.id));
  const focusModes = [
    { id: 'project-planner', labelKey: 'app_focus_modes.code.project_planner', icon: 'list-check' },
    { id: 'research-solutions', labelKey: 'app_focus_modes.code.research_solutions', icon: 'search' },
    { id: 'learn-by-building', labelKey: 'app_focus_modes.code.learn_by_building', icon: 'graduation-cap' },
  ];
  let activeStage = $derived<MatesFocusStoryStage>(MATES_FOCUS_STORY_STAGES[activeStageIndex]?.id ?? 'mates-copy');
  let activeStageDurationMs = $derived(MATES_FOCUS_STORY_STAGES[activeStageIndex]?.durationMs ?? MATES_FOCUS_STORY_STAGES[0].durationMs);
  let activeScrollIndex = $derived(
    activeStage === 'focus'
      ? Math.min(activeItemIndex, focusModes.length - 1)
      : Math.min(activeItemIndex, selectedMates.length - 1),
  );

  onMount(() => { mounted = true; });

  $effect(() => {
    if (!mounted || reducedMotion || !playing) { activeStageIndex = 0; activeItemIndex = 0; return; }
    activeStageIndex = 0;
    activeItemIndex = 0;
    const timeouts: number[] = [];
    let elapsedMs = 0;
    MATES_FOCUS_STORY_STAGES.forEach((stage, index) => {
      const stageStartMs = elapsedMs;
      if (index > 0) timeouts.push(window.setTimeout(() => { activeStageIndex = index; activeItemIndex = 0; }, stageStartMs));
      if (stage.id === 'mates') {
        [1, 2, 3].forEach((itemIndex) => timeouts.push(window.setTimeout(() => { activeItemIndex = itemIndex; }, stageStartMs + 500 + itemIndex * 800)));
      } else if (stage.id === 'focus') {
        [1, 2].forEach((itemIndex) => timeouts.push(window.setTimeout(() => { activeItemIndex = itemIndex; }, stageStartMs + 600 + itemIndex * 1100)));
      }
      elapsedMs += stage.durationMs;
    });
    timeouts.push(window.setTimeout(onComplete, MATES_FOCUS_STORY_DURATION_MS));
    return () => timeouts.forEach((timeout) => window.clearTimeout(timeout));
  });
</script>

<div class="mates-focus-demo" style={`--scroll-index: ${activeScrollIndex}`} data-testid="landing-mates-focus-demo" data-active-stage={activeStage} data-reduced-motion={reducedMotion ? 'true' : 'false'} data-playing={playing ? 'true' : 'false'} aria-hidden="true">
  {#if reducedMotion}
    <div class="reduced-summary">
      <div class="scroll-window mates-window">
        <div class="scroll-track">
          {#each selectedMates as mate}
            <div class="mate-row-demo active" data-testid="landing-mate-profile" data-mate-id={mate.id}>
              <span class="mate-profile {mate.profile_class} mate-profile-demo"></span>
              <span class="mate-text-demo"><strong>{$text(mate.name_translation_key)}</strong><small>{$text(mate.description_translation_key)}</small></span>
              <span class="mate-chevron-demo"></span>
            </div>
          {/each}
        </div>
      </div>
      <div class="scroll-window focus-window">
        <div class="scroll-track">
          {#each focusModes as mode}
            {@const ModeIcon = getLucideIcon(mode.icon)}
            <div class="focus-pill-demo active" data-testid="landing-focus-mode" data-focus-id={mode.id}>
              <span class="focus-pill-body-demo">
                <span class="focus-pill-icon-demo"><ModeIcon size={15} /></span>
                <span class="focus-pill-label-demo">{$text(mode.labelKey)}</span>
                <span class="focus-pill-on-demo">Focus on</span>
              </span>
              <span class="focus-pill-toggle-demo" aria-hidden="true"><span></span></span>
            </div>
          {/each}
        </div>
      </div>
    </div>
  {:else}
    {#key activeStage}
    <LandingSubslideMotion {playing} durationMs={activeStageDurationMs} stage={activeStage}>
      {#if activeStage === 'mates-copy'}
        <p class="story-copy" data-testid="landing-mates-copy">{$text('guest_onboarding.landing_mates_experts')}</p>
      {:else if activeStage === 'mates' || reducedMotion}
        <div class="story-stage">
          <div class="scroll-window mates-window">
            <div class="scroll-track">
              {#each selectedMates as mate, index}
                <div class:active={reducedMotion || index === activeItemIndex} class="mate-row-demo" data-testid="landing-mate-profile" data-mate-id={mate.id}>
                  <span class="mate-profile {mate.profile_class} mate-profile-demo"></span>
                  <span class="mate-text-demo"><strong>{$text(mate.name_translation_key)}</strong><small>{$text(mate.description_translation_key)}</small></span>
                  <span class="mate-chevron-demo"></span>
                </div>
              {/each}
            </div>
          </div>
        </div>
      {:else if activeStage === 'focus-copy'}
        <p class="story-copy" data-testid="landing-focus-copy">{$text('guest_onboarding.landing_mates_focus_modes')}</p>
      {:else}
        <div class="story-stage">
          <div class="scroll-window focus-window">
            <div class="scroll-track">
              {#each focusModes as mode, index}
                {@const ModeIcon = getLucideIcon(mode.icon)}
                <div class:active={reducedMotion || index === activeItemIndex} class="focus-pill-demo" data-testid="landing-focus-mode" data-focus-id={mode.id}>
                  <span class="focus-pill-body-demo">
                    <span class="focus-pill-icon-demo"><ModeIcon size={15} /></span>
                    <span class="focus-pill-label-demo">{$text(mode.labelKey)}</span>
                    <span class="focus-pill-on-demo">Focus on</span>
                  </span>
                  <span class="focus-pill-toggle-demo" aria-hidden="true"><span></span></span>
                </div>
              {/each}
            </div>
          </div>
        </div>
      {/if}
      </LandingSubslideMotion>
    {/key}
  {/if}
</div>

<style>
  .mates-focus-demo { --demo-row-step: 58px; display: grid; place-items: center; width: min(100%,680px); height: 100%; color: var(--color-font-button); pointer-events: none; }
  .reduced-summary { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px; width: 100%; }
  .story-stage { display: grid; place-items: center; width: 100%; height: 100%; }
  .story-copy { max-width: 30rem; margin: 0; font-size: clamp(1.3rem,3.8cqi,1.7rem); font-weight: 800; line-height: 1.35; text-align: center; text-wrap: balance; }
  .scroll-window { width: min(100%, 420px); height: 176px; overflow: hidden; padding: 6px; mask-image: linear-gradient(transparent, black 12%, black 88%, transparent); }
  .scroll-track { display: grid; gap: 8px; transform: translateY(calc(var(--scroll-index) * var(--demo-row-step) * -1)); transition: transform 520ms cubic-bezier(0.22, 1, 0.36, 1); }
  .mate-row-demo { display: grid; grid-template-columns: 48px 1fr auto; align-items: center; min-height: 50px; padding: 3px 12px 3px 0; border-radius: var(--radius-3); background: rgba(255,255,255,.9); opacity: .52; transform: scale(.96); transition: opacity 260ms ease, transform 260ms ease, background 260ms ease; }
  .mate-row-demo.active { background: rgba(255,255,255,.98); opacity: 1; transform: scale(1); box-shadow: var(--shadow-md); }
  .mate-profile-demo { width: 38px !important; height: 38px !important; margin: 6px 8px 6px 10px; }
  .mate-profile-demo::before, .mate-profile-demo::after { display: none !important; }
  .mate-text-demo { display: flex; min-width: 0; flex-direction: column; gap: 1px; }
  .mate-text-demo strong { overflow: hidden; color: #1f2937; font-size: .82rem; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
  .mate-text-demo small { overflow: hidden; color: #4b5563; font-size: .64rem; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }
  .mate-chevron-demo { width: 7px; height: 7px; margin-left: 8px; border-right: 2px solid var(--color-grey-50); border-top: 2px solid var(--color-grey-50); transform: rotate(45deg); }
  .focus-window { display: grid; align-content: center; }
  .focus-pill-demo { display: flex; align-items: center; justify-self: center; height: 36px; max-width: min(100%,360px); overflow: hidden; border-radius: 20px; background: rgba(255,255,255,.24); opacity: .44; transform: scale(.96); box-shadow: var(--shadow-sm); transition: opacity 260ms ease, transform 260ms ease, background 260ms ease; }
  .focus-pill-demo.active { background: var(--color-app-code, linear-gradient(135deg, #155d91, #42abf4)); opacity: 1; transform: scale(1); box-shadow: var(--shadow-md); }
  .focus-pill-body-demo { display: flex; align-items: center; gap: 6px; min-width: 0; height: 100%; padding: 0 10px 0 12px; color: white; font-size: .78rem; font-weight: 700; }
  .focus-pill-icon-demo { display: grid; flex-shrink: 0; place-items: center; width: 16px; height: 16px; }
  .focus-pill-label-demo { overflow: hidden; max-width: 150px; text-overflow: ellipsis; white-space: nowrap; }
  .focus-pill-on-demo { flex-shrink: 0; opacity: .8; font-weight: 500; }
  .focus-pill-toggle-demo { display: grid; flex-shrink: 0; place-items: center; height: 100%; padding: 0 8px; border-left: 1px solid rgba(255,255,255,.25); }
  .focus-pill-toggle-demo span { width: 16px; height: 16px; border-radius: var(--radius-full); background: rgba(255,255,255,.82); box-shadow: inset 0 0 0 3px rgba(255,255,255,.3); }

  :global([data-theme="dark"]) .mate-row-demo { background: rgba(23, 23, 23, .82); border: 1px solid rgba(255,255,255,.14); }
  :global([data-theme="dark"]) .mate-row-demo.active { background: rgba(37, 37, 42, .96); box-shadow: 0 12px 28px rgba(0,0,0,.35); }
  :global([data-theme="dark"]) .mate-text-demo strong { color: rgba(255,255,255,.95); }
  :global([data-theme="dark"]) .mate-text-demo small { color: rgba(255,255,255,.72); }
  :global([data-theme="dark"]) .mate-chevron-demo { border-color: rgba(255,255,255,.5); }

  @container chat-side (max-width: 560px) {
    .mates-focus-demo { --demo-row-step: 48px; }
    .story-copy { font-size: 1.25rem; }
    .scroll-window { width: min(100%,380px); height: 112px; margin: auto; padding: 0 5px; }
    .mate-row-demo { grid-template-columns: 38px 1fr auto; min-height: 42px; }
    .mate-profile-demo { width: 28px !important; height: 28px !important; margin: 4px 5px; }
    .mate-text-demo small { display: block; font-size: .58rem; }
    .focus-window { height: 118px; align-content: center; }
    .focus-pill-demo { width: min(100%,340px); max-width: min(100%,340px); }
    .focus-pill-label-demo { max-width: 145px; }
  }

  @media (prefers-reduced-motion: reduce) { .scroll-track, .mate-row-demo, .focus-pill-demo { transition: none; } }
  @media (prefers-reduced-motion: reduce) {
    .mates-focus-demo { gap: 8px; }
    .story-stage { grid-template-columns: 1fr; gap: 6px; }
    .story-copy { display: none; }
    .scroll-window { height: 138px; }
    .scroll-track { transform: none; }
    .mate-row-demo { min-height: 34px; }
    .mate-text-demo small { display: none; }
  }
</style>
