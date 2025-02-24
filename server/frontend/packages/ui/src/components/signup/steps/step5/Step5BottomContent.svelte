<!--
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
confirm_save_storage_toggle:
    type: 'toggle'
    text: $text('signup.i_stored_backup_codes.text')
    purpose:
        - 'User needs to confirm that they have saved the backup codes safely before continuing to the next signup step'
    processing:
        - 'User clicks the toggle'
        - 'User confirms that they have saved the backup codes'
        - 'Request to server is sent to save in profile that user has saved the backup codes and when'
        - 'Next signup step is loaded'
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
    import Toggle from '../../../Toggle.svelte';

    const dispatch = createEventDispatcher();
    let hasConfirmedStorage = false;

    // Watch for changes to hasConfirmedStorage
    $: if (hasConfirmedStorage) {
        dispatch('step', { step: 6 });
    }
</script>

<div class="bottom-content">
    <div class="confirmation-row">
        <Toggle bind:checked={hasConfirmedStorage} />
        <span class="confirmation-text">
            {$text('signup.i_stored_backup_codes.text')}
        </span>
    </div>
</div>

<style>
    .bottom-content {
        padding: 24px;
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
    }
</style>
