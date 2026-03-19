<!--
    SettingsTabs — Tab bar with icons, animated sliding pill, and optional counters.

    Matches Figma "Tabs" element:
    - Icon-only tabs (no text labels)
    - Active tab: gradient pill slides left/right with CSS transition
    - Inactive icons: var(--color-grey-30)
    - Active icon: white (#fff)
    - Hover on inactive: gradient at 0.5 opacity (smooth transition)
    - Optional counter badges: round, white text, bottom-right next to icon
    - >4 tabs: scrollable with fade gradients at left/right edges

    Icons use --icon-url-{name} CSS custom properties (defined by Icon.svelte :root block)
    so they resolve correctly through Vite's asset pipeline.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    import { onMount } from 'svelte';

    /** Individual tab definition */
    interface TabItem {
        /** Unique identifier for the tab */
        id: string;
        /** Icon name — matches a CSS variable --icon-url-{name} defined in Icon.svelte */
        icon: string;
        /** Optional counter badge number */
        count?: number;
    }

    let {
        tabs = [],
        activeTab = $bindable(''),
        gradientStart = '',
        gradientEnd = '',
        onChange = undefined,
    }: {
        tabs?: TabItem[];
        activeTab?: string;
        gradientStart?: string;
        gradientEnd?: string;
        onChange?: ((tabId: string) => void) | undefined;
    } = $props();

    /** Use OpenMates primary gradient if no custom gradient provided */
    let effectiveGradientStart = $derived(gradientStart || 'var(--color-primary-start)');
    let effectiveGradientEnd = $derived(gradientEnd || 'var(--color-primary-end)');

    let isScrollable = $derived(tabs.length > 4);

    /** Index of the active tab (used for pill offset calculation) */
    let activeIndex = $derived(Math.max(0, tabs.findIndex(t => t.id === activeTab)));

    /** Scroll-edge visibility for fade gradients */
    let scrollEl: HTMLDivElement | null = $state(null);
    let showLeftFade = $state(false);
    let showRightFade = $state(true); // starts true for scrollable

    function updateFades() {
        if (!scrollEl) return;
        const { scrollLeft, scrollWidth, clientWidth } = scrollEl;
        showLeftFade = scrollLeft > 4;
        showRightFade = scrollLeft < scrollWidth - clientWidth - 4;
    }

    onMount(() => {
        if (scrollEl && isScrollable) {
            updateFades();
        }
    });

    function selectTab(tabId: string) {
        activeTab = tabId;
        onChange?.(tabId);
    }

    function handleKeydown(event: KeyboardEvent, tabId: string) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            selectTab(tabId);
        }
    }
</script>

<div class="settings-tabs-wrapper">
    <div
        class="settings-tabs-outer"
        class:scrollable={isScrollable}
        class:fade-left={isScrollable && showLeftFade}
        class:fade-right={isScrollable && showRightFade}
    >
        <div
            class="settings-tabs-container"
            class:scrollable={isScrollable}
            bind:this={scrollEl}
            onscroll={updateFades}
        >
            <div
                class="settings-tabs-track"
                role="tablist"
                style="
                    --tab-count: {tabs.length};
                    --active-index: {activeIndex};
                    --gradient-start: {effectiveGradientStart};
                    --gradient-end: {effectiveGradientEnd};
                "
            >
                <!-- Animated gradient pill (positioned behind tabs via CSS) -->
                <div class="settings-tabs-pill" aria-hidden="true"></div>

                {#each tabs as tab}
                    <button
                        class="settings-tab"
                        class:active={activeTab === tab.id}
                        role="tab"
                        aria-selected={activeTab === tab.id}
                        aria-controls={`tabpanel-${tab.id}`}
                        onclick={() => selectTab(tab.id)}
                        onkeydown={(e) => handleKeydown(e, tab.id)}
                    >
                        <!--
                            Icon uses CSS custom property --icon-url-{name} which is set in :root
                            by Icon.svelte. We pass it via style="" so Svelte's scoped CSS can
                            reference it, bypassing the broken URL interpolation issue.
                        -->
                        <div
                            class="tab-icon"
                            class:active={activeTab === tab.id}
                            style="--tab-icon-url: var(--icon-url-{tab.icon});"
                        ></div>

                        {#if tab.count !== undefined && tab.count > 0}
                            <span class="tab-count">{tab.count}</span>
                        {/if}
                    </button>
                {/each}
            </div>
        </div>
    </div>
</div>

<style>
    .settings-tabs-wrapper {
        padding: 0 0.625rem;
    }

    /* Outer wrapper handles the fade overlays — must not clip them */
    .settings-tabs-outer {
        position: relative;
        border-radius: 3.25rem;
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.1);
    }

    /* Edge fade gradients for scrollable mode */
    .settings-tabs-outer.scrollable::before,
    .settings-tabs-outer.scrollable::after {
        content: '';
        position: absolute;
        top: 0;
        bottom: 0;
        width: 1.25rem;
        pointer-events: none;
        z-index: 2;
        border-radius: 3.25rem;
        opacity: 0;
        transition: opacity 0.25s ease;
    }

    .settings-tabs-outer.scrollable::before {
        left: 0;
        background: linear-gradient(to right, var(--color-grey-0), transparent);
    }

    .settings-tabs-outer.scrollable::after {
        right: 0;
        background: linear-gradient(to left, var(--color-grey-0), transparent);
    }

    .settings-tabs-outer.fade-left::before {
        opacity: 1;
    }

    .settings-tabs-outer.fade-right::after {
        opacity: 1;
    }

    /* Scrollable inner container (no border-radius so it doesn't clip) */
    .settings-tabs-container {
        background: var(--color-grey-0);
        border-radius: 3.25rem;
        overflow: hidden;
    }

    .settings-tabs-container.scrollable {
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
        /* Remove right border-radius when scrollable to allow content to peek */
        border-radius: 3.25rem 0 0 3.25rem;
    }

    .settings-tabs-container.scrollable::-webkit-scrollbar {
        display: none;
    }

    .settings-tabs-track {
        display: flex;
        position: relative;
        min-width: 100%;
    }

    /* ── Animated gradient pill ──────────────────────────────────── */
    .settings-tabs-pill {
        position: absolute;
        top: 0;
        bottom: 0;
        width: calc(100% / var(--tab-count, 1));
        left: calc(100% / var(--tab-count, 1) * var(--active-index, 0));
        background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end));
        border-radius: 3.25rem;
        transition: left 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        z-index: 0;
    }

    /* For scrollable (>4 tabs), pill uses fixed width */
    .scrollable .settings-tabs-pill {
        width: calc(100% / 4.3);
        left: calc(100% / 4.3 * var(--active-index, 0));
    }

    /* ── Tab buttons — full reset of buttons.css globals ─────────── */
    .settings-tab {
        /* Reset ALL buttons.css globals */
        all: unset;
        box-sizing: border-box;

        flex: 1 0 0;
        min-width: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0.5rem 0.75rem;
        height: 2.8rem;
        border-radius: 3.25rem;
        background: transparent;
        cursor: pointer;
        position: relative;
        z-index: 1;
        /* Smooth hover transition */
        transition: background 0.25s ease;
    }

    /* For scrollable tabs (>4), fixed minimum width so last tab gets cut off */
    .scrollable .settings-tab {
        flex: 0 0 auto;
        min-width: calc(100% / 4.3);
    }

    /* Hover on inactive: gradient at 50% opacity with smooth transition */
    .settings-tab:not(.active):hover {
        background: linear-gradient(
            135deg,
            color-mix(in srgb, var(--gradient-start) 50%, transparent),
            color-mix(in srgb, var(--gradient-end) 50%, transparent)
        );
    }

    .settings-tab:focus-visible {
        outline: 0.125rem solid var(--color-primary-start);
        outline-offset: 0.125rem;
    }

    /* ── Tab icon ────────────────────────────────────────────────── */
    .tab-icon {
        width: 1.15rem;
        height: 1.15rem;
        flex-shrink: 0;
        /* Use the CSS custom property passed via style="" */
        -webkit-mask-image: var(--tab-icon-url);
        -webkit-mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-image: var(--tab-icon-url);
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
        background-color: var(--color-grey-30);
        transition: background-color 0.25s ease;
    }

    /* Hover on inactive tab: lighten icon (in sync with pill opacity) */
    .settings-tab:not(.active):hover .tab-icon {
        background-color: #ffffff;
    }

    /* Active tab icon: white */
    .tab-icon.active {
        background-color: #ffffff;
    }

    /* ── Counter badge ───────────────────────────────────────────── */
    /*
     * Positioned at the BOTTOM-RIGHT next to the icon.
     * Must be round: equal width/height, border-radius 50%.
     * White text on red background.
    */
    .tab-count {
        position: absolute;
        /* Bottom-right next to the icon */
        bottom: 0.125rem;
        right: 0.125rem;
        /* Perfect circle */
        width: 1.125rem;
        height: 1.125rem;
        border-radius: 50%;
        background: var(--color-error, #FF553B);
        color: #ffffff;
        font-family: 'Lexend Deca Variable', sans-serif;
        font-weight: 700;
        font-size: 0.625rem;
        /* Center the number */
        display: flex;
        align-items: center;
        justify-content: center;
        line-height: 1;
        box-shadow: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.2);
        z-index: 2;
    }
</style>
