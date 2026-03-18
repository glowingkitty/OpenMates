<!--
    SettingsTabs — Tab bar with icons, animated sliding pill, and optional counters.

    Matches Figma "Tabs" element:
    - Icon-only tabs (no text labels)
    - Active tab: gradient pill slides left/right with transition
    - Inactive icons: var(--color-grey-30)
    - Active icon: white (#fff)
    - Hover on inactive: gradient at 0.5 opacity visible behind icon
    - Optional counter badges (red circle with white number)

    Rules:
    - 4 or fewer tabs: share full width equally
    - More than 4 tabs: horizontal scroll, last tab visually cut off
    - All global button styles from buttons.css are reset

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    /** Individual tab definition */
    interface TabItem {
        /** Unique identifier for the tab */
        id: string;
        /** Icon name (maps to @openmates/ui/static/icons/{icon}.svg) */
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
    <div class="settings-tabs-container" class:scrollable={isScrollable}>
        <div
            class="settings-tabs-track"
            role="tablist"
            style="--tab-count: {tabs.length}; --active-index: {activeIndex}; --gradient-start: {effectiveGradientStart}; --gradient-end: {effectiveGradientEnd};"
        >
            <!-- Animated gradient pill (positioned behind tabs via CSS) -->
            <div class="settings-tabs-pill" aria-hidden="true"></div>

            {#each tabs as tab, i}
                <button
                    class="settings-tab"
                    class:active={activeTab === tab.id}
                    role="tab"
                    aria-selected={activeTab === tab.id}
                    aria-controls={`tabpanel-${tab.id}`}
                    onclick={() => selectTab(tab.id)}
                    onkeydown={(e) => handleKeydown(e, tab.id)}
                >
                    <div
                        class="tab-icon"
                        class:active={activeTab === tab.id}
                        style="-webkit-mask-image: url('@openmates/ui/static/icons/{tab.icon}.svg'); mask-image: url('@openmates/ui/static/icons/{tab.icon}.svg');"
                    ></div>

                    {#if tab.count !== undefined && tab.count > 0}
                        <span class="tab-count">{tab.count}</span>
                    {/if}
                </button>
            {/each}
        </div>
    </div>
</div>

<style>
    .settings-tabs-wrapper {
        padding: 0 0.625rem;
    }

    .settings-tabs-container {
        background: var(--color-grey-0);
        border-radius: 3.25rem;
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.1);
        overflow: hidden;
    }

    .settings-tabs-container.scrollable {
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
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
        height: 2.3125rem;
        border-radius: 3.25rem;
        background: transparent;
        cursor: pointer;
        position: relative;
        z-index: 1;
        transition: background 0.2s ease;
    }

    /* For scrollable tabs (>4), fixed minimum width so last tab gets cut off */
    .scrollable .settings-tab {
        flex: 0 0 auto;
        min-width: calc(100% / 4.3);
    }

    /* Hover on inactive: show gradient at 50% opacity */
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
        -webkit-mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
        background-color: var(--color-grey-30);
        transition: background-color 0.2s ease;
    }

    /* Hover on inactive tab: lighten icon */
    .settings-tab:not(.active):hover .tab-icon {
        background-color: var(--color-grey-0);
    }

    /* Active tab icon: white */
    .tab-icon.active {
        background-color: var(--color-grey-0);
    }

    /* ── Counter badge ───────────────────────────────────────────── */
    .tab-count {
        position: absolute;
        top: -0.25rem;
        right: -0.125rem;
        min-width: 1.3125rem;
        height: 1.3125rem;
        padding: 0 0.25rem;
        border-radius: 50%;
        background: var(--color-error, #FF553B);
        color: var(--color-grey-0);
        font-family: 'Lexend Deca Variable', sans-serif;
        font-weight: 700;
        font-size: 0.75rem;
        line-height: 1.3125rem;
        text-align: center;
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.1);
    }
</style>
