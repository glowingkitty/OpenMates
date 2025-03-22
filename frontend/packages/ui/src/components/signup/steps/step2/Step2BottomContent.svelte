<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount } from 'svelte';
    import { createEventDispatcher } from 'svelte';
    import { getApiEndpoint, apiEndpoints } from '../../../../config/api';
    import { authStore } from '../../../../stores/authStore';
    import { currentSignupStep, isInSignupProcess } from '../../../../stores/signupState';
    import { userDB } from '../../../../services/userDB';
    import { updateProfile } from '../../../../stores/userProfile';
    
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
            
            // We don't need to send email or invite code in the body anymore
            // as they are already in HTTP-only cookies
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.check_confirm_email_code), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    code: code
                }),
                credentials: 'include'  // Important: This sends cookies with the request
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                // User is now created and logged in automatically
                
                // Update auth store with user information
                if (data.user) {
                    // Prepare complete user data object
                    const userData = {
                        id: data.user.id,
                        username: data.user.username || 'User',
                        isAdmin: data.user.is_admin || false,
                        profileImageUrl: data.user.profile_image_url || data.user.avatar_url || null,
                        last_opened: data.user.last_opened || null,
                        credits: data.user.credits || 0
                    };

                    // Use the unified authStore to complete signup
                    authStore.completeSignup(data.user);
                    
                    // Save user data to IndexedDB
                    try {
                        await userDB.saveUserData(userData);
                        
                        // Update the user profile store
                        updateProfile({
                            username: userData.username,
                            profileImageUrl: userData.profileImageUrl,
                            credits: userData.credits,
                            isAdmin: userData.isAdmin,
                            last_opened: userData.last_opened
                        });
                    } catch (dbError) {
                        console.error("Failed to save user data to database:", dbError);
                    }
                    
                    // Make sure we stay in signup flow and move to step 3
                    currentSignupStep.set(3);
                    isInSignupProcess.set(true);
                }
                
                // Proceed to next step on success
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
                    on:input={handleInput}
                    placeholder={$text('signup.enter_one_time_code.text')}
                    inputmode="numeric"
                    maxlength="6"
                    disabled={isVerifying}
                    class:error={showError}
                    class:fade-out={isVerifying}
                />
                <div class="loading-text color-grey-80" class:fade-in={isVerifying}>
                    {$text('login.loading.text')}
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
        padding: 24px;
        display: flex;
        flex-direction: column;
        gap: 16px;
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

    .color-grey-60 {
        color: rgba(0, 0, 0, 0.6);
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
