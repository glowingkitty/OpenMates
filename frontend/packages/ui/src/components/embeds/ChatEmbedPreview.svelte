<!--
  frontend/packages/ui/src/components/embeds/ChatEmbedPreview.svelte
  
  A compact preview card for demo/example chats, designed to be displayed
  in horizontal scrollable groups within message content.
  
  Structure:
  - Icon bar at top with category gradient and icons
  - Chat title
  - Category name
  - Click to navigate to the demo chat
  
  Size: 180x120px (compact card format for horizontal scrolling)
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import type { DemoChat } from '../../demo_chats/types';
  import { translateDemoChat } from '../../demo_chats/translateDemoChat';
  import { getCategoryGradientColors } from '../../utils/categoryUtils';
  
  /**
   * Props interface for ChatEmbedPreview
   */
  interface Props {
    /** The demo chat to display */
    demoChat: DemoChat;
    /** Click handler - called when the card is clicked */
    onClick?: (chatId: string) => void;
  }
  
  let {
    demoChat,
    onClick
  }: Props = $props();
  
  // Translate the demo chat to get localized title and description
  let translatedChat = $derived(translateDemoChat(demoChat));
  
  // Get category gradient colors (with fallback)
  let gradientColors = $derived(getCategoryGradientColors(demoChat.metadata.category) || { start: '#6366f1', end: '#4f46e5' });
  let gradientStyle = $derived(`background: linear-gradient(135deg, ${gradientColors.start} 0%, ${gradientColors.end} 100%);`);
  
  // Get translated category name
  let categoryName = $derived($text(`mates.${demoChat.metadata.category}.text`, { default: demoChat.metadata.category }));
  
  // Get the first icon name for display (or use a default)
  let iconName = $derived(demoChat.metadata.icon_names?.[0] || 'chat');
  
  // Track hover state for tilt effect
  let isHovering = $state(false);
  let mouseX = $state(0);
  let mouseY = $state(0);
  let cardElement = $state<HTMLElement | null>(null);
  
  // Tilt effect configuration (matching UnifiedEmbedPreview)
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
      onClick(demoChat.chat_id);
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
  aria-label={translatedChat.title}
>
  <!-- Icon bar with gradient background -->
  <div class="icon-bar" style={gradientStyle}>
    <div class="icon-container">
      <span class="icon" data-icon={iconName}></span>
    </div>
  </div>
  
  <!-- Content section -->
  <div class="content">
    <span class="title">{translatedChat.title}</span>
    <span class="category">{categoryName}</span>
  </div>
</button>

<style>
  .chat-embed-preview {
    width: 180px;
    min-width: 180px;
    height: 120px;
    background-color: var(--color-grey-25);
    border-radius: 20px;
    border: none;
    padding: 0;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-shadow: 
      0 6px 16px rgba(0, 0, 0, 0.12),
      0 2px 4px rgba(0, 0, 0, 0.08);
    transition: 
      transform 0.15s ease-out,
      box-shadow 0.2s ease-out;
    will-change: transform;
    user-select: none;
    -webkit-user-select: none;
    text-align: left;
    flex-shrink: 0;
  }
  
  .chat-embed-preview.hovering {
    box-shadow: 
      0 4px 10px rgba(0, 0, 0, 0.1),
      0 1px 2px rgba(0, 0, 0, 0.06);
  }
  
  .chat-embed-preview:active {
    transform: scale(0.96) !important;
    transition: transform 0.05s ease-out;
  }
  
  .chat-embed-preview:focus {
    outline: 2px solid var(--color-primary);
    outline-offset: 2px;
  }
  
  /* Icon bar section */
  .icon-bar {
    height: 44px;
    min-height: 44px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 20px 20px 0 0;
  }
  
  .icon-container {
    width: 28px;
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  /* Icon using CSS mask */
  .icon {
    width: 24px;
    height: 24px;
    background-color: white;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-size: contain;
    mask-size: contain;
  }
  
  /* Icon variants based on data-icon attribute */
  .icon[data-icon="introduction"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/introduction.svg');
    mask-image: url('@openmates/ui/static/icons/introduction.svg');
  }
  
  .icon[data-icon="trophy"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/trophy.svg');
    mask-image: url('@openmates/ui/static/icons/trophy.svg');
  }
  
  .icon[data-icon="good"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/good.svg');
    mask-image: url('@openmates/ui/static/icons/good.svg');
  }
  
  .icon[data-icon="coding"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/coding.svg');
    mask-image: url('@openmates/ui/static/icons/coding.svg');
  }
  
  .icon[data-icon="chat"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/chat.svg');
    mask-image: url('@openmates/ui/static/icons/chat.svg');
  }
  
  .icon[data-icon="team"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/team.svg');
    mask-image: url('@openmates/ui/static/icons/team.svg');
  }
  
  .icon[data-icon="book"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/book.svg');
    mask-image: url('@openmates/ui/static/icons/book.svg');
  }
  
  .icon[data-icon="search"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
  
  .icon[data-icon="web"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/web.svg');
    mask-image: url('@openmates/ui/static/icons/web.svg');
  }
  
  .icon[data-icon="insight"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/insight.svg');
    mask-image: url('@openmates/ui/static/icons/insight.svg');
  }
  
  .icon[data-icon="heart"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/heart.svg');
    mask-image: url('@openmates/ui/static/icons/heart.svg');
  }
  
  .icon[data-icon="rating"] {
    -webkit-mask-image: url('@openmates/ui/static/icons/rating.svg');
    mask-image: url('@openmates/ui/static/icons/rating.svg');
  }
  
  /* Content section */
  .content {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 10px 14px;
    gap: 4px;
    overflow: hidden;
  }
  
  .title {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  
  .category {
    font-size: 12px;
    font-weight: 500;
    color: var(--color-grey-60);
    line-height: 1.2;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
