<script lang="ts">
  /**
   * LandingPrivacySafetyDemo.svelte
   *
   * Deterministic privacy explainer for encryption-at-storage, client-side PII
   * placeholders, and explicit memory consent. It is presentation-only and
   * never handles real visitor data.
   */

  import { onMount } from 'svelte';
  import { text } from '@repo/ui';
  import { getLucideIcon } from '../../utils/categoryUtils';
  import {
    PRIVACY_STORY_STAGES,
    type PrivacyStoryStage,
  } from './landingProductStoryTimelines';

  interface Props {
    playing: boolean;
    reducedMotion: boolean;
    onComplete: () => void;
  }

  let { playing, reducedMotion, onComplete }: Props = $props();
  let activeStageIndex = $state(0);
  let mounted = $state(false);

  const LockIcon = getLucideIcon('lock');
  const MessageIcon = getLucideIcon('message-circle');
  const MemoryIcon = getLucideIcon('brain');
  const ProjectIcon = getLucideIcon('folder');
  const TaskIcon = getLucideIcon('list-check');
  const CheckIcon = getLucideIcon('check');
  const PlaneIcon = getLucideIcon('plane');

  let activeStage = $derived<PrivacyStoryStage>(
    PRIVACY_STORY_STAGES[activeStageIndex]?.id ?? PRIVACY_STORY_STAGES[0].id,
  );

  onMount(() => {
    mounted = true;
  });

  $effect(() => {
    if (!mounted || reducedMotion || !playing) {
      activeStageIndex = 0;
      return;
    }

    activeStageIndex = 0;
    const timeouts: number[] = [];
    let elapsedMs = 0;
    PRIVACY_STORY_STAGES.forEach((stage, index) => {
      if (index > 0) {
        timeouts.push(window.setTimeout(() => {
          activeStageIndex = index;
        }, elapsedMs));
      }
      elapsedMs += stage.durationMs;
    });
    timeouts.push(window.setTimeout(onComplete, elapsedMs));

    return () => timeouts.forEach((timeout) => window.clearTimeout(timeout));
  });
</script>

<div
  class="privacy-demo"
  data-testid="landing-privacy-safety-demo"
  data-active-stage={activeStage}
  data-reduced-motion={reducedMotion ? 'true' : 'false'}
  data-playing={playing ? 'true' : 'false'}
  aria-hidden="true"
>
  {#if reducedMotion}
    <div class="privacy-summary" data-testid="landing-privacy-summary">
      <div><LockIcon size={22} /> <span>{$text('demo_chats.for_everyone.landing_privacy_saved_data')}</span></div>
      <div><MessageIcon size={22} /> <span>{$text('demo_chats.for_everyone.landing_privacy_pii')}</span></div>
      <div><MemoryIcon size={22} /> <span>{$text('demo_chats.for_everyone.landing_privacy_memory')}</span></div>
    </div>
  {:else if activeStage === 'encryption'}
    <div class="privacy-stage encryption-stage" data-testid="landing-privacy-encryption">
      <div class="data-orbit" aria-hidden="true">
        <span class="data-icon chat"><MessageIcon size={22} /></span>
        <span class="data-icon memory"><MemoryIcon size={22} /></span>
        <span class="data-icon project"><ProjectIcon size={22} /></span>
        <span class="data-icon task"><TaskIcon size={22} /></span>
        <span class="lock-core"><LockIcon size={34} /></span>
      </div>
      <p>{$text('demo_chats.for_everyone.landing_privacy_saved_data')}</p>
    </div>
  {:else if activeStage === 'pii'}
    <div class="privacy-stage pii-stage">
      <p class="stage-label">{$text('demo_chats.for_everyone.landing_privacy_pii')}</p>
      <div class="pii-message pii-user">
        <span class="pii-original" data-testid="landing-privacy-pii-original">alex@example.com</span>
        <span class="pii-placeholder" data-testid="landing-privacy-pii-placeholder">[EMAIL_com]</span>
      </div>
      <div class="pii-arrow" aria-hidden="true">↓</div>
      <div class="pii-message pii-assistant">
        <span class="assistant-placeholder">[EMAIL_com]</span>
        <span class="assistant-original">alex@example.com</span>
      </div>
    </div>
  {:else}
    <div class="privacy-stage memory-stage">
      <div class="memory-request"><PlaneIcon size={18} /> {$text('demo_chats.for_everyone.landing_privacy_trip_request')}</div>
      <div class="memory-consent" data-testid="landing-privacy-memory-consent">
        <div class="memory-consent-title"><MemoryIcon size={20} /> {$text('demo_chats.for_everyone.landing_privacy_memory')}</div>
        <span class="memory-chip"><CheckIcon size={14} /> {$text('demo_chats.for_everyone.landing_privacy_previous_trips')}</span>
        <span class="memory-chip"><CheckIcon size={14} /> {$text('demo_chats.for_everyone.landing_privacy_favorite_places')}</span>
      </div>
      <p>{$text('demo_chats.for_everyone.landing_privacy_memory_result')}</p>
    </div>
  {/if}
</div>

<style>
  .privacy-demo {
    width: min(100%, 620px);
    height: 100%;
    min-height: 0;
    color: var(--color-font-button);
    pointer-events: none;
  }

  .privacy-stage,
  .privacy-summary {
    display: grid;
    place-items: center;
    align-content: center;
    width: 100%;
    height: 100%;
    gap: 10px;
    text-align: center;
    animation: stageEnter 320ms cubic-bezier(0.22, 1, 0.36, 1) both;
  }

  .privacy-stage p { margin: 0; font-size: clamp(0.78rem, 2.2cqi, 1rem); font-weight: 700; }

  .data-orbit { position: relative; width: 210px; height: 96px; }
  .data-icon,
  .lock-core {
    position: absolute;
    display: grid;
    place-items: center;
    border: 1px solid rgba(255,255,255,.24);
    background: rgba(255,255,255,.14);
    box-shadow: var(--shadow-sm);
    backdrop-filter: blur(10px);
  }
  .data-icon { width: 42px; height: 42px; border-radius: var(--radius-full); animation: protectData 900ms ease-out both; }
  .data-icon.chat { left: 0; top: 8px; }
  .data-icon.memory { right: 0; top: 8px; }
  .data-icon.project { left: 32px; bottom: 0; }
  .data-icon.task { right: 32px; bottom: 0; }
  .lock-core { inset: 18px 72px auto; width: 66px; height: 66px; border-radius: var(--radius-full); background: rgba(255,255,255,.24); animation: closeLock 800ms 400ms cubic-bezier(0.22,1,.36,1) both; }

  .stage-label { opacity: .82; }
  .pii-message { width: min(88%, 360px); padding: 10px 14px; border-radius: 14px; font-size: clamp(.72rem, 2cqi, .92rem); font-weight: 700; box-shadow: var(--shadow-md); }
  .pii-user { justify-self: end; background: var(--color-grey-blue); color: var(--color-font-primary); }
  .pii-assistant { justify-self: start; background: var(--color-grey-0); color: var(--color-font-primary); }
  .pii-original { padding: 1px 4px; border-radius: 5px; background: var(--color-highlight-yellow); animation: hideOriginal 5s linear both; }
  .pii-placeholder { display: inline-block; margin-left: -128px; padding: 1px 4px; border-radius: 5px; background: rgba(74,222,128,.24); color: var(--color-font-primary); opacity: 0; animation: showPlaceholder 5s linear both; }
  .assistant-placeholder { color: var(--color-font-tertiary); animation: hideAssistantPlaceholder 5s linear both; }
  .assistant-original { display: inline-block; margin-left: -78px; color: var(--color-button-primary); opacity: 0; animation: showAssistantOriginal 5s linear both; }
  .pii-arrow { opacity: .65; }

  .memory-request { display: flex; align-items: center; gap: 8px; padding: 9px 14px; border-radius: 14px; background: var(--color-grey-blue); color: var(--color-font-primary); font-size: clamp(.72rem, 2cqi, .9rem); font-weight: 700; }
  .memory-consent { display: flex; flex-wrap: wrap; justify-content: center; gap: 6px; width: min(90%, 420px); padding: 10px; border-radius: 16px; background: var(--color-grey-0); color: var(--color-font-primary); box-shadow: var(--shadow-md); }
  .memory-consent-title { display: flex; justify-content: center; align-items: center; gap: 7px; width: 100%; font-size: .78rem; font-weight: 800; }
  .memory-chip { display: flex; align-items: center; gap: 4px; padding: 5px 9px; border-radius: var(--radius-full); background: var(--color-grey-20); font-size: .68rem; font-weight: 700; }

  .privacy-summary { grid-template-columns: repeat(3, minmax(0,1fr)); }
  .privacy-summary div { display: grid; place-items: center; gap: 7px; font-size: clamp(.66rem, 1.8cqi, .82rem); font-weight: 700; }

  @container chat-side (max-width: 560px) {
    .privacy-stage, .privacy-summary { gap: 5px; }
    .privacy-stage p { font-size: .68rem; }
    .data-orbit { width: 180px; height: 76px; }
    .data-icon { width: 34px; height: 34px; }
    .data-icon.chat, .data-icon.memory { top: 4px; }
    .data-icon.project { left: 28px; }
    .data-icon.task { right: 28px; }
    .lock-core { inset: 11px 63px auto; width: 54px; height: 54px; }
    .pii-message { padding: 6px 10px; }
    .memory-request { padding: 5px 9px; }
    .memory-consent { gap: 3px; padding: 5px; }
    .memory-chip { padding: 3px 6px; }
  }

  @keyframes stageEnter { from { opacity: 0; transform: translateY(10px) scale(.97); } to { opacity: 1; transform: none; } }
  @keyframes protectData { from { opacity: .3; transform: scale(.86); } to { opacity: 1; transform: none; } }
  @keyframes closeLock { from { opacity: .4; transform: scale(.82) rotate(-8deg); } to { opacity: 1; transform: none; } }
  @keyframes hideOriginal { 0%,30% { opacity: 1; } 42%,100% { opacity: 0; } }
  @keyframes showPlaceholder { 0%,34% { opacity: 0; } 46%,100% { opacity: 1; } }
  @keyframes hideAssistantPlaceholder { 0%,62% { opacity: 1; } 76%,100% { opacity: 0; } }
  @keyframes showAssistantOriginal { 0%,68% { opacity: 0; } 82%,100% { opacity: 1; } }

  @media (prefers-reduced-motion: reduce) {
    .privacy-stage, .privacy-summary, .data-icon, .lock-core, .pii-original, .pii-placeholder, .assistant-placeholder, .assistant-original { animation: none !important; }
  }
</style>
