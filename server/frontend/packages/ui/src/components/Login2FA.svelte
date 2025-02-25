<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
check_your_2fa_app_text:
    type: 'text'
    text: $text('login.check_your_2fa_app.text')
    purpose: 'Ask user to check their 2FA app for the one time code'
    bigger_context:
        - 'Login'
    tags:
        - 'login'
        - '2fa'
    connected_documentation:
        - '/login/2fa'
tfa_app_name_text:
    type: 'text'
    text: {name of 2FA app which user used}
    purpose: 'Reminder for user which 2FA app they used, if they saved the name during signup or in settings.'
    processing:
        - 'Name of 2FA app is loaded from server (if user saved it during signup or in settings)'
        - 'Name of 2FA app is shown to user'
    bigger_context:
        - 'Login'
    tags:
        - 'login'
        - '2fa'
    connected_documentation:
        - '/login/2fa'
enter_2fa_code_input_field:
    type: 'input_field'
    placeholder: $text('signup.enter_one_time_code.text')
    purpose:
        - 'Verifies the 2FA code, to login to the user account.'
    processing:
        - 'User clicks field (or, if on desktop, field is focused automatically)'
        - 'User enters numeric code shown in 2FA OTP app'
    bigger_context:
        - 'Login'
    tags:
        - 'login'
        - '2fa'
    connected_documentation:
        - '/login/2fa'
login_button:
    type: 'button'
    text: $text('login.login.text')
    purpose:
        - 'User clicks to login to the user account.'
    processing:
        - 'User clicks the button'
        - 'Server request is sent to validate 2FA code'
        - 'If 2FA code valid: user is logged in'
        - 'If 2FA code not valid: informs user via error message'
    bigger_context:
        - 'Login'
    tags:
        - 'login'
        - '2fa'
    connected_documentation:
        - '/login/2fa'
enter_backup_code_button:
    type: 'button'
    text: $text('login.enter_backup_code.text')
    purpose:
        - 'Switches to interface where user can enter backup code instead of 2FA code.'
    processing:
        - 'User clicks the button'
        - 'User is forwarded to the interface where they can enter backup code'
    bigger_context:
        - 'Login'
    tags:
        - 'login'
        - '2fa'
    connected_documentation:
        - '/login/2fa'
-->

<script lang="ts">
    import { text } from '@repo/ui';

    export let previewMode = false;
    export let previewTfaAppName = 'Google Authenticator';
    export let highlight: (
        'check-2fa'|
        'app-name' |
        'input-area' |
        'login-btn' |
        'enter-backup-code'
    )[] = [];

    const tfaAppName = previewMode ? previewTfaAppName : ''; // In real mode, this would be loaded from server
    let otpCode = '';
    let otpInput: HTMLInputElement;
    let isLoading = false;

    // Map of app names to their icon classes
    const tfaAppIcons = {
        'Google Authenticator': 'google-authenticator',
        'Authy': 'authy',
        'Microsoft Authenticator': 'microsoft-authenticator',
        '2FAS': 'tfas',
        'OTP Auth': 'otp-auth'
    };

    // Get the icon class for the app name, or default if not found
    $: tfaAppIconClass = tfaAppName ? tfaAppIcons[tfaAppName] || 'default' : 'default';

    // Helper function to generate opacity style
    $: getStyle = (id: string) => `opacity: ${highlight.length === 0 || highlight.includes(id) ? 1 : 0.5}`;

    function handleInput(event: Event) {
        const input = event.target as HTMLInputElement;
        otpCode = input.value.replace(/\D/g, '').slice(0, 6);
        
        if (otpCode.length === 6) {
            console.log('OTP code entered:', otpCode);
        }
    }
</script>

<div class="login-2fa" class:preview={previewMode}>
    <p id="check-2fa" class="check-2fa-text" style={getStyle('check-2fa')}>
        {@html $text('login.check_your_2fa_app.text')}
    </p>
    {#if tfaAppName}
        <p id="app-name" class="app-name" style={getStyle('app-name')}>
            <span class="icon provider-{tfaAppIconClass} mini-icon"></span>
            {tfaAppName}
        </p>
    {/if}
    <div id="input-area" style={getStyle('input-area')}>
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
    <button 
        type="submit" 
        id="login-btn"
        class="login-button"
        disabled={isLoading}
        style={getStyle('login-btn')}
    >
        {#if isLoading}
            <span class="loading-spinner"></span>
        {:else}
            {$text('login.login_button.text')}
        {/if}
    </button>
    <div id="enter-backup-code" class="enter-backup-code">
        <a href="" target="_blank" class="text-button">
            {$text('login.enter_backup_code.text')}
        </a>
    </div>
</div>

<style>
    .login-2fa {
        display: flex;
        flex-direction: column;
    }

    .app-name {
        margin: 10px 0 30px 0;
        display: flex;
        align-items: center;
    }

    .check-2fa-text {
        margin: 0px;
        color: var(--color-grey-60);
    }

    .preview {
        cursor: default !important;
    }

    .enter-backup-code {
        margin-top: 20px;
    }

    .mini-icon {
        width: 38px;
        height: 38px;
        border-radius: 8px;
        margin-right: 10px;
    }

    .preview * {
        cursor: default !important;
        pointer-events: none !important;
    }
</style>