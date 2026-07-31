<script lang="ts">
  /**
   * LandingActionableEventDemo.svelte
   *
   * Lightweight logged-out landing animation for the Actionable product slide.
   * It mirrors real chat-message bubbles and the events embed preview while
   * sequencing each stage through the same centered fade-up transition.
   */

  import { onMount } from 'svelte';
  import { fly } from 'svelte/transition';
  import { text } from '@repo/ui';
  import EventEmbedPreview from '../embeds/events/EventEmbedPreview.svelte';

  const ACTIONABLE_STAGE_INTERVAL_MS = 2200;
  const ACTIONABLE_STAGE_TRANSITION_MS = 420;
  const ACTIONABLE_STAGES = ['user-request', 'assistant-response', 'event-preview', 'luma-cta'] as const;

  type ActionableStage = typeof ACTIONABLE_STAGES[number];

  let activeStageIndex = $state(0);
  let activeStage = $derived<ActionableStage>(ACTIONABLE_STAGES[activeStageIndex] ?? ACTIONABLE_STAGES[0]);

  const demoStartDate = new Date('2024-05-22T11:00:00+02:00');
  const demoEndDate = new Date(demoStartDate);
  demoEndDate.setHours(18, 0, 0, 0);

  const demoEvent = {
    embed_id: 'landing-actionable-event-preview',
    id: 'landing-actionable-depin-berlin',
    provider: 'luma',
    title: 'DEPIN DAY BERLIN',
    description: 'The second edition of DePIN Day in Berlin, with research and talks on decentralized compute.',
    url: 'https://luma.com/depin-berlin',
    date_start: demoStartDate.toISOString(),
    date_end: demoEndDate.toISOString(),
    event_type: 'PHYSICAL',
    venue: {
      name: 'Magazin in der Heeresbaeckerei',
      address: 'Koepenicker Strasse 16-17',
      city: 'Berlin',
      country: 'Germany',
      lat: 52.5094,
      lon: 13.4307,
    },
    organizer: { name: 'Fluence' },
    rsvp_count: 460,
    is_paid: false,
    image_url: 'https://images.lumacdn.com/cdn-cgi/image/format=auto,fit=cover,dpr=2,background=white,quality=75,width=400,height=400/event-covers/g3/d98ef380-57c3-4dd8-b751-d7c0ae6c2519',
  };

  function noop() {
    // Non-interactive decorative preview inside the autoplay landing slide.
  }

  onMount(() => {
    const interval = window.setInterval(() => {
      activeStageIndex = (activeStageIndex + 1) % ACTIONABLE_STAGES.length;
    }, ACTIONABLE_STAGE_INTERVAL_MS);

    return () => window.clearInterval(interval);
  });
</script>

<div class="landing-actionable-demo" data-testid="landing-actionable-event-demo" data-active-stage={activeStage}>
  <div class="landing-actionable-scene" data-testid="landing-actionable-event-scene">
    {#key activeStage}
      <div
        class="landing-actionable-stage"
        data-testid="landing-actionable-stage"
        data-stage={activeStage}
        in:fly={{ y: 24, duration: ACTIONABLE_STAGE_TRANSITION_MS }}
        out:fly={{ y: -24, duration: ACTIONABLE_STAGE_TRANSITION_MS }}
      >
        {#if activeStage === 'user-request'}
          <div class="chat-message user landing-actionable-message-stage" data-testid="landing-actionable-user-row">
            <div class="message-align-right">
              <div class="user-message-content" data-testid="landing-actionable-user-message">
                <div class="chat-message-text">{$text('demo_chats.for_everyone.landing_actionable_event_user_message')}</div>
              </div>
            </div>
          </div>
        {:else if activeStage === 'assistant-response'}
          <div class="chat-message assistant landing-actionable-message-stage" data-testid="landing-actionable-assistant-row">
            <div class="mate-profile general_knowledge" data-testid="landing-actionable-assistant-profile"></div>
            <div class="message-align-left">
              <div class="mate-message-content" data-testid="landing-actionable-assistant-message">
                <div class="chat-mate-name" data-testid="landing-actionable-assistant-name">OpenMates</div>
                <div class="chat-message-text">{$text('demo_chats.for_everyone.landing_actionable_event_assistant_message')}</div>
              </div>
            </div>
          </div>
        {:else if activeStage === 'event-preview'}
          <div class="landing-actionable-preview" data-testid="landing-actionable-event-preview">
            <EventEmbedPreview id="landing-actionable-event-preview-card" event={demoEvent} isMobile={false} onFullscreen={noop} />
            <div class="landing-actionable-preview-title" data-testid="landing-actionable-event-title">{$text('demo_chats.for_everyone.landing_actionable_event_title')}</div>
          </div>
        {:else}
          <button class="landing-actionable-luma-button" data-testid="landing-actionable-luma-button" type="button">Open on Luma</button>
        {/if}
      </div>
    {/key}
  </div>
</div>

<style>
  .landing-actionable-demo {
    position: relative;
    flex: 0 1 auto;
    width: min(54vw, 760px);
    min-width: 390px;
    height: calc(100% - 18px);
    min-height: 210px;
    border-radius: var(--radius-4);
    overflow: visible;
    background: rgba(12, 18, 48, 0.48);
    border: 1px solid rgba(255, 255, 255, 0.18);
    box-shadow: var(--shadow-xl);
    pointer-events: none;
  }

  .landing-actionable-scene {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    overflow: hidden;
  }

  .landing-actionable-stage {
    position: absolute;
    inset: 0;
    z-index: var(--z-index-raised);
    display: grid;
    place-items: center;
    width: 100%;
    min-width: 0;
    padding: 18px;
    box-sizing: border-box;
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
    font-size: clamp(0.74rem, 1vw, 0.92rem);
    line-height: 1.25;
    font-weight: 700;
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
    max-width: 100%;
  }

  .landing-actionable-preview :global(.unified-embed-preview) {
    width: 300px;
    height: 200px;
    min-height: 200px;
    max-height: 200px;
  }

  .landing-actionable-preview-title {
    position: absolute;
    left: 20px;
    top: 20px;
    z-index: var(--z-index-raised);
    max-width: 150px;
    color: var(--color-grey-0);
    font-size: 0.92rem;
    line-height: 1.08;
    font-weight: 800;
    letter-spacing: -0.025em;
    pointer-events: none;
  }

  .landing-actionable-luma-button {
    font-weight: 800;
    white-space: nowrap;
  }

  @media (max-width: 730px) {
    .landing-actionable-demo {
      width: 100%;
      min-width: 0;
      height: 100%;
      min-height: 0;
    }

    .landing-actionable-stage {
      padding: 4px 6px;
    }

    .landing-actionable-message-stage {
      width: min(100%, 320px);
      transform: scale(0.9);
    }

    .landing-actionable-preview {
      width: 300px;
      transform: scale(0.58);
    }

    .landing-actionable-luma-button {
      transform: scale(0.9);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .landing-actionable-stage {
      transition: none !important;
    }
  }
</style>
