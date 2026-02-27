<!--
  AppDetailsHeader.svelte

  Expanding/collapsing gradient banner for the App Details settings page.
  Replaces the normal settings-header when viewing app_store/{appId}.

  EXPANDED (scrollTop ≤ 0):
  ┌──────────────────────────────────────────────┐  ~200px
  │  [←] Settings / App Store          [✕]      │  ← breadcrumb row (white, 0.7 op)
  │                                              │
  │  [icon 45×45]   App Name (20px bold)         │
  │                                              │
  │         Description (14px, centered)         │
  │                                              │
  │      3 🖥     1 🎯     1 🧠                  │  ← capability counts
  └──────────────────────────────────────────────┘

  COLLAPSED (scrollTop ≥ COLLAPSE_THRESHOLD):
  ┌──────────────────────────────────────────────┐  ~52px (= normal header height)
  │  [←] Settings / App Store          [✕]      │
  └──────────────────────────────────────────────┘

  Props:
    appId             - the app ID (e.g. "audio")
    app               - AppMetadata for the app
    breadcrumbLabel   - current breadcrumb text
    fullBreadcrumbLabel - tooltip text (full path)
    scrollTop         - current scrollTop of .settings-content-wrapper
    onBack            - navigate back
    onClose           - close settings
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import Icon from '../Icon.svelte';
  import type { AppMetadata } from '../../types/apps';

  // ─── Props ────────────────────────────────────────────────────────────────

  interface Props {
    appId: string;
    app: AppMetadata | undefined;
    breadcrumbLabel?: string;
    fullBreadcrumbLabel?: string;
    scrollTop?: number;
    onBack?: () => void;
    onClose?: () => void;
  }

  let {
    appId,
    app,
    breadcrumbLabel = '',
    fullBreadcrumbLabel = '',
    scrollTop = 0,
    onBack,
    onClose,
  }: Props = $props();

  // ─── Collapse animation ───────────────────────────────────────────────────

  /** How many px to scroll before fully collapsed */
  const COLLAPSE_THRESHOLD = 90;

  /**
   * Ease-in-out cubic: smooth collapse progress [0 = expanded, 1 = collapsed]
   */
  let collapseProgress = $derived.by(() => {
    const raw = Math.min(1, Math.max(0, scrollTop / COLLAPSE_THRESHOLD));
    return raw < 0.5 ? 4 * raw * raw * raw : 1 - Math.pow(-2 * raw + 2, 3) / 2;
  });

  /** Total header height: 200px → 52px */
  let headerHeight = $derived(Math.round(200 - 148 * collapseProgress));

  /**
   * Opacity for description + counts: fades out in the first 55% of collapse
   * so they're gone well before the header reaches compact height.
   */
  let detailsOpacity = $derived(Math.max(0, 1 - collapseProgress / 0.55));

  /**
   * Bottom border-radius: 14px → 0 as we collapse
   * (so the rounded edges only appear in the expanded state)
   */
  let bottomRadius = $derived(Math.round(14 * (1 - collapseProgress)));

  // ─── App data ─────────────────────────────────────────────────────────────

  let appName = $derived(
    app?.name_translation_key ? $text(app.name_translation_key) : (app?.name || appId)
  );

  let appDescription = $derived(
    app?.description_translation_key
      ? $text(app.description_translation_key)
      : (app?.description || '')
  );

  /** Icon name normalised to match CSS variable and icon file conventions */
  let iconName = $derived.by(() => {
    if (!app?.icon_image) return appId;
    let n = app.icon_image.replace(/\.svg$/, '');
    if (n === 'coding') n = 'code';
    if (n === 'heart') n = 'health';
    if (n === 'email') n = 'mail';
    return n;
  });

  let skillCount = $derived(app?.skills?.length ?? 0);
  let focusCount = $derived(app?.focus_modes?.length ?? 0);
  let memoryCount = $derived(app?.settings_and_memories?.length ?? 0);
</script>

<div
  class="app-details-header"
  style="
    height: {headerHeight}px;
    background: var(--color-app-{iconName}, var(--color-primary));
    border-radius: 0 0 {bottomRadius}px {bottomRadius}px;
  "
>
  <!-- ── Nav row: back arrow + breadcrumb + close ── always visible ── -->
  <div class="nav-row">
    {#if onBack}
      <button
        class="nav-btn"
        onclick={onBack}
        aria-label={$text('settings.back')}
        type="button"
      >
        <span class="icon_back nav-icon"></span>
      </button>
    {/if}

    <span
      class="breadcrumb-label"
      title={fullBreadcrumbLabel || breadcrumbLabel}
    >{breadcrumbLabel}</span>

    {#if onClose}
      <button
        class="nav-btn close"
        onclick={onClose}
        aria-label={$text('activity.close')}
        type="button"
      >
        <span class="icon_close nav-icon"></span>
      </button>
    {/if}
  </div>

  <!-- ── App identity row: icon (45×45) left + name right ── -->
  <div class="identity-row">
    {#if app?.icon_image}
      <div class="app-icon-slot">
        <Icon
          name={iconName}
          type="app"
          size="45px"
          borderColor="#ffffff"
        />
      </div>
    {/if}
    <span class="app-name">{appName}</span>
  </div>

  <!-- ── Description + capability counts — fades out on scroll ── -->
  <div
    class="details-block"
    style="opacity: {detailsOpacity};"
    aria-hidden={detailsOpacity < 0.05}
  >
    {#if appDescription}
      <p class="app-description">{appDescription}</p>
    {/if}

    {#if skillCount > 0 || focusCount > 0 || memoryCount > 0}
      <div class="capability-row">
        {#if skillCount > 0}
          <div class="cap-item">
            <span class="cap-num">{skillCount}</span>
            <span class="cap-icon skill-icon"></span>
          </div>
        {/if}
        {#if focusCount > 0}
          <div class="cap-item">
            <span class="cap-num">{focusCount}</span>
            <span class="cap-icon focus-icon"></span>
          </div>
        {/if}
        {#if memoryCount > 0}
          <div class="cap-item">
            <span class="cap-num">{memoryCount}</span>
            <span class="cap-icon memories-icon"></span>
          </div>
        {/if}
      </div>
    {/if}
  </div>
</div>

<style>
  /* ─── Container ─────────────────────────────────────────────────────────── */

  .app-details-header {
    position: sticky;
    top: 0;
    z-index: 10;
    width: 100%;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    /* Height + border-radius driven by inline style — transition for smoothness */
    transition:
      height 0.2s cubic-bezier(0.4, 0, 0.2, 1),
      border-radius 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
    flex-shrink: 0;
    user-select: none;
  }

  /* ─── Nav row ────────────────────────────────────────────────────────────── */

  .nav-row {
    display: flex;
    align-items: center;
    height: 44px;
    padding: 0 10px;
    flex-shrink: 0;
    gap: 4px;
    position: relative;
    z-index: 2;
  }

  .nav-btn {
    all: unset;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 8px;
    cursor: pointer;
    flex-shrink: 0;
    transition: background-color 0.15s ease;
  }

  .nav-btn:hover {
    background-color: rgba(255, 255, 255, 0.18) !important;
  }

  .nav-btn:active {
    background-color: rgba(255, 255, 255, 0.28) !important;
  }

  .nav-btn.close {
    margin-left: auto;
  }

  /* Nav icons: reuse the same icon_back / icon_close mask approach */
  .nav-icon {
    display: block;
    width: 20px;
    height: 20px;
    /* The .icon_back / .icon_close classes in icons.css set -webkit-mask-image.
       We override background-color here to make them white. */
    background-color: rgba(255, 255, 255, 0.85) !important;
    flex-shrink: 0;
  }

  .breadcrumb-label {
    font-size: 14px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.7);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    flex: 1;
    min-width: 0;
  }

  /* ─── App identity row ───────────────────────────────────────────────────── */

  .identity-row {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 0 16px 4px;
    flex-shrink: 0;
    position: relative;
    z-index: 2;
  }

  .app-icon-slot {
    flex-shrink: 0;
    /* Ensure the Icon renders at exactly 45×45 */
    width: 45px;
    height: 45px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .app-name {
    font-size: 20px;
    font-weight: 700;
    color: #ffffff;
    line-height: 1.25;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
  }

  /* ─── Collapsible details block ──────────────────────────────────────────── */

  .details-block {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 4px 20px 14px;
    gap: 10px;
    position: relative;
    z-index: 2;
    /* Opacity driven by inline style; also transition for smoothness */
    transition: opacity 0.12s ease;
    pointer-events: auto;
  }

  .app-description {
    margin: 0;
    font-size: 14px;
    font-weight: 600;
    color: #ffffff;
    text-align: center;
    line-height: 1.45;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  /* ─── Capability counts ──────────────────────────────────────────────────── */

  .capability-row {
    display: flex;
    align-items: center;
    gap: 22px;
    justify-content: center;
  }

  .cap-item {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .cap-num {
    font-size: 15px;
    font-weight: 700;
    color: #ffffff;
    line-height: 1;
  }

  /* Capability icons — mask-based so we can colour them white */
  .cap-icon {
    display: block;
    width: 22px;
    height: 22px;
    background-color: rgba(255, 255, 255, 0.9);
    flex-shrink: 0;
  }

  /* Each icon type uses its own mask image from icons.css variables */
  .skill-icon {
    -webkit-mask-image: url('@openmates/ui/static/icons/skill.svg');
    mask-image: url('@openmates/ui/static/icons/skill.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
  }

  /* Focus modes use the insight icon (same as .icon.focus in icons.css) */
  .focus-icon {
    -webkit-mask-image: url('@openmates/ui/static/icons/insight.svg');
    mask-image: url('@openmates/ui/static/icons/insight.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
  }

  /* Settings & memories use the settings icon */
  .memories-icon {
    -webkit-mask-image: url('@openmates/ui/static/icons/settings.svg');
    mask-image: url('@openmates/ui/static/icons/settings.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
  }
</style>
