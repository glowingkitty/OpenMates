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
     * Get the translated focus mode description.
     */
    let focusModeDescription = $derived(
        focusMode?.description_translation_key 
            ? $text(focusMode.description_translation_key)
            : ''
    );
    
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
        return iconName;
    }
    
    function goBack() {
        dispatch('openSettings', {
            settingsPath: `app_store/${appId}`,
            direction: 'back',
            icon: getIconName(app?.icon_image),
            title: app?.name_translation_key ? $text(app.name_translation_key) : appId
        });
    }
</script>

<div class="focus-mode-details">
    {#if !app || !focusMode}
        <div class="error">
            <p>{$text('settings.app_store.focus_mode_not_found')}</p>
            <button class="back-button" onclick={goBack}>← {$text('settings.app_store.back_to_app')}</button>
        </div>
    {:else}
        <!-- Description section - plain text, no heading, matching skill details layout -->
        {#if focusModeDescription}
            <div class="description-section">
                <p class="focus-mode-description">{focusModeDescription}</p>
            </div>
        {/if}
        
        <!-- Instructions section: bullet-point summary of what the focus mode does,
             plus a collapsible "Show full system prompt" button.
             Uses process_translation_key bullets when available; falls back to showing
             the system prompt directly if no process key is defined. -->
        <div class="section">
            <SettingsItem 
                type="heading"
                icon="ai"
                title={$text('settings.app_store.focus_modes.system_prompt')}
            />
            {#if hasInstructions}
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
                            <svg class="quote-icon quote-icon-top" width="20" height="20" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M15 3a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.717-3.35 3 3 0 012.259-2.47C11.952 37.416 15 33.606 15 26.998v-3H6a6 6 0 01-5.985-5.549L0 17.998V9A5.999 5.999 0 016 3h9zm27 0a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.716-3.35 2.998 2.998 0 012.258-2.47C38.952 37.416 42 33.606 42 26.998v-3h-9a6 6 0 01-5.985-5.549l-.015-.45V9A5.999 5.999 0 0133 3h9z" fill="currentColor"/>
                            </svg>
                            <pre class="instructions-text">{focusModeSystemPrompt}</pre>
                        </div>
                    {/if}
                    <button
                        type="button"
                        class="instructions-toggle"
                        onclick={() => (showFullPrompt = !showFullPrompt)}
                    >
                        {showFullPrompt
                            ? $text('settings.app_store.focus_modes.show_less')
                            : $text('settings.app_store.focus_modes.show_full_instruction')}
                    </button>
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

    /* Description section — matches .description-section in SkillDetails.svelte */
    .description-section {
        margin-bottom: 2rem;
        padding-left: 0;
    }

    .focus-mode-description {
        margin: 0;
        color: var(--color-grey-100);
        font-size: 1rem;
        line-height: 1.6;
        text-align: left;
    }
    
    .section {
        margin-top: 2rem;
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

    /* System prompt block — quote-style, matching SkillDetails how-to-use card style */
    .instructions-block {
        position: relative;
        margin-top: 0.75rem;
        padding: 1rem 1.25rem 1rem 2.5rem;
        background: var(--color-grey-10, #f5f5f5);
        border-radius: 12px;
        border: 1px solid var(--color-grey-20);
    }

    .quote-icon {
        position: absolute;
        top: 10px;
        left: 12px;
        width: 20px;
        height: 20px;
        color: var(--color-grey-50);
        opacity: 0.6;
        pointer-events: none;
    }

    .instructions-text {
        margin: 0;
        padding: 0;
        font-size: 0.9rem;
        line-height: 1.5;
        white-space: pre-wrap;
        word-break: break-word;
        color: var(--color-grey-100);
        overflow-x: auto;
    }
    
    /* Toggle button for showing/hiding the full system prompt */
    .instructions-toggle {
        display: block;
        margin-top: 0.75rem;
        margin-left: 10px;
        padding: 0.35rem 0.6rem;
        font-size: 0.875rem;
        color: var(--color-primary, #0066cc);
        background: transparent;
        border: none;
        cursor: pointer;
        border-radius: 4px;
        font-weight: 500;
    }
    
    .instructions-toggle:hover {
        text-decoration: underline;
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
