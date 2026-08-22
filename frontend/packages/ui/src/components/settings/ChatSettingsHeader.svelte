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
    gradientStart = 'var(--color-primary-start)',
    gradientEnd = 'var(--color-primary-end)',
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
  let isCollapsed = $derived(collapseProgress > 0.5);
  let iconSize = $derived(Math.round(42 - 10 * collapseProgress));
  let detailsOpacity = $derived(Math.max(0, 1 - collapseProgress * 2));
  let resolvedIcon = $derived(resolveIconName(icon || 'chat'));
  let displayCredits = $derived(Number.isFinite(credits) ? Math.max(0, Math.round(credits)) : 0);
</script>

<div
  class="chat-settings-header"
  data-testid="chat-settings-header"
  style:--chat-settings-header-height={`${headerHeight}px`}
  style:--chat-gradient-start={gradientStart}
  style:--chat-gradient-end={gradientEnd}
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

  <div class="chat-settings-main" class:collapsed={isCollapsed}>
    <div class="chat-settings-identity" class:collapsed={isCollapsed}>
      <div
        class="chat-settings-icon"
        aria-hidden="true"
        style:--chat-settings-icon-size={`${iconSize}px`}
        style:--chat-settings-icon-mask={`var(--icon-url-${resolvedIcon})`}
      ></div>
      <h1 class="chat-settings-title" data-testid="chat-settings-title">{title}</h1>
    </div>

    <div
      class="chat-settings-credits"
      data-testid="chat-settings-credits"
      style:--chat-settings-details-opacity={detailsOpacity}
      aria-hidden={detailsOpacity < 0.05}
    >
      <span>{displayCredits}</span>
      <span class="credits-icon" aria-label="credits"></span>
    </div>
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
    height: var(--chat-settings-header-height);
    background: linear-gradient(135deg, var(--chat-gradient-start), var(--chat-gradient-end));
    border-radius: 0 0 var(--radius-6) var(--radius-6);
    color: var(--color-font-button, #fff);
    box-shadow: var(--shadow-lg);
    transition: height var(--duration-fast) var(--easing-default);
    user-select: none;
    pointer-events: none;
  }

  .chat-settings-header,
  .chat-settings-nav,
  .chat-settings-nav span,
  .chat-settings-title,
  .chat-settings-credits,
  .chat-settings-credits span {
    color: var(--color-font-button, #fff) !important;
    -webkit-text-fill-color: var(--color-font-button, #fff) !important;
  }

  .chat-settings-nav {
    all: unset;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    min-height: 3rem;
    gap: var(--spacing-3);
    padding: 0 var(--spacing-5);
    color: var(--color-font-button, #fff);
    font: var(--font-label-md);
    cursor: pointer;
    pointer-events: auto;
  }

  .chat-settings-nav:hover {
    background: color-mix(in srgb, var(--color-font-button, #fff) 8%, transparent);
  }

  .chat-settings-main {
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 0 var(--spacing-5) var(--spacing-5);
    box-sizing: border-box;
    transition: padding var(--duration-fast) var(--easing-default);
  }

  .chat-settings-main.collapsed {
    padding: 0 var(--spacing-5);
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
    width: 100%;
    min-width: 0;
    text-align: center;
    transition: all var(--duration-fast) var(--easing-default);
  }

  .chat-settings-identity.collapsed {
    flex-direction: row;
    justify-content: center;
    text-align: center;
    gap: var(--spacing-2);
  }

  .chat-settings-icon {
    display: none;
    flex: 0 0 auto;
    width: var(--chat-settings-icon-size);
    height: var(--chat-settings-icon-size);
    background: var(--color-font-button, #fff);
    -webkit-mask-image: var(--chat-settings-icon-mask);
    mask-image: var(--chat-settings-icon-mask);
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-size: contain;
    mask-size: contain;
  }

  .chat-settings-header .chat-settings-title {
    max-width: min(100%, 34rem);
    margin: 0;
    font-size: var(--font-size-h3);
    line-height: 1.3;
    font-weight: 700;
    color: var(--color-font-button, #fff) !important;
    -webkit-text-fill-color: var(--color-font-button, #fff) !important;
  }

  .chat-settings-identity.collapsed .chat-settings-title {
    min-width: 0;
    max-width: min(100%, 20rem);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    line-height: 1.2;
  }

  .chat-settings-credits {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-2);
    margin-top: var(--spacing-4);
    font: var(--font-heading-sm);
    font-weight: var(--font-weight-bold);
    opacity: var(--chat-settings-details-opacity);
    color: var(--color-font-button, #fff) !important;
    -webkit-text-fill-color: var(--color-font-button, #fff) !important;
    transition: opacity var(--duration-fast) var(--easing-default);
  }

  .chat-settings-main.collapsed .chat-settings-credits {
    display: none;
  }

  .credits-icon {
    width: 1.375rem;
    height: 1.375rem;
    background: var(--color-font-button, #fff);
    -webkit-mask: url('@openmates/ui/static/icons/coins.svg') center / contain no-repeat;
    mask: url('@openmates/ui/static/icons/coins.svg') center / contain no-repeat;
  }
</style>
