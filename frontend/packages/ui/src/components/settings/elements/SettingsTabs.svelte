<!--
    SettingsTabs — Tab bar with icons and optional counters.

    Matches Figma "Tabs" element:
    Pill-shaped tabs inside a rounded container. Active tab shows
    gradient background, inactive tabs show grey icons. Optional
    counter badges (red circle with white number).

    Rules from Figma:
    - 4 or fewer tabs: share full width equally
    - More than 4 tabs: horizontal scroll, last tab visually cut off
    - Background gradient: app color gradient or OpenMates default

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    /** Individual tab definition */
    interface TabItem {
        /** Unique identifier for the tab */
        id: string;
        /** CSS icon class name (used as mask-image via @openmates/ui/static/icons/{icon}.svg) */
        icon: string;
        /** Optional text label */
        label?: string;
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
            style="--tab-count: {tabs.length};"
        >
            {#each tabs as tab}
                <button
                    class="settings-tab"
                    class:active={activeTab === tab.id}
                    style={activeTab === tab.id ? `background: linear-gradient(135deg, ${effectiveGradientStart}, ${effectiveGradientEnd});` : ''}
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

                    {#if tab.label}
                        <span class="tab-label" class:active={activeTab === tab.id}>{tab.label}</span>
                    {/if}

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
        border-radius: 0.75rem;
        padding-top: 1.25rem;
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
        gap: 0;
        padding: 0 0.75rem;
        min-width: 100%;
    }

    .settings-tab {
        flex: 1 0 0;
        min-width: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.375rem;
        padding: 0.5rem 0.75rem;
        border: none;
        border-radius: 3.25rem;
        background: var(--color-grey-0);
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.1);
        cursor: pointer;
        transition: all 0.2s ease;
        position: relative;
        height: 2.3125rem;
    }

    /* For scrollable tabs (>4), give them a fixed minimum width so last tab gets cut off */
    .scrollable .settings-tab {
        flex: 0 0 auto;
        min-width: calc(100% / 4.3);
    }

    .settings-tab:hover:not(.active) {
        background: var(--color-grey-10);
    }

    .settings-tab:focus-visible {
        outline: 0.125rem solid var(--color-primary-start);
        outline-offset: 0.125rem;
    }

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
        background-color: var(--color-grey-50);
        transition: background-color 0.2s ease;
    }

    .tab-icon.active {
        background-color: var(--color-grey-0);
    }

    .tab-label {
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-weight: 600;
        font-size: 0.75rem;
        line-height: 1.25;
        color: var(--color-grey-50);
        white-space: nowrap;
        transition: color 0.2s ease;
    }

    .tab-label.active {
        color: var(--color-grey-0);
    }

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
