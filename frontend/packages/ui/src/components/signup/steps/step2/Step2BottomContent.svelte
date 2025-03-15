<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount } from 'svelte';
    import { createEventDispatcher } from 'svelte';
    import { getApiEndpoint, apiEndpoints } from '../../../../config/api';
    
    let otpCode = '';
    let otpInput: HTMLInputElement;
    const dispatch = createEventDispatcher();
    
    let isVerifying = false;
    let errorMessage = '';
    let showError = false;

    onMount(() => {
        // Check if device is touch-enabled
        const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
        
        // Only auto-focus on non-touch devices
        if (otpInput && !isTouchDevice) {
            otpInput.focus();
        }
    });

    async function verifyCode(code: string) {
        if (code.length !== 6) return;
        
        try {
            isVerifying = true;
            errorMessage = '';
            showError = false;
            
            // Get the email from localStorage
            const email = localStorage.getItem('signupEmail');
            
            if (!email) {
                errorMessage = 'Email address not found. Please go back and try again.';
                showError = true;
                return;
            }
            
            const response = await fetch(getApiEndpoint(apiEndpoints.signup.check_confirm_email_code), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    email: email,
                    code: code
                })
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                // Proceed to next step on success
                localStorage.removeItem('signupEmail');
                localStorage.removeItem('inviteCode');
                dispatch('step', { step: 3 });
            } else {
                // Show error message
                errorMessage = data.message || 'Invalid verification code. Please try again.';
                showError = true;
                otpCode = ''; // Clear the input
            }
        } catch (error) {
            console.error('Error verifying code:', error);
            errorMessage = 'Error verifying code. Please try again.';
            showError = true;
            otpCode = ''; // Clear the input
        } finally {
            isVerifying = false;
        }
    }

    function handleInput(event: Event) {
        const input = event.target as HTMLInputElement;
        // Only allow numbers and limit to 6 digits
        otpCode = input.value.replace(/\D/g, '').slice(0, 6);
        
        if (otpCode.length === 6) {
            // Verify the code when 6 digits are entered
            verifyCode(otpCode);
        }
    }

    async function handleResend() {
        try {
            const email = localStorage.getItem('signupEmail');
            const username = localStorage.getItem('signupUsername') || '';
            const inviteCode = localStorage.getItem('inviteCode') || '';
            
            if (!email) {
                errorMessage = 'Email address not found. Please go back and try again.';
                showError = true;
                return;
            }
            
            // If we don't have the invite code in localStorage, can't proceed
            if (!inviteCode) {
                errorMessage = 'Missing invite code. Please go back and try again.';
                showError = true;
                return;
            }
            
            const response = await fetch(getApiEndpoint(apiEndpoints.signup.request_confirm_email_code), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    email: email,
                    username: username,
                    invite_code: inviteCode
                }),
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                errorMessage = '';
                showError = false;
            } else {
                errorMessage = data.message || 'Failed to resend code. Please try again.';
                showError = true;
            }
        } catch (error) {
            console.error('Error resending code:', error);
            errorMessage = 'Error resending code. Please try again.';
            showError = true;
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
                disabled={isVerifying}
                class:error={showError}
            />
        </div>
        
        {#if showError}
            <div class="error-message">
                {errorMessage}
            </div>
        {/if}
    </div>
    
    <div class="resend-section">
        <span class="color-grey-60">{@html $text('signup.havent_received_a_code.text')}</span>
        <button class="text-button" on:click={handleResend} disabled={isVerifying}>
            {$text('signup.click_to_resend.text')}
        </button>
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
    
    .error-message {
        color: #e74c3c;
        font-size: 0.9rem;
        margin-top: 8px;
        text-align: center;
    }
    
    .error {
        border-color: #e74c3c !important;
    }
</style>
