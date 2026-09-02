<script lang="ts">
  /**
   * LandingPeopleExperienceDemo.svelte
   *
   * Deterministic provider-choice and cross-platform access story. Provider
   * identities and example commands describe existing product surfaces only.
   */

  import { onMount } from 'svelte';
  import { text } from '@repo/ui';
  import { getLucideIcon } from '../../utils/categoryUtils';
  import ProviderIcon from '../settings/ProviderIcon.svelte';
  import LandingSubslideMotion from './LandingSubslideMotion.svelte';
  import {
    PEOPLE_EXPERIENCE_STORY_DURATION_MS,
    PEOPLE_EXPERIENCE_STORY_STAGES,
    type PeopleExperienceStoryStage,
  } from './landingProductStoryTimelines';

  interface Props { playing: boolean; reducedMotion: boolean; onComplete: () => void; }
  let { playing, reducedMotion, onComplete }: Props = $props();
  let activeStageIndex = $state(0);
  let activeProviderIndex = $state(0);
  let activeAccessIndex = $state(0);
  let mounted = $state(false);

  const GlobeIcon = getLucideIcon('globe');
  const TerminalIcon = getLucideIcon('terminal');
  const CodeIcon = getLucideIcon('code-2');
  const providers = [
    { id: 'google', providerName: 'Google', name: 'Google Gemini' },
    { id: 'anthropic', providerName: 'Anthropic', name: 'Anthropic Claude' },
    { id: 'openai', providerName: 'OpenAI', name: 'OpenAI' },
    { id: 'mistral', providerName: 'Mistral AI', name: 'Mistral' },
  ];
  const access = [
    { id: 'web', label: 'Web', icon: GlobeIcon },
    { id: 'cli', label: 'CLI', icon: TerminalIcon },
    { id: 'sdk', label: 'SDK', icon: CodeIcon },
  ];
  let activeStage = $derived<PeopleExperienceStoryStage>(PEOPLE_EXPERIENCE_STORY_STAGES[activeStageIndex]?.id ?? 'providers-copy');
  let activeStageDurationMs = $derived(PEOPLE_EXPERIENCE_STORY_STAGES[activeStageIndex]?.durationMs ?? PEOPLE_EXPERIENCE_STORY_STAGES[0].durationMs);
  let activeAccess = $derived(access[activeAccessIndex] ?? access[0]);

  onMount(() => { mounted = true; });

  $effect(() => {
    if (!mounted || reducedMotion || !playing) { activeStageIndex = 0; activeProviderIndex = 0; activeAccessIndex = 0; return; }
    activeStageIndex = 0;
    activeProviderIndex = 0;
    activeAccessIndex = 0;
    const timeouts: number[] = [];
    let elapsedMs = 0;
    PEOPLE_EXPERIENCE_STORY_STAGES.forEach((stage, index) => {
      const stageStartMs = elapsedMs;
      if (index > 0) timeouts.push(window.setTimeout(() => { activeStageIndex = index; }, stageStartMs));
      if (stage.id === 'providers') {
        [1, 2, 3].forEach((providerIndex) => timeouts.push(window.setTimeout(() => { activeProviderIndex = providerIndex; }, stageStartMs + 500 + providerIndex * 800)));
      } else if (stage.id === 'access') {
        [1, 2].forEach((accessIndex) => timeouts.push(window.setTimeout(() => { activeAccessIndex = accessIndex; }, stageStartMs + 500 + accessIndex * 1100)));
      }
      elapsedMs += stage.durationMs;
    });
    timeouts.push(window.setTimeout(onComplete, PEOPLE_EXPERIENCE_STORY_DURATION_MS));
    return () => timeouts.forEach((timeout) => window.clearTimeout(timeout));
  });
</script>

<div class="people-demo" data-testid="landing-people-experience-demo" data-active-stage={activeStage} data-reduced-motion={reducedMotion ? 'true' : 'false'} data-playing={playing ? 'true' : 'false'} aria-hidden="true">
  {#if reducedMotion}
    <div class="reduced-summary">
      <div class="provider-grid">
        {#each providers as provider}
          <div class="provider-card active" data-testid="landing-provider-logo" data-provider-id={provider.id}>
            <ProviderIcon name={provider.providerName} size="32px" />
            <span>{provider.name}</span>
          </div>
        {/each}
      </div>
      <div class="access-flow">
        <div class="access-node active" data-testid="landing-platform-node" data-platform={activeAccess.id}>
          <span class="platform-icon"><GlobeIcon size={22} /></span>
          <strong data-testid="landing-platform-label">{activeAccess.label}</strong>
          <div class="web-url-field" data-testid="landing-platform-url">OpenMates.org</div>
        </div>
      </div>
    </div>
  {:else}
    {#key activeStage}
    <LandingSubslideMotion {playing} durationMs={activeStageDurationMs} stage={activeStage}>
      {#if activeStage === 'providers-copy'}
        <p class="story-copy" data-testid="landing-providers-copy">{$text('guest_onboarding.landing_people_models')}</p>
      {:else if activeStage === 'providers' || reducedMotion}
        <div class="provider-grid">
          {#each providers as provider, index}
            <div class:active={reducedMotion || index === activeProviderIndex} class="provider-card" data-testid="landing-provider-logo" data-provider-id={provider.id}>
              <ProviderIcon name={provider.providerName} size="32px" />
              <span>{provider.name}</span>
            </div>
          {/each}
        </div>
      {:else if activeStage === 'access-copy'}
        <p class="story-copy" data-testid="landing-access-copy">{$text('guest_onboarding.landing_people_access')}</p>
      {:else}
        <div class="access-flow">
          {#key activeAccess.id}
            {@const AccessIcon = activeAccess.icon}
            <div class="access-node active" data-testid="landing-platform-node" data-platform={activeAccess.id}>
              <span class="platform-icon"><AccessIcon size={22} /></span>
              <strong data-testid="landing-platform-label">{activeAccess.label}</strong>
              {#if activeAccess.id === 'web'}
                <div class="web-url-field" data-testid="landing-platform-url">OpenMates.org</div>
              {:else if activeAccess.id === 'cli'}
                <div class="terminal-card" data-testid="landing-platform-command"><span>$</span><code>npm install -g openmates</code></div>
              {:else}
                <pre class="sdk-card" data-testid="landing-platform-sdk"><code>from openmates import OpenMates
# Open & create chats, memories & more.</code></pre>
              {/if}
            </div>
          {/key}
        </div>
      {/if}
      </LandingSubslideMotion>
    {/key}
  {/if}
</div>

<style>
  .people-demo { display: grid; place-items: center; align-content: center; gap: 12px; width: min(100%,680px); height: 100%; color: var(--color-font-button); pointer-events: none; }
  .reduced-summary { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); align-items: center; gap: 8px; width: 100%; }
  .story-copy { max-width: 30rem; margin: 0; font-size: clamp(1.3rem,3.8cqi,1.7rem); font-weight: 800; line-height: 1.35; text-align: center; text-wrap: balance; }
  .provider-grid { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 9px; width: min(100%,570px); }
  .provider-card { display: grid; place-items: center; gap: 7px; min-height: 86px; padding: 10px; border: 1px solid rgba(255,255,255,.16); border-radius: 16px; background: rgba(255,255,255,.12); opacity: .38; transform: scale(.94); transition: opacity 260ms ease, transform 260ms ease, background 260ms ease; }
  .provider-card.active { background: rgba(255,255,255,.24); opacity: 1; transform: scale(1); box-shadow: var(--shadow-md); }
  .provider-card span { font-size: .68rem; font-weight: 800; text-align: center; }
  .access-flow { display: grid; place-items: center; width: min(100%,620px); min-height: 120px; }
  .access-node { display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 9px 10px; width: min(100%,430px); min-height: 112px; padding: 14px; border: 1px solid rgba(255,255,255,.16); border-radius: 18px; background: rgba(255,255,255,.18); opacity: 0; transform: translateY(8px); transition: opacity 280ms ease, transform 280ms ease, background 280ms ease; }
  .access-node.active { opacity: 1; transform: none; box-shadow: var(--shadow-md); }
  .platform-icon { display: grid; place-items: center; width: 38px; height: 38px; border-radius: 12px; background: rgba(255,255,255,.18); }
  .access-node strong { font-size: .82rem; }
  .web-url-field { grid-column: 1 / -1; display: flex; align-items: center; min-height: 38px; padding: 0 14px; border-radius: var(--radius-full); background: rgba(255,255,255,.92); color: var(--color-font-primary); font-size: .82rem; font-weight: 800; box-shadow: var(--shadow-sm); }
  .terminal-card, .sdk-card { grid-column: 1 / -1; width: 100%; margin: 0; box-sizing: border-box; border-radius: 12px; background: rgba(13,13,13,.92); color: #f5f5f5; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: .72rem; line-height: 1.45; box-shadow: inset 0 0 0 1px rgba(255,255,255,.08); }
  .terminal-card { display: flex; align-items: center; gap: 8px; min-height: 42px; padding: 0 13px; }
  .terminal-card span { color: #74d97a; }
  .terminal-card code, .sdk-card code { color: inherit; font: inherit; }
  .sdk-card { padding: 11px 13px; white-space: pre-wrap; }

  @container chat-side (max-width: 560px) {
    .people-demo { gap: 7px; }
    .story-copy { font-size: 1.25rem; }
    .provider-grid { gap: 5px; }
    .provider-card { min-height: 58px; padding: 3px; gap: 3px; }
    .provider-card span { font-size: .55rem; }
    .access-flow { min-height: 96px; }
    .access-node { width: min(100%,340px); min-height: 86px; padding: 9px; }
    .platform-icon { width: 30px; height: 30px; }
    .web-url-field { min-height: 32px; font-size: .72rem; }
    .terminal-card, .sdk-card { font-size: .6rem; }
  }

  @media (prefers-reduced-motion: reduce) { .provider-card, .access-node { transition: none; } }
  @media (prefers-reduced-motion: reduce) {
    .people-demo { gap: 8px; }
    .story-copy { display: none; }
    .provider-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .provider-card, .access-node { min-height: 58px; padding: 5px; }
  }
</style>
