<!-- frontend/packages/ui/src/components/settings/FocusModeDetails.svelte
     Component for displaying details of a specific focus mode, including description.
     
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
     * Get the translated focus mode name.
     */
    let focusModeName = $derived(
        focusMode?.name_translation_key 
            ? $text(focusMode.name_translation_key)
            : focusModeId
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
     * Navigate back to app details.
     */
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
        <!-- Focus mode name header -->
        <div class="focus-mode-header">
            <h1>{focusModeName}</h1>
        </div>
        
        <!-- Description section -->
        {#if focusModeDescription}
            <div class="section">
                <SettingsItem 
                    type="heading"
                    icon="description"
                    title={$text('settings.app_store.focus_modes.description')}
                />
                <div class="content">
                    <p>{focusModeDescription}</p>
                </div>
            </div>
        {:else}
            <div class="section">
                <div class="no-description">
                    <p>{$text('settings.app_store.focus_modes.no_description')}</p>
                </div>
            </div>
        {/if}
        
        <!-- System prompt section: shows the prompt used when this focus mode is activated -->
        <div class="section">
            <SettingsItem 
                type="heading"
                icon="ai"
                title={$text('settings.app_store.focus_modes.system_prompt')}
            />
            {#if focusModeSystemPrompt}
                <div class="content system-prompt-content">
                    <pre class="system-prompt-text">{focusModeSystemPrompt}</pre>
                </div>
            {:else}
                <div class="no-description">
                    <p>{$text('settings.app_store.focus_modes.no_system_prompt')}</p>
                </div>
            {/if}
        </div>
    {/if}
</div>

<style>
    .focus-mode-details {
        padding: 2rem;
        max-width: 1400px;
        margin: 0 auto;
    }
    
    .focus-mode-header {
        margin-bottom: 2rem;
    }
    
    .focus-mode-header h1 {
        margin: 0;
        font-size: 2rem;
        font-weight: 600;
        color: var(--text-primary, #000000);
    }
    
    .section {
        margin-top: 2rem;
    }
    
    .content {
        padding: 1rem 0 1rem 10px;
        color: var(--color-grey-100);
        font-size: 1rem;
        line-height: 1.6;
    }
    
    .system-prompt-content {
        padding: 1rem 0 1rem 10px;
    }
    
    .system-prompt-text {
        margin: 0;
        padding: 1rem;
        background: var(--color-grey-10, #f5f5f5);
        border-radius: 8px;
        border: 1px solid var(--border-color, #e0e0e0);
        font-size: 0.9rem;
        line-height: 1.5;
        white-space: pre-wrap;
        word-break: break-word;
        color: var(--color-grey-100);
        overflow-x: auto;
    }
    
    .no-description {
        padding: 2rem;
        text-align: center;
        color: var(--text-secondary, #666666);
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

