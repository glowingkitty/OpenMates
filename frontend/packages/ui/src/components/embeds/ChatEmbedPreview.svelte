<!--
  frontend/packages/ui/src/components/embeds/ChatEmbedPreview.svelte
  
  A preview card for example/demo chats, styled to match the UnifiedEmbedPreview
  layout used by other embeds (300x200px desktop).
  
  Structure (matching UnifiedEmbedPreview + BasicInfosBar pattern):
  - Center content area: first user message preview (or summary fallback)
  - Bottom bar (full width, 61px): Category gradient circle with category icon →
    title only (2 lines max, no mate name)
  
  The gradient circle uses the chat's category-specific gradient from theme.css,
  with the Lucide category icon rendered inside it in white.
  
  Click to navigate to the demo chat.
-->

<script lang="ts">
  import { getValidIconName, getLucideIcon } from '../../utils/categoryUtils';
  
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
    /** Cleartext text shown in the center content area (first user message or summary) */
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
  
  // Get Lucide icon component for the category circle in the bottom bar
  let validIconName = $derived(getValidIconName(iconName ? [iconName] : [], category));
  let IconComponent = $derived(getLucideIcon(validIconName));
  
  // Derive the app/category ID for the gradient CSS variable
  // Maps known categories to their app gradients from theme.css
  let categoryGradientId = $derived((() => {
    // Map categories to their corresponding app gradient IDs from theme.css
    const categoryToAppMap: Record<string, string> = {
      'general_knowledge': 'ai',
      'programming': 'code',
      'web_search': 'web',
      'cooking': 'ai',
      'travel': 'maps',
      'news': 'news',
      'science': 'ai',
      'education': 'ai',
      'health': 'life_coaching',
      'finance': 'ai',
      'openmates_official': 'ai',
    };
    return categoryToAppMap[category] || 'ai';
  })());
  
  // Track hover state for tilt effect (matching UnifiedEmbedPreview)
  let isHovering = $state(false);
  let mouseX = $state(0);
  let mouseY = $state(0);
  let cardElement = $state<HTMLElement | null>(null);
  
  // Tilt effect configuration (matching UnifiedEmbedPreview exactly)
  const TILT_MAX_ANGLE = 3;
  const TILT_PERSPECTIVE = 800;
  const TILT_SCALE = 0.985;
  
  // Calculate tilt transform
  let tiltTransform = $derived.by(() => {
    if (!isHovering) return '';
    const rotateY = mouseX * TILT_MAX_ANGLE;
    const rotateX = -mouseY * TILT_MAX_ANGLE;
    return `perspective(${TILT_PERSPECTIVE}px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(${TILT_SCALE})`;
  });
  
  // Mouse event handlers for tilt effect
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
  
  // Handle click
  function handleClick() {
    if (onClick) {
      onClick(chatId);
    }
  }
  
  // Handle keyboard navigation
  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleClick();
    }
  }
</script>

<button
  bind:this={cardElement}
  class="chat-embed-preview"
  class:hovering={isHovering}
  style={tiltTransform ? `transform: ${tiltTransform};` : ''}
  onclick={handleClick}
  onkeydown={handleKeydown}
  onmouseenter={handleMouseEnter}
  onmousemove={handleMouseMove}
  onmouseleave={handleMouseLeave}
  type="button"
  aria-label={title}
>
  <!-- Details section: first user message preview or summary centered in the content area -->
  <div class="details-section">
    {#if previewText}
      <span class="preview-text">{previewText}</span>
    {:else}
      <span class="preview-text placeholder">{title}</span>
    {/if}
  </div>
  
  <!-- Bottom bar: full width, no border-radius (card's overflow:hidden handles corners) -->
  <!-- Shows category gradient circle with icon + title only (no mate name) -->
  <div class="bottom-bar">
    <!-- Category gradient circle (61x61px) with Lucide category icon inside -->
    <!-- Uses the category-specific gradient from theme.css -->
    <div
      class="gradient-circle"
      style="background: var(--color-app-{categoryGradientId});"
    >
      <div class="category-icon-inner">
        <IconComponent size={26} color="white" />
      </div>
    </div>
    
    <!-- Title only (2 lines max, no mate/category name subtitle) -->
    <div class="info-text">
      <span class="title-text">{title}</span>
    </div>
  </div>
</button>

<style>
  /* ===========================================
     Chat Embed Preview - Matches UnifiedEmbedPreview
     =========================================== */
  
  .chat-embed-preview {
    /* Match UnifiedEmbedPreview desktop dimensions */
    width: 300px;
    min-width: 300px;
    max-width: 300px;
    height: 200px;
    min-height: 200px;
    max-height: 200px;
    /* Match UnifiedEmbedPreview styling */
    background-color: var(--color-grey-25);
    border-radius: 30px;
    border: none;
    padding: 0;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-sizing: border-box;
    /* Match UnifiedEmbedPreview shadow (floating above surface) */
    box-shadow: 
      0 8px 24px rgba(0, 0, 0, 0.16),
      0 2px 6px rgba(0, 0, 0, 0.1);
    /* Match UnifiedEmbedPreview transitions */
    transition: 
      transform 0.15s ease-out,
      box-shadow 0.2s ease-out,
      background-color 0.2s ease;
    will-change: transform;
    user-select: none;
    -webkit-user-select: none;
    -webkit-touch-callout: none;
    text-align: left;
    flex-shrink: 0;
  }
  
  /* Hover state: pressed down shadow (matching UnifiedEmbedPreview) */
  .chat-embed-preview.hovering {
    box-shadow: 
      0 4px 12px rgba(0, 0, 0, 0.12),
      0 1px 3px rgba(0, 0, 0, 0.08);
  }
  
  /* Active/pressed state (matching UnifiedEmbedPreview) */
  .chat-embed-preview:active {
    transform: scale(0.96) !important;
    transition: transform 0.05s ease-out;
  }
  
  /* Focus state (matching UnifiedEmbedPreview) */
  .chat-embed-preview:focus {
    outline: 2px solid var(--color-primary);
    outline-offset: 2px;
  }
  
  /* ===========================================
     Details Section - First User Message Preview
     =========================================== */
  
  .details-section {
    flex: 1;
    min-height: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    /* Match UnifiedEmbedPreview text content padding */
    padding: 16px 20px 8px 20px;
  }
  
  .preview-text {
    font-size: 14px;
    font-weight: 500;
    color: var(--color-grey-80);
    line-height: 1.4;
    text-align: center;
    /* Clamp to 4 lines max */
    display: -webkit-box;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }
  
  /* When showing title as placeholder (no preview text available), style slightly different */
  .preview-text.placeholder {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-70);
  }
  
  /* ===========================================
     Bottom Bar - Full Width (no separate border-radius)
     Card's overflow:hidden + border-radius handles corners
     =========================================== */
  
  .bottom-bar {
    display: flex;
    align-items: center;
    gap: 10px;
    /* Match BasicInfosBar height */
    height: 61px;
    min-height: 61px;
    background-color: var(--color-grey-30);
    /* NO border-radius - the card's overflow:hidden + border-radius:30px handles corners.
       This ensures the bottom bar appears truly full-width without visible rounded top corners. */
    border-radius: 0;
    padding: 0;
    flex-shrink: 0;
  }
  
  /* Category gradient circle: 61x61px with category-specific gradient */
  /* Contains the Lucide category icon in white */
  .gradient-circle {
    width: 61px;
    height: 61px;
    min-width: 61px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  
  /* Inner container for the Lucide icon inside the gradient circle */
  .category-icon-inner {
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  /* Ensure Lucide SVG renders correctly */
  .category-icon-inner :global(svg) {
    display: block;
  }
  
  /* ===========================================
     Info Text - Title Only (2 lines max)
     No mate name or category subtitle
     =========================================== */
  
  .info-text {
    display: flex;
    flex-direction: column;
    justify-content: center;
    flex: 1;
    min-width: 0;
    /* Ensure text doesn't overflow into the rounded corner area */
    padding-right: 16px;
  }
  
  /* Title: 2 lines max with ellipsis */
  .title-text {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.2;
    /* Two lines with ellipsis */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }
</style>
