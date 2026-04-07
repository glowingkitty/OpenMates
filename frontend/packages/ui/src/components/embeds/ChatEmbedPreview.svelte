<!--
  frontend/packages/ui/src/components/embeds/ChatEmbedPreview.svelte
  
  A preview card for example/demo chats displayed in the for-everyone and
  for-developers intro chat messages. Uses the chat's category gradient as the
  full card background with the category icon + title centered on top — matching
  the visual language of ChatHeader.svelte (the gradient banner at the top of
  active chats).
  
  Structure:
  - Full-card category gradient background (135deg, start→end colors)
  - Centered category Lucide icon (32px, white)
  - Chat title (16px, white, bold, max 2 lines)
  - Preview text / summary (12px, white at 0.85 opacity, max 3 lines)
  - Large decorative icons at left/right edges (80px, 0.3 opacity)
  
  Dimensions match UnifiedEmbedPreview for consistency with other embed cards:
  - Desktop: 300x200px
  - Mobile: 150x290px
  
  Click navigates to the demo chat via the onClick callback.
  
  Architecture: This component does NOT use UnifiedEmbedPreview + BasicInfosBar
  because the design calls for the category gradient to fill the entire card
  (not just a bottom bar). The card is self-contained with its own sizing,
  interactions (hover tilt, scale), and click handling.
-->

<script lang="ts">
  import { getCategoryGradientColors, getValidIconName, getLucideIcon, getFallbackIconForCategory } from '../../utils/categoryUtils';
  
  /**
   * Props interface for ChatEmbedPreview
   * Accepts direct cleartext values (not translation keys) since community
   * demo chats already have decrypted data from the server.
   */
  interface Props {
    /** Chat ID for navigation */
    chatId: string;
    /** Cleartext chat title */
    title: string;
    /** Cleartext text shown below the title (chat summary or fallback) */
    previewText: string;
    /** Category string (e.g., 'general_knowledge', 'programming') */
    category: string;
    /** Icon name from Lucide library */
    iconName: string;
    /** Click handler - called when the card is clicked */
    onClick?: (chatId: string) => void;
  }
  
  let {
    chatId,
    title,
    previewText,
    category,
    iconName,
    onClick
  }: Props = $props();
  
  // ─── Category gradient + icon ──────────────────────────────────────────────
  
  /** Category gradient colors for the card background. Falls back to primary if not found. */
  let categoryGradientColors = $derived(getCategoryGradientColors(category));
  
  /** Inline style for the gradient background + orb CSS custom properties.
   *  --orb-color-a (start) and --orb-color-b (end) feed the living gradient orbs. */
  let gradientStyle = $derived(
    categoryGradientColors
      ? `background: linear-gradient(135deg, ${categoryGradientColors.start}, ${categoryGradientColors.end}); --orb-color-a: ${categoryGradientColors.start}; --orb-color-b: ${categoryGradientColors.end}`
      : 'background: var(--color-primary)'
  );
  
  /** Resolved Lucide icon name (tries provided name, then category fallback) */
  let resolvedIconName = $derived(
    iconName
      ? getValidIconName([iconName], category)
      : getFallbackIconForCategory(category)
  );
  
  /** Lucide icon component for the category */
  let CategoryIconComponent = $derived(getLucideIcon(resolvedIconName));
  
  // ─── Hover tilt effect (mirrors UnifiedEmbedPreview) ───────────────────────
  
  let cardElement = $state<HTMLElement | null>(null);
  let isHovering = $state(false);
  let mouseX = $state(0);
  let mouseY = $state(0);
  
  /** Max tilt angle and perspective — subtle, polished feel */
  const TILT_MAX_ANGLE = 3;
  const TILT_PERSPECTIVE = 800;
  const TILT_SCALE = 0.985;
  
  let tiltTransform = $derived.by(() => {
    if (!isHovering) return '';
    const rotateY = mouseX * TILT_MAX_ANGLE;
    const rotateX = -mouseY * TILT_MAX_ANGLE;
    return `perspective(${TILT_PERSPECTIVE}px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(${TILT_SCALE})`;
  });
  
  function handleMouseEnter(e: MouseEvent) {
    isHovering = true;
    updateMousePosition(e);
  }
  
  function handleMouseMove(e: MouseEvent) {
    if (!isHovering || !cardElement) return;
    updateMousePosition(e);
  }
  
  function handleMouseLeave() {
    isHovering = false;
    mouseX = 0;
    mouseY = 0;
  }
  
  function updateMousePosition(e: MouseEvent) {
    if (!cardElement) return;
    const rect = cardElement.getBoundingClientRect();
    mouseX = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
    mouseY = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
  }
  
  // ─── Click handling ────────────────────────────────────────────────────────
  
  function handleClick(e: MouseEvent) {
    e.stopPropagation();
    if (onClick) {
      onClick(chatId);
    }
  }
  
  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      if (onClick) {
        onClick(chatId);
      }
    }
  }
</script>

<div
  bind:this={cardElement}
  class="chat-embed-card"
  class:hovering={isHovering}
  style="{gradientStyle}; {tiltTransform ? `transform: ${tiltTransform};` : ''}"
  role="button"
  tabindex={0}
  onclick={handleClick}
  onkeydown={handleKeydown}
  onmouseenter={handleMouseEnter}
  onmousemove={handleMouseMove}
  onmouseleave={handleMouseLeave}
>
  <!-- Living gradient orbs — three morphing blobs (same system as ActiveChat resume card).
       Uses smaller resumeOrbDrift keyframes + blur(22px) to suit the 300×200px card. -->
  <div class="chat-preview-orbs" aria-hidden="true">
    <div class="orb orb-1"></div>
    <div class="orb orb-2"></div>
    <div class="orb orb-3"></div>
  </div>

  <!-- Large decorative icons at card edges — two-phase: decoEnter → decoFloat orbital.
       Smaller orbit radius (7×8px) for the compact card. -->
  {#if CategoryIconComponent}
    <div class="deco-icon deco-icon-left">
      <CategoryIconComponent size={80} color="white" />
    </div>
    <div class="deco-icon deco-icon-right">
      <CategoryIconComponent size={80} color="white" />
    </div>
  {/if}

  <!-- Centered content: icon + title + summary -->
  <div class="card-content">
    {#if CategoryIconComponent}
      <div class="card-icon">
        <CategoryIconComponent size={32} color="white" />
      </div>
    {/if}

    <!-- eslint-disable-next-line svelte/no-at-html-tags -->
    <span class="card-title" data-testid="card-title">{@html title}</span>

    {#if previewText}
      <p class="card-summary">{previewText}</p>
    {/if}
  </div>
</div>

<style>
  /* ===========================================
     Chat Embed Card — Full gradient card
     Matches ChatHeader.svelte visual language
     =========================================== */

  .chat-embed-card {
    position: relative;
    /* Desktop size (matches UnifiedEmbedPreview) */
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
    will-change: transform;
    /* Shadow matching UnifiedEmbedPreview */
    box-shadow:
      0 8px 24px rgba(0, 0, 0, 0.16),
      0 2px 6px rgba(0, 0, 0, 0.1);
    transition:
      transform 0.15s ease-out,
      box-shadow 0.2s ease-out;
  }

  .chat-embed-card:focus {
    outline: 2px solid rgba(255, 255, 255, 0.5);
    outline-offset: 2px;
  }

  /* Hover: tighter shadow (card appears "pressed closer") */
  .chat-embed-card.hovering {
    box-shadow:
      0 4px 12px rgba(0, 0, 0, 0.12),
      0 1px 3px rgba(0, 0, 0, 0.08);
  }

  .chat-embed-card:active {
    transform: scale(0.96) !important;
    transition: transform 0.05s ease-out;
  }

  /* ===========================================
     Centered content overlay
     =========================================== */

  .card-content {
    position: relative;
    z-index: var(--z-index-raised-2);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-2);
    padding: var(--spacing-8) var(--spacing-12);
    max-width: 260px;
    width: 100%;
  }

  .card-icon {
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .card-title {
    display: block;
    font-size: var(--font-size-p);
    font-weight: 700;
    color: var(--color-grey-100);
    text-align: center;
    line-height: 1.3;
    max-width: 100%;
    /* Clamp to 2 lines */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .card-summary {
    margin: 2px 0 0;
    font-size: var(--font-size-xxs);
    font-weight: 500;
    color: rgba(255, 255, 255, 0.85);
    line-height: 1.4;
    text-align: center;
    /* Clamp to 3 lines */
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  /* ===========================================
     Living gradient orbs (300×200px card)
     Same system as ActiveChat resume card:
     smaller drift (resumeOrbDrift), blur(22px).
     Shared keyframes in animations.css.
     =========================================== */

  .chat-preview-orbs {
    position: absolute;
    inset: 0;
    z-index: var(--z-index-base);
    pointer-events: none;
    overflow: hidden;
    border-radius: 30px; /* match card border-radius so orbs don't bleed */
  }

  .orb {
    position: absolute;
    width: 280px;
    height: 240px;
    filter: blur(22px);
    opacity: 0.55;
    will-change: transform, border-radius;
  }

  /* Orb 1 — color-b (end), top-left anchor */
  .orb-1 {
    top: -60px;
    left: -70px;
    background: radial-gradient(
      ellipse at center,
      var(--orb-color-b, #fff) 0%,
      var(--orb-color-b, #fff) 40%,
      transparent 85%
    );
    animation:
      orbMorph1 11s ease-in-out infinite,
      resumeOrbDrift1 19s ease-in-out infinite;
  }

  /* Orb 2 — color-a (start), bottom-right anchor */
  .orb-2 {
    bottom: -80px;
    right: -80px;
    width: 260px;
    height: 220px;
    background: radial-gradient(
      ellipse at center,
      var(--orb-color-a, #fff) 0%,
      var(--orb-color-a, #fff) 40%,
      transparent 85%
    );
    animation:
      orbMorph2 13s ease-in-out infinite,
      resumeOrbDrift2 23s ease-in-out infinite;
  }

  /* Orb 3 — color-b (end), center-left for depth */
  .orb-3 {
    top: -10px;
    left: 25%;
    width: 200px;
    height: 180px;
    opacity: 0.38;
    background: radial-gradient(
      ellipse at center,
      var(--orb-color-b, #fff) 0%,
      var(--orb-color-b, #fff) 40%,
      transparent 85%
    );
    animation:
      orbMorph3 17s ease-in-out infinite,
      resumeOrbDrift3 29s ease-in-out infinite;
  }

  /* ===========================================
     Decorative icons at card edges
     Two-phase: decoEnter (one-shot) → decoFloat (16s orbital).
     Smaller orbit (7×8px) for 300×200px card.
     Shared keyframes in animations.css.
     =========================================== */

  .deco-icon {
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
    animation:
      decoEnter 0.6s ease-out 0.1s both,
      decoFloat 16s linear 0.7s infinite;
  }

  .deco-icon-left {
    left: -10px;
    bottom: -8px;
    --deco-rotate: -15deg;
  }

  .deco-icon-right {
    right: -10px;
    bottom: -8px;
    --deco-rotate: 15deg;
    /* Negative delay: start mid-orbit (half-cycle) immediately — no freeze */
    animation-delay: 0.1s, -8s;
  }

  /* Ensure Lucide SVGs inside deco icons render at the right size */
  .deco-icon :global(svg) {
    width: 80px !important;
    height: 80px !important;
  }

  /* ===========================================
     Accessibility: disable all animations
     =========================================== */

  @media (prefers-reduced-motion: reduce) {
    .orb {
      animation: none;
    }

    .deco-icon {
      animation: decoEnter 0.6s ease-out 0.1s both !important;
    }
  }
</style>
