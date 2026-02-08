<!--
  frontend/packages/ui/src/components/embeds/ChatEmbedPreview.svelte
  
  A preview card for example/demo chats, styled to match the UnifiedEmbedPreview
  layout used by other embeds (300x200px desktop).
  
  Structure (matching UnifiedEmbedPreview + BasicInfosBar pattern):
  - Center content area: chat summary text
  - Bottom bar (61px): OpenMates gradient circle with chat icon →
    small category-specific Lucide icon → title (2 lines) + category name
  
  All chat embed previews use the same OpenMates AI gradient (--color-app-ai)
  for the large circle, regardless of category. The category is shown as
  text next to the title.
  
  Click to navigate to the demo chat.
-->

<script lang="ts">
  import { text } from '@repo/ui';
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
    /** Cleartext chat summary (shown in center content area) */
    summary: string;
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
    summary,
    category,
    iconName,
    onClick
  }: Props = $props();
  
  // Get translated category name for the bottom bar subtitle
  let categoryName = $derived(
    $text(`mates.${category}.text`, { default: category.replace(/_/g, ' ') })
  );
  
  // Get Lucide icon component for the small skill-like icon in the bottom bar
  let validIconName = $derived(getValidIconName(iconName ? [iconName] : [], category));
  let IconComponent = $derived(getLucideIcon(validIconName));
  
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
  <!-- Details section: chat summary centered in the content area -->
  <div class="details-section">
    {#if summary}
      <span class="summary-text">{summary}</span>
    {:else}
      <span class="summary-text placeholder">{title}</span>
    {/if}
  </div>
  
  <!-- Bottom bar: matches BasicInfosBar desktop layout (61px, grey-30 bg, 30px radius) -->
  <div class="bottom-bar">
    <!-- OpenMates gradient circle (61x61px) with chat icon inside -->
    <!-- All chat embeds use the same --color-app-ai gradient -->
    <div class="gradient-circle">
      <div class="chat-icon-container">
        <svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        </svg>
      </div>
    </div>
    
    <!-- Small category-specific Lucide icon (like the skill icon in BasicInfosBar) -->
    <div class="category-icon-container">
      <IconComponent size={22} color="var(--color-grey-70)" />
    </div>
    
    <!-- Title (2 lines) + category name -->
    <div class="info-text">
      <span class="title-text">{title}</span>
      <span class="category-text">{categoryName}</span>
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
     Details Section - Chat Summary
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
  
  .summary-text {
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
  
  /* When showing title as placeholder (no summary available), style slightly different */
  .summary-text.placeholder {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-70);
  }
  
  /* ===========================================
     Bottom Bar - Matches BasicInfosBar Desktop
     =========================================== */
  
  .bottom-bar {
    display: flex;
    align-items: center;
    gap: 10px;
    /* Match BasicInfosBar desktop dimensions */
    height: 61px;
    min-height: 61px;
    background-color: var(--color-grey-30);
    border-radius: 30px;
    padding: 0;
    flex-shrink: 0;
  }
  
  /* Gradient circle: 61x61px with OpenMates AI gradient (same for all chat embeds) */
  .gradient-circle {
    width: 61px;
    height: 61px;
    min-width: 61px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    /* Use the standard OpenMates AI gradient for all chat embeds */
    background: var(--color-app-ai);
  }
  
  .chat-icon-container {
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  /* Small category icon (matches BasicInfosBar skill-icon sizing) */
  .category-icon-container {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  
  /* Ensure Lucide SVG renders correctly */
  .category-icon-container :global(svg) {
    display: block;
  }
  
  /* ===========================================
     Info Text - Title (2 lines) + Category Name
     =========================================== */
  
  .info-text {
    display: flex;
    flex-direction: column;
    justify-content: center;
    flex: 1;
    min-width: 0;
    gap: 2px;
    /* Ensure text doesn't overflow into the rounded corner area */
    padding-right: 16px;
  }
  
  /* Title: 2 lines with ellipsis (replaces mate name from original design) */
  .title-text {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.2;
    /* Two lines with ellipsis (matching BasicInfosBar title-text.two-lines) */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }
  
  /* Category name: single line under the title */
  .category-text {
    font-size: 14px;
    font-weight: 500;
    color: var(--color-grey-70);
    line-height: 1.2;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
