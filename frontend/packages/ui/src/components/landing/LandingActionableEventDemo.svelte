<script lang="ts">
  /**
   * LandingActionableEventDemo.svelte
   *
   * Lightweight logged-out landing animation for the Actionable product slide.
   * It mirrors the real chat-message bubble classes and real events embed
   * preview/fullscreen visual system without mounting an interactive chat flow.
   */

  import { text } from '@repo/ui';
  import EventEmbedPreview from '../embeds/events/EventEmbedPreview.svelte';

  const demoStartDate = new Date();
  demoStartDate.setHours(19, 0, 0, 0);
  const demoEndDate = new Date(demoStartDate);
  demoEndDate.setHours(21, 0, 0, 0);

  const demoEvent = {
    embed_id: 'landing-actionable-event-preview',
    id: 'landing-actionable-language-exchange',
    provider: 'meetup',
    title: 'Berlin Language Exchange',
    description: 'Practice German and English in small groups, then save the event or ask for similar options.',
    url: 'https://example.com/events/berlin-language-exchange',
    date_start: demoStartDate.toISOString(),
    date_end: demoEndDate.toISOString(),
    event_type: 'PHYSICAL',
    venue: {
      name: 'Cafe Kreuzberg',
      address: 'Oranienstrasse 24',
      city: 'Berlin',
      country: 'Germany',
      lat: 52.5009,
      lon: 13.4215,
    },
    organizer: { name: 'Berlin Language Friends' },
    rsvp_count: 42,
    is_paid: false,
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
    </div>

    <div class="landing-actionable-fullscreen" data-testid="landing-actionable-event-fullscreen">
      <div class="landing-actionable-fullscreen-header">
        <div class="landing-actionable-fullscreen-icon" aria-hidden="true"></div>
        <div>
          <h3>{$text('demo_chats.for_everyone.landing_actionable_event_title')}</h3>
          <p>{$text('demo_chats.for_everyone.landing_actionable_event_meta')}</p>
        </div>
      </div>

      <div class="landing-actionable-fullscreen-layout">
        <div class="landing-actionable-map" data-testid="landing-actionable-event-map">
          <div class="landing-actionable-map-grid"></div>
          <div class="landing-actionable-map-marker"></div>
        </div>

        <div class="landing-actionable-detail-card">
          <div class="event-meta-row">
            <span class="event-type-badge">In Person</span>
            <span class="event-free-badge">Free</span>
            <span class="event-rsvp">42 RSVPs</span>
            <span class="event-source-badge">Meetup</span>
          </div>

          <div class="event-section">
            <div class="section-label">Date &amp; Time</div>
            <div class="section-value date-relative">{$text('demo_chats.for_everyone.landing_actionable_event_chip_day')}</div>
            <div class="section-value">{$text('demo_chats.for_everyone.landing_actionable_event_chip_time')}</div>
          </div>

          <div class="event-section">
            <div class="section-label">Location</div>
            <div class="section-value venue-address">Cafe Kreuzberg<br>Oranienstrasse 24<br>{$text('demo_chats.for_everyone.landing_actionable_event_chip_place')}</div>
          </div>

          <div class="event-section">
            <div class="section-label">About</div>
            <div class="section-value">{$text('demo_chats.for_everyone.landing_actionable_event_detail')}</div>
          </div>
        </div>
      </div>
    </div>
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
    overflow: hidden;
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

  .landing-actionable-fullscreen {
    position: absolute;
    inset: 10px;
    z-index: var(--z-index-dropdown);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border-radius: 22px;
    background: var(--color-grey-0);
    box-shadow: var(--shadow-xl);
    transform: translateY(26px) scale(0.76);
    opacity: 0;
    animation: landingActionableFullscreen 9.6s ease-in-out infinite;
  }

  .landing-actionable-fullscreen-header {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 62px;
    padding: 12px 16px;
    color: white;
    background: linear-gradient(135deg, var(--color-app-events-start, #a20000), var(--color-app-events-end, #e61b3e));
  }

  .landing-actionable-fullscreen-icon {
    width: 38px;
    height: 38px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.92);
    -webkit-mask-image: url('@openmates/ui/static/icons/event.svg');
    mask-image: url('@openmates/ui/static/icons/event.svg');
    -webkit-mask-size: 58%;
    mask-size: 58%;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
  }

  .landing-actionable-fullscreen-header h3,
  .landing-actionable-fullscreen-header p {
    margin: 0;
  }

  .landing-actionable-fullscreen-header h3 {
    font-size: clamp(0.98rem, 1.4vw, 1.25rem);
    line-height: 1.1;
    letter-spacing: -0.025em;
  }

  .landing-actionable-fullscreen-header p {
    margin-top: 3px;
    color: rgba(255, 255, 255, 0.82);
    font-size: 0.78rem;
    font-weight: 650;
  }

  .landing-actionable-fullscreen-layout {
    position: relative;
    flex: 1;
    min-height: 0;
    background: var(--color-background-secondary, #f4f5f8);
  }

  .landing-actionable-map {
    position: absolute;
    inset: 0;
    overflow: hidden;
    background: linear-gradient(135deg, #dbeafe, #eef2ff);
  }

  .landing-actionable-map-grid {
    position: absolute;
    inset: -20%;
    opacity: 0.52;
    background-image:
      linear-gradient(rgba(59, 91, 170, 0.18) 1px, transparent 1px),
      linear-gradient(90deg, rgba(59, 91, 170, 0.18) 1px, transparent 1px);
    background-size: 38px 38px;
    transform: rotate(-7deg) scale(1.1);
  }

  .landing-actionable-map-marker {
    position: absolute;
    left: 64%;
    top: 42%;
    width: 22px;
    height: 22px;
    border-radius: 999px 999px 999px 0;
    background: var(--color-app-events-start, #a20000);
    transform: rotate(-45deg);
    box-shadow: var(--shadow-md);
  }

  .landing-actionable-map-marker::after {
    content: '';
    position: absolute;
    inset: 6px;
    border-radius: 999px;
    background: var(--color-grey-0);
  }

  .landing-actionable-detail-card {
    position: absolute;
    left: 18px;
    top: 18px;
    bottom: 18px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    width: min(48%, 300px);
    overflow: hidden;
    padding: 16px;
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-lg);
    color: var(--color-font-primary);
  }

  .event-meta-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
  }

  .event-type-badge,
  .event-free-badge,
  .event-source-badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 8px;
    border-radius: 100px;
    font-size: 0.64rem;
    font-weight: 700;
  }

  .event-type-badge {
    color: var(--color-grey-0);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    background: var(--color-app-events-start, #a20000);
  }

  .event-free-badge {
    background: rgba(34, 197, 94, 0.15);
    color: var(--color-font-primary);
  }

  .event-rsvp {
    color: var(--color-grey-60);
    font-size: 0.68rem;
  }

  .event-source-badge {
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-25);
    color: var(--color-font-secondary);
  }

  .event-section {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .section-label {
    color: var(--color-grey-60);
    font-size: 0.62rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .section-value {
    color: var(--color-font-primary);
    font-size: 0.78rem;
    line-height: 1.35;
    font-weight: 600;
  }

  .date-relative {
    font-size: 0.96rem;
    font-weight: 800;
  }

  .venue-address {
    font-size: 0.74rem;
  }

  @keyframes landingActionableScene {
    0%, 58% { transform: scale(1); }
    72%, 100% { transform: scale(0.95); }
  }

  @keyframes landingActionableUserMessage {
    0% { opacity: 0; transform: translateY(12px); }
    10%, 100% { opacity: 1; transform: translateY(0); }
  }

  @keyframes landingActionableAssistantMessage {
    0%, 12% { opacity: 0; transform: translateY(12px); }
    22%, 42% { opacity: 1; transform: translateY(0); }
    54%, 100% { opacity: 0; transform: translateY(-18px); }
  }

  @keyframes landingActionablePreview {
    0%, 38% { opacity: 0; transform: translateX(-50%) translateY(18px) scale(0.92); }
    50%, 64% { opacity: 1; transform: translateX(-50%) translateY(0) scale(1); }
    76%, 100% { opacity: 0; transform: translateX(-50%) translateY(-12px) scale(1.08); }
  }

  @keyframes landingActionableFullscreen {
    0%, 62% { opacity: 0; transform: translateY(26px) scale(0.76); }
    76%, 100% { opacity: 1; transform: translateY(0) scale(1); }
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

    .landing-actionable-fullscreen {
      inset: 8px;
    }

    .landing-actionable-detail-card {
      width: min(58%, 230px);
      padding: 11px;
      gap: 7px;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .landing-actionable-scene,
    .landing-actionable-user-row,
    .landing-actionable-assistant-row,
    .landing-actionable-preview,
    .landing-actionable-fullscreen {
      animation: none !important;
    }

    .landing-actionable-user-row,
    .landing-actionable-fullscreen {
      opacity: 1;
      transform: none;
    }

    .landing-actionable-assistant-row,
    .landing-actionable-preview {
      opacity: 0;
    }
  }
</style>
