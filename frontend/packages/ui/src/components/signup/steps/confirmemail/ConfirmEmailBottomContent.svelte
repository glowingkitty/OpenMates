<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount } from 'svelte';
    import { createEventDispatcher } from 'svelte';
    import { getApiEndpoint, apiEndpoints } from '../../../../config/api';
    import { currentSignupStep, isInSignupProcess } from '../../../../stores/signupState';
    import { signupStore } from '../../../../stores/signupStore';
    import { get } from 'svelte/store';
    
    let otpCode = $state('');
    let otpInput: HTMLInputElement;
    const dispatch = createEventDispatcher();
    
    let isVerifying = $state(false);
    let errorMessage = $state('');
    let showError = $state(false);

    onMount(() => {
        // Check if device is touch-enabled
        const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;

        // Only auto-focus on non-touch devices
        if (otpInput && !isTouchDevice) {
            otpInput.focus();
        }
    });

    /** Maximum number of verification attempts for transient "code not found" errors. */
    const MAX_VERIFY_ATTEMPTS = 3;
    /** Delay (ms) between retry attempts — gives the Celery email task time to
     *  finish writing the verification code to cache. */
    const VERIFY_RETRY_DELAY_MS = 2000;

    /**
     * Verify the email confirmation code against the backend.
     *
     * Architecture note: The signup flow dispatches a Celery task to generate
     * the code, store it in Redis, and send the email. Because the API returns
     * "success" *before* the Celery task completes, there is a short window
     * where the code is not yet in cache. If the user (or a Playwright test)
     * enters the code very quickly, the verification can fail with
     * "No verification code requested for this email or code expired."
     *
     * To handle this race condition we retry up to MAX_VERIFY_ATTEMPTS times
     * with a short delay, but ONLY for that specific transient error. Wrong
     * codes and other errors surface immediately without retry.
     */
    async function verifyCode(code: string) {
        if (isVerifying) return; // Prevent re-execution if already verifying
        if (code.length !== 6) return;

        isVerifying = true;
        errorMessage = '';
        showError = false;

        const storeData = get(signupStore);

        for (let attempt = 1; attempt <= MAX_VERIFY_ATTEMPTS; attempt++) {
            try {
                const response = await fetch(getApiEndpoint(apiEndpoints.auth.check_confirm_email_code), {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        code: code,
                        email: storeData.email,
                        username: storeData.username,
                        invite_code: storeData.inviteCode,
                        language: storeData.language,
                        darkmode: storeData.darkmode
                    }),
                    credentials: 'include'
                });

                const data = await response.json();

                if (response.ok && data.success) {
                    // In the new architecture, email verification doesn't create a user yet
                    // It just verifies the email and stores verification status in cache

                    // Make sure we stay in signup flow and move to secure account step
                    currentSignupStep.set('secure_account');
                    isInSignupProcess.set(true);

                    // Proceed to next step on success
                    dispatch('step', { step: 'secure_account' });
                    isVerifying = false;
                    return;
                }

                // Transient "code not yet in cache" error — retry after a short delay.
                // The Celery task that stores the code may still be in flight.
                const isCodeNotFound = typeof data.message === 'string' &&
                    data.message.toLowerCase().includes('no verification code');

                if (isCodeNotFound && attempt < MAX_VERIFY_ATTEMPTS) {
                    console.debug(
                        `[ConfirmEmail] Code not in cache yet (attempt ${attempt}/${MAX_VERIFY_ATTEMPTS}), retrying in ${VERIFY_RETRY_DELAY_MS}ms...`
                    );
                    await new Promise(resolve => setTimeout(resolve, VERIFY_RETRY_DELAY_MS));
                    continue;
                }

                // Final attempt or non-transient error — show to user
                errorMessage = data.message || 'Invalid verification code. Please try again.';
                showError = true;
                otpCode = ''; // Clear the input
                isVerifying = false;
                return;
            } catch (error) {
                console.error('Error verifying code:', error);

                // Network errors on non-final attempts get a retry
                if (attempt < MAX_VERIFY_ATTEMPTS) {
                    console.debug(
                        `[ConfirmEmail] Network error (attempt ${attempt}/${MAX_VERIFY_ATTEMPTS}), retrying in ${VERIFY_RETRY_DELAY_MS}ms...`
                    );
                    await new Promise(resolve => setTimeout(resolve, VERIFY_RETRY_DELAY_MS));
                    continue;
                }

                errorMessage = 'Error verifying code. Please try again.';
                showError = true;
                otpCode = ''; // Clear the input
                isVerifying = false;
                return;
            }
        }

        isVerifying = false;
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
</script>

<div class="bottom-content">
    <div class="input-group">
        <div class="input-wrapper">
            <span class="clickable-icon icon_2fa" class:fade-out={isVerifying}></span>
            <div class="overlay-container">
                <input
                    bind:this={otpInput}
                    type="text"
                    bind:value={otpCode}
                    oninput={handleInput}
                    placeholder={$text('signup.enter_one_time_code')}
                    inputmode="numeric"
                    maxlength="6"
                    disabled={isVerifying}
                    class:error={showError}
                    class:fade-out={isVerifying}
                />
                <div class="loading-text color-grey-80" class:fade-in={isVerifying}>
                    {$text('common.loading')}
                </div>
            </div>
        </div>
        
        {#if showError}
            <div class="error-message">
                {errorMessage}
            </div>
        {/if}
    </div>
</div>

<style>
    .bottom-content {
        padding: var(--spacing-12);
        display: flex;
        flex-direction: column;
        gap: var(--spacing-8);
    }

    .error-message {
        color: var(--color-error);
        font-size: 0.9rem;
        margin-top: var(--spacing-4);
        text-align: center;
    }
    
    .error {
        border-color: var(--color-error) !important;
    }

    .overlay-container {
        position: relative;
        display: inline-block; /* Changed from width: 100% to maintain original size */
        flex: 1; /* Maintain flex properties that were on the input */
    }

    .overlay-container input {
        width: 100%; /* Ensure input keeps its width */
        box-sizing: border-box;
    }

    .fade-in {
        animation: fadeIn 0.3s ease-in-out forwards;
    }

    .fade-out {
        animation: fadeOut 0.3s ease-in-out forwards;
    }

    .loading-text {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0;
        pointer-events: none; /* Prevents interfering with input interaction */
    }


    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }

    @keyframes fadeOut {
        from { opacity: 1; }
        to { opacity: 0; }
    }
</style>
