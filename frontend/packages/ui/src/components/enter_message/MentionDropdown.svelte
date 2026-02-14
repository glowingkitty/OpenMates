<!-- frontend/packages/ui/src/components/enter_message/MentionDropdown.svelte -->
<!--
    Dropdown component for @ mention autocomplete.
    Shows AI models, mates, app skills, focus modes, and settings/memories.
    
    Design based on Figma: https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=4407-53857
-->
<script lang="ts">
    import { fade } from 'svelte/transition';
    import { text } from '@repo/ui';
    import {
        searchMentions,
        type AnyMentionResult,
        type MentionType
    } from './services/mentionSearchService';
    import type { SkillMentionResult, FocusModeMentionResult, SettingsMemoryMentionResult } from './services/mentionSearchService';
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

    // --- Computed ---
    let hasResults = $derived(results.length > 0);

    // --- Effects ---

    // Update results when query changes
    $effect(() => {
        results = searchMentions(query, 4);
        selectedIndex = 0; // Reset selection when results change
    });

    // Handle keyboard navigation
    function handleKeyDown(event: KeyboardEvent) {
        if (!show) return;

        switch (event.key) {
            case 'ArrowDown':
                event.preventDefault();
                selectedIndex = (selectedIndex + 1) % results.length;
                break;
            case 'ArrowUp':
                event.preventDefault();
                selectedIndex = (selectedIndex - 1 + results.length) % results.length;
                break;
            case 'Enter':
            case 'Tab':
                if (hasResults) {
                    event.preventDefault();
                    selectResult(results[selectedIndex]);
                }
                break;
            case 'Escape':
                event.preventDefault();
                onclose?.();
                break;
        }
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
     * Get translated type label for a result.
     */
    function getTypeLabel(type: MentionType): string {
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
        // For skills, focus modes, and settings - resolve translation keys
        if (result.type === 'skill' || result.type === 'focus_mode' || result.type === 'settings_memory') {
            const translated = $text(result.displayName);
            return translated !== result.displayName ? translated : result.displayName.split('.').pop() || '';
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
        // For skills, focus modes, settings - resolve translation keys
        if (result.subtitle) {
            return $text(result.subtitle);
        }
        return getTypeLabel(result.type);
    }

    /**
     * Get the settings deep link path for a result based on its type.
     * Returns the path to pass to settingsDeepLink.set() for programmatic navigation.
     * Uses the same deep link format as the rest of the codebase (e.g., ChatMessage.svelte).
     *
     * - Models: app_store/ai/skill/ask/model/{model_id}
     * - Mates: main (no mate-specific settings page yet)
     * - Skills: app_store/{appId}/skill/{skillId}
     * - Focus modes: app_store/{appId}/focus/{focusModeId}
     * - Settings/memories: app_store/{appId}/settings_memories/{memoryId}
     */
    function getSettingsPath(result: AnyMentionResult): string {
        switch (result.type) {
            case 'model':
                // Deep link to AI model detail page in the AI Ask skill settings
                return `app_store/ai/skill/ask/model/${result.id}`;
            case 'mate':
                // No mate-specific settings page yet — open main settings
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
            default:
                return 'main';
        }
    }

    /**
     * Navigate to settings for a specific mention result.
     * Uses programmatic navigation (settingsDeepLink + panelState) instead of hash links
     * to avoid the deep link handler's hyphen-to-underscore normalization which would
     * corrupt model IDs like "claude-opus-4-6".
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
                    class:selected={index === selectedIndex}
                    role="option"
                    tabindex="-1"
                    aria-selected={index === selectedIndex}
                    onclick={(e) => handleResultClick(result, e)}
                    onmouseenter={() => handleMouseEnter(index)}
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

                    <!-- Settings icon for each row — navigates to the model/skill/focus/memory settings -->
                    <button 
                        class="row-settings-button" 
                        tabindex="-1"
                        aria-label={$text('settings.settings')}
                        onclick={(e) => handleSettingsNavigation(result, e)}
                    >
                        <span class="clickable-icon icon_settings"></span>
                    </button>
                </div>
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
        overflow: hidden;
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

    .result-icon {
        flex-shrink: 0;
        width: 40px;
        height: 40px;
        display: flex;
        align-items: center;
        justify-content: center;
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

    .result-subtitle {
        font-size: 16px;
        color: var(--color-font-tertiary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
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
</style>
