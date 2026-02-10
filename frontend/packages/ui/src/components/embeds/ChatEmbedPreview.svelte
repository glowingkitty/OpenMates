<!--
  frontend/packages/ui/src/components/embeds/ChatEmbedPreview.svelte
  
  A preview card for example/demo chats, using UnifiedEmbedPreview + BasicInfosBar
  for consistent styling, hover effects, and layout with all other embed previews.
  
  Structure:
  - Details section (top): chat summary (AI-generated description of the chat topic)
  - BasicInfosBar (bottom, via UnifiedEmbedPreview):
    - App icon circle (61x61px) with primary blue gradient (appId="chat")
    - Small category circle (24px) with gradient + icon (via titleIcon snippet)
    - Title text (chat title, up to 2 lines)
  
  Uses appId="chat" which maps to --color-app-chat (primary blue gradient)
  and icon_rounded.chat (chat.svg icon) for the BasicInfosBar circle.
  
  The small category circle next to the title shows the chat's category
  (similar to how Chat.svelte renders the category circle in the sidebar).
  
  Click navigates to the demo chat via the onFullscreen handler pattern
  used by UnifiedEmbedPreview.
-->

<script lang="ts">
  import UnifiedEmbedPreview from './UnifiedEmbedPreview.svelte';
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
    /** Cleartext text shown in the center content area (chat summary or fallback) */
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
  
  // Get category gradient colors for the small category circle in the BasicInfosBar
  let categoryGradientColors = $derived(getCategoryGradientColors(category));
  
  // Get Lucide icon component for the small category circle
  // Uses the provided iconName, falls back to category default
  let resolvedIconName = $derived(
    iconName
      ? getValidIconName([iconName], category)
      : getFallbackIconForCategory(category)
  );
  let CategoryIconComponent = $derived(getLucideIcon(resolvedIconName));
  
  /**
   * Handle click via UnifiedEmbedPreview's onFullscreen callback.
   * This triggers navigation to the demo chat.
   */
  function handleFullscreen() {
    if (onClick) {
      onClick(chatId);
    }
  }
</script>

<UnifiedEmbedPreview
  id={chatId}
  appId="chat"
  skillId="chat"
  skillIconName="chat"
  status="finished"
  skillName={title}
  showSkillIcon={false}
  showStatus={false}
  onFullscreen={handleFullscreen}
>
  {#snippet titleIcon()}
    <!-- Small category circle (24x24px) shown next to the title in BasicInfosBar.
         Uses the category-specific gradient with the Lucide category icon,
         matching the pattern from Chat.svelte sidebar. -->
    {#if categoryGradientColors}
      <div
        class="small-category-circle"
        style="background: linear-gradient(135deg, {categoryGradientColors.start}, {categoryGradientColors.end})"
      >
        <CategoryIconComponent size={12} color="white" />
      </div>
    {/if}
  {/snippet}
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="chat-details" class:mobile={isMobileLayout}>
      {#if previewText}
        <span class="preview-text">{previewText}</span>
      {:else}
        <span class="preview-text placeholder">{title}</span>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Chat Details Content (inside UnifiedEmbedPreview)
     =========================================== */
  
  .chat-details {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    padding: 16px 0 8px 0;
  }
  
  .chat-details.mobile {
    padding: 8px 0;
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
  
  .chat-details.mobile .preview-text {
    font-size: 12px;
    -webkit-line-clamp: 6;
    line-clamp: 6;
  }
  
  /* ===========================================
     Small Category Circle (in BasicInfosBar title area)
     Matches Chat.svelte sidebar category circle but smaller (24px)
     =========================================== */
  
  .small-category-circle {
    width: 24px;
    height: 24px;
    min-width: 24px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  
  /* Ensure Lucide SVG in small circle renders correctly */
  .small-category-circle :global(svg) {
    display: block;
  }
</style>
