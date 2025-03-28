<!--
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
step_7_bottom_content_svelte:
    confirm_settings_toggle:
        type: 'toggle'
        text: $text('signup.accept_settings.text')
        purpose:
            - 'User needs to confirm that they accept the settings before completing the signup process'
        processing:
            - 'User clicks the toggle'
            - 'User confirms that they accept the settings'
            - 'Request to server is sent to save the user confirmation'
            - 'Next signup step is loaded automatically'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - 'settings'
        connected_documentation:
            - '/signup/settings'
    click_toggle_to_continue_text:
        type: 'text'
        text: $text('signup.click_toggle_to_continue.text')
        purpose:
            - 'Inform the user that they need to click the toggle to continue to the next signup step'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - 'settings'
        connected_documentation:
            - '/signup/settings'
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui'; // Keep text import for now
    import { userProfile } from '../../../../stores/userProfile'; // Corrected userProfile import path
    // Removed updateProfile import, import API config instead
    import { apiEndpoints, getApiEndpoint } from '../../../../config/api'; 
    import Toggle from '../../../Toggle.svelte';
    import { _ } from 'svelte-i18n'; // For potential error messages

    const dispatch = createEventDispatcher();
    // Use the store value directly for binding, no need for separate local state if not modifying locally first
    // let hasConfirmedSettings = $userProfile.has_consent_privacy || false; // Initialize from store

    // Reactive statement to call API when toggle is activated
    // We bind the toggle directly to the store value for display, 
    // but trigger API call based on user interaction (click/change)
    
    let isLoading = false; // To prevent multiple API calls

    // Update event type hint to CustomEvent and access detail.checked
    async function handleConsentToggleChange(event: CustomEvent<{ checked: boolean }>) { 
        const isChecked = event.detail.checked;
        
        if (isChecked && !isLoading && !$userProfile.has_consent_privacy) {
            isLoading = true;
            try {
                const response = await fetch(getApiEndpoint(apiEndpoints.settings.user.consent_privacy_apps), {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'Origin': window.location.origin
                    },
                    credentials: 'include'
                });

                const data = await response.json();

                if (response.ok && data.success) {
                    console.debug("Privacy/Apps consent recorded successfully.");
                    // Update local store state AFTER successful API call
                    // This might be handled automatically if authStore.checkAuth is called after navigation
                    // Or manually update if needed:
                    // updateProfile({ has_consent_privacy: true }); 
                    dispatch('step', { step: 8 });
                } else {
                    console.error("Failed to record privacy/apps consent:", data.message || response.statusText);
                    // Optionally show an error message to the user
                    // Revert toggle state visually if API failed? Requires local state management.
                }
            } catch (error) {
                console.error("Error calling privacy/apps consent API:", error);
                // Optionally show an error message
            } finally {
                isLoading = false;
            }
        } else if (isChecked && $userProfile.has_consent_privacy) {
             // If already consented, just dispatch to next step immediately
             dispatch('step', { step: 8 });
        }
        // If unchecked, do nothing (consent cannot be revoked here)
    }

</script>
<!-- Bind toggle directly to store value for display, handle logic in on:change -->
<div class="bottom-content">
    <div class="confirmation-row">
        <Toggle 
            checked={$userProfile.has_consent_privacy || false} 
            id="confirm-settings-toggle-step7" 
            on:change={handleConsentToggleChange} 
            disabled={isLoading || $userProfile.has_consent_privacy} 
        />
        <label for="confirm-settings-toggle-step7" class="confirmation-text">
            {$text('signup.accept_settings.text')}
        </label>
    </div>
    <div class="click-toggle-text">
        {$text('signup.click_toggle_to_continue.text')}
    </div>
</div>

<style>
    .bottom-content {
        padding: 24px;
        display: flex;
        flex-direction: column;
        align-items: center;
    }

    .confirmation-row {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-top: 20px;
    }

    .confirmation-text {
        color: var(--color-grey-60);
        font-size: 16px;
        text-align: left;
        cursor: pointer;
    }
    
    .click-toggle-text {
        color: var(--color-grey-50);
        font-size: 14px;
        margin-top: 28px;
    }
</style>
