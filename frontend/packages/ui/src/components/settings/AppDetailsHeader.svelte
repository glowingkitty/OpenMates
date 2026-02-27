<!--
  AppDetailsHeader.svelte

  Collapsing gradient banner used for two contexts:

  1. TOP-LEVEL app page (app_store/{appId}) — no subItem prop:
  EXPANDED (scrollTop ≤ 0):
  ┌──────────────────────────────────────────────┐  240px
  │  [←] Settings / App Store  (clickable)       │  ← nav row (white, 0.7 op)
  │  [icon 45×45]        App Name (20px, centered)│
  │         Description (14px, centered)         │
  │      3 🖥     1 🎯     1 🧠                  │  ← capability counts
  └──────────────────────────────────────────────┘

  2. SUB-ITEM page (skill / focus / memories) — subItem prop provided:
  EXPANDED (scrollTop ≤ 0):
  ┌──────────────────────────────────────────────┐  240px
  │  [←] Settings / App Store / AppName          │  ← nav row (white, 0.7 op)
  │  [icon 45×45]      Item Name (20px, centered)│
  │               Type Label (12px, white 0.7)   │
  │         Item description (14px, centered)    │
  └──────────────────────────────────────────────┘

  COLLAPSED (scrollTop ≥ COLLAPSE_THRESHOLD):
  ┌──────────────────────────────────────────────┐  124px
  │  [←] Settings / App Store  (clickable)       │
  │  [icon 45×45]        Item Name (20px, centered)│
  └──────────────────────────────────────────────┘

  The breadcrumb label is also a clickable back button — tapping anywhere on
  the nav row navigates back, just like pressing the arrow.

  Props:
    appId             - the app ID (e.g. "audio")
    app               - AppMetadata for the app
    breadcrumbLabel   - current breadcrumb text
    fullBreadcrumbLabel - tooltip text (full path)
    scrollTop         - current scrollTop of .settings-content-wrapper
    onBack            - navigate back
    subItem           - optional: when set, shows item name/type label instead of
                        app description + capability counts
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import Icon from '../Icon.svelte';
  import type { AppMetadata } from '../../types/apps';

  // ─── Props ────────────────────────────────────────────────────────────────

  interface SubItem {
    /** Display name of the skill / focus mode / memory category */
    name: string;
    /** Short type label shown below the name, e.g. "Skill", "Focus mode" */
    typeLabel: string;
    /** Optional description shown in the collapsible details block */
    description?: string;
  }

  interface Props {
    appId: string;
    app: AppMetadata | undefined;
    breadcrumbLabel?: string;
    fullBreadcrumbLabel?: string;
    scrollTop?: number;
    onBack?: () => void;
    /**
     * When provided the banner shows the sub-item (skill/focus/memories) identity
     * instead of the app description + capability counts.
     */
    subItem?: SubItem;
  }

  let {
    appId,
    app,
    breadcrumbLabel = '',
    fullBreadcrumbLabel = '',
    scrollTop = 0,
    onBack,
    subItem,
  }: Props = $props();

  // ─── Collapse animation ───────────────────────────────────────────────────

  /**
   * Scroll distance (px) after which the header is fully collapsed.
   * The description + counts fade out; nav row + identity row stay visible.
   */
  const COLLAPSE_THRESHOLD = 80;

  /** Smooth ease-in-out cubic progress: 0 = expanded, 1 = collapsed */
  let collapseProgress = $derived.by(() => {
    const raw = Math.min(1, Math.max(0, scrollTop / COLLAPSE_THRESHOLD));
    return raw < 0.5 ? 4 * raw * raw * raw : 1 - Math.pow(-2 * raw + 2, 3) / 2;
  });

  /** Height: 240px → 124px. 124px holds nav row (44px) + identity row (56px) + padding */
  let headerHeight = $derived(Math.round(240 - 116 * collapseProgress));

  /**
   * Opacity for description + counts: fades out in the first half of collapse
   * so content is gone before the header reaches its minimum height.
   */
  let detailsOpacity = $derived(Math.max(0, 1 - collapseProgress * 2));

  // ─── App data ─────────────────────────────────────────────────────────────

  let appName = $derived(
    app?.name_translation_key ? $text(app.name_translation_key) : (app?.name || appId)
  );

  let appDescription = $derived(
    app?.description_translation_key
      ? $text(app.description_translation_key)
      : (app?.description || '')
  );

  /**
   * Normalise icon_image filename → CSS variable name.
   * The CSS variables use the app ID (e.g. --color-app-books, --color-app-images),
   * but the icon files may differ (book.svg → books, image.svg → images).
   * We also handle the special-cased renames done elsewhere in Settings.svelte.
   */
  let iconName = $derived.by(() => {
    if (!app?.icon_image) return appId;
    let n = app.icon_image.replace(/\.svg$/, '');
    // Special-case renames: icon file name → CSS variable / app ID
    if (n === 'coding') n = 'code';
    if (n === 'heart')  n = 'health';
    if (n === 'email')  n = 'mail';
    if (n === 'book')   n = 'books';   // book.svg → --color-app-books
    if (n === 'image')  n = 'images';  // image.svg → --color-app-images
    return n;
  });

  let skillCount  = $derived(app?.skills?.length ?? 0);
  let focusCount  = $derived(app?.focus_modes?.length ?? 0);
  let memoryCount = $derived(app?.settings_and_memories?.length ?? 0);
</script>

<div
  class="app-details-header"
  style="
    height: {headerHeight}px;
    background: var(--color-app-{iconName}, var(--color-primary));
  "
>
  <!-- ── Nav row: back arrow + breadcrumb (entire row is clickable) ── -->
  <button
    class="nav-row"
    onclick={onBack}
    aria-label={$text('settings.back')}
    type="button"
    title={fullBreadcrumbLabel || breadcrumbLabel}
  >
    <div class="clickable-icon icon_back nav-back-icon"></div>
    <span class="breadcrumb-label">{breadcrumbLabel}</span>
  </button>

  <!-- ── App identity: icon left-anchored, name absolutely centred ── -->
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
    <!-- Absolutely centered so it doesn't shift with the icon -->
    <span class="app-name">{subItem ? subItem.name : appName}</span>
  </div>

  <!-- ── Collapsible details block — fades out on scroll ── -->
  <div
    class="details-block"
    style="opacity: {detailsOpacity}; pointer-events: {detailsOpacity < 0.05 ? 'none' : 'auto'};"
    aria-hidden={detailsOpacity < 0.05}
  >
    {#if subItem}
      <!-- Sub-item mode: show type label + item description -->
      <span class="sub-item-type-label">{subItem.typeLabel}</span>
      {#if subItem.description}
        <p class="app-description">{subItem.description}</p>
      {/if}
    {:else}
      <!-- Top-level app mode: show app description + capability counts -->
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
    {/if}
  </div>
</div>

<style>
  /* ─── Container ─────────────────────────────────────────────────────────── */

  .app-details-header {
    /* Height driven by inline style (240px → 124px on scroll) */
    width: 100%;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    border-radius: 0 0 14px 14px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
    flex-shrink: 0;
    user-select: none;
    /* Smooth height animation as user scrolls */
    transition: height 0.15s cubic-bezier(0.4, 0, 0.2, 1);
  }

  /* ─── Nav row (entire row is the back button) ────────────────────────────── */

  .nav-row {
    /* Reset button defaults */
    all: unset;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    height: 44px;
    padding: 0 10px;
    flex-shrink: 0;
    gap: 6px;
    cursor: pointer;
    /* Subtle hover/active feedback on the entire row */
    border-radius: 0;
    transition: background-color 0.15s ease;
  }

  .nav-row:hover {
    background-color: rgba(255, 255, 255, 0.1);
  }

  .nav-row:active {
    background-color: rgba(255, 255, 255, 0.2);
  }

  /* Back icon — inherits .clickable-icon mask sizing from icons.css,
     but we force the colour to white since we're on a gradient. */
  .nav-back-icon {
    flex-shrink: 0;
    /* icons.css .clickable-icon sets mask-image; we just override colour */
    background-color: rgba(255, 255, 255, 0.85) !important;
  }

  .breadcrumb-label {
    font-size: 14px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.7);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
  }

  /* ─── App identity row ───────────────────────────────────────────────────── */

  .identity-row {
    /* Relative container so app-name can be absolutely centred */
    position: relative;
    display: flex;
    align-items: center;
    padding: 0 16px;
    flex-shrink: 0;
    /* Give enough height to hold the 45px icon comfortably */
    min-height: 56px;
  }

  .app-icon-slot {
    /* Left-aligned: stays in document flow */
    flex-shrink: 0;
    width: 45px;
    height: 45px;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    z-index: 1; /* above the absolutely-positioned name */
  }

  .app-name {
    /* Absolutely centred over the full row width, regardless of icon position */
    position: absolute;
    left: 0;
    right: 0;
    text-align: center;
    font-size: 20px;
    font-weight: 700;
    color: #ffffff;
    line-height: 1.25;
    padding: 0 60px; /* avoid overlapping icon on left and give matching space on right */
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    pointer-events: none;
  }

  /* ─── Collapsible details block ──────────────────────────────────────────── */

  .details-block {
    display: flex;
    flex-direction: column;
    align-items: center;
    /* Extra vertical breathing room above and below description */
    padding: 12px 20px 14px;
    gap: 12px;
    flex: 1;
    justify-content: center;
  }

  /* Type label for sub-item mode (e.g. "Skill", "Focus mode") */
  .sub-item-type-label {
    font-size: 12px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.7);
    text-align: center;
    letter-spacing: 0.04em;
    text-transform: uppercase;
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

  /* Settings & memories */
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
