<!--
  StartScreenChatCard.svelte — the one large card of the start-screen row.

  Used for every entry of the Chats row (own chats, reminder-priority chats, drafts,
  example chats and daily inspirations). There is no small "pill" variant: the
  start screens always show large cards (TASK-1321). A daily inspiration is the
  same card with a small label, so every card in the Chats row opens a chat. Inspirations
  never show their video or article image as the card background (Marco, 21 Nov).

  Native counterpart: apple/OpenMates/Sources/Features/Chat/Views/ChatWelcomeContinueCards.swift
  Spec: specifications/features/daily-inspiration (start-row assertions)
-->
<script lang="ts">
  import ContinueCardUnreadBadge from '../workspace/ContinueCardUnreadBadge.svelte';
  import { getContinueGradientColors, getResumeCardGradientStyle } from '../activeChatUtils';
  import { getLucideIcon, getValidIconName } from '../../utils/categoryUtils';
  import type { ResumeCardImageBubble } from '../../types/chat';
  // Privacy placeholders in the summary read as in the message view ([PERSON_NAME_1]), never with their nonce.
  import { aliasEnhancedPlaceholders } from '../../services/piiDisplayAliases';

  /** Optional long-press / context-menu handlers of own chat cards. */
  export type StartScreenCardGestures = {
    onContextMenu: (event: MouseEvent) => void;
    onTouchStart: (event: TouchEvent) => void;
    onTouchMove: (event: TouchEvent) => void;
    onTouchEnd: (event: TouchEvent) => void;
  };

  type Badge = { label: string; testId: string; icon?: string | null };

  type Props = {
    testId: string;
    title: string;
    summary?: string | null;
    category?: string | null;
    icon?: string | null;
    appId?: string | null;
    imageBubbles?: ResumeCardImageBubble[] | null;
    chatId?: string | null;
    pinned?: boolean;
    /** Small label inside the card content (Shared, Example, Daily inspiration). */
    badge?: Badge | null;
    /** Label pinned to the top-left corner (reminder or date priority). */
    cornerLabel?: Badge | null;
    /** Running chat (or parent of a running sub-chat): corner "Active" label with a live dot; replaces cornerLabel. */
    active?: { label: string; testId: string } | null;
    /** Draft-only chats and chats waiting for credits show a label and preview instead of an icon. */
    preview?: { label: string; text: string } | null;
    dataAttributes?: Record<string, string>;
    gestures: StartScreenCardGestures | null;
    onActivate: () => void;
  };

  let {
    testId,
    title,
    summary = null,
    category = null,
    icon = null,
    appId = null,
    imageBubbles = null,
    chatId = null,
    pinned = false,
    badge = null,
    cornerLabel = null,
    active = null,
    preview = null,
    dataAttributes = {},
    gestures,
    onActivate,
  }: Props = $props();

  const TILT_MAX_ANGLE = 3;
  const TILT_PERSPECTIVE = 800;
  const TILT_SCALE = 0.985;

  let element = $state<HTMLButtonElement | null>(null);
  let hovering = $state(false);
  let mouseX = $state(0);
  let mouseY = $state(0);

  let iconCategory = $derived(category || 'general_knowledge');
  let IconComponent = $derived(preview ? null : getLucideIcon(getValidIconName(icon || '', iconCategory)));
  let BadgeIcon = $derived(badge?.icon ? getLucideIcon(badge.icon) : null);
  let CornerIcon = $derived(cornerLabel?.icon ? getLucideIcon(cornerLabel.icon) : null);
  let PinIcon = getLucideIcon('pin');
  let bubbles = $derived(imageBubbles && imageBubbles.length > 0 ? imageBubbles.slice(0, 2) : null);

  let cardStyle = $derived.by(() => {
    const parts = [preview && !category ? '' : getResumeCardGradientStyle(getContinueGradientColors(iconCategory, appId))];
    if (hovering) {
      const rotateY = mouseX * TILT_MAX_ANGLE;
      const rotateX = -mouseY * TILT_MAX_ANGLE;
      parts.push(`transform: perspective(${TILT_PERSPECTIVE}px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(${TILT_SCALE})`);
    }
    return parts.filter(Boolean).join('; ');
  });

  function updatePosition(event: MouseEvent): void {
    if (!element) return;
    const rect = element.getBoundingClientRect();
    mouseX = ((event.clientX - rect.left) / rect.width - 0.5) * 2;
    mouseY = ((event.clientY - rect.top) / rect.height - 0.5) * 2;
  }

  function handleMouseEnter(event: MouseEvent): void {
    hovering = true;
    updatePosition(event);
  }

  function handleMouseMove(event: MouseEvent): void {
    if (hovering) updatePosition(event);
  }

  function handleMouseLeave(): void {
    hovering = false;
    mouseX = 0;
    mouseY = 0;
  }
</script>

<button
  bind:this={element}
  type="button"
  class="resume-chat-large-card"
  class:hovering
  class:active={!!active}
  data-active={active ? 'true' : undefined}
  class:neutral-preview={!!preview && !category}
  data-testid={testId}
  data-chat-id={chatId ?? undefined}
  data-pinned={chatId ? (pinned ? 'true' : 'false') : undefined}
  {...dataAttributes}
  style={cardStyle}
  onclick={onActivate}
  oncontextmenu={gestures?.onContextMenu}
  ontouchstart={gestures?.onTouchStart}
  ontouchmove={gestures?.onTouchMove}
  ontouchend={gestures?.onTouchEnd}
  onmouseenter={handleMouseEnter}
  onmousemove={handleMouseMove}
  onmouseleave={handleMouseLeave}
>
  {#if chatId}
    <ContinueCardUnreadBadge {chatId} variant="large" />
  {/if}
  {#if pinned}
    <div class="resume-card-pin-badge" data-testid="resume-card-pin">
      <PinIcon size={18} color="white" />
    </div>
  {/if}
  {#if active}
    <div class="continue-priority-pill active-pill" data-testid={active.testId}>
      <span class="active-dot" aria-hidden="true"></span>
      <span>{active.label}</span>
    </div>
  {:else if cornerLabel}
    <div class="continue-priority-pill" data-testid={cornerLabel.testId}>
      {#if CornerIcon}<CornerIcon size={12} color="white" />{/if}
      <span>{cornerLabel.label}</span>
    </div>
  {/if}

  {#if !preview || category}
    <div class="resume-large-orbs" aria-hidden="true">
      <div class="resume-orb resume-orb-1"></div>
      <div class="resume-orb resume-orb-2"></div>
      <div class="resume-orb resume-orb-3"></div>
    </div>
    {#if IconComponent && !bubbles}
      <div class="resume-large-deco resume-large-deco-left"><IconComponent size={80} color="white" /></div>
      <div class="resume-large-deco resume-large-deco-right"><IconComponent size={80} color="white" /></div>
    {/if}
    {#if bubbles}
      <div class="resume-card-image-bubbles" aria-hidden="true">
        {#each bubbles as bubble, index}
          <div class="resume-card-image-bubble" class:resume-card-image-bubble-left={index === 0} class:resume-card-image-bubble-right={index !== 0}>
            <img src={bubble.imageUrl} alt="" loading="lazy" decoding="async" />
          </div>
        {/each}
      </div>
    {/if}
  {/if}

  <div class="resume-large-content">
    {#if badge}
      <span class="resume-chat-kind-badge" data-testid={badge.testId}>
        {#if BadgeIcon}<BadgeIcon size={11} color="currentColor" />{/if}
        {badge.label}
      </span>
    {/if}
    {#if preview}
      <span class="start-card-preview-label">{preview.label}</span>
      <span class="resume-large-title start-card-preview-text" data-testid="resume-large-title">{preview.text}</span>
    {:else}
      {#if IconComponent}
        <div class="resume-large-icon" data-testid="start-card-icon"><IconComponent size={32} color="white" /></div>
      {/if}
      <span class="resume-large-title" data-testid="resume-large-title">{title}</span>
      {#if summary}
        <p class="resume-large-summary">{aliasEnhancedPlaceholders(summary)}</p>
      {/if}
    {/if}
  </div>
</button>

<style>
  .resume-chat-large-card {
    position: relative;
    flex-shrink: 0;
    width: 300px;
    min-width: 300px;
    max-width: 300px;
    height: 200px;
    min-height: 200px;
    max-height: 200px;
    border-radius: 30px;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    user-select: none;
    -webkit-user-select: none;
    -webkit-touch-callout: none;
    border: none;
    padding: 0;
    margin: 0;
    filter: none;
    background-color: transparent;
    scale: 1;
    pointer-events: auto;
    isolation: isolate;
    box-shadow:
      0 5px 16px rgba(0, 0, 0, 0.11),
      0 1px 4px rgba(0, 0, 0, 0.08);
    transition:
      transform 0.15s ease-out,
      box-shadow 0.2s ease-out;
  }

  /* Phones: keep a part of the next card visible so the row reads as scrollable. */
  @media (max-width: 480px) {
    .resume-chat-large-card {
      width: min(280px, 76vw);
      min-width: min(280px, 76vw);
      max-width: min(280px, 76vw);
    }
  }

  .resume-chat-large-card:hover,
  .resume-chat-large-card:active,
  .resume-chat-large-card.hovering {
    background-color: transparent;
    filter: none;
    scale: 1;
  }

  .resume-chat-large-card.hovering,
  .resume-chat-large-card:hover:not(.hovering) {
    box-shadow:
      0 3px 9px rgba(0, 0, 0, 0.1),
      0 1px 2px rgba(0, 0, 0, 0.07);
  }

  .resume-chat-large-card:hover:not(.hovering) {
    transform: scale(0.98);
  }

  .resume-chat-large-card:active {
    transform: scale(0.96) !important;
    transition: transform 0.05s ease-out;
  }

  .resume-chat-large-card:focus-visible {
    outline: 2px solid var(--color-button-primary);
    outline-offset: 2px;
  }

  /* Draft-only chats have no category yet: neutral surface like the sidebar draft row. */
  .resume-chat-large-card.neutral-preview {
    background: var(--color-grey-0);
    border: 1px solid var(--color-grey-25);
  }

  .resume-chat-large-card.neutral-preview .resume-large-title,
  .resume-chat-large-card.neutral-preview .start-card-preview-label {
    color: var(--color-font-primary);
    text-shadow: none;
  }

  .resume-chat-large-card.neutral-preview .resume-large-content {
    text-shadow: none;
  }

  .resume-large-content {
    position: relative;
    z-index: var(--z-index-raised-3);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-2);
    padding: var(--spacing-8) var(--spacing-12);
    max-width: 260px;
    width: 100%;
    box-sizing: border-box;
    text-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
  }

  .resume-chat-kind-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    width: fit-content;
    border-radius: var(--radius-full);
    padding: 3px 8px;
    background: rgba(255, 255, 255, 0.2);
    color: rgba(255, 255, 255, 0.96);
    font-size: 0.68rem;
    font-weight: 700;
    line-height: 1;
    letter-spacing: 0.01em;
    text-shadow: 0 1px 3px rgba(0, 0, 0, 0.22);
    backdrop-filter: blur(10px);
  }

  .resume-large-icon {
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .resume-large-title {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    font-size: var(--font-size-p);
    font-weight: 700;
    /* Always white regardless of theme: the text sits on a gradient or image. */
    color: var(--color-font-button);
    text-align: center;
    line-height: 1.3;
    max-width: 100%;
  }

  /* Draft text gets a third line (Marco, 22 Nov): two lines wasted the card. */
  .resume-large-title.start-card-preview-text {
    -webkit-line-clamp: 3;
    line-clamp: 3;
  }

  .start-card-preview-label {
    font-size: var(--font-size-small);
    color: var(--color-font-tertiary);
  }

  .resume-large-summary {
    margin: 2px 0 0;
    font-size: var(--font-size-xxs);
    font-weight: 500;
    color: rgba(255, 255, 255, 0.85);
    line-height: 1.4;
    text-align: center;
    display: -webkit-box;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .resume-card-pin-badge {
    position: absolute;
    top: 12px;
    right: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.22);
    backdrop-filter: blur(4px);
    z-index: var(--z-index-raised-2);
  }

  .resume-card-pin-badge :global(svg) {
    transform: rotate(45deg);
  }

  .continue-priority-pill {
    position: absolute;
    top: 12px;
    left: 12px;
    z-index: var(--z-index-raised-4);
    display: inline-flex;
    align-items: center;
    gap: 5px;
    max-width: calc(100% - 24px);
    padding: 5px 9px;
    border-radius: 999px;
    background: rgba(0, 0, 0, 0.28);
    color: white;
    font-size: var(--font-size-xxs);
    font-weight: 700;
    line-height: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    backdrop-filter: blur(8px);
    border: 1px solid rgba(255, 255, 255, 0.2);
    text-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
  }

  /* Active (running) chat: the corner pill gets a live dot and the card a light ring. */
  .resume-chat-large-card.active {
    box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.85), 0 8px 24px rgba(0, 0, 0, 0.18);
  }

  .active-pill {
    background: rgba(0, 0, 0, 0.4);
  }

  .active-dot {
    flex: none;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #3ddc84;
    box-shadow: 0 0 0 0 rgba(61, 220, 132, 0.7);
    animation: active-dot-pulse 1.6s ease-out infinite;
  }

  @keyframes active-dot-pulse {
    0% { box-shadow: 0 0 0 0 rgba(61, 220, 132, 0.7); }
    70% { box-shadow: 0 0 0 6px rgba(61, 220, 132, 0); }
    100% { box-shadow: 0 0 0 0 rgba(61, 220, 132, 0); }
  }

  /* Living gradient orbs; --orb-color-a/b come from getResumeCardGradientStyle(). */
  .resume-large-orbs {
    position: absolute;
    inset: 0;
    z-index: -1;
    pointer-events: none;
    overflow: hidden;
    border-radius: 30px;
  }

  .resume-orb {
    position: absolute;
    width: 280px;
    height: 240px;
    background: radial-gradient(ellipse at center, var(--orb-color-b) 0%, var(--orb-color-b) 40%, transparent 85%);
    filter: blur(22px);
    opacity: 0.35;
    will-change: transform, border-radius;
  }

  .resume-orb-1 {
    top: -60px;
    left: -70px;
    animation: orbMorph1 11s ease-in-out infinite, resumeOrbDrift1 19s ease-in-out infinite;
  }

  .resume-orb-2 {
    bottom: -80px;
    right: -80px;
    width: 260px;
    height: 220px;
    animation: orbMorph2 13s ease-in-out infinite, resumeOrbDrift2 23s ease-in-out infinite;
  }

  .resume-orb-3 {
    top: -10px;
    left: 25%;
    width: 200px;
    height: 180px;
    opacity: 0.38;
    animation: orbMorph3 17s ease-in-out infinite, resumeOrbDrift3 29s ease-in-out infinite;
  }

  .resume-large-deco {
    position: absolute;
    width: 80px;
    height: 80px;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: var(--z-index-raised);
    pointer-events: none;
    --float-rx: 7px;
    --float-ry: 8px;
    --deco-target-opacity: 0.3;
    animation: decoEnter 0.6s ease-out 0.1s both, decoFloat 16s linear 0.7s infinite;
  }

  .resume-large-deco-left {
    left: -10px;
    bottom: -8px;
    --deco-rotate: -15deg;
  }

  .resume-large-deco-right {
    right: -10px;
    bottom: -8px;
    --deco-rotate: 15deg;
    animation-delay: 0.1s, -8s;
  }

  .resume-large-deco :global(svg) {
    width: 80px !important;
    height: 80px !important;
  }

  .resume-card-image-bubbles {
    position: absolute;
    inset: 0;
    z-index: var(--z-index-raised-2);
    pointer-events: none;
  }

  .resume-card-image-bubble {
    position: absolute;
    width: 92px;
    height: 92px;
    border-radius: 999px;
    overflow: hidden;
    box-sizing: border-box;
    opacity: 0.52;
    background:
      radial-gradient(circle at 28% 20%, rgba(255, 255, 255, 0.64), transparent 16%),
      radial-gradient(circle at 70% 76%, rgba(0, 0, 0, 0.25), transparent 38%),
      rgba(255, 255, 255, 0.12);
    border: 2px solid rgba(255, 255, 255, 0.42);
    box-shadow:
      inset 10px 12px 22px rgba(255, 255, 255, 0.32),
      inset -12px -16px 26px rgba(0, 0, 0, 0.28),
      inset 0 0 0 5px rgba(255, 255, 255, 0.08),
      0 14px 28px rgba(0, 0, 0, 0.24);
    animation: startCardBubbleFloat 18s linear infinite;
  }

  .resume-card-image-bubble img {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    filter: saturate(1.1) contrast(1.06);
    transform: scale(1.04);
  }

  .resume-card-image-bubble-left {
    left: -18px;
    bottom: -18px;
    --resume-image-bubble-rotate: -14deg;
  }

  .resume-card-image-bubble-right {
    right: -18px;
    bottom: -18px;
    --resume-image-bubble-rotate: 14deg;
    animation-delay: -9s;
  }

  @keyframes startCardBubbleFloat {
    0%, 100% { transform: translate3d(0, -7px, 0) rotate(var(--resume-image-bubble-rotate, 0deg)); }
    25% { transform: translate3d(6px, 0, 0) rotate(calc(var(--resume-image-bubble-rotate, 0deg) + 2deg)); }
    50% { transform: translate3d(0, 7px, 0) rotate(var(--resume-image-bubble-rotate, 0deg)); }
    75% { transform: translate3d(-6px, 0, 0) rotate(calc(var(--resume-image-bubble-rotate, 0deg) - 2deg)); }
  }

  @media (prefers-reduced-motion: reduce) {
    .resume-orb,
    .resume-card-image-bubble,
    .active-dot { animation: none !important; }
    .resume-large-deco { animation: decoEnter 0.6s ease-out 0.1s both !important; }
  }
</style>
