<!--
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
signup_enter_2fa_code_input_field:
    type: 'input_field'
    placeholder: $text('signup.enter_one_time_code.text')
    purpose:
        - 'Verifies the 2FA code, to setup 2FA for the user account.'
    processing:
        - 'User clicks field (or, if on desktop, field is focused automatically)'
        - 'User enters numeric code shown in 2FA OTP app'
        - 'Server request is sent to validate 2FA code'
        - 'If 2FA code valid: next signup step is loaded'
        - 'If 2FA code not valid: informs user via error message'
    bigger_context:
        - 'Signup'
    tags:
        - 'signup'
        - '2fa'
    connected_documentation:
        - '/signup/2fa'
click_to_show_free_2fa_apps_button:
    type: 'button'
    text: $text('signup.click_here_to_show_free_2fa_apps.text')
    purpose:
        - 'User clicks and is forwarded to the documentation page about 2FA (which should include links to free 2FA apps)'
    processing:
        - 'User clicks the button'
        - 'User is forwarded to the documentation page about 2FA (which should include links to free 2FA apps)'
    bigger_context:
        - 'Signup'
    tags:
        - 'signup'
        - '2fa'
    connected_documentation:
        - '/signup/2fa'
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount } from 'svelte';
    import { createEventDispatcher } from 'svelte';
    import { routes } from '../../../../config/links';
    
    let otpCode = '';
    let otpInput: HTMLInputElement;
    const dispatch = createEventDispatcher();

    onMount(() => {
        const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
        if (otpInput && !isTouchDevice) {
            otpInput.focus();
        }
    });

    function handleInput(event: Event) {
        const input = event.target as HTMLInputElement;
        otpCode = input.value.replace(/\D/g, '').slice(0, 6);
        
        if (otpCode.length === 6) {
            dispatch('step', { step: 5 });
        }
    }
</script>

<div class="bottom-content">
    <div class="input-group">
        <div class="input-wrapper">
            <span class="clickable-icon icon_2fa"></span>
            <input
                bind:this={otpInput}
                type="text"
                bind:value={otpCode}
                on:input={handleInput}
                placeholder={$text('signup.enter_one_time_code.text')}
                inputmode="numeric"
                maxlength="6"
            />
        </div>
    </div>
    
    <div class="resend-section">
        <span class="color-grey-60">{@html $text('signup.dont_have_2fa_app.text')}</span>
        <a href={routes.docs.userGuide_signup_4} target="_blank" class="text-button">
            {$text('signup.click_here_to_show_free_2fa_apps.text')}
        </a>
    </div>
</div>

<style>
    .bottom-content {
        padding: 24px;
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    .resend-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
    }
</style>
