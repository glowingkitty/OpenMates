<!--
  ChatHeader.svelte

  Displays a permanent, display-only header card at the top of the active chat history.
  Shown only for new chats (where we generated a title/category/icon on first message).
  Mirrors the visual design of Chat.svelte's sidebar item (category gradient circle + title),
  but scaled up for use inside the chat area.

  States:
    - isLoading=true  → shows "Generating title..." placeholder with AI icon shimmer
    - isLoading=false → shows full card with gradient circle + icon + title

  Props:
    title       - decrypted/plaintext chat title (empty while generating)
    category    - category string (e.g. "technology", "science") — null while generating
    icon        - icon name string (e.g. "cpu") — null while generating
    isLoading   - true while title/category/icon are not yet received from the server
-->
<script lang="ts">
  import { fade } from 'svelte/transition';
  import { getCategoryGradientColors, getValidIconName, getLucideIcon } from '../utils/categoryUtils';
  import { text } from '@repo/ui';

  // Props
  let {
    title = '',
    category = null,
    icon = null,
    isLoading = false,
  }: {
    title?: string;
    category?: string | null;
    icon?: string | null;
    isLoading?: boolean;
  } = $props();

  // Gradient colours derived from category
  let gradientColors = $derived(category ? getCategoryGradientColors(category) : null);

  // Icon component resolved from the icon name + category fallback
  let IconComponent = $derived.by(() => {
    if (!category) return null;
    const iconName = getValidIconName(icon || '', category);
    return getLucideIcon(iconName);
  });
</script>

{#if isLoading}
  <!-- Placeholder shown while the server is generating title/category/icon.
       Uses the same AI icon shimmer as the old centered overlay but placed inline
       at the very top of the chat, above the first user message. -->
  <div class="chat-header-placeholder" in:fade={{ duration: 200 }} out:fade={{ duration: 150 }}>
    <div class="placeholder-ai-icon"></div>
    <span class="placeholder-text">{$text('enter_message.status.generating_title')}</span>
  </div>
{:else if title && category}
  <!-- Full header card: category gradient circle + icon + title.
       Matches Chat.svelte sidebar item design but scaled up. -->
  <div class="chat-header-card" in:fade={{ duration: 300 }}>
    <!-- Category circle (gradient background + lucide icon) -->
    <div class="chat-header-circle-wrapper">
      <div
        class="chat-header-circle"
        style={gradientColors
          ? `background: linear-gradient(135deg, ${gradientColors.start}, ${gradientColors.end})`
          : 'background: #cccccc'}
      >
        {#if IconComponent}
          <div class="chat-header-circle-icon">
            <IconComponent size={22} color="white" />
          </div>
        {/if}
      </div>
    </div>

    <!-- Title text -->
    <div class="chat-header-title-wrapper">
      <!-- eslint-disable-next-line svelte/no-at-html-tags -->
      <span class="chat-header-title">{@html title}</span>
    </div>
  </div>
{/if}

<style>
  /* ─── Loading placeholder ─────────────────────────────────────────────── */

  .chat-header-placeholder {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px 16px;
    margin-bottom: 8px;
    /* Subtle card-like appearance matching the full card below */
    border-radius: 14px;
    background: var(--color-grey-10, rgba(255, 255, 255, 0.04));
    border: 1px solid var(--color-grey-20, rgba(255, 255, 255, 0.08));
  }

  /* AI icon with shimmer — mirrors the icon used in the old centered overlay */
  .placeholder-ai-icon {
    width: 38px;
    height: 38px;
    flex-shrink: 0;
    -webkit-mask-image: url('@openmates/ui/static/icons/ai.svg');
    mask-image: url('@openmates/ui/static/icons/ai.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
    background: linear-gradient(
      90deg,
      var(--color-grey-30, #ccc) 0%,
      var(--color-grey-30, #ccc) 40%,
      var(--color-grey-10, #f0f0f0) 50%,
      var(--color-grey-30, #ccc) 60%,
      var(--color-grey-30, #ccc) 100%
    );
    background-size: 200% 100%;
    animation: chat-header-shimmer 1.5s infinite linear;
  }

  .placeholder-text {
    font-size: 15px;
    font-style: italic;
    background: linear-gradient(
      90deg,
      var(--color-grey-60) 0%,
      var(--color-grey-60) 40%,
      var(--color-grey-40) 50%,
      var(--color-grey-60) 60%,
      var(--color-grey-60) 100%
    );
    background-size: 200% 100%;
    background-clip: text;
    -webkit-background-clip: text;
    color: transparent;
    animation: chat-header-shimmer 1.5s infinite linear;
  }

  @keyframes chat-header-shimmer {
    0%   { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }

  /* ─── Full chat header card ───────────────────────────────────────────── */

  .chat-header-card {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 14px 16px;
    margin-bottom: 8px;
    border-radius: 14px;
    background: var(--color-grey-10, rgba(255, 255, 255, 0.04));
    border: 1px solid var(--color-grey-20, rgba(255, 255, 255, 0.08));
    /* No interactivity — purely decorative */
    pointer-events: none;
    user-select: none;
  }

  /* Category circle: scaled-up version of Chat.svelte .category-circle (28px → 44px) */
  .chat-header-circle-wrapper {
    flex-shrink: 0;
    position: relative;
    width: 44px;
    height: 44px;
  }

  .chat-header-circle {
    width: 44px;
    height: 44px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0px 3px 8px rgba(0, 0, 0, 0.15);
    border: 2px solid var(--color-background, #fff);
  }

  .chat-header-circle-icon {
    width: 22px;
    height: 22px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  /* Title: larger than sidebar (16px → 20px) with medium weight */
  .chat-header-title-wrapper {
    flex: 1;
    min-width: 0;
    overflow: hidden;
  }

  .chat-header-title {
    display: block;
    font-size: 20px;
    font-weight: 600;
    color: var(--color-text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.3;
  }
</style>
