<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { fade } from 'svelte/transition';
    import { _ } from 'svelte-i18n';
    import WaitingList from '../../WaitingList.svelte';
    import Toggle from '../../Toggle.svelte';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    import { tick } from 'svelte';
    import { externalLinks, getWebsiteUrl } from '../../../config/links';
    import { onMount, onDestroy } from 'svelte';
    import InputWarning from '../../common/InputWarning.svelte';
    
    const dispatch = createEventDispatcher();

    let inviteCode = '';
    let isValidFormat = false;
    let isLoading = false;
    let isValidated = false;
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
    });

    onDestroy(() => {
        if (rateLimitTimer) {
            clearTimeout(rateLimitTimer);
        }
    });

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
            const response = await fetch(getApiEndpoint(apiEndpoints.signup.check_invite_token_valid), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ invite_code: inviteCode }),
            });

            const data = await response.json();

            if (response.status === 429) {
                isRateLimited = true;
                localStorage.setItem('inviteCodeRateLimit', Date.now().toString());
                setRateLimitTimer(RATE_LIMIT_DURATION);
                return;
            }

            if (response.ok && data.valid) {
                isValidated = true;
            } else {
                showWarning = true;
                isValidated = false;
            }
        } catch (error) {
            console.error('Error validating invite code:', error);
            showWarning = true;
            isValidated = false;
        } finally {
            isLoading = false;
        }
    }

    // Handle form submission
    async function handleSubmit(event: Event) {
        event.preventDefault();
        
        if (!passwordsMatch) {
            return;
        }

        // Continue with form submission
        // TODO: Add your form submission logic here
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
            passwordError = $_('signup.passwords_do_not_match.text');
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
            emailError = $_('signup.at_missing.text');
            showEmailWarning = true;
            isEmailValidationPending = false;
            return;
        }

        if (!email.match(/\.[a-z]{2,}$/i)) {
            emailError = $_('signup.domain_ending_missing.text');
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
            usernameError = $_('signup.username_too_short.text');
            showUsernameWarning = true;
            return false;
        }

        if (normalizedUsername.length > 20) {
            usernameError = $_('signup.username_too_long.text');
            showUsernameWarning = true;
            return false;
        }

        // Check for at least one letter (including international letters)
        if (!/\p{L}/u.test(normalizedUsername)) {
            usernameError = $_('signup.password_needs_letter.text');
            showUsernameWarning = true;
            return false;
        }

        // Allow letters (including international), numbers, dots, and underscoress        // Include specific Unicode ranges for Thai [\u0E00-\u0E7F]
        if (!/^[\p{L}\p{M}0-9._]+$/u.test(normalizedUsername)) {
            usernameError = $_('signup.username_invalid_chars.text');
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
                     password && 
                     passwordRepeat && 
                     termsAgreed && 
                     privacyAgreed &&
                     passwordsMatch &&
                     !passwordStrengthError;

    function checkPasswordStrength(pwd: string): boolean {
        if (pwd.length < 8) {
            passwordStrengthError = $_('signup.password_too_short.text');
            showPasswordStrengthWarning = true;
            return false;
        }

        if (pwd.length > 60) {
            passwordStrengthError = $_('signup.password_too_long.text');
            showPasswordStrengthWarning = true;
            return false;
        }

        // Use Unicode categories for letter detection (includes international letters)
        if (!/\p{L}/u.test(pwd)) {
            passwordStrengthError = $_('signup.password_needs_letter.text');
            showPasswordStrengthWarning = true;
            return false;
        }

        if (!/[0-9]/.test(pwd)) {
            passwordStrengthError = $_('signup.password_needs_number.text');
            showPasswordStrengthWarning = true;
            return false;
        }

        if (!/[^A-Za-z0-9\p{L}]/u.test(pwd)) {
            passwordStrengthError = $_('signup.password_needs_special.text');
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
            debouncedCheckEmail(email);
        } else {
            emailError = '';
            showEmailWarning = false;
            isEmailValidationPending = false;
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
</script>

<div class="content-area">
    <h1><mark>{$_('signup.sign_up.text')}</mark></h1>
    <h2>{$_('login.to_chat_to_your.text')}<br><mark>{$_('login.digital_team_mates.text')}</mark></h2>
    
    <div class="form-container">
        {#if !isValidated}
            <form>
                <div class="input-group">
                    {#if isRateLimited}
                        <div class="rate-limit-message" transition:fade>
                            {$_('signup.too_many_requests.text')}
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
                                placeholder={$_('signup.enter_personal_invite_code.text')}
                                maxlength="14"
                                disabled={isLoading}
                            />
                            {#if showWarning}
                                <InputWarning 
                                    message={$_('signup.code_is_invalid.text')}
                                    target={inviteCodeInput}
                                />
                            {/if}
                        </div>
                    {/if}
                    {#if isLoading}
                        <div class="loading-message-container" transition:fade>
                            <div class="loading-message">
                                {$_('signup.checking_code.text')}
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
                            placeholder={$_('signup.enter_username.text')}
                            required
                            autocomplete="username"
                            class:error={!!usernameError}
                        />
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
                            placeholder={$_('login.email_placeholder.text')}
                            required
                            autocomplete="email"
                            class:error={!!emailError}
                        />
                        {#if showEmailWarning && emailError}
                            <InputWarning 
                                message={emailError}
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
                            placeholder={$_('login.password_placeholder.text')}
                            required
                            autocomplete="new-password"
                            class:error={!!passwordStrengthError}
                        />
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
                            placeholder={$_('signup.repeat_password.text')}
                            required
                            maxlength="60"
                            autocomplete="new-password"
                            class:error={!passwordsMatch && passwordRepeat}
                        />
                        {#if showPasswordMatchWarning && passwordError && passwordRepeat}
                            <InputWarning 
                                message={passwordError}
                                target={passwordRepeatInput}
                            />
                        {/if}
                    </div>
                </div>

                <div class="agreement-row">
                    <Toggle bind:checked={termsAgreed} />
                    <div class="agreement-text">
                        {$_('signup.agree_to.text')} 
                        <a href={getWebsiteUrl(externalLinks.legal.terms)} target="_blank" rel="noopener noreferrer">
                            <mark>{$_('signup.terms_of_service.text')}</mark>
                        </a>
                    </div>
                </div>

                <div class="agreement-row">
                    <Toggle bind:checked={privacyAgreed} />
                    <div class="agreement-text">
                        {$_('signup.agree_to.text')} 
                        <a href={getWebsiteUrl(externalLinks.legal.privacyPolicy)} target="_blank" rel="noopener noreferrer">
                            <mark>{$_('signup.privacy_policy.text')}</mark>
                        </a>
                    </div>
                </div>
            </form>
        {/if}
    </div>
    <div class="bottom-positioned">
        {#if !isValidated}
            <WaitingList showPersonalInviteMessage={true} />
        {:else}
            <button 
                class="signup-button" 
                disabled={!isFormValid}
                on:click={handleSubmit}
            >
                {$_('signup.create_new_account.text')}
            </button>
        {/if}
    </div>
</div>