<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml

-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { createEventDispatcher } from 'svelte';
    import { incognitoMode } from '../../../stores/incognitoModeStore';

    const dispatch = createEventDispatcher();

    // Activate incognito mode, navigate back to main settings, close settings menu, and trigger new chat
    async function handleActivate() {
        // Activate incognito mode
        await incognitoMode.set(true);
        
        // Navigate back to main settings
        dispatch('openSettings', {
            settingsPath: 'main',
            direction: 'backward',
            icon: '',
            title: ''
        });
        
        // Close settings menu by dispatching close event
        // This ensures the settings menu closes before creating the new chat
        if (typeof window !== 'undefined') {
            // Wait a bit for the navigation animation to complete
            await new Promise(resolve => setTimeout(resolve, 300));
            
            // Close settings menu
            const { settingsMenuVisible } = await import('../../Settings.svelte');
            settingsMenuVisible.set(false);
            
            // Wait a bit more for the menu to close
            await new Promise(resolve => setTimeout(resolve, 200));
            
            // Dispatch event to trigger new chat creation
            // This allows the user to immediately start a new incognito chat
            window.dispatchEvent(new CustomEvent('triggerNewChat'));
        }
    }
</script>

<div class="incognito-info-container">
    <div class="info-header">
        <div class="info-icon">
            <div class="icon settings_size subsetting_icon incognito"></div>
        </div>
        <h2 class="info-title">{$text('settings.incognito')}</h2>
    </div>

    <div class="info-content">
        <p class="info-description">
            {$text('settings.incognito_explainer_description')}
        </p>

        <div class="info-features">
            <div class="info-feature">
                <div class="feature-icon">✓</div>
                <div class="feature-text">
                    {$text('settings.incognito_explainer_feature_device_specific')}
                </div>
            </div>
            <div class="info-feature">
                <div class="feature-icon">✓</div>
                <div class="feature-text">
                    {$text('settings.incognito_explainer_feature_not_stored')}
                </div>
            </div>
            <div class="info-feature">
                <div class="feature-icon">✓</div>
                <div class="feature-text">
                    {$text('settings.incognito_explainer_feature_session_only')}
                </div>
            </div>
            <div class="info-feature">
                <div class="feature-icon">⚠</div>
                <div class="feature-text">
                    {$text('settings.incognito_explainer_feature_no_recovery')}
                </div>
            </div>
        </div>

        <div class="info-warning">
            <div class="warning-icon">⚠</div>
            <div class="warning-content">
                <p class="warning-title">{$text('settings.incognito_explainer_warning_title')}</p>
                <p class="warning-text">
                    {$text('settings.incognito_explainer_warning_providers')}
                </p>
                <p class="warning-text">
                    {$text('settings.incognito_explainer_warning_personal_info')}
                </p>
            </div>
        </div>
    </div>

    <div class="info-footer">
        <button data-testid="incognito-activate-button" onclick={handleActivate}>
            {$text('settings.incognito_explainer_understood')}
        </button>
    </div>
</div>

<style>
    .incognito-info-container {
        display: flex;
        flex-direction: column;
        padding: 20px;
        gap: 24px;
    }

    .info-header {
        display: flex;
        align-items: center;
        gap: 12px;
        padding-bottom: 16px;
        border-bottom: 1px solid var(--color-grey-30);
    }

    .info-icon {
        width: 44px;
        height: 44px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
    }

    .info-title {
        font-size: 22px;
        font-weight: 600;
        color: var(--color-grey-100);
        margin: 0;
    }

    .info-content {
        display: flex;
        flex-direction: column;
        gap: 24px;
    }

    .info-description {
        font-size: 16px;
        color: var(--color-grey-80);
        line-height: 1.6;
        margin: 0;
    }

    .info-features {
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    .info-feature {
        display: flex;
        align-items: flex-start;
        gap: 12px;
    }

    .feature-icon {
        width: 24px;
        height: 24px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 18px;
        font-weight: 600;
        color: var(--color-primary);
        flex-shrink: 0;
        margin-top: 2px;
    }

    .feature-text {
        font-size: 15px;
        color: var(--color-grey-70);
        line-height: 1.5;
        flex: 1;
    }

    .info-warning {
        display: flex;
        gap: 12px;
        padding: 16px;
        background-color: var(--color-grey-10);
        border-radius: 8px;
        border-left: 4px solid var(--color-warning);
    }

    .warning-icon {
        width: 24px;
        height: 24px;
        display: flex;
        align-items: flex-start;
        justify-content: center;
        font-size: 20px;
        font-weight: 600;
        color: var(--color-warning);
        flex-shrink: 0;
        margin-top: 2px;
    }

    .warning-content {
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .warning-title {
        font-size: 16px;
        font-weight: 600;
        color: var(--color-grey-100);
        margin: 0;
    }

    .warning-text {
        font-size: 15px;
        color: var(--color-grey-70);
        line-height: 1.5;
        margin: 0;
    }

    .info-footer {
        padding-top: 16px;
        border-top: 1px solid var(--color-grey-30);
        display: flex;
        justify-content: flex-end;
    }
</style>
