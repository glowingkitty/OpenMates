<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { fade } from 'svelte/transition';
    import { _ } from 'svelte-i18n';
    import WaitingList from '../WaitingList.svelte';
    import Toggle from '../Toggle.svelte';
    import { getApiEndpoint, apiEndpoints } from '../../config/api';
    import { tick } from 'svelte';
    import { externalLinks, getWebsiteUrl } from '../../config/links';
    import { onMount } from 'svelte';
    import InputWarning from '../common/InputWarning.svelte';
    
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

    onMount(() => {
        // Focus the invite code input when component mounts
        if (inviteCodeInput) {
            inviteCodeInput.focus();
        }
    });

    // Watch for changes in isValidated
    $: if (isValidated && usernameInput) {
        // Use tick to ensure DOM is updated
        tick().then(() => {
            usernameInput.focus();
        });
    }

    function handleLoginClick() {
        dispatch('switchToLogin');
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
        } else {
            passwordError = '';
        }
    }, 500);

    // Debounced password strength check
    const debouncedCheckPasswordStrength = debounce((pwd: string) => {
        checkPasswordStrength(pwd);
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
                     email && 
                     password && 
                     passwordRepeat && 
                     termsAgreed && 
                     privacyAgreed &&
                     passwordsMatch &&
                     !passwordStrengthError;

    function checkPasswordStrength(pwd: string): boolean {
        if (pwd.length < 8) {
            passwordStrengthError = $_('signup.password_too_short.text');
            return false;
        }

        if (pwd.length > 60) {
            passwordStrengthError = $_('signup.password_too_long.text');
            return false;
        }

        if (!/[a-zA-Z]/.test(pwd)) {
            passwordStrengthError = $_('signup.password_needs_letter.text');
            return false;
        }

        if (!/[0-9]/.test(pwd)) {
            passwordStrengthError = $_('signup.password_needs_number.text');
            return false;
        }

        if (!/[^A-Za-z0-9]/.test(pwd)) {
            passwordStrengthError = $_('signup.password_needs_special.text');
            return false;
        }

        passwordStrengthError = '';
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
</script>

<div class="nav-area">
    <button class="back-link" on:click={handleLoginClick}>
        <div class="clickable-icon icon_back"></div>
        {$_('login.login_button.text')}
    </button>
</div>

<div class="content-area">
    <h1><mark>{$_('signup.sign_up.text')}</mark></h1>
    <h2>{$_('login.to_chat_to_your.text')}<br><mark>{$_('login.digital_team_mates.text')}</mark></h2>
    
    <div class="form-container">
        {#if !isValidated}
            <form>
                <div class="input-group">
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
                        />
                    </div>
                </div>

                <div class="input-group">
                    <div class="input-wrapper">
                        <span class="clickable-icon icon_mail"></span>
                        <input 
                            type="email" 
                            bind:value={email}
                            placeholder={$_('login.email_placeholder.text')}
                            required
                            autocomplete="email"
                        />
                    </div>
                </div>

                <div class="input-group">
                    <div class="input-wrapper">
                        <span class="clickable-icon icon_secret"></span>
                        <input 
                            type="password" 
                            bind:value={password}
                            placeholder={$_('login.password_placeholder.text')}
                            required
                            autocomplete="new-password"
                            class:error={passwordStrengthError}
                        />
                    </div>
                    {#if passwordStrengthError}
                        <div class="error-message password-strength-error" transition:fade>
                            {passwordStrengthError}
                        </div>
                    {/if}
                </div>

                <div class="input-group">
                    <div class="input-wrapper">
                        <span class="clickable-icon icon_secret"></span>
                        <input 
                            type="password" 
                            bind:value={passwordRepeat}
                            placeholder={$_('signup.repeat_password.text')}
                            required
                            maxlength="60"
                            autocomplete="new-password"
                            class:error={!passwordsMatch && passwordRepeat}
                        />
                    </div>
                </div>

                {#if passwordError}
                    <div class="error-message password-match-error" transition:fade>
                        {passwordError}
                    </div>
                {/if}

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