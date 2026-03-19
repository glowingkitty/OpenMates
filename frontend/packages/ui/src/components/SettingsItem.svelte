<!--
    SettingsItem — Universal settings menu row component.

    Handles 5 of the 12 canonical Figma settings UI element types:
    1. Subsettings menu link  → type="submenu"
    2. Settings item with toggle → hasToggle=true
    3. Clickable action → type="quickaction"
    4. Settings item with value → subtitle + hasModifyButton
    5. Settings subheading → type="heading"

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    See also: docs/architecture/settings-ui.md
    Preview: /dev/preview/settings (shows all variants side-by-side)
-->
<script lang="ts">
    import Toggle from './Toggle.svelte';
    import ModifyButton from './buttons/ModifyButton.svelte';
    import { getCategoryGradientColors } from '../utils/categoryUtils';
    import type { Snippet } from 'svelte';

    /** Supported SettingsItem display types */
    type SettingsItemType = 'heading' | 'submenu' | 'quickaction' | 'subsubmenu' | 'nested';

    /** Icon rendering mode — determines how the left icon area is styled */
    type SettingsItemIconType = 'default' | 'app' | 'memory' | 'skill' | 'focus' | 'category';

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
        iconType = 'default',
        category = undefined,
        categoryIcon = undefined,
        rightActionIcon = undefined,
        creditsDisplay = undefined,
        children
    }: {
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
        iconType?: SettingsItemIconType;
        category?: string | undefined;
        categoryIcon?: string | undefined;
        /**
         * Optional right-side action button icon name (e.g. 'download' shows a download button).
         * Renders a gradient circle button identical to ModifyButton but with a different icon.
         * When provided alongside hasModifyButton, both are shown.
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

    // Computed values
    let isClickable = $derived(onClick !== undefined);
    let hasAnySubtitle = $derived(displaySubtitleTop || subtitleBottom);
    let iconClass = $derived(type === 'quickaction' || type === 'subsubmenu' ? 
        `icon settings_size subsetting_icon ${icon}` : `icon settings_size ${icon}`);

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

<!-- Single unified template — clickable vs non-clickable is handled via conditional attributes -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<div 
    class="menu-item"
    class:clickable={isClickable}
    class:disabled={disabled}
    class:heading={type === 'heading'}
    class:submenu={type === 'submenu'}
    class:quickaction={type === 'quickaction'}
    class:subsubmenu={type === 'subsubmenu'}
    class:nested={type === 'nested'}
    class:has-nested-items={hasNestedItems}
    onclick={isClickable ? handleItemClick : undefined}
    onkeydown={isClickable ? (e) => !disabled && handleKeydown(e, () => onClick?.()) : undefined}
    role={isClickable ? 'menuitem' : 'presentation'}
    tabindex={isClickable ? (disabled ? -1 : 0) : undefined}
>
    <div class="menu-item-content">
        <div class="menu-item-left">
            <!-- Icon rendering: app icon, memory/skill/focus gradient icon, category gradient circle, or default mask icon -->
            {#if iconType === 'app'}
                <div class="icon-container">
                    <div class={`icon settings_size subsetting_icon ${icon}`} style="--icon-color: var(--color-app-{icon});"></div>
                </div>
            {:else if iconType === 'memory' || iconType === 'skill' || iconType === 'focus'}
                <!-- Renders icon SVG with type-specific gradient color (no rounded bg) -->
                <div class="icon-container">
                    <div class={`icon settings_size subsetting_icon ${icon}`} style={
                        iconType === 'memory' ? '--icon-color: var(--icon-memory-background);' :
                        iconType === 'skill' ? '--icon-color: var(--icon-skill-background);' :
                        '--icon-color: var(--icon-focus-background);'
                    }></div>
                </div>
            {:else if iconType === 'category' && category}
                {@const gradientColors = getCategoryGradientColors(category)}
                <div class="icon-container">
                    <div class={`icon settings_size subsetting_icon ${icon}`} style={gradientColors
                        ? `--icon-color: linear-gradient(135deg, ${gradientColors.start} 9.04%, ${gradientColors.end} 90.06%);`
                        : ''
                    }></div>
                </div>
            {:else}
                <div class="icon-container">
                    <div class={iconClass}></div>
                </div>
            {/if}
            
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
                    <div class="right-action-icon" style="--right-action-icon-url: var(--icon-url-{rightActionIcon});"></div>
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
</div>

<style>
    .menu-item {
        display: flex;
        flex-direction: column;
        padding: 5px 10px;
        border-radius: 8px;
        transition: background-color 0.2s ease;
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

    .text-and-nested-container {
        display: flex;
        flex-direction: column;
        flex: 1;
        min-width: 0;
    }

    .text-container {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .text-container.has-title {
        gap: 4px;
    }

    .text-container.has-subtitle {
        gap: 2px;
    }

    .menu-title {
        font-size: 16px;
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

    .heading .menu-title strong {
        font-weight: 600;
    }

    .menu-subtitle-top,
    .menu-subtitle-bottom {
        font-size: 14px;
        color: var(--color-grey-60);
        text-align: start;
    }

    .menu-credits {
        font-size: 12px;
        color: var(--color-grey-50);
        font-weight: 500;
    }

    .nested-content {
        margin-top: 8px;
        /* Logical property: indent nested items from the inline-start side */
        padding-inline-start: 36px;
    }

    .menu-item-right {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-shrink: 0;
    }

    .app-icons-container {
        display: flex;
        gap: 4px;
        align-items: center;
    }

    .app-icon {
        width: 20px;
        height: 20px;
        border-radius: 4px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 10px;
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
        padding: 4px;
        border-radius: 4px;
        transition: background-color 0.2s ease;
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
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
        flex-shrink: 0;
        transition: transform 0.2s ease;
    }

    .right-action-button:hover {
        transform: scale(1.1);
    }

    .right-action-icon {
        position: absolute;
        inset: 0;
        background-color: #ffffff;
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
        gap: 4px;
        flex-shrink: 0;
    }

    .credits-display-text {
        font-size: 14px;
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
            padding: 4px 10px;
        }
    }
</style>
