<!--
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
step_8_bottom_content_svelte:
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
            - 'mates'
        connected_documentation:
            - '/signup/mates'
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
            - 'mates'
        connected_documentation:
            - '/signup/mates'
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import Toggle from '../../../Toggle.svelte';

    const dispatch = createEventDispatcher();
    let hasConfirmedSettings = false;

    // Watch for changes to hasConfirmedSettings
    $: if (hasConfirmedSettings) {
        dispatch('step', { step: 9 });
    }
    
    // Handle click on the confirmation row
    function handleRowClick() {
        hasConfirmedSettings = !hasConfirmedSettings;
    }
</script>

<div class="bottom-content">
    <div class="confirmation-row" on:click={handleRowClick} role="button" tabindex="0">
        <Toggle bind:checked={hasConfirmedSettings} />
        <span class="confirmation-text">
            {$text('signup.accept_settings.text')}
        </span>
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
        cursor: pointer;
    }

    .confirmation-text {
        color: var(--color-grey-60);
        font-size: 16px;
        text-align: left;
    }
    
    .click-toggle-text {
        color: var(--color-grey-50);
        font-size: 14px;
        margin-top: 28px;
    }
</style>
