<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { fade } from 'svelte/transition';
    import { text } from '@repo/ui';
    import WaitingList from '../../../WaitingList.svelte';
    import Toggle from '../../../Toggle.svelte';
    import { requireInviteCode } from '../../../../stores/signupRequirements';
    import { getApiEndpoint, apiEndpoints } from '../../../../config/api';
    import { tick } from 'svelte';
    import { externalLinks, getWebsiteUrl } from '../../../../config/links';
    import { onMount, onDestroy } from 'svelte';
    import { get } from 'svelte/store';
    import InputWarning from '../../../common/InputWarning.svelte';
    import { updateUsername } from '../../../../stores/userProfile';
    import { signupStore } from '../../../../stores/signupStore';
    import * as cryptoService from '../../../../services/cryptoService';

    const dispatch = createEventDispatcher();

    // --- Inactivity Timer ---
    const SIGNUP_INACTIVITY_TIMEOUT_MS = 120000; // 2 minutes
    let signupTimer: ReturnType<typeof setTimeout> | null = null;
    let isSignupTimerActive = false;
    // --- End Inactivity Timer ---

    // Props using Svelte 5 runes mode
    let { isValidated = false, is_admin = false }: { isValidated?: boolean, is_admin?: boolean } = $props();
    
    // Form state using Svelte 5 runes
    let inviteCode = $state('');
    let isValidFormat = $state(false);
    let isLoading = $state(false);
    let showWarning = $state(false);

    // Signup form fields using Svelte 5 runes
    let username = $state('');
    let email = $state('');

    // Agreement toggles state using Svelte 5 runes
    let termsAgreed = $state(false);
    let privacyAgreed = $state(false);
    let stayLoggedIn = $state(false); // Add stay logged in toggle

    // Add reference for the input using Svelte 5 runes
    let inviteCodeInput = $state<HTMLInputElement>();
    let usernameInput = $state<HTMLInputElement>();
    let emailInput = $state<HTMLInputElement>();

    // Add state for input warnings using Svelte 5 runes
    let showEmailWarning = $state(false);
    let emailError = $state('');

    // Add email validation state tracker using Svelte 5 runes
    let isEmailValidationPending = $state(false);
    let emailAlreadyInUse = $state(false); // Add new state variable

    // Add username validation state using Svelte 5 runes
    let showUsernameWarning = $state(false);
    let usernameError = $state('');
    let isUsernameValidationPending = $state(false);

    const RATE_LIMIT_DURATION = 120000; // 120 seconds in milliseconds
    let isRateLimited = $state(false);
    let rateLimitTimer = $state<ReturnType<typeof setTimeout>>();

    // Add touch detection
    let isTouchDevice = false;

    // Auto-validate if invite code is not required using Svelte 5 runes
    $effect(() => {
        if (!$requireInviteCode && !isValidated) {
            console.debug("Invite code not required, auto-validating");
            isValidated = true;
            is_admin = false; // Non-invite users are not admins
        }
    });

    onMount(() => {
        // Restore state from store when coming back to this step
        const storeData = get(signupStore);
        if (storeData) {
            username = storeData.username || '';
            email = storeData.email || '';
            inviteCode = storeData.inviteCode || '';
        }

        // Subscribe to store changes to clear local state when store is cleared for privacy
        const unsubscribe = signupStore.subscribe(storeData => {
            // If store data is cleared (empty strings), clear local state
            if (storeData.email === '' && storeData.username === '' && storeData.inviteCode === '') {
                username = '';
                email = '';
                inviteCode = '';
                // Also clear form state for privacy
                termsAgreed = false;
                privacyAgreed = false;
                stayLoggedIn = false;
                // Clear any error states
                showEmailWarning = false;
                emailError = '';
                emailAlreadyInUse = false;
                showUsernameWarning = false;
                usernameError = '';
            }
        });

        // Check if device is touch-enabled
        isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;

        // Check if we're still rate limited
        const rateLimitTimestamp = localStorage.getItem('inviteCodeRateLimit');
        if (rateLimitTimestamp) {
            const timeLeft = parseInt(rateLimitTimestamp) + RATE_LIMIT_DURATION - Date.now();
            if (timeLeft > 0) {
                isRateLimited = true;
                setRateLimitTimer(timeLeft);
            } else {
                localStorage.removeItem('inviteCodeRateLimit');
            }
        }

        // Focus the invite code input when component mounts (if not rate limited and not touch device)
        if (inviteCodeInput && !isRateLimited && !isTouchDevice) {
            inviteCodeInput.focus();
        }

        // --- Inactivity Timer Cleanup ---
        return () => {
            if (rateLimitTimer) {
                clearTimeout(rateLimitTimer);
            }
            // Clear signup timer on component destruction
            if (signupTimer) {
                clearTimeout(signupTimer);
                console.debug("Signup Step Basics inactivity timer cleared on destroy");
            }
            // Cleanup store subscription
            if (unsubscribe) {
                unsubscribe();
            }
        };
        // --- End Inactivity Timer Cleanup ---
    });

    onDestroy(() => {
        if (rateLimitTimer) {
            clearTimeout(rateLimitTimer);
        }
        // Ensure signup timer is cleared if onMount cleanup didn't run or failed
        if (signupTimer) {
            clearTimeout(signupTimer);
        }
    });

    // --- Inactivity Timer Functions ---
    function handleSignupTimeout() {
        console.debug("Signup Step Basics inactivity timeout triggered.");
        // Clear local state
        username = '';
        email = '';
        termsAgreed = false;
        privacyAgreed = false;
        stayLoggedIn = false;
        // Clear errors/warnings related to these fields
        showEmailWarning = false;
        emailError = '';
        emailAlreadyInUse = false;
        showUsernameWarning = false;
        usernameError = '';

        stopSignupTimer(); // Stop the timer state

        // Dispatch event to request switch back to login
        dispatch('requestSwitchToLogin');
    }

    function resetSignupTimer() {
        if (signupTimer) clearTimeout(signupTimer);
        console.debug("Resetting Signup Step Basics inactivity timer...");
        signupTimer = setTimeout(handleSignupTimeout, SIGNUP_INACTIVITY_TIMEOUT_MS);
        isSignupTimerActive = true;
    }

    function stopSignupTimer() {
        if (signupTimer) {
            clearTimeout(signupTimer);
            console.debug("Stopping Signup Step Basics inactivity timer.");
            signupTimer = null;
        }
        isSignupTimerActive = false;
    }

    function checkSignupActivityAndManageTimer() {
        // Check if any relevant field has content (only when signup form is shown)
        if (isValidated && (username || email)) {
             if (!isSignupTimerActive) {
                console.debug("Signup Step Basics activity detected, starting timer.");
            }
            resetSignupTimer();
        } else if (isValidated) {
            // If validated but all fields are empty, stop the timer
             if (isSignupTimerActive) {
                console.debug("Signup Step Basics fields empty, stopping timer.");
                stopSignupTimer();
            }
        }
        // If not validated (invite code screen), timer remains stopped.
    }
    // --- End Inactivity Timer Functions ---


    function setRateLimitTimer(duration: number) {
        if (rateLimitTimer) clearTimeout(rateLimitTimer);
        rateLimitTimer = setTimeout(() => {
            isRateLimited = false;
            localStorage.removeItem('inviteCodeRateLimit');
        }, duration);
    }

    // Watch for changes in isValidated using Svelte 5 runes
    $effect(() => {
        if (isValidated && emailInput && !isTouchDevice) {
            // Use tick to ensure DOM is updated
            tick().then(() => {
                emailInput.focus();
            });
        }
    });

    // Format the invite code as user types
    function formatInviteCode(code: string): string {
        // Remove any non-alphanumeric characters first
        const cleaned = code.replace(/[^A-Z0-9]/gi, '');
        
        // Split into groups of 4
        const groups = [];
        for (let i = 0; i < cleaned.length && i < 12; i += 4) {
            groups.push(cleaned.slice(i, i + 4));
        }
        
        // Join with hyphens
        return groups.join('-');
    }

    // Handle input changes
    async function handleInviteCodeInput(event: Event) {
        const input = event.target as HTMLInputElement;
        const cursorPosition = input.selectionStart || 0;
        const previousLength = inviteCode.length;
        
        // Format the code
        const formatted = formatInviteCode(input.value.toUpperCase());
        inviteCode = formatted;

        // Hide warning if field is empty
        if (!formatted) {
            showWarning = false;
        }
        
        // Calculate new cursor position
        await tick(); // Wait for DOM update
        const newPosition = cursorPosition + (formatted.length - previousLength);
        input.setSelectionRange(newPosition, newPosition);
        
        // Check if the format is valid
        isValidFormat = /^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/i.test(formatted);
        
        if (isValidFormat) {
            await validateInviteCode();
        }
    }

    // Handle paste event
    function handlePaste(event: ClipboardEvent) {
        event.preventDefault();
        const pastedText = event.clipboardData?.getData('text') || '';
        const formatted = formatInviteCode(pastedText.toUpperCase());
        inviteCode = formatted;
        
        if (/^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/i.test(formatted)) {
            validateInviteCode();
        }
    }

    // Validate invite code with server
    async function validateInviteCode() {
        isLoading = true;
        showWarning = false;

        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.check_invite_token_valid), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ invite_code: inviteCode }),
                credentials: 'include'  // Important: This sends cookies with the request
            });

            // Check for rate limiting first
            if (response.status === 429) {
                isRateLimited = true;
                localStorage.setItem('inviteCodeRateLimit', Date.now().toString());
                setRateLimitTimer(RATE_LIMIT_DURATION);
                return;
            }

            // Check for server errors
            if (!response.ok) {
                console.error('Server error:', response.status);
                showWarning = true;
                isValidated = false;
                return;
            }

            const data = await response.json();

            if (data.valid) {
                isValidated = true;
                if (data.is_admin) {
                    is_admin = true;
                } else {
                    is_admin = false;
                }
            } else {
                showWarning = true;
                isValidated = false;
                is_admin = false;
            }
        } catch (error) {
            console.error('Error validating invite code:', error);
            showWarning = true;
            isValidated = false;
            is_admin = false;
        } finally {
            isLoading = false;
        }
    }

    // Handle form submission
    async function handleSubmit(event: Event) {
        event.preventDefault();
        
        if (emailAlreadyInUse) {
            return;
        }

        try {
            isLoading = true;
            
            // Get current language from localStorage or use browser default
            const currentLang = localStorage.getItem('preferredLanguage') || 
                              navigator.language.split('-')[0] || 
                              'en';
            
            // Get dark mode setting from system preference or user setting
            const prefersDarkMode = window.matchMedia && 
                                  window.matchMedia('(prefers-color-scheme: dark)').matches;
            const darkModeEnabled = localStorage.getItem('darkMode') === 'true' || prefersDarkMode;

            // Hash the email for lookup and uniqueness check
            const hashedEmail = await cryptoService.hashEmail(email);
            
            // Request email verification code
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.request_confirm_email_code), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    email: email,
                    hashed_email: hashedEmail,
                    invite_code: $requireInviteCode ? inviteCode : "", // Only send invite code if required
                    language: currentLang,
                    darkmode: darkModeEnabled
                }),
                credentials: 'include'
            });

            if (response.status === 429) {
                isRateLimited = true;
                localStorage.setItem('inviteCodeRateLimit', Date.now().toString());
                setRateLimitTimer(RATE_LIMIT_DURATION);
                return;
            }

            const data = await response.json();

            if (response.ok && data.success) {
                // Update the Svelte store
                signupStore.update(store => ({
                    ...store,
                    email,
                    username,
                    inviteCode,
                    language: currentLang,
                    darkmode: darkModeEnabled,
                    stayLoggedIn: stayLoggedIn
                }));
                
                // Dispatch the next event to transition to step 2
                dispatch('next');
            } else {
                if (data.error_code === 'EMAIL_ALREADY_EXISTS') {
                    emailAlreadyInUse = true;
                    showEmailWarning = true;
                    if (emailInput && !isTouchDevice) {
                        emailInput.focus();
                    }
                } else if (data.error_code === 'DOMAIN_NOT_ALLOWED') {
                    showEmailWarning = true;
                    emailError = $text('signup.domain_not_allowed.text');
                    if (emailInput && !isTouchDevice) {
                        emailInput.focus();
                    }
                } else {
                    showWarning = true;
                    console.error('Error requesting verification code:', data.message);
                }
            }
        } catch (error) {
            showWarning = true;
            console.error('Error during signup Step Basics:', error);
        } finally {
            isLoading = false;
        }
    }

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


    // Modify email validation check
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

    // Update username validation function
    const checkUsername = (username: string): boolean => {
        if (!username) {
            usernameError = '';
            showUsernameWarning = false;
            return true;
        }

        // Normalize the username to handle combining characters
        const normalizedUsername = username.normalize('NFC');

        if (normalizedUsername.length < 3) {
            usernameError = $text('signup.username_too_short.text');
            showUsernameWarning = true;
            return false;
        }

        if (normalizedUsername.length > 20) {
            usernameError = $text('signup.username_too_long.text');
            showUsernameWarning = true;
            return false;
        }

        // Check for at least one letter (including international letters)
        if (!/\p{L}/u.test(normalizedUsername)) {
            usernameError = $text('signup.password_needs_letter.text');
            showUsernameWarning = true;
            return false;
        }

        // Allow letters (including international), numbers, dots, and underscoress        // Include specific Unicode ranges for Thai [\u0E00-\u0E7F]
        if (!/^[\p{L}\p{M}0-9._]+$/u.test(normalizedUsername)) {
            usernameError = $text('signup.username_invalid_chars.text');
            showUsernameWarning = true;
            return false;
        }

        usernameError = '';
        showUsernameWarning = false;
        return true;
    };

    // Update debounced username check to clear warnings when empty
    const debouncedCheckUsername = debounce((username: string) => {
        if (!username) {
            usernameError = '';
            showUsernameWarning = false;
            isUsernameValidationPending = false;
            return;
        }
        isUsernameValidationPending = false;
        checkUsername(username);
    }, 500);

    // Helper function to check if form is valid using Svelte 5 runes
    let isFormValid = $derived(username && 
                     !usernameError &&
                     !isUsernameValidationPending &&
                     email && 
                     !emailError &&
                     !isEmailValidationPending &&
                     !emailAlreadyInUse && // Block submission if email is already in use
                     termsAgreed && 
                     privacyAgreed);

    // Update reactive statements to include email validation using Svelte 5 runes
    $effect(() => {
        if (email) {
            isEmailValidationPending = true;
            emailAlreadyInUse = false; // Reset the already in use warning when email changes
            debouncedCheckEmail(email);
        } else {
            emailError = '';
            showEmailWarning = false;
            isEmailValidationPending = false;
            emailAlreadyInUse = false;
        }
    });

    // Update reactive statements to include username validation using Svelte 5 runes
    $effect(() => {
        if (!username) {
            usernameError = '';
            showUsernameWarning = false;
            isUsernameValidationPending = false;
        } else {
            isUsernameValidationPending = true;
            debouncedCheckUsername(username);
        }
    });

    // Add watcher to update the username store when it changes using Svelte 5 runes
    $effect(() => {
        if (username) {
            updateUsername(username);
        }
    });
</script>

<div class="content-area">
    <h1><mark>{@html $text('signup.sign_up.text')}</mark></h1>
    <h2>{@html $text('login.to_chat_to_your.text')}<br><mark>{@html $text('login.digital_team_mates.text')}</mark></h2>
    
    <div class="form-container">
        {#if !isValidated && $requireInviteCode}
            <form>
                <div class="input-group">
                    {#if isRateLimited}
                        <div class="rate-limit-message" transition:fade>
                            {$text('signup.too_many_requests.text')}
                        </div>
                    {:else}
                        <div class="input-wrapper">
                            <span class="clickable-icon icon_secret"></span>
                            <input 
                                bind:this={inviteCodeInput}
                                type="text" 
                                bind:value={inviteCode}
                                oninput={handleInviteCodeInput}
                                onpaste={handlePaste}
                                placeholder={$text('signup.enter_personal_invite_code.text')}
                                maxlength="14"
                                disabled={isLoading}
                            />
                            {#if showWarning}
                                <InputWarning 
                                    message={$text('signup.code_is_invalid.text')}
                                    target={inviteCodeInput}
                                />
                            {/if}
                        </div>
                    {/if}
                    {#if isLoading}
                        <div class="loading-message-container" transition:fade>
                            <div class="loading-message">
                                {$text('signup.checking_code.text')}
                            </div>
                        </div>
                    {/if}
                </div>
            </form>

        {:else}
            <form onsubmit={handleSubmit}>
                <div class="input-group">
                    <div class="input-wrapper">
                        <span class="clickable-icon icon_mail"></span>
                        <input 
                            bind:this={emailInput}
                            type="email" 
                            bind:value={email}
                            placeholder={$text('login.email_placeholder.text')}
                            required
                            autocomplete="email"
                            class:error={!!emailError || emailAlreadyInUse}
                            oninput={(e) => {
                                checkSignupActivityAndManageTimer();
                                // Auto-fill username based on email if username is empty
                                if (!username && email.includes('@')) {
                                    const emailParts = email.split('@');
                                    username = emailParts[0];
                                }
                            }} />
                        {#if showEmailWarning && emailError}
                            <InputWarning
                                message={emailError}
                                target={emailInput}
                            />
                        {/if}
                        {#if emailAlreadyInUse}
                            <InputWarning 
                                message={$text('signup.email_address_already_in_use.text')}
                                target={emailInput}
                            />
                        {/if}
                    </div>
                </div>

                <div class="input-group">
                    <div class="input-wrapper">
                        <span class="clickable-icon icon_user"></span>
                        <input 
                            bind:this={usernameInput}
                            type="text" 
                            bind:value={username}
                            placeholder={$text('signup.enter_username.text')}
                            required
                            autocomplete="username"
                            class:error={!!usernameError}
                            oninput={checkSignupActivityAndManageTimer} />
                        {#if showUsernameWarning && usernameError}
                            <InputWarning
                                message={usernameError}
                                target={usernameInput}
                            />
                        {/if}
                    </div>
                </div>

                <div class="agreement-row">
                    <Toggle 
                        id="stayLoggedIn" 
                        name="stayLoggedIn" 
                        bind:checked={stayLoggedIn} 
                        ariaLabel={$text('login.stay_logged_in.text')} 
                    />
                    <label for="stayLoggedIn" class="agreement-text">{@html $text('login.stay_logged_in.text')}</label>
                </div>

                <div class="agreement-row">
                    <Toggle bind:checked={termsAgreed} id="terms-agreed-toggle" />
                    <label for="terms-agreed-toggle" class="agreement-text">
                        {$text('signup.agree_to.text')} 
                        <a href={getWebsiteUrl(externalLinks.legal.terms)} target="_blank" rel="noopener noreferrer">
                            <mark>{@html $text('signup.terms_of_service.text')}</mark>
                        </a>
                    </label>
                </div>

                <div class="agreement-row">
                    <Toggle bind:checked={privacyAgreed} id="privacy-agreed-toggle" />
                    <label for="privacy-agreed-toggle" class="agreement-text">
                        {$text('signup.agree_to.text')} 
                        <a href={getWebsiteUrl(externalLinks.legal.privacyPolicy)} target="_blank" rel="noopener noreferrer">
                            <mark>{@html $text('signup.privacy_policy.text')}</mark>
                        </a>
                    </label>
                </div>
            </form>
        {/if}
    </div>
    <div class="bottom-positioned">
        {#if !isValidated && $requireInviteCode}
            <WaitingList showPersonalInviteMessage={true} />
        {:else}
            {#if isRateLimited}
                <div class="rate-limit-message" transition:fade>
                    {$text('signup.too_many_requests.text')}
                </div>
            {:else}
                <div class="action-button-container">
                    <button 
                        class="action-button signup-button" 
                        class:loading={isLoading}
                        disabled={!isFormValid || isLoading}
                        onclick={handleSubmit}
                        transition:fade
                    >
                        {isLoading ? $text('login.loading.text') : $text('signup.create_new_account.text')}
                    </button>
                </div>
            {/if}
        {/if}
    </div>
</div>

<style>
    .action-button.loading {
        opacity: 0.6;
        cursor: not-allowed;
    }

    .agreement-text {
        text-align: left;
        cursor: pointer;
    }
</style>
