<!--
  frontend/packages/ui/src/components/embeds/AiGeneratedBadge.svelte

  Media-agnostic "AI generated" overlay for generated images and videos.

  A round grey badge with the AI icon, pinned to a corner of its
  `position: relative` parent. Expands on hover, focus or click to show the
  label and an optional detail line (for example the model name). It is a UI
  overlay only and is never drawn into the media itself.
-->

<script lang="ts">
  import { text } from '@repo/ui';

  interface Props {
    variant?: 'preview' | 'fullscreen';
    detail?: string;
    corner?: 'top-right' | 'top-left' | 'bottom-right' | 'bottom-left';
  }

  let { variant = 'preview', detail, corner = 'top-right' }: Props = $props();
  // Hover opens it for pointer users, a click or key press pins it open (touch
  // has no hover), so a click while hovering never closes it under the pointer.
  let isHovered = $state(false);
  let isPinned = $state(false);
  let isExpanded = $derived(isHovered || isPinned);

  let label = $derived($text('app_skills.images.view.ai_generated'));
  let accessibleName = $derived(detail ? `${label}, ${detail}` : label);

  function toggleExpanded(event?: MouseEvent | KeyboardEvent) {
    event?.stopPropagation();
    isPinned = !isPinned;
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    toggleExpanded(event);
  }
</script>

<div
  class="ai-generated-badge {variant} {corner}"
  class:expanded={isExpanded}
  data-testid="ai-generated-badge"
  aria-label={accessibleName}
  title={accessibleName}
  role="button"
  aria-expanded={isExpanded}
  tabindex="0"
  onclick={toggleExpanded}
  onkeydown={handleKeydown}
  onmouseenter={() => (isHovered = true)}
  onmouseleave={() => (isHovered = false)}
>
  <span class="ai-generated-badge-icon" aria-hidden="true"></span>
  <span class="ai-generated-badge-details">
    <span class="ai-generated-badge-label">{label}</span>
    {#if detail}
      <span class="ai-generated-badge-detail">{detail}</span>
    {/if}
  </span>
</div>

<style>
  .ai-generated-badge {
    --badge-offset: 8px;
    position: absolute;
    z-index: 2;
    display: flex;
    align-items: center;
    justify-content: flex-start;
    width: 28px;
    height: 28px;
    max-width: 28px;
    min-height: 28px;
    padding: 0;
    border-radius: var(--radius-full);
    border: 1px solid rgba(255, 255, 255, 0.58);
    background: var(--color-grey-70);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.24);
    box-sizing: border-box;
    overflow: hidden;
    cursor: pointer;
    pointer-events: auto;
    transition:
      max-width var(--duration-fast) var(--easing-default),
      width var(--duration-fast) var(--easing-default),
      padding var(--duration-fast) var(--easing-default);
  }

  .ai-generated-badge.fullscreen {
    --badge-offset: 12px;
    width: 32px;
    height: 32px;
    max-width: 32px;
    min-height: 32px;
  }

  .ai-generated-badge.top-right,
  .ai-generated-badge.top-left {
    top: var(--badge-offset);
  }

  .ai-generated-badge.bottom-right,
  .ai-generated-badge.bottom-left {
    bottom: var(--badge-offset);
  }

  .ai-generated-badge.top-right,
  .ai-generated-badge.bottom-right {
    right: var(--badge-offset);
  }

  .ai-generated-badge.top-left,
  .ai-generated-badge.bottom-left {
    left: var(--badge-offset);
  }

  .ai-generated-badge:hover,
  .ai-generated-badge:focus-visible,
  .ai-generated-badge:focus-within,
  .ai-generated-badge.expanded {
    width: auto;
    height: auto;
    max-width: min(340px, calc(100% - 16px));
    padding: var(--spacing-2) var(--spacing-4) var(--spacing-2) var(--spacing-3);
    gap: var(--spacing-2);
    align-items: flex-start;
  }

  .ai-generated-badge.fullscreen:hover,
  .ai-generated-badge.fullscreen:focus-visible,
  .ai-generated-badge.fullscreen:focus-within,
  .ai-generated-badge.fullscreen.expanded {
    max-width: min(380px, calc(100% - 24px));
    padding: var(--spacing-3) var(--spacing-5) var(--spacing-3) var(--spacing-4);
  }

  .ai-generated-badge:focus-visible {
    outline: 2px solid var(--color-grey-0);
    outline-offset: 2px;
  }

  .ai-generated-badge-icon {
    display: block;
    flex: 0 0 auto;
    width: 14px;
    height: 14px;
    margin: auto;
    background: var(--color-grey-0);
    -webkit-mask-image: url('@openmates/ui/static/icons/ai.svg');
    mask-image: url('@openmates/ui/static/icons/ai.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
  }

  .ai-generated-badge.fullscreen .ai-generated-badge-icon {
    width: 15px;
    height: 15px;
  }

  .ai-generated-badge:hover .ai-generated-badge-icon,
  .ai-generated-badge:focus-visible .ai-generated-badge-icon,
  .ai-generated-badge:focus-within .ai-generated-badge-icon,
  .ai-generated-badge.expanded .ai-generated-badge-icon {
    margin: 1px 0 0 0;
  }

  .ai-generated-badge-details {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--spacing-1);
    max-width: 0;
    opacity: 0;
    overflow: hidden;
    white-space: nowrap;
    color: var(--color-grey-0);
    font-size: var(--font-size-tiny);
    font-weight: 600;
    line-height: 1.25;
    transition:
      max-width var(--duration-fast) var(--easing-default),
      opacity var(--duration-fast) var(--easing-default);
  }

  .ai-generated-badge:hover .ai-generated-badge-details,
  .ai-generated-badge:focus-visible .ai-generated-badge-details,
  .ai-generated-badge:focus-within .ai-generated-badge-details,
  .ai-generated-badge.expanded .ai-generated-badge-details {
    max-width: 290px;
    opacity: 1;
  }

  .ai-generated-badge-detail {
    font-size: var(--font-size-tiny);
    font-weight: 500;
    opacity: 0.9;
  }
</style>
