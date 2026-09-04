<script lang="ts">
  /**
   * LandingActionableEventDemo.svelte
   *
   * One-shot logged-out landing animation for the Actionable product slide.
   * It reuses real chat and event-preview surfaces while coordinating staged
   * motion, visible pointer clicks, localization, and carousel completion.
   */

  import { onMount } from 'svelte';
  import { text } from '@repo/ui';
  import { getLucideIcon } from '../../utils/categoryUtils';
  import EventEmbedPreview from '../embeds/events/EventEmbedPreview.svelte';
  import LandingSubslideMotion from './LandingSubslideMotion.svelte';
  import {
    ACTIONABLE_CTA_CLICK_MS,
    ACTIONABLE_CTA_POINTER_TARGET_MS,
    ACTIONABLE_PREVIEW_CLICK_MS,
    ACTIONABLE_PREVIEW_POINTER_TARGET_MS,
    ACTIONABLE_STAGE_SEQUENCE,
    type ActionableStage,
  } from './landingActionableEventTimeline';

  interface Props {
    playing: boolean;
    onComplete: () => void;
  }

  type InteractionState = 'idle' | 'preview-targeted' | 'preview-clicked' | 'cta-targeted' | 'cta-clicked';

  let { playing, onComplete }: Props = $props();

  const MousePointerIcon = getLucideIcon('mouse-pointer-2');
  const demoStartDate = new Date('2024-05-22T11:00:00+02:00');
  const demoEndDate = new Date(demoStartDate);
  demoEndDate.setHours(18, 0, 0, 0);

  let activeStageIndex = $state(0);
  let interactionState = $state<InteractionState>('idle');
  let playbackRunId = $state(0);
  let mounted = $state(false);

  let activeStage = $derived<ActionableStage>(
    ACTIONABLE_STAGE_SEQUENCE[activeStageIndex]?.id ?? ACTIONABLE_STAGE_SEQUENCE[0].id,
  );
  let activeStageDurationMs = $derived(
    ACTIONABLE_STAGE_SEQUENCE[activeStageIndex]?.durationMs ?? ACTIONABLE_STAGE_SEQUENCE[0].durationMs,
  );
  let demoEvent = $derived.by(() => ({
    embed_id: 'landing-actionable-event-preview',
    id: 'landing-actionable-depin-berlin',
    provider: 'luma',
    title: $text('guest_onboarding.landing_actionable_event_title'),
    description: $text('guest_onboarding.landing_actionable_event_detail'),
    url: 'https://luma.com/depin-berlin',
    date_start: demoStartDate.toISOString(),
    date_end: demoEndDate.toISOString(),
    event_type: 'PHYSICAL',
    venue: {
      name: $text('guest_onboarding.landing_actionable_event_venue'),
      address: $text('guest_onboarding.landing_actionable_event_address'),
      city: $text('guest_onboarding.landing_actionable_event_city'),
      country: $text('guest_onboarding.landing_actionable_event_country'),
      lat: 52.5094,
      lon: 13.4307,
    },
    organizer: { name: $text('guest_onboarding.landing_actionable_event_organizer') },
    rsvp_count: 460,
    is_paid: false,
    image_url: 'https://images.lumacdn.com/cdn-cgi/image/format=auto,fit=cover,dpr=2,background=white,quality=75,width=400,height=400/event-covers/g3/d98ef380-57c3-4dd8-b751-d7c0ae6c2519',
  }));

  function noop() {
    // Non-interactive decorative preview inside the autoplay landing slide.
  }

  onMount(() => {
    mounted = true;
  });

  $effect(() => {
    if (!mounted) return;
    if (!playing) {
      activeStageIndex = 0;
      interactionState = 'idle';
      return;
    }

    activeStageIndex = 0;
    interactionState = 'idle';
    playbackRunId = window.performance.now();

    const timeouts: number[] = [];
    const schedule = (delayMs: number, callback: () => void) => {
      timeouts.push(window.setTimeout(callback, delayMs));
    };

    let stageStartMs = 0;
    ACTIONABLE_STAGE_SEQUENCE.forEach((stage, index) => {
      if (index > 0) {
        schedule(stageStartMs, () => {
          activeStageIndex = index;
          interactionState = 'idle';
        });
      }

      if (stage.id === 'event-preview') {
        schedule(stageStartMs + ACTIONABLE_PREVIEW_POINTER_TARGET_MS, () => {
          interactionState = 'preview-targeted';
        });
        schedule(stageStartMs + ACTIONABLE_PREVIEW_CLICK_MS, () => {
          interactionState = 'preview-clicked';
        });
      }

      if (stage.id === 'luma-cta') {
        schedule(stageStartMs + ACTIONABLE_CTA_POINTER_TARGET_MS, () => {
          interactionState = 'cta-targeted';
        });
        schedule(stageStartMs + ACTIONABLE_CTA_CLICK_MS, () => {
          interactionState = 'cta-clicked';
        });
      }

      stageStartMs += stage.durationMs;
    });

    schedule(stageStartMs, onComplete);

    return () => {
      timeouts.forEach((timeout) => window.clearTimeout(timeout));
    };
  });
</script>

<div
  class="landing-actionable-demo"
  class:playing
  data-testid="landing-actionable-event-demo"
  data-active-stage={activeStage}
  data-interaction-state={interactionState}
  data-playing={playing ? 'true' : 'false'}
>
  <div class="landing-actionable-scene" data-testid="landing-actionable-event-scene">
    {#key `${playbackRunId}-${activeStage}`}
      <div
        class="landing-actionable-stage"
        data-testid="landing-actionable-stage"
        data-stage={activeStage}
      >
        <LandingSubslideMotion {playing} durationMs={activeStageDurationMs} stage={activeStage}>
          <div class="landing-actionable-stage-content" data-testid="landing-actionable-stage-content" data-stage={activeStage}>
            {#if activeStage === 'user-request'}
              <div class="chat-message user landing-actionable-message-stage" data-testid="landing-actionable-user-row">
                <div class="message-align-right">
                  <div class="user-message-content" data-testid="landing-actionable-user-message">
                    <div class="chat-message-text">{$text('guest_onboarding.landing_actionable_event_user_message')}</div>
                  </div>
                </div>
              </div>
            {:else if activeStage === 'assistant-response'}
              <div class="chat-message assistant landing-actionable-message-stage" data-testid="landing-actionable-assistant-row">
                <div class="mate-profile general_knowledge" data-testid="landing-actionable-assistant-profile"></div>
                <div class="message-align-left">
                  <div class="mate-message-content" data-testid="landing-actionable-assistant-message">
                    <div class="chat-mate-name" data-testid="landing-actionable-assistant-name">{$text('mates.general_knowledge')}</div>
                    <div class="chat-message-text">{$text('guest_onboarding.landing_actionable_event_assistant_message')}</div>
                  </div>
                </div>
              </div>
            {:else if activeStage === 'event-preview'}
              <div
                class="landing-actionable-preview"
                data-testid="landing-actionable-event-preview"
                data-demo-pressed={interactionState === 'preview-clicked' ? 'true' : 'false'}
              >
                <EventEmbedPreview
                  id="landing-actionable-event-preview-card"
                  event={demoEvent}
                  isMobile={false}
                  onlineLabel={$text('guest_onboarding.landing_actionable_event_online')}
                  inPersonLabel={$text('guest_onboarding.landing_actionable_event_in_person')}
                  rsvpLabel={$text('guest_onboarding.landing_actionable_event_rsvps')}
                  onFullscreen={noop}
                />
              </div>
            {:else}
              <div
                class="landing-actionable-luma-button"
                data-testid="landing-actionable-luma-button"
                data-demo-pressed={interactionState === 'cta-clicked' ? 'true' : 'false'}
              >
                {$text('guest_onboarding.landing_actionable_event_open_luma')}
              </div>
            {/if}
          </div>
        </LandingSubslideMotion>
      </div>
    {/key}

    {#if activeStage === 'event-preview' || activeStage === 'luma-cta'}
      <div class="landing-actionable-pointer" data-testid="landing-actionable-pointer" aria-hidden="true">
        <MousePointerIcon size={34} strokeWidth={2.6} />
      </div>
    {/if}
  </div>
</div>

<style>
  .landing-actionable-demo {
    position: relative;
    flex: 0 1 auto;
    width: 100%;
    min-width: 0;
    height: 100%;
    min-height: 0;
    --landing-actionable-preview-center-lift: -16px;
    border-radius: var(--radius-4);
    overflow: visible;
    background: transparent;
    border: 0;
    box-shadow: none;
    pointer-events: none;
  }

  .landing-actionable-scene,
  .landing-actionable-stage {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
  }

  .landing-actionable-scene {
    overflow: visible;
  }

  .landing-actionable-stage {
    z-index: var(--z-index-raised);
    min-width: 0;
    padding: 18px;
    box-sizing: border-box;
  }

  .landing-actionable-stage-content {
    display: grid;
    place-items: center;
    width: 100%;
    transform-origin: center;
  }

  .landing-actionable-message-stage {
    width: min(100%, 520px);
    transform-origin: center;
  }

  .landing-actionable-message-stage :global(.mate-profile) {
    width: 42px !important;
    height: 42px !important;
    margin: 0 !important;
    flex: 0 0 auto;
  }

  .landing-actionable-message-stage :global(.mate-profile::after) {
    width: 16px !important;
    height: 16px !important;
    right: -4px !important;
    bottom: -4px !important;
  }

  .landing-actionable-message-stage :global(.mate-profile::before) {
    width: 10px !important;
    height: 10px !important;
    right: -1px !important;
    bottom: -1px !important;
  }

  .landing-actionable-message-stage :global(.message-align-right) {
    max-width: min(78%, 440px);
    padding-inline-start: 0;
    margin-left: auto;
  }

  .landing-actionable-message-stage :global(.message-align-left) {
    max-width: min(82%, 470px);
    padding-inline-end: 0;
  }

  .landing-actionable-message-stage :global(.user-message-content),
  .landing-actionable-message-stage :global(.mate-message-content) {
    flex: 0 1 auto;
    padding: 10px 12px;
    margin-top: 0;
    margin-bottom: 0;
    font-size: clamp(1rem, 2.6cqi, 1.35rem);
    line-height: 1.35;
    font-weight: 700;
  }

  .landing-actionable-message-stage :global(.chat-message-text) {
    font-size: inherit;
    line-height: inherit;
  }

  .landing-actionable-message-stage :global(.chat-mate-name) {
    margin-bottom: 3px;
    font-size: 0.68rem;
    color: var(--color-grey-60);
  }

  .landing-actionable-preview {
    position: relative;
    z-index: var(--z-index-raised-2);
    width: 300px;
    transform: translateY(var(--landing-actionable-preview-center-lift));
    transition: transform var(--duration-fast) ease;
  }

  .landing-actionable-preview[data-demo-pressed='true'] {
    transform: translateY(var(--landing-actionable-preview-center-lift)) scale(0.96);
  }

  .landing-actionable-preview :global(.unified-embed-preview) {
    width: 300px;
    height: 200px;
    min-height: 200px;
    max-height: 200px;
  }

  .landing-actionable-luma-button {
    min-width: 0 !important;
    height: auto !important;
    margin: 0 !important;
    padding: 12px 22px !important;
    border: 0 !important;
    border-radius: var(--radius-8) !important;
    background: var(--color-button-primary) !important;
    color: white !important;
    box-shadow: var(--shadow-md) !important;
    font: inherit;
    font-size: clamp(1rem, 2.8cqi, 1.3rem);
    font-weight: 800 !important;
    white-space: nowrap;
    transition:
      background var(--duration-fast) ease,
      box-shadow var(--duration-fast) ease,
      transform var(--duration-fast) ease;
  }

  .landing-actionable-luma-button[data-demo-pressed='true'] {
    background: var(--color-button-primary-pressed) !important;
    box-shadow: var(--shadow-xs) !important;
    transform: scale(0.97);
  }

  .landing-actionable-pointer {
    position: absolute;
    left: 54%;
    top: calc(100% + 40px);
    z-index: var(--z-index-modal);
    display: grid;
    place-items: center;
    width: 38px;
    height: 38px;
    color: white;
    opacity: 0;
    filter: drop-shadow(0 2px 2px rgba(0, 0, 0, 0.65)) drop-shadow(0 5px 12px rgba(0, 0, 0, 0.35));
    transform: translate(-15%, -12%) scale(0.82);
    transition:
      left 620ms cubic-bezier(0.16, 1, 0.3, 1),
      top 620ms cubic-bezier(0.16, 1, 0.3, 1),
      opacity 180ms ease,
      transform 140ms ease;
  }

  .landing-actionable-pointer::after {
    content: '';
    position: absolute;
    left: 4px;
    top: 4px;
    width: 18px;
    height: 18px;
    border: 2px solid rgba(255, 255, 255, 0.88);
    border-radius: var(--radius-full);
    opacity: 0;
    transform: scale(0.35);
  }

  .landing-actionable-demo[data-interaction-state='preview-targeted'] .landing-actionable-pointer,
  .landing-actionable-demo[data-interaction-state='preview-clicked'] .landing-actionable-pointer {
    left: 57%;
    top: 53%;
    opacity: 1;
    transform: translate(-15%, -12%) scale(1);
  }

  .landing-actionable-demo[data-interaction-state='cta-targeted'] .landing-actionable-pointer,
  .landing-actionable-demo[data-interaction-state='cta-clicked'] .landing-actionable-pointer {
    left: 54%;
    top: 51%;
    opacity: 1;
    transform: translate(-15%, -12%) scale(1);
  }

  .landing-actionable-demo[data-interaction-state='preview-clicked'] .landing-actionable-pointer,
  .landing-actionable-demo[data-interaction-state='cta-clicked'] .landing-actionable-pointer {
    transform: translate(-15%, -12%) scale(0.78);
  }

  .landing-actionable-demo[data-interaction-state='preview-clicked'] .landing-actionable-pointer::after,
  .landing-actionable-demo[data-interaction-state='cta-clicked'] .landing-actionable-pointer::after {
    animation: landingActionableClickPulse 420ms ease-out;
  }

  @keyframes landingActionableClickPulse {
    from { opacity: 0.9; transform: scale(0.35); }
    to { opacity: 0; transform: scale(1.65); }
  }

  @container chat-side (max-width: 730px) {
    .landing-actionable-stage {
      padding: 2px 6px;
    }

    .landing-actionable-stage-content[data-stage='user-request'],
    .landing-actionable-stage-content[data-stage='assistant-response'] {
      transform: scale(1);
    }

    .landing-actionable-stage-content[data-stage='event-preview'] {
      position: relative;
      width: 100%;
      height: 100%;
      transform: none;
    }

    .landing-actionable-stage-content[data-stage='event-preview'] .landing-actionable-preview {
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%) scale(0.54);
    }

    .landing-actionable-stage-content[data-stage='event-preview'] .landing-actionable-preview[data-demo-pressed='true'] {
      transform: translate(-50%, -50%) scale(0.52);
    }

    .landing-actionable-message-stage {
      position: relative;
      width: min(calc(100% + 20px), 360px);
      left: auto;
      justify-self: center;
      margin-inline: auto;
      transform: none;
    }

    .landing-actionable-message-stage :global(.message-align-right),
    .landing-actionable-message-stage :global(.message-align-left) {
      max-width: 90%;
    }

    .landing-actionable-message-stage :global(.user-message-content),
    .landing-actionable-message-stage :global(.mate-message-content) {
      padding: 12px 14px;
      font-size: clamp(1rem, 4.2cqi, 1.2rem);
    }

    .landing-actionable-stage-content[data-stage='luma-cta'] {
      transform: scale(0.9);
    }

  }

  @container chat-side (min-width: 431px) and (max-width: 560px) {
    .landing-actionable-stage-content[data-stage='event-preview'] .landing-actionable-preview {
      transform: translate(-50%, -50%) scale(0.72);
    }

    .landing-actionable-stage-content[data-stage='event-preview'] .landing-actionable-preview[data-demo-pressed='true'] {
      transform: translate(-50%, -50%) scale(0.69);
    }
  }

  @container chat-side (min-width: 561px) and (max-width: 730px) {
    .landing-actionable-stage-content[data-stage='event-preview'] .landing-actionable-preview {
      transform: translate(-50%, -50%) scale(0.9);
    }

    .landing-actionable-stage-content[data-stage='event-preview'] .landing-actionable-preview[data-demo-pressed='true'] {
      transform: translate(-50%, -50%) scale(0.87);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .landing-actionable-pointer,
    .landing-actionable-preview,
    .landing-actionable-luma-button {
      transition-duration: 1ms !important;
    }
  }

</style>
