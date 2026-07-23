<script lang="ts">
  /**
   * LandingActionableEventDemo.svelte
   *
   * Lightweight logged-out landing animation for the Actionable product slide.
   * It mirrors real chat-message bubbles and the events embed preview while
   * showing a cursor opening a real Luma event CTA.
   */

  import { text } from '@repo/ui';
  import EventEmbedPreview from '../embeds/events/EventEmbedPreview.svelte';

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
</script>

<div class="landing-actionable-demo" data-testid="landing-actionable-event-demo">
  <div class="landing-actionable-scene" data-testid="landing-actionable-event-scene">
    <div class="landing-actionable-chat">
      <div class="chat-message user landing-actionable-user-row" data-testid="landing-actionable-user-row">
        <div class="message-align-right">
          <div class="user-message-content" data-testid="landing-actionable-user-message">
            <div class="chat-message-text">{$text('demo_chats.for_everyone.landing_actionable_event_user_message')}</div>
          </div>
        </div>
      </div>

      <div class="chat-message assistant landing-actionable-assistant-row" data-testid="landing-actionable-assistant-row">
        <div class="mate-profile general_knowledge" data-testid="landing-actionable-assistant-profile"></div>
        <div class="message-align-left">
          <div class="mate-message-content" data-testid="landing-actionable-assistant-message">
            <div class="chat-mate-name" data-testid="landing-actionable-assistant-name">OpenMates</div>
            <div class="chat-message-text">{$text('demo_chats.for_everyone.landing_actionable_event_assistant_message')}</div>
          </div>
        </div>
      </div>
    </div>

    <div class="landing-actionable-preview" data-testid="landing-actionable-event-preview">
      <EventEmbedPreview id="landing-actionable-event-preview-card" event={demoEvent} isMobile={false} onFullscreen={noop} />
      <div class="landing-actionable-preview-title" data-testid="landing-actionable-event-title">{$text('demo_chats.for_everyone.landing_actionable_event_title')}</div>
    </div>

    <div class="landing-actionable-cta-card" data-testid="landing-actionable-event-cta-card">
      <div class="landing-actionable-cta-copy">
        <span>{$text('demo_chats.for_everyone.landing_actionable_event_source')}</span>
        <strong>{$text('demo_chats.for_everyone.landing_actionable_event_title')}</strong>
      </div>
      <button class="landing-actionable-luma-button" data-testid="landing-actionable-luma-button" type="button">Open on Luma</button>
    </div>

    <div class="landing-actionable-cursor" data-testid="landing-actionable-cursor" aria-hidden="true"></div>
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
    transform-origin: center;
    animation: landingActionableScene 9.6s ease-in-out infinite;
  }

  .landing-actionable-chat {
    position: absolute;
    inset: 18px 18px auto;
    z-index: var(--z-index-raised);
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .landing-actionable-chat :global(.chat-message) {
    transform-origin: center;
  }

  .landing-actionable-user-row {
    animation: landingActionableUserMessage 9.6s ease-in-out infinite;
  }

  .landing-actionable-assistant-row {
    animation: landingActionableAssistantMessage 9.6s ease-in-out infinite;
  }

  .landing-actionable-chat :global(.mate-profile) {
    width: 42px !important;
    height: 42px !important;
    margin: 0 !important;
    flex: 0 0 auto;
  }

  .landing-actionable-chat :global(.mate-profile::after) {
    width: 16px !important;
    height: 16px !important;
    right: -4px !important;
    bottom: -4px !important;
  }

  .landing-actionable-chat :global(.mate-profile::before) {
    width: 10px !important;
    height: 10px !important;
    right: -1px !important;
    bottom: -1px !important;
  }

  .landing-actionable-chat :global(.message-align-right) {
    max-width: min(72%, 440px);
    padding-inline-start: 0;
  }

  .landing-actionable-chat :global(.message-align-left) {
    max-width: min(78%, 470px);
    padding-inline-end: 0;
  }

  .landing-actionable-chat :global(.user-message-content),
  .landing-actionable-chat :global(.mate-message-content) {
    flex: 0 1 auto;
    padding: 10px 12px;
    margin-top: 0;
    margin-bottom: 0;
    font-size: clamp(0.74rem, 1vw, 0.92rem);
    line-height: 1.25;
    font-weight: 700;
  }

  .landing-actionable-chat :global(.chat-mate-name) {
    margin-bottom: 3px;
    font-size: 0.68rem;
    color: var(--color-grey-60);
  }

  .landing-actionable-preview {
    position: absolute;
    left: 50%;
    bottom: 18px;
    z-index: var(--z-index-raised-2);
    width: 300px;
    transform: translateX(-50%) translateY(18px) scale(0.92);
    opacity: 0;
    animation: landingActionablePreview 9.6s ease-in-out infinite;
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
    color: var(--color-grey-100);
    font-size: 0.92rem;
    line-height: 1.08;
    font-weight: 800;
    letter-spacing: -0.025em;
    pointer-events: none;
  }

  .landing-actionable-cta-card {
    position: absolute;
    left: 50%;
    bottom: 30px;
    z-index: var(--z-index-dropdown);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    width: min(86%, 430px);
    padding: 16px;
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-xl);
    color: var(--color-font-primary);
    transform: translateX(-50%) translateY(28px) scale(0.94);
    opacity: 0;
    animation: landingActionableCtaCard 9.6s ease-in-out infinite;
  }

  .landing-actionable-cta-copy {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }

  .landing-actionable-cta-copy span {
    color: var(--color-grey-60);
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .landing-actionable-cta-copy strong {
    overflow: hidden;
    font-size: 1rem;
    line-height: 1.15;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .landing-actionable-luma-button {
    flex: 0 0 auto;
    min-width: 136px;
    height: 42px;
    padding: 0 18px;
    border: 0;
    border-radius: 999px;
    color: white;
    background: #111827;
    box-shadow: 0 8px 18px rgba(17, 24, 39, 0.2);
    font: inherit;
    font-size: 0.86rem;
    font-weight: 800;
  }

  .landing-actionable-cursor {
    position: absolute;
    left: 24%;
    top: 50%;
    z-index: var(--z-index-popover);
    width: 24px;
    height: 24px;
    filter: drop-shadow(0 5px 8px rgba(0, 0, 0, 0.3));
    transform: translate(-50%, -50%);
    animation: landingActionableCursor 9.6s ease-in-out infinite;
  }

  .landing-actionable-cursor::before {
    content: '';
    position: absolute;
    inset: 0;
    background: white;
    clip-path: polygon(0 0, 0 100%, 28% 76%, 45% 100%, 60% 92%, 44% 68%, 78% 68%);
  }

  .landing-actionable-cursor::after {
    content: '';
    position: absolute;
    left: 8px;
    top: 8px;
    width: 22px;
    height: 22px;
    border-radius: 999px;
    border: 2px solid rgba(255, 255, 255, 0.84);
    opacity: 0;
    transform: scale(0.28);
    animation: landingActionableCursorClick 9.6s ease-in-out infinite;
  }

  @keyframes landingActionableScene {
    0%, 100% { transform: scale(1); }
  }

  @keyframes landingActionableUserMessage {
    0% { opacity: 0; transform: translateY(12px); }
    10%, 100% { opacity: 1; transform: translateY(0); }
  }

  @keyframes landingActionableAssistantMessage {
    0%, 12% { opacity: 0; transform: translateY(12px); }
    22%, 100% { opacity: 1; transform: translateY(0); }
  }

  @keyframes landingActionablePreview {
    0%, 38% { opacity: 0; transform: translateX(-50%) translateY(18px) scale(0.92); }
    50%, 100% { opacity: 1; transform: translateX(-50%) translateY(0) scale(1); }
  }

  @keyframes landingActionableCtaCard {
    0%, 66% { opacity: 0; transform: translateX(-50%) translateY(28px) scale(0.94); }
    76%, 100% { opacity: 1; transform: translateX(-50%) translateY(0) scale(1); }
  }

  @keyframes landingActionableCursor {
    0%, 46% { opacity: 0; left: 28%; top: 54%; transform: translate(-50%, -50%) scale(1); }
    52%, 62% { opacity: 1; left: 54%; top: 71%; transform: translate(-50%, -50%) scale(1); }
    66% { opacity: 1; left: 54%; top: 71%; transform: translate(-50%, -50%) scale(0.86); }
    72%, 84% { opacity: 1; left: 64%; top: 83%; transform: translate(-50%, -50%) scale(1); }
    88% { opacity: 1; left: 73%; top: 83%; transform: translate(-50%, -50%) scale(0.86); }
    96%, 100% { opacity: 0; left: 73%; top: 83%; transform: translate(-50%, -50%) scale(1); }
  }

  @keyframes landingActionableCursorClick {
    0%, 62%, 70%, 84%, 92%, 100% { opacity: 0; transform: scale(0.28); }
    66%, 88% { opacity: 0.9; transform: scale(1); }
  }

  @media (max-width: 730px) {
    .landing-actionable-demo {
      width: 100%;
      min-width: 0;
      height: 100%;
      min-height: 0;
    }

    .landing-actionable-chat {
      inset: 10px 10px auto;
      gap: 8px;
    }

    .landing-actionable-preview {
      bottom: 10px;
      width: min(100%, 300px);
    }

    .landing-actionable-cta-card {
      bottom: 14px;
      width: min(92%, 360px);
      padding: 12px;
      gap: 10px;
    }

    .landing-actionable-luma-button {
      min-width: 118px;
      height: 38px;
      padding: 0 14px;
      font-size: 0.78rem;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .landing-actionable-scene,
    .landing-actionable-user-row,
    .landing-actionable-assistant-row,
    .landing-actionable-preview,
    .landing-actionable-cta-card,
    .landing-actionable-cursor,
    .landing-actionable-cursor::after {
      animation: none !important;
    }

    .landing-actionable-user-row,
    .landing-actionable-preview,
    .landing-actionable-cta-card {
      opacity: 1;
    }

    .landing-actionable-preview {
      transform: translateX(-50%);
    }

    .landing-actionable-cta-card {
      transform: translateX(-50%);
    }
  }
</style>
