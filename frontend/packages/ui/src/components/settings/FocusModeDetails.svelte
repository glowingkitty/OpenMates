<!-- frontend/packages/ui/src/components/settings/FocusModeDetails.svelte
     Component for displaying details of a specific focus mode, including description and instructions.
     
     Layout matches the skills detail page (SkillDetails.svelte):
     - The app icon + focus mode name header is rendered by Settings.svelte (submenu-info block),
       not here — this component only renders the body content below the header.
     - Description section: plain text description.
     - Instructions section: bullet-point summary of what the focus mode does (from
       process_translation_key), with a "Show full system prompt" button to reveal the raw prompt.
     
     This component is used for the app_store/{app_id}/focus/{focus_mode_id} nested route.
     
     **Backend Implementation**:
     - Data source: Static appsMetadata.ts (generated at build time)
     - Store: frontend/packages/ui/src/stores/appSkillsStore.ts
     - Types: frontend/packages/ui/src/types/apps.ts
-->

<script lang="ts">
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import SettingsItem from '../SettingsItem.svelte';
    import type { AppMetadata, FocusModeMetadata } from '../../types/apps';
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { setAppStoreNavList, clearAppStoreNav } from '../../stores/appStoreNavigationStore';
    import { onDestroy } from 'svelte';
    import { pendingMentionStore } from '../../stores/pendingMentionStore';
    import { panelState } from '../../stores/panelStateStore';
    
    // Create event dispatcher for navigation
    const dispatch = createEventDispatcher();
    
    interface Props {
        appId: string;
        focusModeId: string;
    }
    
    let { appId, focusModeId }: Props = $props();
    
    // Get store state reactively (Svelte 5)
    let storeState = $state(appSkillsStore.getState());
    
    // Get app and focus mode metadata from store
    let app = $derived<AppMetadata | undefined>(storeState.apps[appId]);
    let focusMode = $derived<FocusModeMetadata | undefined>(
        app?.focus_modes.find(f => f.id === focusModeId)
    );

    /**
     * Build the @mention display name for this focus mode.
     * Matches the format used in mentionSearchService: "AppName-FocusModeName"
     * e.g., appId="jobs", focusModeId="career_insights" → "Jobs-Career-Insights"
     */
    function capitalizeHyphenated(str: string): string {
        return str.split('-').map((w: string) => w.charAt(0).toUpperCase() + w.slice(1)).join('-');
    }

    let focusMentionDisplayName = $derived(
        `${capitalizeHyphenated(appId)}-${capitalizeHyphenated(focusModeId.replace(/_/g, '-'))}`
    );

    /**
     * Get "How to use" example instructions for this focus mode.
     * Derives translation keys from the focus mode's name_translation_key by appending .how_to_use.{1|2|3}.
     * Only includes examples where a translation exists (key doesn't resolve to itself).
     */
    let howToUseExamples = $derived.by(() => {
        if (!focusMode?.name_translation_key) return [];
        const examples: string[] = [];
        for (let i = 1; i <= 3; i++) {
            const key = `${focusMode.name_translation_key}.how_to_use.${i}`;
            const translated = $text(key);
            if (translated && translated !== key) {
                examples.push(translated);
            }
        }
        return examples;
    });

    /**
     * Parse **word** markdown syntax into HTML with highlighted spans.
     * Words wrapped in double asterisks (**word**) are rendered as
     * <span class="highlight-word"> elements styled with the app's gradient color.
     */
    function parseHighlightedText(rawText: string): string {
        const escaped = rawText
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
        return escaped.replace(/\*\*(.+?)\*\*/g, '<span class="highlight-word">$1</span>');
    }
    
    /**
     * System prompt text shown when this focus mode is activated.
     * Either the literal system_prompt or the resolved system_prompt_translation_key.
     */
    let focusModeSystemPrompt = $derived(
        focusMode?.system_prompt
            ? focusMode.system_prompt
            : focusMode?.system_prompt_translation_key
                ? $text(focusMode.system_prompt_translation_key)
                : ''
    );

    /**
     * Bullet-point process summary.
     * Resolved from process_translation_key — each line starting with "- " is a bullet.
     * Falls back to empty string if not defined.
     */
    let focusModeProcess = $derived(
        focusMode?.process_translation_key
            ? $text(focusMode.process_translation_key)
            : ''
    );

    /**
     * Parse the process text into individual bullet point strings.
     * Filters lines that start with "- " and strips the leading dash.
     */
    let processBullets = $derived(
        focusModeProcess
            ? focusModeProcess
                .split('\n')
                .map((line: string) => line.trim())
                .filter((line: string) => line.startsWith('- '))
                .map((line: string) => line.slice(2).trim())
            : []
    );

    /**
     * Whether the instructions section has any content to show:
     * either process bullets or a system prompt.
     */
    let hasInstructions = $derived(processBullets.length > 0 || focusModeSystemPrompt.length > 0);

    /**
     * Whether the full system prompt is currently expanded.
     */
    let showFullPrompt = $state(false);

    /**
     * Get icon name from icon_image filename.
     * Maps icon_image like "ai.svg" to icon name "ai" for the Icon component.
     * Also handles special cases:
     * - "coding.svg" -> "code" (since the app ID is "code" but icon file is coding.svg)
     */
    function getIconName(iconImage: string | undefined): string {
        if (!iconImage) return appId;
        let iconName = iconImage.replace(/\.svg$/, '');
        // Handle special case: coding.svg -> code (since the app ID is "code" but icon file is coding.svg)
        // This ensures the correct CSS variable --color-app-code is used instead of --color-app-coding
        if (iconName === 'coding') {
            iconName = 'code';
        }
        // Handle special case: heart.svg -> health (since the app ID is "health" but icon file is heart.svg)
        // This ensures the correct CSS variable --color-app-health is used instead of --color-app-heart
        if (iconName === 'heart') {
            iconName = 'health';
        }
        return iconName;
    }
    
    /**
     * Register sibling focus modes for prev/next navigation in AppDetailsHeader.
     * Re-runs whenever app or focusModeId changes (deep link changes the current focus mode).
     * Clears the navigation state when this component is destroyed.
     */
    $effect(() => {
        const focusModes = app?.focus_modes ?? [];
        if (focusModes.length > 1) {
            setAppStoreNavList(
                focusModes.map(f => ({
                    id: f.id,
                    name: f.name_translation_key ? $text(f.name_translation_key) : f.id,
                })),
                focusModeId,
                (targetFocusModeId) => {
                    dispatch('openSettings', {
                        settingsPath: `app_store/${appId}/focus/${targetFocusModeId}`,
                        direction: 'forward',
                        icon: getIconName(app?.icon_image),
                        title: app?.name_translation_key ? $text(app.name_translation_key) : appId,
                    });
                },
            );
        } else {
            // Single focus mode — no siblings to navigate to
            clearAppStoreNav();
        }
    });

    onDestroy(() => {
        clearAppStoreNav();
    });

    function goBack() {
        dispatch('openSettings', {
            settingsPath: `app_store/${appId}`,
            direction: 'back',
            icon: getIconName(app?.icon_image),
            title: app?.name_translation_key ? $text(app.name_translation_key) : appId
        });
    }

    /**
     * Insert the focus mode @mention into the message input and close settings.
     * Uses pendingMentionStore with "@focus:{appId}:{focusModeId}" syntax.
     * MessageInput.svelte watches this store and renders it as a styled mention chip.
     */
    function insertFocusMention() {
        pendingMentionStore.set(`@focus:${appId}:${focusModeId}`);
        panelState.closeSettings();
    }
</script>

<div class="focus-mode-details">
    {#if !app || !focusMode}
        <div class="error">
            <p>{$text('settings.app_store.focus_mode_not_found')}</p>
            <button class="back-button" onclick={goBack}>← {$text('settings.app_store.back_to_app')}</button>
        </div>
    {:else}
        <!-- How to use section: scrollable example prompts, only shown if translations exist -->
        {#if howToUseExamples.length > 0}
            <div class="section how-to-use-section">
                <SettingsItem
                    type="heading"
                    icon="skill"
                    title={$text('settings.app_store.skills.how_to_use')}
                />
                <!-- "Just ask your mates something like:" prefix -->
                <p class="how-to-use-prefix">{$text('settings.app_store.focus_modes.how_to_use_prefix')}</p>
                <div class="how-to-use-scroll-container">
                    <div class="how-to-use-scroll">
                        {#each howToUseExamples as example}
                            <div
                                class="how-to-use-card"
                                style="--highlight-color: var(--color-app-{appId}-start, var(--color-primary-start))"
                            >
                                <!-- Opening quote — top-right corner -->
                                <svg class="quote-icon quote-open" width="20" height="20" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                                    <path d="M15 3a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.717-3.35 3 3 0 012.259-2.47C11.952 37.416 15 33.606 15 26.998v-3H6a6 6 0 01-5.985-5.549L0 17.998V9A5.999 5.999 0 016 3h9zm27 0a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.716-3.35 2.998 2.998 0 012.258-2.47C38.952 37.416 42 33.606 42 26.998v-3h-9a6 6 0 01-5.985-5.549l-.015-.45V9A5.999 5.999 0 0133 3h9z" fill="currentColor"/>
                                </svg>
                                <!-- How-to-use text with **word** highlight support -->
                                <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                                <p class="how-to-use-text">{@html parseHighlightedText(example)}</p>
                                <!-- Closing quote — bottom-left corner (flipped 180°) -->
                                <svg class="quote-icon quote-close" width="20" height="20" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                                    <path d="M15 3a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.716-3.35 2.998 2.998 0 012.258-2.47C38.952 37.416 42 33.606 42 26.998v-3h-9a6 6 0 01-5.985-5.549l-.015-.45V9A5.999 5.999 0 0133 3h9z" fill="currentColor"/>
                                </svg>
                            </div>
                        {/each}
                    </div>
                </div>
                <!-- "Or mention @FocusModeName in your message..." footer -->
                <!-- Clicking the @mention inserts it into the message input (same as "Chat with this mate") -->
                <p class="how-to-use-mention">
                    {$text('settings.app_store.focus_modes.how_to_use_mention').split('{focusname}')[0]}<button type="button" class="mention-name" onclick={insertFocusMention}>@{focusMentionDisplayName}</button>{$text('settings.app_store.focus_modes.how_to_use_mention').split('{focusname}')[1]}
                </p>
            </div>
        {/if}

        <!-- Instructions section: bullet-point summary of what the focus mode does,
             plus a collapsible "Show full system prompt" button.
             Uses process_translation_key bullets when available; falls back to showing
             the system prompt directly if no process key is defined. -->
        <div class="section">
            <SettingsItem 
                type="heading"
                icon="systemprompt"
                title={$text('settings.app_store.focus_modes.system_prompt')}
            />
            {#if hasInstructions}
                <!-- "An overview, over what the focus mode will do:" label -->
                {#if processBullets.length > 0}
                    <p class="instructions-overview">{$text('settings.app_store.focus_modes.instructions_overview')}</p>
                {/if}

                <!-- Bullet-point summary from process_translation_key -->
                {#if processBullets.length > 0}
                    <ul class="process-bullets">
                        {#each processBullets as bullet}
                            <li class="process-bullet">{bullet}</li>
                        {/each}
                    </ul>
                {/if}

                <!-- System prompt: hidden by default, revealed on button click -->
                {#if focusModeSystemPrompt}
                    {#if showFullPrompt}
                        <div class="instructions-block">
                            <!-- Opening quote — top-left corner (absolute inside block) -->
                            <svg class="prompt-quote prompt-quote-open" width="20" height="20" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                                <path d="M15 3a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.717-3.35 3 3 0 012.259-2.47C11.952 37.416 15 33.606 15 26.998v-3H6a6 6 0 01-5.985-5.549L0 17.998V9A5.999 5.999 0 016 3h9zm27 0a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.716-3.35 2.998 2.998 0 012.258-2.47C38.952 37.416 42 33.606 42 26.998v-3h-9a6 6 0 01-5.985-5.549l-.015-.45V9A5.999 5.999 0 0133 3h9z" fill="currentColor"/>
                            </svg>
                            <p class="instructions-text">{focusModeSystemPrompt}</p>
                            <!-- Closing quote — bottom-right corner, rotated 180° -->
                            <svg class="prompt-quote prompt-quote-close" width="20" height="20" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                                <path d="M15 3a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.717-3.35 3 3 0 012.259-2.47C11.952 37.416 15 33.606 15 26.998v-3H6a6 6 0 01-5.985-5.549L0 17.998V9A5.999 5.999 0 016 3h9zm27 0a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.716-3.35 2.998 2.998 0 012.258-2.47C38.952 37.416 42 33.606 42 26.998v-3h-9a6 6 0 01-5.985-5.549l-.015-.45V9A5.999 5.999 0 0133 3h9z" fill="currentColor"/>
                            </svg>
                        </div>
                    {/if}
                    <!-- Toggle styled as a plain text link (same style as mention-name) -->
                    <button
                        type="button"
                        class="instructions-toggle"
                        onclick={() => (showFullPrompt = !showFullPrompt)}
                    >{showFullPrompt
                            ? $text('settings.app_store.focus_modes.show_less')
                            : $text('settings.app_store.focus_modes.show_full_instruction')}</button>
                {/if}
            {:else}
                <div class="no-instructions">
                    <p>{$text('settings.app_store.focus_modes.no_system_prompt')}</p>
                </div>
            {/if}
        </div>
    {/if}
</div>

<style>
    .focus-mode-details {
        padding: 14px;
        max-width: 1400px;
        margin: 0 auto;
    }

    .section {
        margin-top: 2rem;
    }

    /* How to use section */
    .how-to-use-section {
        margin-top: 1.5rem;
    }

    /* "Just ask your mates something like:" label above example cards */
    .how-to-use-prefix {
        margin: 0.5rem 0 0 0;
        padding: 0;
        font-size: 0.9rem;
        font-weight: 600;
        line-height: 1.5;
        color: var(--color-grey-100);
    }

    /* Horizontal scroll container for how-to-use example cards */
    .how-to-use-scroll-container {
        overflow-x: auto;
        overflow-y: hidden;
        padding-bottom: 0.5rem;
        margin-top: 0.75rem;
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
        transition: scrollbar-color 0.2s ease;
    }

    .how-to-use-scroll-container:hover {
        scrollbar-color: rgba(128, 128, 128, 0.5) transparent;
    }

    .how-to-use-scroll-container::-webkit-scrollbar {
        height: 8px;
    }

    .how-to-use-scroll-container::-webkit-scrollbar-track {
        background: transparent;
    }

    .how-to-use-scroll-container::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.2);
        border-radius: 4px;
        border: 2px solid var(--color-grey-20);
    }

    .how-to-use-scroll-container:hover::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.5);
    }

    .how-to-use-scroll {
        display: flex;
        gap: 0.75rem;
        padding-right: 1rem;
        min-width: min-content;
    }

    /* Individual example card */
    .how-to-use-card {
        flex: 0 0 auto;
        width: 260px;
        padding: 1rem;
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-20);
        border-radius: 12px;
        display: grid;
        /* Opening quote top-left, text spans middle, closing quote bottom-right */
        grid-template-areas:
            "open text"
            ".    close";
        grid-template-columns: auto 1fr;
        grid-template-rows: auto 1fr;
        gap: 0.4rem;
    }

    /* Opening quote — top-LEFT */
    .quote-open {
        grid-area: open;
        align-self: start;
        justify-self: start;
        color: var(--color-grey-40);
        opacity: 0.5;
        flex-shrink: 0;
    }

    /* Closing quote — bottom-RIGHT, rotated 180° to face the other direction */
    .quote-close {
        grid-area: close;
        align-self: end;
        justify-self: end;
        color: var(--color-grey-40);
        opacity: 0.5;
        flex-shrink: 0;
        transform: rotate(180deg);
    }

    .how-to-use-text {
        grid-area: text;
        margin: 0;
        font-size: 0.9rem;
        line-height: 1.5;
        color: var(--color-grey-100);
        word-break: break-word;
        align-self: start;
    }

    /* Highlighted trigger words (from **word** syntax in i18n) */
    .how-to-use-text :global(.highlight-word) {
        color: var(--highlight-color, var(--color-primary-start));
        font-weight: 600;
    }

    /* "Or mention @FocusModeName in your message..." footer below example cards */
    .how-to-use-mention {
        margin: 0.75rem 0 0 0;
        padding: 0;
        font-size: 0.9rem;
        font-weight: 600;
        line-height: 1.6;
        color: var(--color-grey-100);
        white-space: pre-line;
    }

    /* The @mention name — styled as an inline clickable text link (no underline) */
    .how-to-use-mention .mention-name {
        display: inline;
        padding: 0;
        margin: 0;
        border: none;
        background: none;
        font: inherit;
        font-size: inherit;
        font-weight: 600;
        line-height: inherit;
        color: var(--color-primary-start);
        cursor: pointer;
        text-decoration: none;
    }

    .how-to-use-mention .mention-name:hover {
        text-decoration: none;
        opacity: 0.8;
    }

    /* "An overview, over what the focus mode will do:" label */
    .instructions-overview {
        margin: 0.5rem 0 0 0;
        padding: 0;
        font-size: 0.95rem;
        font-weight: 600;
        line-height: 1.5;
        color: var(--color-grey-100);
    }

    /* Bullet-point process summary list */
    .process-bullets {
        margin: 0.75rem 0 0 10px;
        padding: 0 0 0 1.25rem;
        list-style: none;
        display: flex;
        flex-direction: column;
        gap: 0.4rem;
    }

    .process-bullet {
        position: relative;
        padding-left: 1.25rem;
        font-size: 0.95rem;
        line-height: 1.5;
        color: var(--color-grey-100);
    }

    .process-bullet::before {
        content: '•';
        position: absolute;
        left: 0;
        color: var(--color-primary-start, #5856d6);
        font-weight: 700;
        font-size: 1rem;
        line-height: 1.5;
    }

    /* System prompt block — quote-style card with opening and closing quote marks */
    .instructions-block {
        position: relative;
        margin-top: 0.75rem;
        /* pad: top leaves room for quote icon, bottom-right leaves room for closing quote */
        padding: 2rem 2.5rem 2rem 2.5rem;
        background: var(--color-grey-10, #f5f5f5);
        border-radius: 12px;
        border: 1px solid var(--color-grey-20);
    }

    /* Opening quote — top-left corner of the prompt block */
    .prompt-quote-open {
        position: absolute;
        top: 10px;
        left: 12px;
        width: 20px;
        height: 20px;
        color: var(--color-grey-50);
        opacity: 0.6;
        pointer-events: none;
    }

    /* Closing quote — bottom-right corner of the prompt block, rotated 180° */
    .prompt-quote-close {
        position: absolute;
        bottom: 10px;
        right: 12px;
        width: 20px;
        height: 20px;
        color: var(--color-grey-50);
        opacity: 0.6;
        pointer-events: none;
        transform: rotate(180deg);
    }

    /* Full system prompt text — regular body text (not monospace) */
    .instructions-text {
        margin: 0;
        padding: 0;
        font-family: var(--font-family-primary);
        font-size: 0.9rem;
        line-height: 1.6;
        white-space: pre-wrap;
        word-break: break-word;
        color: var(--color-grey-100);
    }

    /* Toggle button — styled as a plain text link, same style as .mention-name */
    .instructions-toggle {
        display: inline;
        margin-top: 0.75rem;
        margin-left: 10px;
        padding: 0;
        font-size: 0.875rem;
        background: none;
        border: none;
        cursor: pointer;
        font-weight: 600;
        text-align: left;
        color: var(--color-primary-start);
        text-decoration: none;
    }

    .instructions-toggle:hover {
        opacity: 0.8;
        text-decoration: none;
    }
    
    .no-instructions {
        padding: 1.25rem 0 0 10px;
        color: var(--color-grey-60);
        font-size: 0.95rem;
    }

    .no-instructions p {
        margin: 0;
    }
    
    .error {
        padding: 3rem;
        text-align: center;
        color: var(--error-color, #dc3545);
    }
    
    .back-button {
        background: var(--button-background, #f0f0f0);
        border: 1px solid var(--border-color, #e0e0e0);
        border-radius: 6px;
        padding: 0.5rem 1rem;
        margin-top: 1rem;
        cursor: pointer;
        font-size: 0.9rem;
        color: var(--text-primary, #000000);
        transition: background 0.2s ease;
    }
    
    .back-button:hover {
        background: var(--button-hover-background, #e0e0e0);
    }
</style>
