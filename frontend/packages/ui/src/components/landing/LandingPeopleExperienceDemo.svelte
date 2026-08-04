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
    { id: 'web', label: 'Web', detail: 'app.openmates.org', icon: GlobeIcon },
    { id: 'cli', label: 'CLI', detail: 'openmates chats list', icon: TerminalIcon },
    { id: 'sdk', label: 'SDK', detail: 'await client.chats.list()', icon: CodeIcon },
  ];
  let activeStage = $derived<PeopleExperienceStoryStage>(PEOPLE_EXPERIENCE_STORY_STAGES[activeStageIndex]?.id ?? 'providers');

  onMount(() => { mounted = true; });

  $effect(() => {
    if (!mounted || reducedMotion || !playing) { activeStageIndex = 0; activeProviderIndex = 0; activeAccessIndex = 0; return; }
    activeStageIndex = 0;
    activeProviderIndex = 0;
    activeAccessIndex = 0;
    const timeouts: number[] = [];
    [1, 2, 3].forEach((index) => timeouts.push(window.setTimeout(() => { activeProviderIndex = index; }, 900 + index * 1100)));
    const accessStartMs = PEOPLE_EXPERIENCE_STORY_STAGES[0].durationMs;
    timeouts.push(window.setTimeout(() => { activeStageIndex = 1; }, accessStartMs));
    [1, 2].forEach((index) => timeouts.push(window.setTimeout(() => { activeAccessIndex = index; }, accessStartMs + 900 + index * 1500)));
    timeouts.push(window.setTimeout(onComplete, PEOPLE_EXPERIENCE_STORY_DURATION_MS));
    return () => timeouts.forEach((timeout) => window.clearTimeout(timeout));
  });
</script>

<div class="people-demo" data-testid="landing-people-experience-demo" data-active-stage={activeStage} data-reduced-motion={reducedMotion ? 'true' : 'false'} data-playing={playing ? 'true' : 'false'} aria-hidden="true">
  {#if activeStage === 'providers' || reducedMotion}
    <p class="story-copy">{$text('demo_chats.for_everyone.landing_people_models')}</p>
    <div class="provider-grid">
      {#each providers as provider, index}
        <div class:active={reducedMotion || index === activeProviderIndex} class="provider-card" data-testid="landing-provider-logo" data-provider-id={provider.id}>
          <ProviderIcon name={provider.providerName} size="32px" />
          <span>{provider.name}</span>
        </div>
      {/each}
    </div>
  {/if}
  {#if activeStage === 'access' || reducedMotion}
    <p class="story-copy">{$text('demo_chats.for_everyone.landing_people_access')}</p>
    <div class="access-flow">
      {#each access as item, index}
        {@const AccessIcon = item.icon}
        <div class:active={index <= activeAccessIndex} class="access-node" data-testid="landing-platform-node" data-platform={item.id}>
          <AccessIcon size={21} />
          <strong data-testid="landing-platform-label">{item.label}</strong>
          <code>{item.detail}</code>
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .people-demo { display: grid; place-items: center; align-content: center; gap: 12px; width: min(100%,680px); height: 100%; color: var(--color-font-button); pointer-events: none; }
  .story-copy { margin: 0; font-size: clamp(.8rem,2.1cqi,1rem); font-weight: 800; text-align: center; }
  .provider-grid { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 9px; width: min(100%,570px); }
  .provider-card { display: grid; place-items: center; gap: 7px; min-height: 86px; padding: 10px; border: 1px solid rgba(255,255,255,.16); border-radius: 16px; background: rgba(255,255,255,.12); opacity: .38; transform: scale(.94); transition: opacity 260ms ease, transform 260ms ease, background 260ms ease; }
  .provider-card.active { background: rgba(255,255,255,.24); opacity: 1; transform: scale(1); box-shadow: var(--shadow-md); }
  .provider-card span { font-size: .68rem; font-weight: 800; text-align: center; }
  .access-flow { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 10px; width: min(100%,620px); }
  .access-node { display: grid; place-items: center; gap: 5px; min-height: 92px; padding: 10px; border: 1px solid rgba(255,255,255,.16); border-radius: 16px; background: rgba(255,255,255,.1); opacity: .3; transform: translateY(8px); transition: opacity 280ms ease, transform 280ms ease, background 280ms ease; }
  .access-node.active { background: rgba(255,255,255,.22); opacity: 1; transform: none; }
  .access-node strong { font-size: .82rem; }
  .access-node code { max-width: 100%; overflow: hidden; color: var(--color-font-button); font-size: .58rem; text-overflow: ellipsis; white-space: nowrap; }

  @container chat-side (max-width: 560px) {
    .provider-grid { gap: 5px; }
    .provider-card { min-height: 62px; padding: 5px; }
    .provider-card span { font-size: .55rem; }
    .access-flow { gap: 5px; }
    .access-node { min-height: 66px; padding: 5px; }
    .access-node code { display: none; }
  }

  @media (prefers-reduced-motion: reduce) { .provider-card, .access-node { transition: none; } }
  @media (prefers-reduced-motion: reduce) {
    .people-demo { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .story-copy { display: none; }
    .provider-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .provider-card, .access-node { min-height: 58px; padding: 5px; }
    .access-flow { grid-template-columns: 1fr; }
    .access-node code { display: none; }
  }
</style>
