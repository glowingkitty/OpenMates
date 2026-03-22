<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
step_5_bottom_content_svelte:
    confirm_save_storage_toggle:
        type: 'toggle'
        text: $text('signup.i_stored_backup_codes')
        purpose:
            - 'User needs to confirm that they have saved the backup codes safely before continuing to the next signup step'
        processing:
            - 'User clicks the toggle or the text next to it'
            - 'User confirms that they have saved the backup codes'
            - 'Request to server is sent to save in profile that user has saved the backup codes and when'
            - 'Next signup step is loaded automatically'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - '2fa'
            - 'backup codes'
        connected_documentation:
            - '/signup/backup-codes'
    click_toggle_to_continue_text:
        type: 'text'
        text: $text('signup.click_toggle_to_continue')
        purpose:
            - 'Inform the user that they need to click the toggle to continue to the next signup step'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - '2fa'
            - 'backup codes'
        connected_documentation:
            - '/signup/backup-codes'
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import Toggle from '../../../Toggle.svelte';
    import { getApiEndpoint, apiEndpoints } from '../../../../config/api';
    import { recoveryKeyLoaded, recoveryKeyData } from '../../../../stores/recoveryKeyState';

    // Props using Svelte 5 runes
    let { paymentEnabled = true }: { paymentEnabled?: boolean } = $props();
    
    const dispatch = createEventDispatcher();
    let hasConfirmedStorage = $state(false);
    let isSubmitting = $state(false);

    // Watch for changes to hasConfirmedStorage using Svelte 5 runes
    $effect(() => {
        if (hasConfirmedStorage) { // Removed !isSubmitting check here, rely on check inside function
            confirmRecoveryKeyStored();
        }
    });
    
    // Call API to confirm that recovery key has been stored
    async function confirmRecoveryKeyStored() {
        // Immediate check to prevent concurrent executions
        if (isSubmitting) return; 
        if (!hasConfirmedStorage) return; // Keep this check for safety
        
        isSubmitting = true;
        
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.confirm_recoverykey_stored), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({
                    confirmed: true,
                    lookup_hash: $recoveryKeyData.lookupHash,
                    wrapped_master_key: $recoveryKeyData.wrappedMasterKey,
                    key_iv: $recoveryKeyData.keyIv,
                    salt: $recoveryKeyData.salt
                })
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                // Proceed to next step only after successful API response
                // Navigate to credits step if payment is enabled, otherwise go to completion (self-hosted mode)
                const nextStep = paymentEnabled ? 'credits' : 'completion';
                dispatch('step', { step: nextStep });
            } else {
                // If API call failed, reset the toggle
                console.error('Failed to confirm recovery key stored:', data.message);
                hasConfirmedStorage = false; // Reset state on failure
            }
        } catch (err) {
            console.error('Error confirming recovery key stored:', err);
            hasConfirmedStorage = false; // Reset state on error
        } finally {
            isSubmitting = false;
        }
    }
</script>

<div class="bottom-content">
    <div class="content-wrapper" class:disabled={!$recoveryKeyLoaded} transition:fade={{ duration: 300 }}>
        <div class="confirmation-row">
            <Toggle bind:checked={hasConfirmedStorage} id="confirm-storage-toggle-step5" disabled={!$recoveryKeyLoaded} />
            <label for="confirm-storage-toggle-step5" class="confirmation-text">
                {$text('signup.i_stored_recovery_key')}
            </label>
        </div>
        <div class="click-toggle-text">
            {$text('signup.click_toggle_to_continue')}
        </div>
    </div>
</div>

<style>
    .bottom-content {
        padding: 24px;
    }

    .content-wrapper {
        transition: opacity 0.3s ease, filter 0.3s ease;
    }

    .content-wrapper.disabled {
        opacity: 0;
        filter: grayscale(30%);
        pointer-events: none;
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