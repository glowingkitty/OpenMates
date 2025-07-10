<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { fade } from 'svelte/transition';
    import { text } from '@repo/ui';
    import WaitingList from '../../../WaitingList.svelte';
    import Toggle from '../../../Toggle.svelte';
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

    let inviteCode = '';
    let isValidFormat = false;
    let isLoading = false;
    export let isValidated = false;
    export let is_admin = false;
    let showWarning = false;

    // Signup form fields
    let username = '';
    let email = '';
    let password = '';
    let passwordRepeat = '';

    // Agreement toggles state
    let termsAgreed = false;
    let privacyAgreed = false;

    let passwordError = '';
    let passwordStrengthError = '';

    // Add reference for the input
    let inviteCodeInput: HTMLInputElement;
    let usernameInput: HTMLInputElement;
    let passwordInput: HTMLInputElement;
    let passwordRepeatInput: HTMLInputElement;
    let emailInput: HTMLInputElement;

    // Add state for input warnings
    let showPasswordStrengthWarning = false;
    let showPasswordMatchWarning = false;
    let showEmailWarning = false;
    let emailError = '';

    // Add email validation state tracker
    let isEmailValidationPending = false;
    let emailAlreadyInUse = false; // Add new state variable

    // Add username validation state
    let showUsernameWarning = false;
    let usernameError = '';
    let isUsernameValidationPending = false;

    const RATE_LIMIT_DURATION = 120000; // 120 seconds in milliseconds
    let isRateLimited = false;
    let rateLimitTimer: ReturnType<typeof setTimeout>;

    // Add touch detection
    let isTouchDevice = false;

    onMount(() => {
        // Restore state from store when coming back to this step
        const storeData = get(signupStore);
        if (storeData) {
            username = storeData.username || '';
            email = storeData.email || '';
            inviteCode = storeData.inviteCode || '';
        }

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
                console.debug("Signup Step 1 inactivity timer cleared on destroy");
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
        console.debug("Signup Step 1 inactivity timeout triggered.");
        // Clear local state
        username = '';
        email = '';
        password = '';
        passwordRepeat = '';
        termsAgreed = false;
        privacyAgreed = false;
        // Clear errors/warnings related to these fields
        passwordError = '';
        passwordStrengthError = '';
        showPasswordStrengthWarning = false;
        showPasswordMatchWarning = false;
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
        console.debug("Resetting Signup Step 1 inactivity timer...");
        signupTimer = setTimeout(handleSignupTimeout, SIGNUP_INACTIVITY_TIMEOUT_MS);
        isSignupTimerActive = true;
    }

    function stopSignupTimer() {
        if (signupTimer) {
            clearTimeout(signupTimer);
            console.debug("Stopping Signup Step 1 inactivity timer.");
            signupTimer = null;
        }
        isSignupTimerActive = false;
    }

    function checkSignupActivityAndManageTimer() {
        // Check if any relevant field has content (only when signup form is shown)
        if (isValidated && (username || email || password || passwordRepeat)) {
             if (!isSignupTimerActive) {
                console.debug("Signup Step 1 activity detected, starting timer.");
            }
            resetSignupTimer();
        } else if (isValidated) {
            // If validated but all fields are empty, stop the timer
             if (isSignupTimerActive) {
                console.debug("Signup Step 1 fields empty, stopping timer.");
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

    // Watch for changes in isValidated
    $: if (isValidated && usernameInput && !isTouchDevice) {
        // Use tick to ensure DOM is updated
        tick().then(() => {
            usernameInput.focus();
        });
    }

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
        
        if (!passwordsMatch || emailAlreadyInUse) {
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

            // --- New Crypto and Store Logic ---
            // 1. Generate master key and salt
            const masterKey = cryptoService.generateUserMasterKey();
            const salt = cryptoService.generateSalt();

            // 2. Derive wrapping key from password
            const wrappingKey = await cryptoService.deriveKeyFromPassword(password, salt);

            // 3. Encrypt (wrap) the master key
            const encryptedMasterKey = cryptoService.encryptKey(masterKey, wrappingKey);

            // Request email verification code
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.request_confirm_email_code), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    email: email,
                    invite_code: inviteCode,
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
            // 4. Update the Svelte store
            let saltBinary = '';
            const saltLen = salt.byteLength;
            for (let i = 0; i < saltLen; i++) {
                saltBinary += String.fromCharCode(salt[i]);
            }
            const saltB64 = window.btoa(saltBinary);

            signupStore.update(store => ({
                ...store,
                email,
                username,
                password, // Note: Storing password temporarily on the client is a trade-off.
                inviteCode,
                language: currentLang,
                darkmode: darkModeEnabled,
                encryptedMasterKey: encryptedMasterKey, // Already a base64 string
                salt: saltB64
            }));
                
                // 5. Dispatch the next event to transition to step 2
                dispatch('next');
            } else {
                if (data.error_code === 'EMAIL_ALREADY_EXISTS') {
                    emailAlreadyInUse = true;
                    showEmailWarning = true;
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
            console.error('Error during signup step 1:', error);
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

    // Debounced password check
    const checkPasswordsMatch = debounce(() => {
        if (passwordRepeat && password !== passwordRepeat) {
            passwordError = $text('signup.passwords_do_not_match.text');
            showPasswordMatchWarning = true;
        } else {
            passwordError = '';
            showPasswordMatchWarning = false;
        }
    }, 500);

    // Debounced password strength check
    const debouncedCheckPasswordStrength = debounce((pwd: string) => {
        checkPasswordStrength(pwd);
    }, 500);

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

    // Update reactive statements
    $: {
        if (password || passwordRepeat) {
            checkPasswordsMatch();
        }
    }

    // Add reactive statement to check passwords match
    $: passwordsMatch = !passwordRepeat || password === passwordRepeat;

    // Helper function to check if form is valid
    $: isFormValid = username && 
                     !usernameError &&
                     !isUsernameValidationPending &&
                     email && 
                     !emailError &&
                     !isEmailValidationPending &&
                     !emailAlreadyInUse && // Block submission if email is already in use
                     password && 
                     passwordRepeat && 
                     termsAgreed && 
                     privacyAgreed &&
                     passwordsMatch &&
                     !passwordStrengthError;

    function checkPasswordStrength(pwd: string): boolean {
        if (pwd.length < 8) {
            passwordStrengthError = $text('signup.password_too_short.text');
            showPasswordStrengthWarning = true;
            return false;
        }

        if (pwd.length > 60) {
            passwordStrengthError = $text('signup.password_too_long.text');
            showPasswordStrengthWarning = true;
            return false;
        }

        // Use Unicode categories for letter detection (includes international letters)
        if (!/\p{L}/u.test(pwd)) {
            passwordStrengthError = $text('signup.password_needs_letter.text');
            showPasswordStrengthWarning = true;
            return false;
        }

        if (!/[0-9]/.test(pwd)) {
            passwordStrengthError = $text('signup.password_needs_number.text');
            showPasswordStrengthWarning = true;
            return false;
        }

        if (!/[^A-Za-z0-9\p{L}]/u.test(pwd)) {
            passwordStrengthError = $text('signup.password_needs_special.text');
            showPasswordStrengthWarning = true;
            return false;
        }

        passwordStrengthError = '';
        showPasswordStrengthWarning = false;
        return true;
    }

    // Update reactive statements to include password strength
    $: {
        if (password) {
            debouncedCheckPasswordStrength(password);
        } else {
            passwordStrengthError = '';
        }
    }

    // Update reactive statements to include email validation
    $: {
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
    }

    // Update reactive statements to include username validation
    $: {
        if (!username) {
            usernameError = '';
            showUsernameWarning = false;
            isUsernameValidationPending = false;
        } else {
            isUsernameValidationPending = true;
            debouncedCheckUsername(username);
        }
    }

    // Add watcher to update the username store when it changes
    $: if (username) {
        updateUsername(username);
    }
</script>

<div class="content-area">
    <h1><mark>{@html $text('signup.sign_up.text')}</mark></h1>
    <h2>{@html $text('login.to_chat_to_your.text')}<br><mark>{@html $text('login.digital_team_mates.text')}</mark></h2>
    
    <div class="form-container">
        {#if !isValidated}
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
                                on:input={handleInviteCodeInput}
                                on:paste={handlePaste}
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
            <form on:submit={handleSubmit}>
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
                            on:input={checkSignupActivityAndManageTimer} />
                        {#if showUsernameWarning && usernameError}
                            <InputWarning
                                message={usernameError}
                                target={usernameInput}
                            />
                        {/if}
                    </div>
                </div>

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
                            on:input={checkSignupActivityAndManageTimer} />
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
                        <span class="clickable-icon icon_secret"></span>
                        <input 
                            bind:this={passwordInput}
                            type="password" 
                            bind:value={password}
                            placeholder={$text('login.password_placeholder.text')}
                            required
                            autocomplete="new-password"
                            class:error={!!passwordStrengthError}
                            on:input={checkSignupActivityAndManageTimer} />
                        {#if showPasswordStrengthWarning && passwordStrengthError}
                            <InputWarning
                                message={passwordStrengthError}
                                target={passwordInput}
                            />
                        {/if}
                    </div>
                </div>

                <div class="input-group">
                    <div class="input-wrapper">
                        <span class="clickable-icon icon_secret"></span>
                        <input 
                            bind:this={passwordRepeatInput}
                            type="password" 
                            bind:value={passwordRepeat}
                            placeholder={$text('signup.repeat_password.text')}
                            required
                            maxlength="60"
                            autocomplete="new-password"
                            class:error={!passwordsMatch && passwordRepeat}
                            on:input={checkSignupActivityAndManageTimer} />
                        {#if showPasswordMatchWarning && passwordError && passwordRepeat}
                            <InputWarning
                                message={passwordError}
                                target={passwordRepeatInput}
                            />
                        {/if}
                    </div>
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
        {#if !isValidated}
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
                        on:click={handleSubmit}
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
</style>
