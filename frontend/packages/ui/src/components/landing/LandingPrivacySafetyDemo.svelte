<script lang="ts">
  /**
   * LandingPrivacySafetyDemo.svelte
   *
   * Nine-scene privacy story built from product-faithful chat, PII, and memory
   * permission surfaces. The story is deterministic, presentation-only, and
   * never reads or writes visitor data or live permission stores.
   */

  import { onMount } from 'svelte';
  import { text } from '@repo/ui';
  import AppSettingsMemoriesPermissionDialog from '../AppSettingsMemoriesPermissionDialog.svelte';
  import { getLucideIcon } from '../../utils/categoryUtils';
  import LandingSubslideMotion from './LandingSubslideMotion.svelte';
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
  const UnlockIcon = getLucideIcon('lock-open');
  const MessageIcon = getLucideIcon('message-circle');
  const MemoryIcon = getLucideIcon('brain');
  const ProjectIcon = getLucideIcon('folder');
  const TaskIcon = getLucideIcon('list-check');
  const FileIcon = getLucideIcon('file-text');
  const PlaneIcon = getLucideIcon('plane');
  const ShieldIcon = getLucideIcon('shield-check');

  let activeStage = $derived<PrivacyStoryStage>(
    PRIVACY_STORY_STAGES[activeStageIndex]?.id ?? PRIVACY_STORY_STAGES[0].id,
  );
  let activeStageDurationMs = $derived(
    PRIVACY_STORY_STAGES[activeStageIndex]?.durationMs ?? PRIVACY_STORY_STAGES[0].durationMs,
  );
  let tripPreviewCategories = $derived([{
    key: 'travel.trips',
    appId: 'travel',
    displayName: $text('app_settings_memories.travel.trips'),
    entryCount: 2,
    selected: true,
    entries: [
      {
        id: 'landing-trip-lisbon',
        title: $text('demo_chats.for_everyone.landing_privacy_previous_trips'),
        subtitle: 'Lisbon · 2025',
        selected: true,
      },
      {
        id: 'landing-trip-favorites',
        title: $text('demo_chats.for_everyone.landing_privacy_favorite_places'),
        subtitle: 'Coast · cafés · museums',
        selected: true,
      },
    ],
  }]);

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
      <div><MemoryIcon size={22} /> <span>{$text('demo_chats.for_everyone.landing_privacy_memory_result')}</span></div>
    </div>
  {:else}
    {#key activeStage}
      <LandingSubslideMotion playing={playing} durationMs={activeStageDurationMs} stage={activeStage}>
        {#if activeStage === 'saved-data-copy'}
          <div class="privacy-stage copy-stage" data-testid="landing-privacy-saved-data-copy">
            <ShieldIcon size={38} />
            <p>{$text('demo_chats.for_everyone.landing_privacy_saved_data')}</p>
          </div>
        {:else if activeStage === 'encryption-lock'}
          <div class="privacy-stage encryption-stage" data-testid="landing-privacy-encryption">
            <div class="data-orbit">
              <span class="data-icon chat"><MessageIcon size={21} /></span>
              <span class="data-icon file"><FileIcon size={21} /></span>
              <span class="data-icon project"><ProjectIcon size={21} /></span>
              <span class="data-icon task"><TaskIcon size={21} /></span>
              <span class="lock-core" data-testid="landing-privacy-lock" data-lock-state="locked">
                <span class="unlock-icon"><UnlockIcon size={34} /></span>
                <span class="locked-icon"><LockIcon size={34} /></span>
              </span>
            </div>
          </div>
        {:else if activeStage === 'pii-copy'}
          <div class="privacy-stage copy-stage" data-testid="landing-privacy-pii-copy">
            <MessageIcon size={38} />
            <p>{$text('demo_chats.for_everyone.landing_privacy_pii')}</p>
          </div>
        {:else if activeStage === 'pii-detection'}
          <div class="privacy-stage message-stage">
            <div class="user-message-shell">
              Send the details to <span class="pii-highlight" data-testid="landing-privacy-pii-highlight">alex@example.com</span>
            </div>
          </div>
        {:else if activeStage === 'originals-copy'}
          <div class="privacy-stage copy-stage" data-testid="landing-privacy-originals-copy">
            <ShieldIcon size={38} />
            <p>{$text('demo_chats.for_everyone.landing_privacy_originals')}</p>
          </div>
        {:else if activeStage === 'pii-reveal'}
          <div class="privacy-stage reveal-stage" data-testid="landing-privacy-pii-reveal" data-pii-revealed="true">
            <div class="assistant-message-shell">
              <span class="pii-restored pii-hidden">[EMAIL_1]</span>
              <span class="reveal-arrow" aria-hidden="true">→</span>
              <span class="pii-restored pii-revealed">alex@example.com</span>
            </div>
          </div>
        {:else if activeStage === 'personalized-copy'}
          <div class="privacy-stage copy-stage" data-testid="landing-privacy-personalized-copy">
            <MemoryIcon size={38} />
            <p>{$text('demo_chats.for_everyone.landing_privacy_memory_result')}</p>
          </div>
        {:else if activeStage === 'trip-request'}
          <div class="privacy-stage message-stage">
            <div class="user-message-shell trip-request" data-testid="landing-privacy-trip-request">
              <PlaneIcon size={18} />
              {$text('demo_chats.for_everyone.landing_privacy_trip_request')}
            </div>
          </div>
        {:else}
          <div class="privacy-stage permission-stage">
            <AppSettingsMemoriesPermissionDialog previewMode previewCategories={tripPreviewCategories} />
          </div>
        {/if}
      </LandingSubslideMotion>
    {/key}
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
    gap: var(--spacing-8);
    text-align: center;
  }

  .copy-stage p {
    max-width: 30rem;
    margin: 0;
    font-size: clamp(1rem, 3.2cqi, 1.45rem);
    font-weight: 800;
    line-height: 1.35;
    text-wrap: balance;
  }

  .data-orbit {
    position: relative;
    width: 260px;
    height: 150px;
  }

  .data-icon,
  .lock-core {
    position: absolute;
    display: grid;
    place-items: center;
    border: 1px solid rgba(255, 255, 255, 0.24);
    background: rgba(255, 255, 255, 0.14);
    box-shadow: var(--shadow-md);
    backdrop-filter: blur(10px);
  }

  .data-icon {
    width: 46px;
    height: 46px;
    border-radius: var(--radius-full);
    animation: floatProtectedData 2.8s ease-in-out infinite;
  }

  .data-icon.chat { inset: 4px auto auto 18px; }
  .data-icon.file { inset: 4px 18px auto auto; animation-delay: -0.7s; }
  .data-icon.project { inset: auto auto 4px 42px; animation-delay: -1.4s; }
  .data-icon.task { inset: auto 42px 4px auto; animation-delay: -2.1s; }

  .lock-core {
    inset: 38px 91px auto;
    width: 78px;
    height: 78px;
    overflow: hidden;
    border-radius: var(--radius-full);
    background: rgba(255, 255, 255, 0.25);
  }

  .unlock-icon,
  .locked-icon {
    position: absolute;
    display: grid;
    place-items: center;
  }

  .unlock-icon { animation: unlockExit 3s both; }
  .locked-icon { animation: lockEnter 3s both; }

  .message-stage,
  .reveal-stage {
    padding-inline: var(--spacing-12);
  }

  .user-message-shell,
  .assistant-message-shell {
    position: relative;
    width: min(88%, 28rem);
    padding: var(--spacing-8) var(--spacing-10);
    border-radius: var(--radius-6);
    color: var(--color-font-primary);
    font-size: clamp(0.84rem, 2.4cqi, 1.05rem);
    font-weight: 600;
    line-height: 1.5;
    box-shadow: var(--shadow-md);
  }

  .user-message-shell {
    justify-self: end;
    background: var(--color-grey-blue);
    text-align: start;
  }

  .user-message-shell::after {
    position: absolute;
    inset: auto -6px 4px auto;
    width: 14px;
    height: 16px;
    background: inherit;
    clip-path: polygon(0 0, 100% 100%, 0 72%);
    content: '';
  }

  .assistant-message-shell {
    display: flex;
    justify-self: start;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-6);
    background: var(--color-grey-0);
  }

  .assistant-message-shell::before {
    position: absolute;
    inset: auto auto 4px -6px;
    width: 14px;
    height: 16px;
    background: inherit;
    clip-path: polygon(100% 0, 0 100%, 100% 72%);
    content: '';
  }

  .pii-highlight {
    padding: 0 2px;
    border-radius: 2px;
    background-color: rgba(250, 204, 21, 0.35);
    color: var(--color-font-primary);
    font-weight: 600;
  }

  .pii-restored { font-weight: 600; }
  .pii-hidden { color: #4ade80; }
  .pii-revealed { color: #f59e0b; }
  .reveal-arrow { color: var(--color-font-tertiary); }
  .trip-request { display: flex; align-items: center; gap: var(--spacing-4); }

  .permission-stage {
    width: min(100%, 520px);
  }

  .privacy-summary {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .privacy-summary div {
    display: grid;
    place-items: center;
    gap: var(--spacing-4);
    font-size: clamp(0.68rem, 1.8cqi, 0.86rem);
    font-weight: 700;
  }

  @container chat-side (max-width: 560px) {
    .privacy-stage,
    .privacy-summary { gap: var(--spacing-4); }
    .copy-stage p { font-size: 0.9rem; }
    .data-orbit { width: 220px; height: 110px; }
    .data-icon { width: 38px; height: 38px; }
    .data-icon.chat { inset: 2px auto auto 12px; }
    .data-icon.file { inset: 2px 12px auto auto; }
    .data-icon.project { inset: auto auto 2px 34px; }
    .data-icon.task { inset: auto 34px 2px auto; }
    .lock-core { inset: 25px 78px auto; width: 64px; height: 64px; }
    .message-stage,
    .reveal-stage { padding-inline: var(--spacing-4); }
    .user-message-shell,
    .assistant-message-shell { padding: var(--spacing-6) var(--spacing-8); }
    .permission-stage { width: min(122%, 520px); }
  }

  @keyframes floatProtectedData {
    0%, 100% { transform: translate3d(0, -3px, 0); }
    50% { transform: translate3d(0, 4px, 0); }
  }

  @keyframes unlockExit {
    0%, 28% { opacity: 1; transform: translate3d(0, 0, 0) rotate(-7deg); }
    48%, 100% { opacity: 0; transform: translate3d(0, -18px, 0) rotate(5deg); }
  }

  @keyframes lockEnter {
    0%, 32% { opacity: 0; transform: translate3d(0, 18px, 0) scale(0.8); }
    54%, 100% { opacity: 1; transform: translate3d(0, 0, 0) scale(1); }
  }

  @media (prefers-reduced-motion: reduce) {
    .data-icon,
    .unlock-icon,
    .locked-icon { animation: none; }
    .unlock-icon { display: none; }
  }
</style>
