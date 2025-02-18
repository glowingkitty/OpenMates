<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { fade } from 'svelte/transition';
    import { _ } from 'svelte-i18n';
    import WaitingList from '../WaitingList.svelte';
    import Toggle from '../Toggle.svelte';
    import { getApiEndpoint, apiEndpoints } from '../../config/api';
    import { tick } from 'svelte';
    import { externalLinks, getWebsiteUrl } from '../../config/links';

    const dispatch = createEventDispatcher();

    let inviteCode = '';
    let isValidFormat = false;
    let isLoading = false;
    let isValidated = false;
    let errorMessage = '';

    // Signup form fields
    let username = '';
    let email = '';
    let password = '';
    let passwordRepeat = '';

    // Agreement toggles state
    let termsAgreed = false;
    let privacyAgreed = false;

    let passwordError = '';

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
        errorMessage = '';

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
                errorMessage = 'Invalid invite code';
                isValidated = false;
            }
        } catch (error) {
            console.error('Error validating invite code:', error);
            errorMessage = 'Error validating invite code';
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
                     passwordsMatch;
</script>

<div class="signup-container">
    <button class="back-link" on:click={handleLoginClick}>
        <div class="clickable-icon icon_back"></div>
        {$_('login.login_button.text')}
    </button>
    
    <h1><mark>{$_('signup.sign_up.text')}</mark></h1>
    <h3>{$_('login.to_chat_to_your.text')}<br><mark>{$_('login.digital_team_mates.text')}</mark></h3>
    
    <div class="form-container">
        {#if !isValidated}
            <form>
                {#if errorMessage}
                    <div class="error-message" transition:fade>
                        {errorMessage}
                    </div>
                {/if}

                <div class="input-group">
                    <div class="input-wrapper">
                        <span class="clickable-icon icon_secret"></span>
                        <input 
                            type="text" 
                            bind:value={inviteCode}
                            on:input={handleInviteCodeInput}
                            on:paste={handlePaste}
                            placeholder={$_('signup.enter_personal_invite_code.text')}
                            maxlength="14"
                            disabled={isLoading}
                        />
                    </div>
                </div>
            </form>

            <p class="no-invite-text">{$_('signup.dont_have_personal_invite_code.text')}</p>
            <WaitingList />
        {:else}
            <form on:submit={handleSubmit}>
                <div class="input-group">
                    <div class="input-wrapper">
                        <span class="clickable-icon icon_user"></span>
                        <input 
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
                        />
                    </div>
                </div>

                <div class="input-group">
                    <div class="input-wrapper">
                        <span class="clickable-icon icon_secret"></span>
                        <input 
                            type="password" 
                            bind:value={passwordRepeat}
                            placeholder={$_('signup.repeat_password.text')}
                            required
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

                <button 
                    type="submit" 
                    class="signup-button" 
                    disabled={!isFormValid}
                >
                    {$_('signup.create_new_account.text')}
                </button>
            </form>
        {/if}
    </div>
</div>

<style>
    .signup-container {
        position: relative;
        width: 100%;
    }

    .back-link {
        all: unset;
        position: absolute;
        top: 0;
        left: 0;
        font-size: 14px;
        color: #858585;
        background: none;
        border: none;
        cursor: pointer;
        padding: 0;
    }

    .form-container {
        margin-top: 35px;
    }

    .input-group {
        margin-bottom: 1rem;
    }

    .input-wrapper {
        position: relative;
        display: flex;
        align-items: center;
    }

    .input-wrapper .clickable-icon {
        position: absolute;
        left: 1rem;
        color: var(--color-grey-60);
        z-index: 1;
    }

    input {
        width: 100%;
        padding: 12px 16px 12px 45px;
        border: 2px solid var(--color-grey-0);
        border-radius: 24px;
        font-size: 16px;
        transition: border-color 0.2s;
        background-color: var(--color-grey-0);
        color: var(--color-grey-100);
        box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
    }

    input:focus {
        border-color: var(--color-grey-50);
        outline: none;
    }

    input:disabled {
        opacity: 0.7;
        cursor: not-allowed;
    }

    input.error {
        border-color: var(--color-error);
    }

    .error-message {
        background: var(--color-error-light);
        color: var(--color-error);
        padding: 0.75rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
    }

    .password-match-error {
        margin-top: -0.5rem;
        margin-bottom: 1rem;
        font-size: 0.875rem;
    }

    .no-invite-text {
        color: var(--color-grey-60);
        text-align: center;
        margin: 2rem 0 1rem;
    }

    .signup-button {
        width: 100%;
        margin: 1.5rem 0 1rem;
    }

    .agreement-row {
        display: flex;
        align-items: center;
        gap: 1rem;
        margin: 1rem 0;
    }

    .agreement-text {
        color: var(--color-grey-60);
    }

    .agreement-text a {
        text-decoration: none;
    }

    .signup-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
</style>
