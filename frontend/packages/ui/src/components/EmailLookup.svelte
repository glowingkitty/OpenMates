<script lang="ts">
    /**
     * EmailLookup.svelte - Separate component for email input and lookup
     * Handles the first step of the multi-step login flow
     */
    import { createEventDispatcher } from 'svelte';
    import { fade } from 'svelte/transition';
    import { text } from '@repo/ui';
    import InputWarning from './common/InputWarning.svelte';
    import Toggle from './Toggle.svelte';
    import { getApiEndpoint, apiEndpoints } from '../config/api';
    import * as cryptoService from '../services/cryptoService';
    import { sessionExpiredWarning } from '../stores/uiStateStore';
    import { base64ToUint8Array } from '../services/cryptoService';

    const dispatch = createEventDispatcher();

    // Props using Svelte 5 runes
    let { 
        email = $bindable(''),
        isLoading = $bindable(false),
        loginFailedWarning = $bindable(false),
        stayLoggedIn = $bindable(false)
    }: {
        email?: string;
        isLoading?: boolean;
        loginFailedWarning?: boolean;
        stayLoggedIn?: boolean;
    } = $props();

    // Form data
    let emailInputValue = $state(''); // Separate variable for the input field value
    let emailInput: HTMLInputElement = $state();

    // Email validation state
    let emailError = $state('');
    let showEmailWarning = $state(false);
    let isEmailValidationPending = $state(false);
    
    // Add rate limiting state
    const RATE_LIMIT_DURATION = 120000; // 120 seconds in milliseconds
    let isRateLimited = $state(false);
    let rateLimitTimer: ReturnType<typeof setTimeout>;

    // Add debounce helper
    function debounce<T extends (...args: any[]) => void>(
        fn: T,
        delay: number
    ): (...args: Parameters<T>) => void {
        let timeoutId: ReturnType<typeof setTimeout>;
        return (...args: Parameters<T>) => {
            clearTimeout(timeoutId);
            timeoutId = setTimeout(() => fn(...args), delay);
        };
    }

    // Email validation check
    const debouncedCheckEmail = debounce((email: string) => {
        if (!email) {
            emailError = '';
            showEmailWarning = false;
            isEmailValidationPending = false;
            return;
        }

        if (!email.includes('@')) {
            emailError = $text('signup.at_missing.text');
            showEmailWarning = true;
            isEmailValidationPending = false;
            return;
        }

        if (!email.match(/\.[a-z]{2,}$/i)) {
            emailError = $text('signup.domain_ending_missing.text');
            showEmailWarning = true;
            isEmailValidationPending = false;
            return;
        }

        emailError = '';
        showEmailWarning = false;
        isEmailValidationPending = false;
    }, 800);

    // Initialize emailInputValue with email using Svelte 5 runes
    $effect(() => {
        if (email && !emailInputValue) {
            emailInputValue = email;
        }
    });

    // Clear warnings when email changes and dispatch activity using Svelte 5 runes
    $effect(() => {
        if (emailInputValue) {
            loginFailedWarning = false;
            $sessionExpiredWarning = false;
            // Dispatch activity event for inactivity timer
            dispatch('userActivity');
        }
    });

    // Handle toggle changes and dispatch activity
    function handleToggleChange() {
        // Dispatch activity event when toggle is changed
        dispatch('userActivity');
    }

    // Update reactive statements to include email validation using Svelte 5 runes
    $effect(() => {
        if (emailInputValue) {
            isEmailValidationPending = true;
            debouncedCheckEmail(emailInputValue);
        } else {
            emailError = '';
            showEmailWarning = false;
            isEmailValidationPending = false;
        }
    });

    // Rate limiting functions
    function setRateLimitTimer(duration: number) {
        if (rateLimitTimer) clearTimeout(rateLimitTimer);
        rateLimitTimer = setTimeout(() => {
            isRateLimited = false;
            localStorage.removeItem('emailLookupRateLimit');
        }, duration);
    }

    // Validation state using Svelte 5 runes
    let hasValidEmail = $derived(emailInputValue && !emailError && !isEmailValidationPending);

    // Handle email lookup
    async function handleEmailLookup(event) {
        // Prevent default form submission behavior
        event.preventDefault();
        if (!hasValidEmail || isLoading) return;

        isLoading = true;
        loginFailedWarning = false;
        $sessionExpiredWarning = false;

        try {
            // Update the email value with the current input value
            email = emailInputValue;
            
            // Generate hashed email for lookup using cryptoService for consistency
            const hashed_email = await cryptoService.hashEmail(email);
            
            // Send hashed email to server to get available login methods
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.lookup), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                body: JSON.stringify({ hashed_email }),
                credentials: 'include'
            });
            
            // Check for rate limiting first
            if (response.status === 429) {
                console.warn("Rate limit hit for email lookup");
                isRateLimited = true;
                localStorage.setItem('emailLookupRateLimit', Date.now().toString());
                setRateLimitTimer(RATE_LIMIT_DURATION);
                return;
            }
            
            const data = await response.json();
            
            if (response.ok) {
                // Store the email salt if provided
                if (data.user_email_salt) {
                    try {
                        // Convert base64 string to Uint8Array and store it
                        const emailSalt = base64ToUint8Array(data.user_email_salt);
                        cryptoService.saveEmailSalt(emailSalt, stayLoggedIn);
                        console.debug('Email salt stored successfully');
                        
                        // Generate and store email encryption key for zero-knowledge email decryption
                        try {
                            // Derive email encryption key from email and salt
                            const emailEncryptionKey = await cryptoService.deriveEmailEncryptionKey(email, emailSalt);
                            // Store the email encryption key on the client for server communication
                            cryptoService.saveEmailEncryptionKey(emailEncryptionKey, stayLoggedIn);
                            console.debug('Email encryption key generated and stored successfully');
                        } catch (encKeyError) {
                            console.error('Error generating email encryption key:', encKeyError);
                            // Continue with login even if encryption key generation fails
                        }
                    } catch (error) {
                        console.error('Error storing email salt:', error);
                        // Continue with login even if salt storage fails
                    }
                }
                
                // Dispatch success event with email and available methods
                dispatch('lookupSuccess', {
                    email,
                    availableLoginMethods: data.available_login_methods || ['password', 'recovery_key'],
                    preferredLoginMethod: data.login_method || 'password',
                    stayLoggedIn,
                    tfa_app_name: data.tfa_app_name || null,
                    tfa_enabled: data.tfa_enabled || true // Include tfa_enabled flag from response
                });
                
                // Clear only the input field value after successful lookup
                emailInputValue = '';
            } else {
                // Handle error
                console.warn("Email lookup failed:", data.error || "Unknown error");
                loginFailedWarning = true;
                // Still dispatch with default methods if lookup fails
                dispatch('lookupSuccess', {
                    email,
                    availableLoginMethods: ['password', 'recovery_key'],
                    preferredLoginMethod: 'password',
                    stayLoggedIn,
                    tfa_app_name: null,
                    tfa_enabled: true // Default to false if lookup fails
                });
                
                // Clear only the input field value after lookup
                emailInputValue = '';
            }
        } catch (error) {
            console.error('Email lookup error:', error);
            loginFailedWarning = true;
            // Still dispatch with default methods if lookup fails
            dispatch('lookupSuccess', {
                email,
                availableLoginMethods: ['password'],
                preferredLoginMethod: 'password',
                stayLoggedIn,
                tfa_app_name: null,
                tfa_enabled: true // Default to false if lookup fails
            });
            
            // Clear only the input field value after lookup
            emailInputValue = '';
        } finally {
            isLoading = false;
        }
    }

    // Expose email value to parent
    export { email };

    // Focus input when component mounts (if not touch device)
    import { onMount } from 'svelte';
    let isTouchDevice = false;

    onMount(() => {
        isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
        
        // Clear the input field value when component mounts
        emailInputValue = '';
        
        if (emailInput && !isTouchDevice) {
            emailInput.focus();
        }
        
        // Check if we're still rate limited on mount
        const rateLimitTimestamp = localStorage.getItem('emailLookupRateLimit');
        if (rateLimitTimestamp) {
            const timeLeft = parseInt(rateLimitTimestamp) + RATE_LIMIT_DURATION - Date.now();
            if (timeLeft > 0) {
                isRateLimited = true;
                setRateLimitTimer(timeLeft);
            } else {
                localStorage.removeItem('emailLookupRateLimit');
            }
        }
    });
</script>

<div class="email-lookup" in:fade={{ duration: 300 }}>
    {#if isRateLimited}
        <div class="rate-limit-message" in:fade={{ duration: 200 }}>
            {$text('signup.too_many_requests.text')}
        </div>
    {:else}
        <form onsubmit={handleEmailLookup}>
            <div class="input-group">
                <div class="input-wrapper">
                    <span class="clickable-icon icon_mail"></span>
                    <input
                        type="email"
                        name="username"
                        bind:value={emailInputValue}
                        bind:this={emailInput}
                        placeholder={$text('login.email_placeholder.text')}
                        required
                        autocomplete="username"
                        class:error={!!emailError || loginFailedWarning || $sessionExpiredWarning}
                    />
                    {#if showEmailWarning && emailError}
                        <InputWarning
                            message={emailError}
                            target={emailInput}
                        />
                    {:else if loginFailedWarning}
                        <InputWarning
                            message={$text('login.login_failed.text')}
                            target={emailInput}
                        />
                    {:else if $sessionExpiredWarning}
                        <InputWarning
                            message={$text('login.session_expired.text')}
                            target={emailInput}
                        />
                    {/if}
                </div>
            </div>

            <div class="input-group toggle-group">
                <Toggle
                    id="stayLoggedIn"
                    name="stayLoggedIn"
                    bind:checked={stayLoggedIn}
                    ariaLabel={$text('login.stay_logged_in.text')}
                    on:change={handleToggleChange}
                />
                <label for="stayLoggedIn" class="agreement-text">{@html $text('login.stay_logged_in.text')}</label>
            </div>

            <button
                type="submit"
                class="login-button"
                disabled={isLoading || !hasValidEmail}
            >
                {#if isLoading}
                    <span class="loading-spinner"></span>
                {:else}
                    {$text('signup.continue.text')}
                {/if}
            </button>
        </form>
    {/if}
</div>

<style>
    .email-lookup {
        display: flex;
        flex-direction: column;
        width: 100%;
    }

    .loading-spinner {
        border: 3px solid rgba(255, 255, 255, 0.3);
        border-radius: 50%;
        border-top: 3px solid white;
        width: 18px;
        height: 18px;
        animation: spin 1s linear infinite;
    }

    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }

    .toggle-group {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 12px;
        max-width: 350px;
        margin: 15px auto;
    }

    .agreement-text {
        text-align: left;
        cursor: pointer;
    }

    .rate-limit-message {
        color: var(--color-error);
        padding: 24px;
        text-align: center;
        font-weight: 500;
        font-size: 16px;
        line-height: 1.5;
        background-color: var(--color-error-light);
        border-radius: 8px;
        margin: 24px 0;
    }
</style>