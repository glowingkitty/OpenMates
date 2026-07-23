<script lang="ts">
  /**
   * LandingActionableEventDemo.svelte
   *
   * Lightweight logged-out landing animation for the Actionable product slide.
   * It intentionally does not mount the full chat or event embed runtime; the
   * goal is a visually faithful, public, deterministic product explainer that
   * can autoplay safely inside the daily inspiration banner.
   */

  import { text } from '@repo/ui';
</script>

<div class="landing-actionable-demo" data-testid="landing-actionable-event-demo" aria-hidden="true">
  <div class="landing-actionable-scene" data-testid="landing-actionable-event-scene">
    <div class="landing-actionable-chat">
      <div class="landing-actionable-message landing-actionable-message-user" data-testid="landing-actionable-user-message">
        {$text('demo_chats.for_everyone.landing_actionable_event_user_message')}
      </div>
      <div class="landing-actionable-message landing-actionable-message-assistant" data-testid="landing-actionable-assistant-message">
        {$text('demo_chats.for_everyone.landing_actionable_event_assistant_message')}
      </div>
    </div>

    <div class="landing-actionable-preview" data-testid="landing-actionable-event-preview">
      <div class="landing-actionable-preview-topline">
        <span class="landing-actionable-preview-icon"></span>
        <span>{$text('demo_chats.for_everyone.landing_actionable_event_source')}</span>
      </div>
      <h3>{$text('demo_chats.for_everyone.landing_actionable_event_title')}</h3>
      <p>{$text('demo_chats.for_everyone.landing_actionable_event_meta')}</p>
      <div class="landing-actionable-preview-tags">
        <span>{$text('demo_chats.for_everyone.landing_actionable_event_tag_language')}</span>
        <span>{$text('demo_chats.for_everyone.landing_actionable_event_tag_level')}</span>
      </div>
    </div>

    <div class="landing-actionable-fullscreen" data-testid="landing-actionable-event-fullscreen">
      <div class="landing-actionable-fullscreen-header">
        <span class="landing-actionable-window-dot"></span>
        <span class="landing-actionable-window-dot"></span>
        <span class="landing-actionable-window-dot"></span>
      </div>
      <div class="landing-actionable-fullscreen-body">
        <p class="landing-actionable-detail-label">{$text('demo_chats.for_everyone.landing_actionable_event_source')}</p>
        <h3>{$text('demo_chats.for_everyone.landing_actionable_event_title')}</h3>
        <p>{$text('demo_chats.for_everyone.landing_actionable_event_detail')}</p>
        <div class="landing-actionable-detail-grid">
          <span>{$text('demo_chats.for_everyone.landing_actionable_event_chip_day')}</span>
          <span>{$text('demo_chats.for_everyone.landing_actionable_event_chip_time')}</span>
          <span>{$text('demo_chats.for_everyone.landing_actionable_event_chip_place')}</span>
        </div>
      </div>
    </div>
  </div>
</div>

<style>
  .landing-actionable-demo {
    position: relative;
    flex: 0 1 auto;
    width: min(54vw, 720px);
    min-width: 390px;
    height: calc(100% - 18px);
    min-height: 210px;
    border-radius: var(--radius-4);
    overflow: hidden;
    background:
      radial-gradient(circle at 18% 18%, rgba(255, 255, 255, 0.2), transparent 32%),
      linear-gradient(135deg, rgba(18, 25, 62, 0.56), rgba(19, 37, 88, 0.68));
    border: 1px solid rgba(255, 255, 255, 0.18);
    box-shadow: 0 18px 44px rgba(0, 0, 0, 0.28), 0 4px 12px rgba(0, 0, 0, 0.16);
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
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .landing-actionable-message {
    width: fit-content;
    max-width: min(82%, 430px);
    padding: 10px 14px;
    border-radius: 16px;
    font-size: clamp(0.78rem, 1.1vw, 0.98rem);
    line-height: 1.25;
    font-weight: 700;
    box-shadow: 0 10px 24px rgba(0, 0, 0, 0.2);
  }

  .landing-actionable-message-user {
    align-self: flex-end;
    color: var(--color-grey-100);
    background: var(--color-grey-blue);
    animation: landingActionableUserMessage 9.6s ease-in-out infinite;
  }

  .landing-actionable-message-assistant {
    align-self: flex-start;
    color: rgba(20, 35, 74, 0.92);
    background: rgba(255, 255, 255, 0.94);
    animation: landingActionableAssistantMessage 9.6s ease-in-out infinite;
  }

  .landing-actionable-preview,
  .landing-actionable-fullscreen {
    position: absolute;
    color: rgba(18, 29, 62, 0.94);
    background: rgba(255, 255, 255, 0.96);
    border: 1px solid rgba(255, 255, 255, 0.7);
    box-shadow: 0 18px 42px rgba(5, 12, 36, 0.28);
  }

  .landing-actionable-preview {
    left: 50%;
    bottom: 18px;
    width: min(76%, 410px);
    padding: 14px;
    border-radius: 18px;
    transform: translateX(-50%) translateY(18px) scale(0.92);
    opacity: 0;
    animation: landingActionablePreview 9.6s ease-in-out infinite;
  }

  .landing-actionable-preview-topline,
  .landing-actionable-preview-tags,
  .landing-actionable-detail-grid {
    display: flex;
    align-items: center;
  }

  .landing-actionable-preview-topline {
    gap: 7px;
    margin-bottom: 8px;
    color: rgba(48, 77, 139, 0.8);
    font-size: 0.72rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  .landing-actionable-preview-icon {
    width: 18px;
    height: 18px;
    border-radius: 6px;
    background: var(--color-app-events, #4d8cff);
  }

  .landing-actionable-preview h3,
  .landing-actionable-fullscreen h3,
  .landing-actionable-preview p,
  .landing-actionable-fullscreen p {
    margin: 0;
  }

  .landing-actionable-preview h3,
  .landing-actionable-fullscreen h3 {
    font-size: clamp(1rem, 1.55vw, 1.4rem);
    line-height: 1.1;
    letter-spacing: -0.03em;
  }

  .landing-actionable-preview p,
  .landing-actionable-fullscreen p {
    margin-top: 7px;
    color: rgba(35, 45, 76, 0.72);
    font-size: 0.82rem;
    line-height: 1.32;
    font-weight: 650;
  }

  .landing-actionable-preview-tags {
    flex-wrap: wrap;
    gap: 7px;
    margin-top: 12px;
  }

  .landing-actionable-preview-tags span,
  .landing-actionable-detail-grid span {
    border-radius: 999px;
    padding: 5px 8px;
    background: rgba(75, 113, 214, 0.12);
    color: rgba(46, 72, 138, 0.9);
    font-size: 0.72rem;
    font-weight: 800;
  }

  .landing-actionable-fullscreen {
    inset: 14px;
    display: flex;
    flex-direction: column;
    border-radius: 22px;
    transform: translateY(26px) scale(0.78);
    opacity: 0;
    animation: landingActionableFullscreen 9.6s ease-in-out infinite;
  }

  .landing-actionable-fullscreen-header {
    display: flex;
    gap: 6px;
    padding: 12px 14px;
    border-bottom: 1px solid rgba(28, 45, 89, 0.1);
  }

  .landing-actionable-window-dot {
    width: 8px;
    height: 8px;
    border-radius: 999px;
    background: rgba(46, 72, 138, 0.28);
  }

  .landing-actionable-fullscreen-body {
    display: flex;
    flex: 1;
    flex-direction: column;
    justify-content: center;
    padding: 14px 18px 18px;
  }

  .landing-actionable-detail-label {
    margin-top: 0 !important;
    color: rgba(48, 77, 139, 0.78) !important;
    font-size: 0.72rem !important;
    font-weight: 850 !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  .landing-actionable-detail-grid {
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 14px;
  }

  @keyframes landingActionableScene {
    0%, 58% { transform: scale(1); }
    72%, 100% { transform: scale(0.93); }
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
    0%, 62% { opacity: 0; transform: translateY(26px) scale(0.78); }
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
      inset: 12px 12px auto;
    }

    .landing-actionable-message {
      max-width: 88%;
      padding: 8px 10px;
      font-size: 0.74rem;
    }

    .landing-actionable-preview {
      bottom: 12px;
      width: min(86%, 330px);
      padding: 11px;
    }

    .landing-actionable-preview p,
    .landing-actionable-preview-tags,
    .landing-actionable-fullscreen p {
      display: none;
    }

    .landing-actionable-fullscreen {
      inset: 10px;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .landing-actionable-scene,
    .landing-actionable-message-user,
    .landing-actionable-message-assistant,
    .landing-actionable-preview,
    .landing-actionable-fullscreen {
      animation: none !important;
    }

    .landing-actionable-message-user,
    .landing-actionable-fullscreen {
      opacity: 1;
      transform: none;
    }

    .landing-actionable-message-assistant,
    .landing-actionable-preview {
      opacity: 0;
    }
  }
</style>
