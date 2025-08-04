<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
step_4_bottom_content_svelte:
    password_input_field:
        type: 'input_field'
        placeholder: $text('login.password_placeholder.text')
        purpose:
            - 'Collects user password required by Directus for 2FA setup'
        processing:
            - 'User enters their password'
            - 'Password is sent to the backend when setup button is clicked'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - '2fa'
            - 'password'
        connected_documentation:
            - '/signup/2fa'
    setup_2fa_button:
        type: 'button'
        text: $text('signup.setup_2fa.text')
        purpose:
            - 'Submits the password to initiate 2FA setup'
        processing:
            - 'User clicks the button'
            - 'Password is sent to the backend'
            - 'If successful, 2FA setup UI appears'
            - 'If unsuccessful, error message is shown'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - '2fa'
        connected_documentation:
            - '/signup/2fa'
    enter_2fa_code_input_field:
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
    import { fade } from 'svelte/transition';
    import { routes } from '../../../../config/links';
    import { getApiEndpoint, apiEndpoints } from '../../../../config/api';
    import { userProfile } from '../../../../stores/userProfile'; // Import userProfile store
    import { 
        twoFASetupComplete,
        twoFAVerificationStatus,
        setVerifying,
        setVerificationError,
        clearVerificationError
    } from '../../../../stores/twoFAState';
    
    let otpCode = '';
    let otpInput: HTMLInputElement;
    let isLoading = false;
    const dispatch = createEventDispatcher();
    
    // Detect device OS
    let isIOS = false;
    let isAndroid = false;
    
    onMount(() => {
        // Modern way to detect iOS devices
        isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent) || 
                (/Mac/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
        
        // Modern way to detect Android devices
        isAndroid = /Android/.test(navigator.userAgent);
    });
    
    // Get appropriate app store search URL
    function getAppStoreUrl() {
        if (isIOS) {
            // iOS App Store search for 2FA apps
            return 'https://apps.apple.com/search?term=2fa+otp+app';
        } else if (isAndroid) {
            // Google Play Store search for 2FA apps
            return 'https://play.google.com/store/search?q=2fa+otp+app';
        } else {
            // Default search for non-mobile devices
            return 'https://search.brave.com/search?q=best+free+2fa+otp+apps';
        }
    }

    // React to store changes
    $: setupComplete = $twoFASetupComplete;
    $: verifying = $twoFAVerificationStatus.verifying;
    $: error = $twoFAVerificationStatus.error;
    $: errorMessage = $twoFAVerificationStatus.errorMessage;

    // Focus input when the component becomes visible after setup complete
    $: if (setupComplete && otpInput) {
        const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
        if (!isTouchDevice) {
            setTimeout(() => otpInput.focus(), 300);
        }
    }

    // Function to expose for focusing the input
    export function focusInput() {
        if (otpInput) {
            otpInput.focus();
        }
    }

    async function verifyCode() {
        if (otpCode.length !== 6 || verifying) return;
        
        setVerifying(true);
        
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.verify_2fa_code), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({ code: otpCode })
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                // Verification successful, proceed to next step
                dispatch('step', { step: 'tfa_app_reminder' });
            } else {
                // Show error message
                setVerificationError(data.message || 'Invalid verification code');
                otpCode = '';
                
                // Clear error after 3 seconds
                setTimeout(() => {
                    clearVerificationError();
                }, 3000);
            }
        } catch (err) {
            console.error('Error verifying 2FA code:', err);
            setVerificationError('An error occurred while verifying your code');
            
            // Clear error after 3 seconds
            setTimeout(() => {
                clearVerificationError();
            }, 3000);
        }
    }

    function handleInput(event: Event) {
        const input = event.target as HTMLInputElement;
        otpCode = input.value.replace(/\D/g, '').slice(0, 6);
        
        if (otpCode.length === 6) {
            verifyCode();
        }
    }
</script>

{#if !$userProfile.tfa_enabled}
<div class="bottom-content">
    
    
    <!-- Show the verification code input only after setup is complete -->
    <div class="input-group" class:hidden={!setupComplete} transition:fade={{ duration: 300 }}>
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
                disabled={verifying}
                class:error={error}
            />
            {#if verifying}
            <div class="loader"></div>
            {/if}
        </div>
        {#if error}
        <div class="error-message" transition:fade>
            {errorMessage}
        </div>
        {/if}
    </div>

    <!-- Always show the 2FA apps information -->
    <div class="resend-section">
        <span class="color-grey-60">{@html $text('signup.dont_have_2fa_app.text')}</span>
        <!-- <a href={routes.docs.userGuide_signup_4} target="_blank" class="text-button"> -->
        <a href={getAppStoreUrl()} target="_blank" class="text-button">
            {$text('signup.click_here_to_show_free_2fa_apps.text')}
        </a>
    </div>
</div>
{/if}

<style>
    .bottom-content {
        padding: 24px;
        display: flex;
        flex-direction: column;
        /* gap: 16px; */
    }

    .resend-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
    }

    .hidden {
        display: none;
    }
</style>
