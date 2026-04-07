<!--
    SettingsItem — Universal settings menu row component.

    Handles 5 of the 12 canonical Figma settings UI element types:
    1. Subsettings menu link  → type="submenu"
    2. Settings item with toggle → hasToggle=true
    3. Clickable action → type="quickaction"
    4. Settings item with value → subtitle + hasModifyButton
    5. Settings subheading → type="heading"

    Icon system (v2):
    - icon: simple name string (e.g. "chat", "lock", "travel")
    - iconColor: CSS gradient/color for the SVG icon itself (default: var(--color-primary))
    - iconBackground: container background — 'none' (flat icon) or 'primary' (blue square + white icon)
    - Icons are resolved via auto-generated --icon-url-{name} CSS variables
      (see scripts/generate-icon-urls.js, src/styles/icon-urls.generated.css)

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    See also: docs/architecture/settings-ui.md
    Preview: /dev/preview/settings (shows all variants side-by-side)
-->
<script lang="ts">
    import Toggle from './Toggle.svelte';
    import ModifyButton from './buttons/ModifyButton.svelte';
    import type { Snippet, Component } from 'svelte';
    import { resolveIconName } from '../utils/iconNameResolver';

    /** Supported SettingsItem display types */
    type SettingsItemType = 'heading' | 'submenu' | 'quickaction' | 'subsubmenu' | 'nested';

    /**
     * Icon background mode:
     * - 'none': transparent background, icon rendered as flat gradient SVG via CSS mask
     * - 'primary': var(--color-primary) blue gradient rounded square with white SVG inside
     */
    type SettingsIconBackground = 'none' | 'primary';

    /** App/provider icon displayed on the right side of the row */
    interface AppIconEntry {
        name: string;
        type?: 'app' | 'provider';
    }

    // Props using Svelte 5 runes
    let { 
        icon,
        type = 'heading',
        title = undefined,
        subtitleTop = undefined,
        subtitle = undefined,
        subtitleBottom = undefined,
        showCredits = false,
        creditAmount = undefined,
        creditCurrency = undefined,
        appIcons = undefined,
        maxVisibleIcons = 3,
        hasToggle = false,
        hasModifyButton = false,
        checked = false,
        disabled = false,
        onClick = undefined,
        onModifyClick = undefined,
        hasNestedItems = false,
        iconColor = undefined,
        iconBackground = undefined,
        lucideIcon = undefined,
        rightActionIcon = undefined,
        creditsDisplay = undefined,
        children
    }: {
        /** Icon name — resolved to --icon-url-{name} CSS variable. See ICON_NAME_MAP for aliases. */
        icon: string;
        type?: SettingsItemType;
        title?: string | undefined;
        subtitleTop?: string;
        subtitle?: string;
        subtitleBottom?: string;
        showCredits?: boolean;
        creditAmount?: number | undefined;
        creditCurrency?: string;
        appIcons?: AppIconEntry[];
        maxVisibleIcons?: number;
        hasToggle?: boolean;
        hasModifyButton?: boolean;
        checked?: boolean;
        disabled?: boolean;
        onClick?: (() => void) | undefined;
        onModifyClick?: (() => void) | undefined;
        hasNestedItems?: boolean;
        /**
         * CSS gradient/color for the SVG icon itself.
         * Examples: "var(--color-primary)", "var(--color-app-travel)",
         *           "linear-gradient(135deg, #4867cd, #5a85eb)"
         * Default: "var(--color-primary)" (blue gradient)
         */
        iconColor?: string | undefined;
        /**
         * Container background mode:
         * - 'none': transparent — flat gradient-colored SVG icon (subsetting style)
         * - 'primary': var(--color-primary) blue rounded square with white SVG inside
         * Default: 'primary' for heading/submenu, 'none' for quickaction/subsubmenu/nested
         */
        iconBackground?: SettingsIconBackground | undefined;
        /**
         * Optional Lucide icon component to render instead of the CSS mask-based icon.
         * When provided, the Lucide component renders inside the icon container with
         * the same background/sizing as the standard icon. Useful for dynamic/category icons.
         */
        lucideIcon?: Component<{ size?: number; color?: string }> | undefined;
        /**
         * Optional right-side action button icon name (e.g. 'download' shows a download button).
         * Renders a gradient circle button identical to ModifyButton but with a different icon.
         */
        rightActionIcon?: string | undefined;
        /**
         * Credits display on the right side (usage entries).
         * Shows "{creditsDisplay} [coins icon]" in var(--color-grey-50).
         */
        creditsDisplay?: string | undefined;
        children?: Snippet | undefined;
    } = $props();

    // Backward-compat: `subtitle` is an alias for `subtitleTop`, without mutating props.
    let displaySubtitleTop = $derived(subtitleTop ?? subtitle);

    // Resolved icon SVG name (handles "subsetting_icon " prefix and name aliases)
    let resolvedIconName = $derived(resolveIconName(icon));

    // Determine icon background: explicit prop > type-based default
    let resolvedBackground: SettingsIconBackground = $derived(
        iconBackground ?? (
            (type === 'quickaction' || type === 'subsubmenu' || type === 'nested')
                ? 'none'
                : 'primary'
        )
    );

    // Determine icon color
    let resolvedColor = $derived(iconColor ?? 'var(--color-primary)');

    // Whether this icon has a solid background (blue square) or is transparent (flat icon)
    let hasIconBg = $derived(resolvedBackground === 'primary');

    // Build inline style for the icon element
    // When iconColor is explicitly provided with a background, use it for --si-bg
    // so custom gradients (e.g. app-specific colors) render on the icon container.
    let iconStyle = $derived(
        `--si-icon: var(--icon-url-${resolvedIconName});` +
        (hasIconBg
            ? ` --si-bg: ${iconColor ?? 'var(--color-primary)'};`
            : ` --si-color: ${resolvedColor};`)
    );

    // Computed values
    let isClickable = $derived(onClick !== undefined);
    let hasAnySubtitle = $derived(displaySubtitleTop || subtitleBottom);

    /**
     * Whether the title should use the OpenMates gradient text colour.
     * Applied to all clickable settings items (submenu, quickaction, value entries)
     * but NOT to non-clickable headings.
     */
    let hasTitleGradient = $derived(isClickable && type !== 'heading');

    // Handle events — use Event base type since handlers are shared by mouse and keyboard
    function handleItemClick(event: Event) {
        event.stopPropagation();
        if (!disabled && isClickable && onClick) {
            onClick();
        }
    }

    function handleToggleClick(event: Event) {
        event.stopPropagation();
        event.preventDefault();
        if (!disabled && isClickable && onClick) {
            onClick();
        }
    }

    function handleModifyClick(event: Event) {
        event.stopPropagation();
        if (onModifyClick) {
            onModifyClick();
        }
    }

    function handleKeydown(event: KeyboardEvent, handler: () => void) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            event.stopPropagation();
            handler();
        }
    }
</script>

<!-- Shared inner content rendered via snippet to avoid duplication across interactive/non-interactive variants -->
{#snippet menuItemContent()}
    <div class="menu-item-content">
        <div class="menu-item-left">
            <!-- Unified icon rendering — single element, two CSS modes via .has-bg -->
            <div class="icon-container">
                {#if lucideIcon}
                    {@const LucideComp = lucideIcon}
                    <div
                        class="settings-icon lucide-icon"
                        class:has-bg={hasIconBg}
                        style={hasIconBg ? `--si-bg: ${resolvedColor};` : `background: linear-gradient(135deg, var(--color-grey-20), var(--color-grey-30));`}
                    >
                        <LucideComp size={hasIconBg ? 20 : 22} color={hasIconBg ? 'white' : resolvedColor} />
                    </div>
                {:else}
                    <div
                        class="settings-icon"
                        class:has-bg={hasIconBg}
                        style={iconStyle}
                    ></div>
                {/if}
            </div>
            
            <div class="text-and-nested-container">
                <div class="text-container" class:has-title={!!title} class:has-subtitle={hasAnySubtitle} class:heading-text={type === 'heading'}>
                    <!-- Top subtitle if present -->
                    {#if displaySubtitleTop}
                        <div class="menu-subtitle-top">{displaySubtitleTop}</div>
                    {/if}
                    
                    <!-- Main title -->
                    {#if title}
                        <div class="menu-title" class:gradient-text={hasTitleGradient}>
                            {#if type === 'heading'}
                                <strong>{title}</strong>
                            {:else}
                                {title}
                            {/if}
                        </div>
                    {/if}
                    
                    <!-- Bottom subtitle if present -->
                    {#if subtitleBottom}
                        <div class="menu-subtitle-bottom">{subtitleBottom}</div>
                    {/if}
                    
                    <!-- Credits display if enabled -->
                    {#if showCredits && creditAmount !== undefined}
                        <div class="menu-credits">
                            {creditAmount} {creditCurrency || 'credits'}
                        </div>
                    {/if}
                </div>
                
                <!-- Nested content if present -->
                {#if hasNestedItems && children}
                    <div class="nested-content">
                        {@render children()}
                    </div>
                {/if}
            </div>
        </div>
        
        <div class="menu-item-right">
            <!-- App icons if present -->
            {#if appIcons && appIcons.length > 0}
                <div class="app-icons-container">
                    {#each appIcons.slice(0, maxVisibleIcons || 3) as appIcon}
                        <div class="app-icon" class:app={appIcon.type === 'app'} class:provider={appIcon.type === 'provider'}>
                            {appIcon.name}
                        </div>
                    {/each}
                    {#if appIcons.length > (maxVisibleIcons || 3)}
                        <div class="app-icon more">+{appIcons.length - (maxVisibleIcons || 3)}</div>
                    {/if}
                </div>
            {/if}
            
            <!-- Toggle if present -->
            {#if hasToggle}
                <div 
                    onmousedown={(e) => { e.preventDefault(); e.stopPropagation(); }}
                    onclick={handleToggleClick}
                    onkeydown={(e) => handleKeydown(e, () => onClick?.())}
                    role="button" 
                    tabindex="0"
                    class="toggle-container"
                    data-testid="toggle-container"
                >
                    <Toggle 
                        checked={checked}
                        name={title || displaySubtitleTop?.toLowerCase?.() || ''}
                        ariaLabel={`Toggle ${(title || displaySubtitleTop || '').toLowerCase()} mode`}
                        disabled={disabled}
                    />
                </div>
            {/if}
            
            <!-- Modify button if explicitly enabled -->
            {#if hasModifyButton}
                <div
                    onclick={handleModifyClick}
                    onkeydown={(e) => handleKeydown(e, () => onModifyClick?.())}
                    role="button"
                    tabindex="0"
                    class="modify-button-container"
                >
                    <ModifyButton />
                </div>
            {/if}

            <!-- Right-side action icon button (e.g. download) -->
            {#if rightActionIcon}
                <div class="right-action-button" aria-label={rightActionIcon}>
                    <div class="right-action-icon" style="--right-action-icon-url: var(--icon-url-{resolveIconName(rightActionIcon)});"></div>
                </div>
            {/if}

            <!-- Credits display with coins icon -->
            {#if creditsDisplay}
                <div class="credits-display">
                    <span class="credits-display-text">{creditsDisplay}</span>
                    <div class="credits-display-coins" aria-hidden="true"></div>
                </div>
            {/if}
        </div>
    </div>
{/snippet}

<!-- Clickable variant: interactive role with keyboard support -->
{#if isClickable}
<div
    class="menu-item settings-item clickable"
    data-testid="menu-item"
    class:disabled={disabled}
    class:heading={type === 'heading'}
    class:submenu={type === 'submenu'}
    class:quickaction={type === 'quickaction'}
    class:subsubmenu={type === 'subsubmenu'}
    class:nested={type === 'nested'}
    class:has-nested-items={hasNestedItems}
    onclick={handleItemClick}
    onkeydown={(e) => !disabled && handleKeydown(e, () => onClick?.())}
    role="menuitem"
    tabindex={disabled ? -1 : 0}
>
    {@render menuItemContent()}
</div>
{:else}
<!-- Non-clickable variant: presentation role, no tabindex -->
<div
    class="menu-item settings-item"
    data-testid="menu-item"
    class:disabled={disabled}
    class:heading={type === 'heading'}
    class:submenu={type === 'submenu'}
    class:quickaction={type === 'quickaction'}
    class:subsubmenu={type === 'subsubmenu'}
    class:nested={type === 'nested'}
    class:has-nested-items={hasNestedItems}
    role="presentation"
>
    {@render menuItemContent()}
</div>
{/if}

<style>
    .menu-item {
        display: flex;
        flex-direction: column;
        padding: 5px 10px;
        border-radius: var(--radius-3);
        transition: background-color var(--duration-normal) var(--easing-default);
        cursor: default;
        position: relative;
    }

    .menu-item.clickable {
        cursor: pointer;
    }

    .menu-item.clickable:hover {
        background-color: var(--color-grey-10);
    }

    .menu-item.disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .menu-item-content {
        display: flex;
        align-items: center;
        justify-content: space-between;
        width: 100%;
        min-height: 40px;
    }

    .menu-item-left {
        display: flex;
        align-items: center;
        flex: 1;
        min-width: 0;
    }

    /* Shared icon area sizing — all icon types use the same 44px slot */
    .icon-container {
        width: 44px;
        height: 44px;
        margin-inline-end: 12px;
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    /*
     * Unified settings icon — two rendering modes:
     *
     * Mode A (.settings-icon without .has-bg):
     *   Transparent background. SVG rendered as flat gradient-colored shape via CSS mask on ::after.
     *   Used for quickaction, subsubmenu, nested, app icons, category icons, etc.
     *
     * Mode B (.settings-icon.has-bg):
     *   Gradient background (var(--si-bg)). White SVG icon via ::before with brightness invert.
     *   Used for heading and submenu section icons.
     */
    .settings-icon {
        width: 44px;
        height: 44px;
        border-radius: var(--radius-4);
        position: relative;
    }

    /* Mode A: Subtle grey gradient background — flat gradient-colored icon via CSS mask */
    .settings-icon:not(.has-bg) {
        background: linear-gradient(135deg, var(--color-grey-20), var(--color-grey-30));
    }

    .settings-icon:not(.has-bg)::after {
        content: '';
        position: absolute;
        inset: 0;
        background: var(--si-color, var(--color-primary));
        -webkit-mask-image: var(--si-icon);
        -webkit-mask-size: 50%;
        -webkit-mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-image: var(--si-icon);
        mask-size: 50%;
        mask-repeat: no-repeat;
        mask-position: center;
    }

    /* Mode B: Solid background — white icon on gradient square */
    .settings-icon.has-bg {
        background: var(--si-bg, var(--color-primary));
    }

    .settings-icon.has-bg::before {
        content: '';
        position: absolute;
        inset: 0;
        background-image: var(--si-icon);
        background-size: 50%;
        background-repeat: no-repeat;
        background-position: center;
        filter: brightness(0) invert(1);
    }

    /* Mode C: Lucide icon component rendered inside the container */
    .settings-icon.lucide-icon {
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .settings-icon.lucide-icon:not(.has-bg) {
        color: var(--si-color, var(--color-primary));
    }

    .text-and-nested-container {
        display: flex;
        flex-direction: column;
        flex: 1;
        min-width: 0;
    }

    .text-container {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-1);
    }

    .text-container.has-title {
        gap: var(--spacing-2);
    }

    .text-container.has-subtitle {
        gap: var(--spacing-1);
    }

    .menu-title {
        font-size: var(--font-size-p);
        color: var(--color-grey-100);
        /* Use logical alignment: left in LTR, right in RTL */
        text-align: start;
        display: -webkit-box;
        -webkit-line-clamp: 3;
        line-clamp: 3;
        -webkit-box-orient: vertical;
        overflow: hidden;
        font-weight: 500;
    }

    /* Gradient text for all clickable settings items (submenu, action, toggle, value) */
    .menu-title.gradient-text {
        background: var(--color-primary);
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
        /* Must override the -webkit-box display for gradient to render */
        display: block;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-weight: 500;
    }

    /* Brighter gradient for dark mode readability */
    :global([data-theme="dark"]) .menu-title.gradient-text {
        background: linear-gradient(135deg, #6387ff 9.04%, #7ea4ff 90.06%);
        -webkit-background-clip: text;
        background-clip: text;
    }

    .heading .menu-title strong {
        font-weight: 600;
    }

    .menu-subtitle-top,
    .menu-subtitle-bottom {
        font-size: var(--font-size-small);
        color: var(--color-grey-60);
        text-align: start;
    }

    .menu-credits {
        font-size: var(--font-size-xxs);
        color: var(--color-grey-50);
        font-weight: 500;
    }

    .nested-content {
        margin-top: var(--spacing-4);
        /* Logical property: indent nested items from the inline-start side */
        padding-inline-start: 36px;
    }

    .menu-item-right {
        display: flex;
        align-items: center;
        gap: var(--spacing-4);
        flex-shrink: 0;
    }

    .app-icons-container {
        display: flex;
        gap: var(--spacing-2);
        align-items: center;
    }

    .app-icon {
        width: 20px;
        height: 20px;
        border-radius: var(--radius-1);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: null;
        font-weight: 500;
        color: white;
        background-color: var(--color-grey-40);
    }

    .app-icon.app {
        background-color: var(--color-primary);
    }

    .app-icon.provider {
        background-color: var(--color-secondary);
    }

    .app-icon.more {
        background-color: var(--color-grey-50);
    }

    .toggle-container {
        display: flex;
        align-items: center;
        cursor: pointer;
        padding: var(--spacing-2);
        border-radius: var(--radius-1);
        transition: background-color var(--duration-normal) var(--easing-default);
    }

    .toggle-container:hover {
        background-color: var(--color-grey-10);
    }

    .toggle-container:focus {
        outline: 2px solid var(--color-primary);
        outline-offset: 2px;
    }

    .modify-button-container {
        display: flex;
        align-items: center;
        cursor: pointer;
    }

    /* Right-side action button (e.g. download) — same circle style as ModifyButton */
    .right-action-button {
        width: 30px;
        height: 30px;
        border-radius: 50%;
        background: var(--color-primary);
        cursor: pointer;
        position: relative;
        box-shadow: var(--shadow-sm);
        flex-shrink: 0;
        transition: transform var(--duration-normal) var(--easing-default);
    }

    .right-action-button:hover {
        transform: scale(1.1);
    }

    .right-action-icon {
        position: absolute;
        inset: 0;
        background-color: var(--color-grey-0);
        -webkit-mask-image: var(--right-action-icon-url);
        -webkit-mask-size: 50%;
        -webkit-mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-image: var(--right-action-icon-url);
        mask-size: 50%;
        mask-position: center;
        mask-repeat: no-repeat;
    }

    /* Credits display (coin icon + amount) for usage entries */
    .credits-display {
        display: flex;
        align-items: center;
        gap: var(--spacing-2);
        flex-shrink: 0;
    }

    .credits-display-text {
        font-size: var(--font-size-small);
        font-weight: 500;
        color: var(--color-grey-50);
    }

    .credits-display-coins {
        width: 18px;
        height: 18px;
        background-color: var(--color-grey-50);
        -webkit-mask-image: var(--icon-url-coins);
        -webkit-mask-size: contain;
        -webkit-mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-image: var(--icon-url-coins);
        mask-size: contain;
        mask-position: center;
        mask-repeat: no-repeat;
    }

    /* Responsive adjustments */
    @media (max-width: 600px) {
        .menu-item {
            padding: var(--spacing-2) var(--spacing-5);
        }
    }
</style>
