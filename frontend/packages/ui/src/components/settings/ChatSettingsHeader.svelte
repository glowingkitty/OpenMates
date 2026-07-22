<!--
  ChatSettingsHeader.svelte

  Gradient Settings-shell banner for a single chat. It mirrors the app detail
  header navigation contract while rendering chat-specific identity: breadcrumb,
  icon, title, and total known credits.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import { resolveIconName } from '../../utils/iconNameResolver';

  const COLLAPSE_THRESHOLD = 80;
  const COLLAPSED_HEIGHT = 88;
  const EXPANDED_HEIGHT_DESKTOP = 250;
  const EXPANDED_HEIGHT_MOBILE = 220;

  let {
    title,
    icon = 'chat',
    credits = 0,
    gradientStart = '#063f4d',
    gradientEnd = '#0d6b7c',
    breadcrumbLabel = '',
    fullBreadcrumbLabel = '',
    scrollTop = 0,
    onBack,
  }: {
    title: string;
    icon?: string;
    credits?: number;
    gradientStart?: string;
    gradientEnd?: string;
    breadcrumbLabel?: string;
    fullBreadcrumbLabel?: string;
    scrollTop?: number;
    onBack: () => void;
  } = $props();

  let collapseProgress = $derived.by(() => {
    const raw = Math.min(1, Math.max(0, scrollTop / COLLAPSE_THRESHOLD));
    return raw < 0.5 ? 4 * raw * raw * raw : 1 - Math.pow(-2 * raw + 2, 3) / 2;
  });

  let expandedHeight = $derived.by(() => {
    if (typeof window === 'undefined') return EXPANDED_HEIGHT_DESKTOP;
    return window.innerWidth <= 730 ? EXPANDED_HEIGHT_MOBILE : EXPANDED_HEIGHT_DESKTOP;
  });

  let headerHeight = $derived(
    Math.round(expandedHeight - (expandedHeight - COLLAPSED_HEIGHT) * collapseProgress)
  );
  let iconSize = $derived(Math.round(42 - 10 * collapseProgress));
  let titleSize = $derived(Math.round(26 - 8 * collapseProgress));
  let detailsOpacity = $derived(Math.max(0, 1 - collapseProgress * 2));
  let resolvedIcon = $derived(resolveIconName(icon || 'chat'));
  let displayCredits = $derived(Number.isFinite(credits) ? Math.max(0, Math.round(credits)) : 0);
</script>

<div
  class="chat-settings-header"
  data-testid="chat-settings-header"
  style="height: {headerHeight}px; --chat-gradient-start: {gradientStart}; --chat-gradient-end: {gradientEnd};"
>
  <button
    class="chat-settings-nav"
    data-testid="banner-back-button"
    type="button"
    onclick={onBack}
    aria-label={$text('common.back')}
    title={fullBreadcrumbLabel || breadcrumbLabel}
  >
    <div class="nav-back-icon clickable-icon icon_back"></div>
    <span>{breadcrumbLabel}</span>
  </button>

  <div class="chat-settings-identity" class:collapsed={collapseProgress > 0.5}>
    <div
      class="chat-settings-icon"
      aria-hidden="true"
      style="width: {iconSize}px; height: {iconSize}px; -webkit-mask-image: var(--icon-url-{resolvedIcon}); mask-image: var(--icon-url-{resolvedIcon});"
    ></div>
    <h1 data-testid="chat-settings-title" style="font-size: {titleSize}px;">{title}</h1>
  </div>

  <div
    class="chat-settings-credits"
    data-testid="chat-settings-credits"
    style="opacity: {detailsOpacity};"
    aria-hidden={detailsOpacity < 0.05}
  >
    <span>{displayCredits}</span>
    <span class="credits-icon" aria-label="credits"></span>
  </div>
</div>

<style>
  .chat-settings-header {
    position: relative;
    flex-shrink: 0;
    width: 100%;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    background: linear-gradient(135deg, var(--chat-gradient-start), var(--chat-gradient-end));
    border-radius: 0 0 var(--radius-xl) var(--radius-xl);
    color: var(--color-white);
    box-shadow: var(--shadow-md);
    transition: height var(--duration-fast) var(--easing-default);
    user-select: none;
  }

  .chat-settings-nav {
    all: unset;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    min-height: 3rem;
    gap: var(--spacing-3);
    padding: 0 var(--spacing-5);
    color: rgba(255, 255, 255, 0.78);
    font: var(--font-label-md);
    cursor: pointer;
  }

  .chat-settings-nav:hover {
    background: rgba(255, 255, 255, 0.08);
  }

  .nav-back-icon {
    flex: 0 0 auto;
    background: currentColor;
  }

  .chat-settings-identity {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-3);
    padding: var(--spacing-2) var(--spacing-6) 0;
    text-align: center;
    transition: all var(--duration-fast) var(--easing-default);
  }

  .chat-settings-identity.collapsed {
    flex-direction: row;
    justify-content: flex-start;
    text-align: left;
    padding: 0 var(--spacing-5);
  }

  .chat-settings-icon {
    flex: 0 0 auto;
    background: var(--color-white);
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-size: contain;
    mask-size: contain;
  }

  h1 {
    max-width: 22rem;
    margin: 0;
    line-height: 1.18;
    font-weight: var(--font-weight-bold);
    color: var(--color-white);
  }

  .chat-settings-credits {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-2);
    margin-top: var(--spacing-4);
    font: var(--font-heading-sm);
    font-weight: var(--font-weight-bold);
    transition: opacity var(--duration-fast) var(--easing-default);
  }

  .credits-icon {
    width: 1.375rem;
    height: 1.375rem;
    background: var(--color-white);
    -webkit-mask: var(--icon-url-credits) center / contain no-repeat;
    mask: var(--icon-url-credits) center / contain no-repeat;
  }
</style>
