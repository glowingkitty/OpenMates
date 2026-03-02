<!--
  AppDetailsHeader.svelte

  Collapsing gradient banner used for two contexts:

  1. TOP-LEVEL app page (app_store/{appId}) — no subItem prop:
  EXPANDED (scrollTop = 0):
  ┌──────────────────────────────────────────────┐  240px (mobile: 190px)
  │  [←] Settings / App Store  (clickable)       │  ← nav row
  │              [icon 50×50]                    │  ← icon centered
  │              App Name (20px, bold)           │  ← name centered below icon
  │         Description (14px, centered)         │
  │      3 🖥     1 🎯     1 🧠                  │
  └──────────────────────────────────────────────┘

  COLLAPSED (scrollTop ≥ COLLAPSE_THRESHOLD):
  ┌──────────────────────────────────────────────┐  88px
  │  [←] Settings / App Store  (clickable)       │  ← nav row
  │  [icon 36×36]  App Name  (left-aligned)      │  ← icon + name in a row
  └──────────────────────────────────────────────┘

  2. SUB-ITEM page (skill / focus / memories) — subItem prop provided:
  Same layout but the collapsible block shows item type label + description
  instead of app description + capability counts. The identity row shows the
  item name (not app name) in both expanded and collapsed states.

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
  import {
    appStoreNavigationStore,
    appStoreNavigatePrev,
    appStoreNavigateNext,
  } from '../../stores/appStoreNavigationStore';
  import { getLucideIcon } from '../../utils/categoryUtils';

  // ─── Props ────────────────────────────────────────────────────────────────

  interface SubItem {
    name: string;            // Display name of skill / focus mode / memory category
    typeLabel: string;       // Short type label, e.g. "Skill", "Focus mode"
    description?: string;    // Optional description in collapsible block
    iconName?: string;       // Icon name (without .svg) for item-specific icon
    iconType?: 'skill' | 'focus' | 'memory';
                             // 'skill'  → grey gradient (--icon-skill-background)
                             // 'focus'  → purple gradient (--icon-focus-background)
                             // 'memory' → pink gradient (--icon-memory-background)
  }

  /**
   * When settingsPage is provided, this banner is used for a standard settings
   * sub-page (e.g. Privacy, Billing, Usage) instead of an app store page.
   * The gradient defaults to --color-app-openmates and the icon is shown as
   * a white mask icon via the icon_{icon} CSS class system.
   * The `app` prop is not required when settingsPage is set.
   */
  interface SettingsPageStat {
    count: number;            // Numeric count to display
    iconClass: string;        // CSS class suffix for the icon (e.g. 'apps', 'skill', 'focus', 'memory')
  }

  interface SettingsPage {
    title: string;           // Page title (already translated)
    icon: string;            // CSS icon name (used as `icon_{icon}` class)
    description?: string;    // Optional description text
    stats?: SettingsPageStat[]; // Optional capability stats row (e.g. for App Store header)
  }

  interface Props {
    appId?: string;
    app?: AppMetadata | undefined;
    breadcrumbLabel?: string;
    fullBreadcrumbLabel?: string;
    scrollTop?: number;
    onBack?: () => void;
    subItem?: SubItem;       // When provided: banner shows sub-item identity
    settingsPage?: SettingsPage; // When provided: banner shows standard settings page
  }

  let {
    appId = '',
    app,
    breadcrumbLabel = '',
    fullBreadcrumbLabel = '',
    scrollTop = 0,
    onBack,
    subItem,
    settingsPage,
  }: Props = $props();

  // ─── Sub-item navigation (prev/next arrows) ───────────────────────────────

  /**
   * Navigation state from the sub-item pages (SkillDetails, FocusModeDetails,
   * AppSettingsMemoriesCategory) via the shared appStoreNavigationStore.
   * Only shown when subItem is provided (i.e., we are on a skill/focus/memories page).
   */
  let navState = $derived($appStoreNavigationStore);

  /** Lucide chevron icons for the prev/next arrow buttons. */
  const ChevronLeft = getLucideIcon('chevron-left');
  const ChevronRight = getLucideIcon('chevron-right');

  function handlePrev(e: MouseEvent) {
    e.stopPropagation();
    appStoreNavigatePrev();
  }

  function handleNext(e: MouseEvent) {
    e.stopPropagation();
    appStoreNavigateNext();
  }

  // ─── Collapse animation ───────────────────────────────────────────────────

  /**
   * Scroll distance (px) after which the header is fully collapsed.
   */
  const COLLAPSE_THRESHOLD = 80;

  /** Smooth ease-in-out cubic progress: 0 = expanded, 1 = collapsed */
  let collapseProgress = $derived.by(() => {
    const raw = Math.min(1, Math.max(0, scrollTop / COLLAPSE_THRESHOLD));
    return raw < 0.5 ? 4 * raw * raw * raw : 1 - Math.pow(-2 * raw + 2, 3) / 2;
  });

  /**
   * Expanded height: 240px desktop / 190px mobile.
   * We read a CSS custom property set by the media query via a reactive derivation.
   * Collapsed height: 88px (nav row 44px + identity row 44px).
   *
   * The JS doesn't know screen width directly, so we use CSS to drive height and
   * only use collapseProgress for the opacity / layout transitions below.
   * However, height IS set via inline style so we need to know the expanded height.
   * We use a window check — SSR-safe via the $derived lazy evaluation.
   */
  const COLLAPSED_HEIGHT = 88;
  const EXPANDED_HEIGHT_DESKTOP = 240;
  const EXPANDED_HEIGHT_MOBILE = 190;

  let expandedHeight = $derived.by(() => {
    if (typeof window === 'undefined') return EXPANDED_HEIGHT_DESKTOP;
    return window.innerWidth <= 730 ? EXPANDED_HEIGHT_MOBILE : EXPANDED_HEIGHT_DESKTOP;
  });

  /** Height: expandedHeight → 88px */
  let headerHeight = $derived(
    Math.round(expandedHeight - (expandedHeight - COLLAPSED_HEIGHT) * collapseProgress)
  );

  /**
   * Opacity for description + counts: fades out in the first half of collapse.
   */
  let detailsOpacity = $derived(Math.max(0, 1 - collapseProgress * 2));

  /**
   * Icon size interpolated: 50px (expanded) → 36px (collapsed).
   * Also drives the identity-row layout switch.
   */
  let iconSize = $derived(Math.round(50 - 14 * collapseProgress));

  /**
   * Name font size interpolated: 20px (expanded) → 17px (collapsed).
   */
  let nameFontSize = $derived(Math.round(20 - 3 * collapseProgress));

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
   */
  let iconName = $derived.by(() => {
    if (!app?.icon_image) return appId;
    let n = app.icon_image.replace(/\.svg$/, '');
    if (n === 'coding') n = 'code';
    if (n === 'heart')  n = 'health';
    if (n === 'email')  n = 'mail';
    if (n === 'book')   n = 'books';
    // Note: "image" is intentionally NOT mapped to "images" here.
    // Icon.svelte's getAppIdForCssVariable() already maps "image" → "images" for the
    // gradient background, and --icon-url-image is the correct CSS variable for the SVG.
    return n;
  });

  let skillCount  = $derived(app?.skills?.length ?? 0);
  let focusCount  = $derived(app?.focus_modes?.length ?? 0);
  let memoryCount = $derived(app?.settings_and_memories?.length ?? 0);

  // ─── settingsPage mode helpers (declared before displayName / appColorId) ──

  /** Display name for settingsPage mode */
  let settingsPageTitle = $derived(settingsPage?.title ?? '');

  /** Icon name for settingsPage mode (used as CSS class `icon_{name}`) */
  let settingsPageIcon = $derived(settingsPage?.icon ?? '');

  /** Description for settingsPage mode */
  let settingsPageDescription = $derived(settingsPage?.description ?? '');

  /** Stats for settingsPage mode (e.g. App Store aggregate capability counts) */
  let settingsPageStats = $derived(settingsPage?.stats ?? []);

  // ─────────────────────────────────────────────────────────────────────────────

  /** Display name shown in the identity row */
  let displayName = $derived(
    settingsPage ? settingsPageTitle :
    subItem ? subItem.name :
    appName
  );

  /**
   * App ID to use for the background gradient CSS variable (--color-app-{appColorId}).
   * - For settingsPage mode: always use 'openmates' (the primary brand gradient).
   * - For app store mode: use appId directly (keyed by app ID, not icon name).
   *   Falls back to iconName for apps that don't have an explicit ID.
   */
  let appColorId = $derived(settingsPage ? 'openmates' : (appId || iconName));
</script>

<div
  class="app-details-header"
  style="
    height: {headerHeight}px;
    background: var(--color-app-{appColorId}, var(--color-primary));
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
    <div class="nav-back-icon clickable-icon icon_back"></div>
    <span class="breadcrumb-label">{breadcrumbLabel}</span>
  </button>

  <!-- ── Identity block: expanded = column (icon above name, centered);
          collapsed = row (icon + name, left-aligned) ── -->
  <div
    class="identity-block"
    class:collapsed={collapseProgress > 0.5}
    style="
      align-items: {collapseProgress > 0.5 ? 'center' : 'center'};
      flex-direction: {collapseProgress > 0.5 ? 'row' : 'column'};
      justify-content: {collapseProgress > 0.5 ? 'flex-start' : 'center'};
      padding: {collapseProgress > 0.5 ? '0 16px' : '0 16px 4px'};
    "
  >
    {#if settingsPage && settingsPageIcon}
      <!-- Standard settings sub-page: show a white mask icon on the gradient -->
      <div
        class="app-icon-slot settings-page-icon-slot"
        style="
          width: {iconSize}px;
          height: {iconSize}px;
          flex-shrink: 0;
        "
      >
        <div
          class="settings-page-mask-icon icon_{settingsPageIcon}"
          style="width: {Math.round(iconSize * 0.58)}px; height: {Math.round(iconSize * 0.58)}px;"
        ></div>
      </div>
    {:else if subItem?.iconName}
      <!-- Sub-item page: show item-specific icon with skill/focus/memory gradient -->
      <div
        class="app-icon-slot"
        style="
          width: {iconSize}px;
          height: {iconSize}px;
          flex-shrink: 0;
        "
      >
        <Icon
          name={subItem.iconName}
          type={subItem.iconType ?? 'skill'}
          size="{iconSize}px"
          borderColor="#ffffff"
          noAnimation={true}
        />
      </div>
    {:else if app?.icon_image}
      <!-- Top-level app page: show app icon with app gradient -->
      <div
        class="app-icon-slot"
        style="
          width: {iconSize}px;
          height: {iconSize}px;
          flex-shrink: 0;
        "
      >
        <Icon
          name={iconName}
          type="app"
          size="{iconSize}px"
          borderColor="#ffffff"
          noAnimation={true}
        />
      </div>
    {/if}
    <!-- Name + category label stacked vertically when expanded -->
    <div
      class="name-category-block"
      class:name-category-block-row={collapseProgress > 0.5}
    >
      <span
        class="app-name"
        class:app-name-row={collapseProgress > 0.5}
        style="font-size: {nameFontSize}px;"
      >{displayName}</span>
      <!-- Category label: only shown in expanded mode and only for sub-item pages.
           Displayed at the same font size as the name but at 0.7 opacity, directly below the title. -->
      {#if subItem?.typeLabel && collapseProgress < 0.5}
        <span
          class="sub-item-category-label"
          style="font-size: {nameFontSize}px;"
        >{subItem.typeLabel}</span>
      {/if}
    </div>
  </div>

  <!-- ── Collapsible details block — fades out on scroll ── -->
  <div
    class="details-block"
    style="opacity: {detailsOpacity}; pointer-events: {detailsOpacity < 0.05 ? 'none' : 'auto'};"
    aria-hidden={detailsOpacity < 0.05}
  >
    {#if settingsPage}
      <!-- Standard settings page mode: show page description and optional stats row -->
      {#if settingsPageDescription}
        <p class="app-description">{settingsPageDescription}</p>
      {/if}
      {#if settingsPageStats.length > 0}
        <div class="capability-row">
          {#each settingsPageStats as stat (stat.iconClass)}
            {#if stat.count > 0}
              <div class="cap-item">
                <span class="cap-num">{stat.count}</span>
                <span class="cap-icon settings-stat-icon {stat.iconClass}-stat-icon"></span>
              </div>
            {/if}
          {/each}
        </div>
      {/if}
    {:else if subItem}
      <!-- Sub-item mode: show item description only (type label is now inline below the title) -->
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
          {#if memoryCount > 0}
            <div class="cap-item">
              <span class="cap-num">{memoryCount}</span>
              <span class="cap-icon memories-icon"></span>
            </div>
          {/if}
          {#if focusCount > 0}
            <div class="cap-item">
              <span class="cap-num">{focusCount}</span>
              <span class="cap-icon focus-icon"></span>
            </div>
          {/if}
        </div>
      {/if}
    {/if}
  </div>

  <!-- ── Sub-item navigation arrows ──
       Shown at the left and right edges when there are adjacent sibling items
       (skills, focus modes, or settings/memories categories) to navigate to.
       Only rendered when subItem is set (i.e. we are on a sub-item detail page).
       Uses pointer-events:auto to override the banner-level pointer-events:none. -->
  {#if subItem && navState.hasPrev}
    <button
      class="nav-arrow nav-arrow-left"
      onclick={handlePrev}
      aria-label={$text('settings.app_store.nav.previous_item', { values: { name: navState.prevName } })}
      type="button"
    >
      <ChevronLeft size={22} color="rgba(255,255,255,0.85)" />
    </button>
  {/if}
  {#if subItem && navState.hasNext}
    <button
      class="nav-arrow nav-arrow-right"
      onclick={handleNext}
      aria-label={$text('settings.app_store.nav.next_item', { values: { name: navState.nextName } })}
      type="button"
    >
      <ChevronRight size={22} color="rgba(255,255,255,0.85)" />
    </button>
  {/if}
</div>

<style>
  /* ─── Container ─────────────────────────────────────────────────────────── */

  .app-details-header {
    /* Height driven by inline style */
    position: relative; /* Required for absolute-positioned nav arrows */
    width: 100%;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    border-radius: 0 0 14px 14px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
    flex-shrink: 0;
    user-select: none;
    /* Decorative content is non-interactive; nav arrows override with pointer-events:auto */
    pointer-events: none;
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
    transition: background-color 0.15s ease;
    pointer-events: auto; /* Re-enable clicks despite parent pointer-events:none */
  }

  .nav-row:hover {
    background-color: rgba(255, 255, 255, 0.1);
  }

  .nav-row:active {
    background-color: rgba(255, 255, 255, 0.2);
  }

  /* Back icon — force white.
     icons.css sets `background: var(--color-primary)` via a shorthand.
     We must also use the shorthand `background` (not background-color) to win. */
  .nav-back-icon {
    flex-shrink: 0;
    background: rgba(255, 255, 255, 0.85) !important;
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

  /* ─── Identity block: column (expanded) ↔ row (collapsed) ───────────────── */

  .identity-block {
    /* Layout direction, alignment and padding are driven by inline style above.
       flex + gap ensure icon and name are neatly spaced in both orientations. */
    display: flex;
    gap: 10px;
    flex-shrink: 0;
    /* When expanded (column), this takes up the remaining height before details-block */
    flex: 0 0 auto;
    transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .app-icon-slot {
    display: flex;
    align-items: center;
    justify-content: center;
    /* Size is driven by inline style */
    transition: width 0.15s, height 0.15s;
  }

  /* Settings page icon slot: semi-transparent white circle + white mask icon inside */
  .settings-page-icon-slot {
    border-radius: 14px;
    background-color: rgba(255, 255, 255, 0.2);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  }

  /* The mask icon rendered inside the settings page icon slot.
     icons.css sets background to --color-primary; we override it to white here. */
  .settings-page-mask-icon {
    background: rgba(255, 255, 255, 0.95) !important;
    /* Size is driven by inline style */
    transition: width 0.15s, height 0.15s;
  }

  /* Wrapper that stacks name + category label vertically */
  .name-category-block {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
  }

  /* In row (collapsed) mode, name-category-block aligns left */
  .name-category-block-row {
    align-items: flex-start;
    justify-content: center;
  }

  .app-name {
    font-weight: 700;
    color: #ffffff;
    line-height: 1.25;
    text-align: center; /* centered in expanded (column) mode */
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    /* Font size driven by inline style */
    transition: font-size 0.15s;
  }

  /* In row (collapsed) mode: name is left-aligned, single line */
  .app-name-row {
    text-align: left;
    -webkit-line-clamp: 1;
    line-clamp: 1;
    align-self: center;
  }

  /* Category label shown directly below the title at the same font size, opacity 0.7.
     E.g. "Skill", "Focus mode", "Settings & memories" */
  .sub-item-category-label {
    font-weight: 600;
    color: rgba(255, 255, 255, 0.7);
    text-align: center;
    line-height: 1.25;
    /* Font size driven by inline style (matches nameFontSize) */
    transition: font-size 0.15s;
  }

  /* ─── Collapsible details block ──────────────────────────────────────────── */

  .details-block {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 6px 20px 14px;
    gap: 10px;
    flex: 1;
    justify-content: center;
    transition: opacity 0.1s ease;
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

  /* ─── Settings page stats row icons (used in settingsPage mode, e.g. App Store) ─ */

  /* Apps count — uses app.svg (the diamond/grid icon) */
  .apps-stat-icon {
    -webkit-mask-image: url('@openmates/ui/static/icons/app.svg');
    mask-image: url('@openmates/ui/static/icons/app.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
  }

  /* Skills count — uses skill.svg (same as top-level app skill-icon) */
  .skill-stat-icon {
    -webkit-mask-image: url('@openmates/ui/static/icons/skill.svg');
    mask-image: url('@openmates/ui/static/icons/skill.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
  }

  /* Focus modes count — uses insight.svg (same as top-level app focus-icon) */
  .focus-stat-icon {
    -webkit-mask-image: url('@openmates/ui/static/icons/insight.svg');
    mask-image: url('@openmates/ui/static/icons/insight.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
  }

  /* Settings & memory types count — uses settings.svg (same as top-level app memories-icon) */
  .memory-stat-icon {
    -webkit-mask-image: url('@openmates/ui/static/icons/settings.svg');
    mask-image: url('@openmates/ui/static/icons/settings.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
  }

  /* ─── Mobile adjustments (≤730px) — matches ChatHeader ─────────────────── */

  @media (max-width: 730px) {
    /* Expanded height is handled by the JS expandedHeight variable reading window.innerWidth.
       No CSS override needed for the height itself since it is set via inline style.
       We only need to scale down text sizes for the details block on mobile. */

    .app-description {
      font-size: 13px;
      -webkit-line-clamp: 2;
      line-clamp: 2;
    }

    .details-block {
      padding: 4px 16px 10px;
      gap: 8px;
    }

    .cap-icon {
      width: 18px;
      height: 18px;
    }

    .cap-num {
      font-size: 13px;
    }

    .breadcrumb-label {
      font-size: 13px;
    }
  }

  /* ─── Sub-item navigation arrows ────────────────────────────────────────────
     Positioned at the left and right edges of the header banner (identical layout
     to ChatHeader's .nav-arrow). Only shown on skill/focus/memories detail pages.
     pointer-events:auto overrides .app-details-header pointer-events:none so
     only the arrows are interactive. ALL global button{} rules are overridden
     with !important. */

  .nav-arrow {
    position: absolute;
    top: 0;
    bottom: 0;
    padding: 0 !important;
    min-width: unset !important;
    width: 40px !important;
    height: 100% !important;
    border-radius: 0 !important;
    background-color: transparent !important;
    filter: none !important;
    margin: 0 !important;
    border: none;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: background-color 0.15s ease;
    z-index: 20;
    pointer-events: auto; /* Re-enable interactivity despite banner pointer-events:none */
    flex-shrink: 0;
  }

  .nav-arrow:hover {
    background-color: rgba(255, 255, 255, 0.1) !important;
    scale: none !important;
  }

  .nav-arrow:active {
    background-color: rgba(255, 255, 255, 0.18) !important;
    scale: none !important;
    filter: none !important;
  }

  .nav-arrow-left {
    left: 0;
    border-radius: 0 10px 10px 0 !important;
  }

  .nav-arrow-right {
    right: 0;
    border-radius: 10px 0 0 10px !important;
  }
</style>
