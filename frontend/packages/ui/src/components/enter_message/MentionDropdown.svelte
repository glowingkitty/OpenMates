<!-- frontend/packages/ui/src/components/enter_message/MentionDropdown.svelte -->
<!--
    Dropdown component for @ mention autocomplete.
    Shows AI models, mates, app skills, focus modes, and settings/memories.
    Settings/memory categories can be expanded to show individual entries.
    
    Design based on Figma: https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=4407-53857
-->
<script lang="ts">
    import { fade } from 'svelte/transition';
    import { slide } from 'svelte/transition';
    import { text } from '@repo/ui';
    import {
        searchMentions,
        getSettingsMemoryEntryResults,
        type AnyMentionResult,
        type MentionType,
        type SettingsMemoryMentionResult,
        type SettingsMemoryEntryMentionResult,
    } from './services/mentionSearchService';
    import type { SkillMentionResult, FocusModeMentionResult } from './services/mentionSearchService';
    import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
    import { panelState } from '../../stores/panelStateStore';

    // --- Props ---
    interface Props {
        /** Whether the dropdown is visible */
        show?: boolean;
        /** Search query (text after @) */
        query?: string;
        /** Y position for the dropdown (top of input) */
        positionY?: number;
        /** Position direction: 'above' (default) or 'below' the input */
        positionDirection?: 'above' | 'below';
        /** Callback when a result is selected */
        onselect?: (result: AnyMentionResult) => void;
        /** Callback when dropdown is closed */
        onclose?: () => void;
    }

    let {
        show = $bindable(false),
        query = '',
        positionY = 0,
        positionDirection = 'above',
        onselect,
        onclose,
    }: Props = $props();

    // --- State ---
    let dropdownElement = $state<HTMLElement | null>(null);
    let selectedIndex = $state(0);
    let results = $state<AnyMentionResult[]>([]);
    
    // --- Expandable Category State ---
    // Tracks which settings/memory categories are expanded (by result.id)
    let expandedCategories = $state<Set<string>>(new Set());
    // Cache of loaded entries per category (by result.id)
    let categoryEntries = $state<Map<string, { entries: SettingsMemoryEntryMentionResult[]; totalCount: number; showAll: boolean }>>(new Map());

    // --- Computed ---
    let hasResults = $derived(results.length > 0);

    // --- Effects ---

    // Update results when query changes (no second arg = use search limit so settings/memories can appear)
    $effect(() => {
        results = searchMentions(query);
        selectedIndex = 0; // Reset selection when results change
        // Collapse all expanded categories when query changes
        expandedCategories = new Set();
        categoryEntries = new Map();
    });

    // Handle keyboard navigation
    function handleKeyDown(event: KeyboardEvent) {
        if (!show) return;

        // Build flat list of navigable items (results + expanded entries)
        const flatItems = buildFlatNavigableItems();

        switch (event.key) {
            case 'ArrowDown':
                event.preventDefault();
                if (flatItems.length > 0) {
                    selectedIndex = (selectedIndex + 1) % flatItems.length;
                }
                break;
            case 'ArrowUp':
                event.preventDefault();
                if (flatItems.length > 0) {
                    selectedIndex = (selectedIndex - 1 + flatItems.length) % flatItems.length;
                }
                break;
            case 'Enter':
            case 'Tab':
                if (flatItems.length > 0 && selectedIndex < flatItems.length) {
                    event.preventDefault();
                    const selectedItem = flatItems[selectedIndex];
                    if (selectedItem) {
                        selectResult(selectedItem);
                    }
                }
                break;
            case 'Escape':
                event.preventDefault();
                onclose?.();
                break;
        }
    }

    /**
     * Build a flat list of navigable items for keyboard navigation.
     * Includes top-level results and expanded entry items.
     */
    function buildFlatNavigableItems(): AnyMentionResult[] {
        const items: AnyMentionResult[] = [];
        for (const result of results) {
            items.push(result);
            // If this is an expanded settings_memory category, add its entries
            if (result.type === 'settings_memory' && expandedCategories.has(result.id)) {
                const data = categoryEntries.get(result.id);
                if (data) {
                    const entriesToShow = data.showAll ? data.entries : data.entries.slice(0, 5);
                    items.push(...entriesToShow);
                }
            }
        }
        return items;
    }

    // Add global keyboard listener when shown
    $effect(() => {
        if (show) {
            document.addEventListener('keydown', handleKeyDown, true);
            return () => {
                document.removeEventListener('keydown', handleKeyDown, true);
            };
        }
    });

    // --- Functions ---

    function selectResult(result: AnyMentionResult) {
        onselect?.(result);
    }

    function handleResultClick(result: AnyMentionResult, event: MouseEvent) {
        event.preventDefault();
        event.stopPropagation();
        selectResult(result);
    }

    /**
     * Prevent mousedown from causing editor blur.
     * When user clicks on the dropdown, we prevent the default mousedown
     * behavior which would otherwise blur the editor before the click is processed.
     */
    function handleMouseDown(event: MouseEvent) {
        event.preventDefault();
        event.stopPropagation();
    }

    function handleMouseEnter(index: number) {
        selectedIndex = index;
    }

    /**
     * Get the flat index for a given result, accounting for expanded entries.
     * Used to correctly highlight the selected item during mouse hover.
     */
    function getFlatIndex(resultIndex: number, entryIndex?: number): number {
        let flatIdx = 0;
        for (let i = 0; i < results.length; i++) {
            if (i === resultIndex && entryIndex === undefined) return flatIdx;
            flatIdx++;
            const result = results[i];
            if (result.type === 'settings_memory' && expandedCategories.has(result.id)) {
                const data = categoryEntries.get(result.id);
                if (data) {
                    const count = data.showAll ? data.entries.length : Math.min(5, data.entries.length);
                    if (i === resultIndex && entryIndex !== undefined) {
                        return flatIdx + entryIndex;
                    }
                    flatIdx += count;
                }
            }
        }
        return flatIdx;
    }

    /**
     * Toggle expansion of a settings/memory category.
     * Loads individual entries on first expansion.
     */
    function toggleCategoryExpand(result: SettingsMemoryMentionResult, event: MouseEvent) {
        event.preventDefault();
        event.stopPropagation();
        
        const newExpanded = new Set(expandedCategories);
        if (newExpanded.has(result.id)) {
            newExpanded.delete(result.id);
        } else {
            newExpanded.add(result.id);
            // Load entries if not cached
            if (!categoryEntries.has(result.id)) {
                const { entries, totalCount } = getSettingsMemoryEntryResults(
                    result.appId,
                    result.memoryCategoryId,
                    // Load enough entries for "show more" - get all of them but only show 5 initially
                    100,
                );
                const newEntries = new Map(categoryEntries);
                newEntries.set(result.id, { entries, totalCount, showAll: false });
                categoryEntries = newEntries;
            }
        }
        expandedCategories = newExpanded;
    }

    /**
     * Show all entries for a category (when "Show more" is clicked).
     */
    function handleShowMore(resultId: string, event: MouseEvent) {
        event.preventDefault();
        event.stopPropagation();
        const data = categoryEntries.get(resultId);
        if (data) {
            const newEntries = new Map(categoryEntries);
            newEntries.set(resultId, { ...data, showAll: true });
            categoryEntries = newEntries;
        }
    }

    /**
     * Get translated type label for a result.
     */
    function getTypeLabel(type: MentionType): string {
        if (type === 'settings_memory_entry') {
            return $text('enter_message.mention_dropdown.type_labels.settings_memory');
        }
        return $text(`enter_message.mention_dropdown.type_labels.${type}`);
    }

    /**
     * Get translated display name for a result.
     * Some results have translation keys, others have direct text.
     */
    function getDisplayName(result: AnyMentionResult): string {
        // For mates, resolve the translation key
        if (result.type === 'mate') {
            const translated = $text(result.displayName);
            return translated !== result.displayName ? translated : result.displayName.split('.').pop() || '';
        }
        // For skills, focus modes, and settings categories - resolve translation keys
        if (result.type === 'skill' || result.type === 'focus_mode' || result.type === 'settings_memory') {
            const translated = $text(result.displayName);
            return translated !== result.displayName ? translated : result.displayName.split('.').pop() || '';
        }
        // For individual entries, displayName is the entry title (not a translation key)
        if (result.type === 'settings_memory_entry') {
            return result.displayName;
        }
        return result.displayName;
    }

    /**
     * Get translated subtitle for a result.
     */
    function getSubtitle(result: AnyMentionResult): string {
        // For models, subtitle is provider name - use translation template
        if (result.type === 'model') {
            return $text('enter_message.mention_dropdown.from_provider').replace('{provider}', result.subtitle);
        }
        // For mates, use the mate description translation key
        if (result.type === 'mate') {
            return $text(`mate_descriptions.${result.id}`);
        }
        // For individual entries, subtitle is the entry subtitle value (e.g., "Expert")
        if (result.type === 'settings_memory_entry') {
            return result.subtitle || '';
        }
        // For skills, focus modes, settings - resolve translation keys
        if (result.subtitle) {
            return $text(result.subtitle);
        }
        return getTypeLabel(result.type);
    }

    /**
     * Get the settings deep link path for a result based on its type.
     */
    function getSettingsPath(result: AnyMentionResult): string {
        switch (result.type) {
            case 'model':
                return `app_store/ai/skill/ask/model/${result.id}`;
            case 'mate':
                return 'main';
            case 'skill': {
                const skillResult = result as SkillMentionResult;
                const skillId = result.id.split(':')[1] || result.id;
                return `app_store/${skillResult.appId}/skill/${skillId}`;
            }
            case 'focus_mode': {
                const focusResult = result as FocusModeMentionResult;
                const focusModeId = result.id.split(':')[1] || result.id;
                return `app_store/${focusResult.appId}/focus/${focusModeId}`;
            }
            case 'settings_memory': {
                const memoryResult = result as SettingsMemoryMentionResult;
                const memoryId = result.id.split(':')[1] || result.id;
                return `app_store/${memoryResult.appId}/settings_memories/${memoryId}`;
            }
            case 'settings_memory_entry': {
                const entryResult = result as SettingsMemoryEntryMentionResult;
                return `app_store/${entryResult.appId}/settings_memories/${entryResult.memoryCategoryId}`;
            }
            default:
                return 'main';
        }
    }

    /**
     * Navigate to settings for a specific mention result.
     */
    function handleSettingsNavigation(result: AnyMentionResult, event: MouseEvent) {
        event.preventDefault();
        event.stopPropagation();
        const path = getSettingsPath(result);
        settingsDeepLink.set(path);
        panelState.openSettings();
        onclose?.();
    }

    /**
     * Navigate to the main settings page (header settings button).
     */
    function handleHeaderSettingsClick(event: MouseEvent) {
        event.preventDefault();
        event.stopPropagation();
        settingsDeepLink.set('main');
        panelState.openSettings();
        onclose?.();
    }
</script>

{#if show && hasResults}
    <div
        bind:this={dropdownElement}
        class="mention-dropdown"
        class:position-below={positionDirection === 'below'}
        style="{positionDirection === 'below' ? 'top' : 'bottom'}: {positionY}px;"
        transition:fade={{ duration: 150 }}
        role="listbox"
        tabindex="-1"
        aria-label="Mention suggestions"
        onmousedown={handleMouseDown}
    >
        <!-- Header text -->
        <div class="mention-dropdown-header">
            <span class="header-text">
                {$text('enter_message.mention_dropdown.header')}
            </span>
            <button 
                class="settings-button" 
                aria-label={$text('settings.settings')}
                onclick={handleHeaderSettingsClick}
            >
                <span class="clickable-icon icon_settings"></span>
            </button>
        </div>

        <!-- Results list -->
        <div class="mention-results">
            {#each results as result, index (result.id)}
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <div
                    class="mention-result"
                    class:selected={getFlatIndex(index) === selectedIndex}
                    role="option"
                    tabindex="-1"
                    aria-selected={getFlatIndex(index) === selectedIndex}
                    onclick={(e) => handleResultClick(result, e)}
                    onmouseenter={() => { selectedIndex = getFlatIndex(index); }}
                >
                    <!-- Icon -->
                    <div class="result-icon">
                        {#if result.type === 'model'}
                            <!-- Provider logo - icon is already a resolved URL from getProviderIconUrl() -->
                            <img 
                                src={result.icon} 
                                alt={result.subtitle}
                                class="provider-logo"
                            />
                        {:else if result.type === 'mate'}
                            <!-- Mate profile -->
                            <div class="mate-profile mate-profile-small {result.iconStyle}"></div>
                        {:else}
                            <!-- App skill/focus/memory icon -->
                            <div 
                                class="app-icon"
                                style={result.iconStyle ? `background: ${result.iconStyle};` : ''}
                            >
                                {#if result.type === 'skill'}
                                    <span class="mention-icon icon_search"></span>
                                {:else if result.type === 'focus_mode'}
                                    <span class="mention-icon icon_filter"></span>
                                {:else}
                                    <span class="mention-icon icon_heart"></span>
                                {/if}
                            </div>
                        {/if}
                    </div>

                    <!-- Text content -->
                    <div class="result-content">
                        <span class="result-name">{getDisplayName(result)}</span>
                        <span class="result-subtitle">{getSubtitle(result)}</span>
                    </div>

                    <!-- Expand button for settings/memory categories with entries -->
                    {#if result.type === 'settings_memory'}
                        {@const memResult = result as SettingsMemoryMentionResult}
                        <button
                            class="expand-button"
                            class:expanded={expandedCategories.has(result.id)}
                            tabindex="-1"
                            aria-label={expandedCategories.has(result.id) ? 'Collapse entries' : 'Expand entries'}
                            onclick={(e) => toggleCategoryExpand(memResult, e)}
                        >
                            <span class="expand-icon">
                                {#if expandedCategories.has(result.id)}▾{:else}▸{/if}
                            </span>
                            <span class="entry-count">{memResult.entryCount}</span>
                        </button>
                    {/if}

                    <!-- Settings icon for each row -->
                    <button 
                        class="row-settings-button" 
                        tabindex="-1"
                        aria-label={$text('settings.settings')}
                        onclick={(e) => handleSettingsNavigation(result, e)}
                    >
                        <span class="clickable-icon icon_settings"></span>
                    </button>
                </div>

                <!-- Expanded entries for settings/memory categories -->
                {#if result.type === 'settings_memory' && expandedCategories.has(result.id)}
                    {@const data = categoryEntries.get(result.id)}
                    {#if data}
                        {@const entriesToShow = data.showAll ? data.entries : data.entries.slice(0, 5)}
                        <div class="expanded-entries" transition:slide={{ duration: 150 }}>
                            {#each entriesToShow as entry, entryIdx (entry.id)}
                                <!-- svelte-ignore a11y_click_events_have_key_events -->
                                <div
                                    class="mention-result entry-item"
                                    class:selected={getFlatIndex(index, entryIdx) === selectedIndex}
                                    role="option"
                                    tabindex="-1"
                                    aria-selected={getFlatIndex(index, entryIdx) === selectedIndex}
                                    onclick={(e) => handleResultClick(entry, e)}
                                    onmouseenter={() => { selectedIndex = getFlatIndex(index, entryIdx); }}
                                >
                                    <!-- Entry icon (indented) -->
                                    <div class="result-icon entry-icon">
                                        <div 
                                            class="app-icon app-icon-small"
                                            style={entry.iconStyle ? `background: ${entry.iconStyle};` : ''}
                                        >
                                            <span class="mention-icon mention-icon-small icon_heart"></span>
                                        </div>
                                    </div>

                                    <!-- Entry content -->
                                    <div class="result-content">
                                        <span class="result-name entry-name">{entry.entryTitle}</span>
                                        {#if entry.entrySubtitle}
                                            <span class="result-subtitle">{entry.entrySubtitle}</span>
                                        {/if}
                                    </div>
                                </div>
                            {/each}

                            <!-- Show more button -->
                            {#if !data.showAll && data.totalCount > 5}
                                <!-- svelte-ignore a11y_click_events_have_key_events -->
                                <div
                                    class="show-more-button"
                                    role="button"
                                    tabindex="-1"
                                    onclick={(e) => handleShowMore(result.id, e)}
                                >
                                    {$text('enter_message.mention_dropdown.show_more').replace('{count}', String(data.totalCount - 5))}
                                </div>
                            {/if}
                        </div>
                    {/if}
                {/if}
            {/each}
        </div>

        <!-- Footer hint -->
        {#if query}
            <div class="mention-dropdown-footer">
                {$text('enter_message.mention_dropdown.autocomplete_hint')}
            </div>
        {/if}
    </div>
{/if}

<style>
    .mention-dropdown {
        position: absolute;
        z-index: 1000;
        background: var(--color-grey-blue);
        border-radius: 16px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
        min-width: 380px;
        max-width: 450px;
        max-height: 420px;
        overflow-y: auto;
        overflow-x: hidden;
        font-family: var(--font-family-primary);
        /* Center horizontally above the input field */
        left: 50% !important;
        transform: translateX(-50%);
    }
    
    /* When positioned below the input (e.g., in notification view) */
    .mention-dropdown.position-below {
        /* Shadow should appear above instead of below */
        box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.15);
    }

    .mention-dropdown-header {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        padding: 16px 16px 12px;
        border-bottom: 1px solid var(--color-grey-20);
    }

    .header-text {
        flex: 1;
        font-size: 16px;
        line-height: 1.4;
        color: var(--color-font-tertiary);
    }

    .settings-button {
        flex-shrink: 0;
        width: 32px;
        height: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: transparent;
        border: none;
        border-radius: 8px;
        cursor: pointer;
        color: var(--color-grey-60);
        transition: background-color 0.15s ease;
    }

    .settings-button:hover {
        background: var(--color-grey-15);
        color: var(--color-grey-80);
    }

    .mention-results {
        padding: 8px 0;
    }

    .mention-result {
        display: flex;
        align-items: center;
        gap: 12px;
        width: 100%;
        padding: 10px 16px;
        background: transparent;
        border: none;
        cursor: pointer;
        text-align: left;
        transition: background-color 0.1s ease;
    }

    .mention-result:hover,
    .mention-result.selected {
        background: var(--color-grey-15);
    }

    /* Indented entry items within expanded categories */
    .mention-result.entry-item {
        padding-left: 32px;
    }

    .result-icon {
        flex-shrink: 0;
        width: 40px;
        height: 40px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .result-icon.entry-icon {
        width: 32px;
        height: 32px;
    }

    .provider-logo {
        width: 36px;
        height: 36px;
        border-radius: 8px;
        object-fit: contain;
        background: var(--color-grey-10);
        padding: 4px;
    }

    .mate-profile.mate-profile-small {
        width: 36px;
        height: 36px;
        margin: 0;
    }

    .app-icon {
        width: 36px;
        height: 36px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--color-grey-40);
    }

    .app-icon.app-icon-small {
        width: 28px;
        height: 28px;
        border-radius: 8px;
    }

    /* Icon styles for skill/focus/memory icons inside app-icon */
    .mention-icon {
        width: 18px;
        height: 18px;
        display: block;
        background-color: white;
        -webkit-mask-position: center;
        mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
        -webkit-mask-size: contain;
        mask-size: contain;
    }

    .mention-icon.mention-icon-small {
        width: 14px;
        height: 14px;
    }

    .mention-icon.icon_search {
        -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
        mask-image: url('@openmates/ui/static/icons/search.svg');
    }

    .mention-icon.icon_filter {
        -webkit-mask-image: url('@openmates/ui/static/icons/filter.svg');
        mask-image: url('@openmates/ui/static/icons/filter.svg');
    }

    .mention-icon.icon_heart {
        -webkit-mask-image: url('@openmates/ui/static/icons/heart.svg');
        mask-image: url('@openmates/ui/static/icons/heart.svg');
    }

    .result-content {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .result-name {
        font-size: 16px;
        font-weight: 500;
        color: var(--color-primary-start);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .entry-name {
        font-size: 15px;
        font-weight: 400;
    }

    .result-subtitle {
        font-size: 16px;
        color: var(--color-font-tertiary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    /* Expand button for settings/memory categories */
    .expand-button {
        flex-shrink: 0;
        display: flex;
        align-items: center;
        gap: 4px;
        padding: 4px 8px;
        background: var(--color-grey-15);
        border: none;
        border-radius: 6px;
        cursor: pointer;
        color: var(--color-grey-60);
        font-size: 13px;
        font-family: var(--font-family-primary);
        transition: background-color 0.15s ease, color 0.15s ease;
    }

    .expand-button:hover {
        background: var(--color-grey-25);
        color: var(--color-grey-80);
    }

    .expand-button.expanded {
        background: var(--color-grey-20);
        color: var(--color-grey-80);
    }

    .expand-icon {
        font-size: 12px;
        line-height: 1;
    }

    .entry-count {
        font-variant-numeric: tabular-nums;
    }

    /* Expanded entries container */
    .expanded-entries {
        border-left: 2px solid var(--color-grey-20);
        margin-left: 34px;
        margin-bottom: 4px;
    }

    /* Show more button */
    .show-more-button {
        padding: 8px 16px 8px 32px;
        font-size: 14px;
        color: var(--color-primary-start);
        cursor: pointer;
        transition: background-color 0.1s ease;
        font-weight: 500;
    }

    .show-more-button:hover {
        background: var(--color-grey-15);
    }

    .row-settings-button {
        flex-shrink: 0;
        width: 28px;
        height: 28px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: transparent;
        border: none;
        border-radius: 6px;
        cursor: pointer;
        color: var(--color-grey-50);
        opacity: 0;
        padding: 0;
        font: inherit;
        transition: opacity 0.15s ease, background-color 0.15s ease;
    }

    .mention-result:hover .row-settings-button,
    .mention-result.selected .row-settings-button {
        opacity: 1;
    }

    .row-settings-button:hover {
        background: var(--color-grey-25);
        color: var(--color-grey-80);
    }

    .mention-dropdown-footer {
        padding: 10px 16px;
        font-size: 16px;
        color: var(--color-font-secondary);
        text-align: center;
        border-top: 1px solid var(--color-grey-15);
    }

    /* Dark mode support */
    :global(.dark) .mention-dropdown {
        background: var(--color-grey-10);
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
    }

    :global(.dark) .mention-dropdown-header {
        border-bottom-color: var(--color-grey-25);
    }

    :global(.dark) .mention-result:hover,
    :global(.dark) .mention-result.selected {
        background: var(--color-grey-20);
    }

    :global(.dark) .provider-logo {
        background: var(--color-grey-20);
    }

    :global(.dark) .expanded-entries {
        border-left-color: var(--color-grey-25);
    }

    :global(.dark) .expand-button {
        background: var(--color-grey-20);
    }

    :global(.dark) .expand-button:hover {
        background: var(--color-grey-30);
    }

    :global(.dark) .expand-button.expanded {
        background: var(--color-grey-25);
    }
</style>
