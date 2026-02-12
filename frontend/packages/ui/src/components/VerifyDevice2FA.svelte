<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
login_2fa_svelte:
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
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount, onDestroy, createEventDispatcher } from 'svelte';
    import InputWarning from './common/InputWarning.svelte';
    import { getApiEndpoint, apiEndpoints } from '../config/api';
    import { tfaAppIcons } from '../config/tfa';

    // Props using Svelte 5 runes
    let { 
        reason = null,
        previewMode = false,
        previewTfaAppName = 'Google Authenticator',
        tfaAppName = null,
        highlight = [],
        isLoading = $bindable(false),
        errorMessage = $bindable(null)
    }: {
        reason?: 'new_device' | 'location_change' | null;
        previewMode?: boolean;
        previewTfaAppName?: string;
        tfaAppName?: string | null;
        highlight?: (
            'check-2fa' |
            'input-area' |
            'login-btn' |
            'enter-backup-code'
        )[];
        isLoading?: boolean;
        errorMessage?: string | null;
    } = $props();

    const dispatch = createEventDispatcher(); // Create dispatcher

    let otpCode = $state('');
    let otpInput: HTMLInputElement = $state();

    // TFA app display logic
    let currentAppIndex = 0;
    let animationInterval: number | null = null;
    let currentDisplayedApp = previewMode ? previewTfaAppName : (tfaAppName || '');
    const appNames = Object.keys(tfaAppIcons);

    // Get the icon class for the app name, or undefined if not found using Svelte 5 runes
    let tfaAppIconClass = $derived(currentDisplayedApp in tfaAppIcons ? tfaAppIcons[currentDisplayedApp] : undefined);

    let getStyle = $derived((id: string) => `opacity: ${highlight.length === 0 || highlight.includes(id as any) ? 1 : 0.5}`);

    // Function to dispatch event to switch back to login - RESTORED
    function handleSwitchToLogin(event: Event) {
        event.preventDefault(); // Prevent default link behavior
        dispatch('switchToLogin');
    }

    function handleInput(event: Event) {
        const input = event.target as HTMLInputElement;
        // Allow only digits and limit length
        otpCode = input.value.replace(/\D/g, '').slice(0, 6);
        input.value = otpCode; // Ensure input reflects sanitized value

        // Dispatch activity event whenever input changes
        dispatch('tfaActivity');

        // Optionally auto-submit when 6 digits are entered
        if (otpCode.length === 6) {
            handleSubmit();
        }
    }

    // Modified handleSubmit for device verification
    async function handleSubmit() { // Added async
        if (isLoading || otpCode.length !== 6) return;

        // Added API call logic
        isLoading = true;
        errorMessage = null;
        console.debug("Submitting device verification code...");

        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.verifyDevice2FA), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                body: JSON.stringify({ tfa_code: otpCode }),
                credentials: 'include'
            });

            const data = await response.json();

            if (response.ok && data.success) {
                console.debug("Device verification successful.");
                dispatch('deviceVerified'); // Dispatch success event
            } else {
                console.warn("Device verification failed:", data.message);
                errorMessage = data.message || 'Invalid verification code';
            }

        } catch (error) {
            console.error("Device verification fetch/network error:", error);
            errorMessage = 'An error occurred during verification.';
        } finally {
            isLoading = false;
        }
    }

    // Clear error message when user starts typing again using Svelte 5 runes
    $effect(() => {
        if (otpCode) {
            errorMessage = null;
        }
    });

    // Focus input on mount if not preview mode
    onMount(() => {
        if (!previewMode && otpInput) {
            otpInput.focus();
        }
    });
</script>

<div class="login-2fa" class:preview={previewMode}>
    {#if reason === 'location_change'}
        <div class="location-change-notice">
            <span class="icon icon_shield"></span>
            <p>{$text('login.verify_device_location_change_notice.text')}</p>
        </div>
    {/if}

    <p id="check-2fa" class="check-2fa-text" style={getStyle('check-2fa')}>
        {#if currentDisplayedApp}
            <span class="app-name-inline">{@html $text('login.check_your_2fa_app.text').replace('{tfa_app}', '')}</span>
            <span class="app-name-inline">
                {#if tfaAppIconClass}
                    <span class="icon provider-{tfaAppIconClass} mini-icon {previewMode && !tfaAppName ? 'fade-animation' : ''}"></span>
                {/if}
                <span class="{previewMode && !tfaAppName ? 'fade-text' : ''}">{currentDisplayedApp}</span>
            </span>
        {:else}
            {@html $text('login.check_your_2fa_app.text').replace('{tfa_app}', $text('login.your_tfa_app.text'))}
        {/if}
    </p>
    
    <div id="input-area" style={getStyle('input-area')}>
        <div class="input-wrapper">
            <span class="clickable-icon icon_2fa"></span>
            <input
                bind:this={otpInput}
                type="text"
                pattern="[0-9]*"
                bind:value={otpCode}
                oninput={handleInput}
                placeholder={$text('signup.enter_one_time_code.text')}
                inputmode="numeric"
                maxlength="6"
                autocomplete="one-time-code"
                class:error={!!errorMessage}
            />
             {#if errorMessage}
                <InputWarning 
                    message={errorMessage} 
                />
            {/if}
        </div>
    </div>
    
   <div class="switch-account">
        <button type="button" onclick={handleSwitchToLogin} class="text-button">
            {$text('login.login_with_another_account.text')}
        </button>
    </div>
</div>

<style>
    .login-2fa {
        display: flex;
        flex-direction: column;
    }

    .location-change-notice {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 12px 14px;
        margin-bottom: 15px;
        background-color: var(--color-warning-bg, var(--color-grey-10));
        border-radius: 8px;
        border-left: 3px solid var(--color-warning, var(--color-primary));
    }

    .location-change-notice .icon {
        width: 20px;
        height: 20px;
        flex-shrink: 0;
        margin-top: 2px;
    }

    .location-change-notice p {
        margin: 0;
        font-size: 14px;
        line-height: 1.4;
        color: var(--color-grey-70);
    }

    .check-2fa-text {
        margin: 0px;
        margin-bottom: 15px;
        color: var(--color-grey-60);
    }

    .app-name-inline {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        vertical-align: middle
    }

    .mini-icon {
        width: 24px;
        height: 24px;
        border-radius: 4px;
        flex-shrink: 0;
    }

    .preview {
        cursor: default !important;
    }

    .switch-account {
        margin-top: 10px;
    }

    .preview * {
        cursor: default !important;
        pointer-events: none !important;
    }

    @media (max-width: 600px) {
        .login-2fa {
            align-items: center;
        }
    }
</style>