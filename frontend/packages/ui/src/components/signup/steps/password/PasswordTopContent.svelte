<script lang="ts">
    /* eslint-disable @typescript-eslint/no-explicit-any */
    /* eslint-disable svelte/no-at-html-tags */
    import { text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import { createEventDispatcher } from 'svelte';
    import { signupStore } from '../../../../stores/signupStore';
    import { get } from 'svelte/store';
    import { onMount } from 'svelte';
    
    const dispatch = createEventDispatcher();

    const MIN_PASSWORD_LENGTH = 10;
    const MAX_PASSWORD_LENGTH = 60;
    // Passwords that trivially satisfy length + character-class rules but are
    // well-known and easily guessed. Checked case-insensitively.
    const COMMON_PASSWORD_BLOCKLIST = new Set([
        'password1!',
        'password1@',
        'password1#',
        'password123!',
        'password123@',
        'qwerty12345',
        'qwerty123!',
        'iloveyou123!',
        'letmein123!',
        'admin12345!',
        'welcome123!',
        'changeme123!',
        'openmates123!',
        'openmates2024!',
        'openmates2025!',
        'openmates2026!',
        'abcd1234!',
        'test1234!',
        'test12345!',
        '12345678',
        '123456789',
        '1234567890',
        '12345678910',
        'qwerty123',
        'qwerty1234',
        'qwertyuiop',
        'password',
        'password1',
        'password12',
        'password123',
        'password1234',
        'passw0rd',
        'admin123',
        'welcome123',
        'letmein123',
        'iloveyou123',
        'changeme123',
        'openmates123',
        'openmates2024',
        'openmates2025',
        'openmates2026',
        'abcd1234',
        'abc12345',
        'test1234',
        'test12345',
        'asdf1234',
        'zxcv1234',
        'aa123456',
        '11111111',
        '00000000'
    ]);
    
    // Form state using Svelte 5 runes
    let password = $state('');
    let passwordRepeat = $state('');
    let passwordInput = $state<HTMLInputElement>();
    let passwordRepeatInput = $state<HTMLInputElement>();
    
    // Get email from the signup store for the hidden email field using Svelte 5 runes
    let email = $state('');
    
    // Password validation states using Svelte 5 runes
    let passwordError = $state('');
    let passwordStrengthError = $state('');
    // showPasswordStrengthWarning tracks whether the user has started typing, so we
    // only reveal the error after the first validation run (not on initial empty state).
    let showPasswordStrengthWarning = $state(false);
    let showPasswordMatchWarning = $state(false);
    
    // Touch device detection using Svelte 5 runes
    let isTouchDevice = $state(false);
    
    onMount(() => {
        // Check if device is touch-enabled
        isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
        
        // Focus password input on mount (if not touch device)
        if (passwordInput && !isTouchDevice) {
            passwordInput.focus();
        }
        
        // Get email from store
        const storeData = get(signupStore);
        if (storeData && storeData.email) {
            email = storeData.email;
        }
        
        // Explicitly dispatch initial password state to ensure bottom content gets notified
        dispatch('passwordChange', { 
            password, 
            passwordRepeat, 
            isValid: isFormValid 
        });
    });
    
    // Debounce helper
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
    
    // Password strength validation.
    // Requirements: 10–60 characters, at least one letter (\p{L}), one digit, one special character.
    // Uppercase/lowercase case-sensitivity requirements are intentionally dropped — case rules
    // add friction without meaningfully increasing entropy beyond what length + character
    // diversity already provide.
    function checkPasswordStrength(pwd: string): boolean {
        if (pwd.length < MIN_PASSWORD_LENGTH) {
            passwordStrengthError = $text('signup.password_too_short');
            showPasswordStrengthWarning = true;
            return false;
        }

        if (pwd.length > MAX_PASSWORD_LENGTH) {
            passwordStrengthError = $text('signup.password_too_long');
            showPasswordStrengthWarning = true;
            return false;
        }

        if (COMMON_PASSWORD_BLOCKLIST.has(pwd.toLowerCase())) {
            passwordStrengthError = $text('signup.password_too_common');
            showPasswordStrengthWarning = true;
            return false;
        }

        // At least one Unicode letter (covers all scripts, not just Latin)
        if (!/\p{L}/u.test(pwd)) {
            passwordStrengthError = $text('signup.password_needs_letter');
            showPasswordStrengthWarning = true;
            return false;
        }

        if (!/[0-9]/.test(pwd)) {
            passwordStrengthError = $text('signup.password_needs_number');
            showPasswordStrengthWarning = true;
            return false;
        }

        // At least one character that is not a letter and not a digit
        if (!/[^A-Za-z0-9\p{L}]/u.test(pwd)) {
            passwordStrengthError = $text('signup.password_needs_special');
            showPasswordStrengthWarning = true;
            return false;
        }

        passwordStrengthError = '';
        showPasswordStrengthWarning = false;
        return true;
    }
    
    // Password match validation
    const checkPasswordsMatch = debounce(() => {
        if (passwordRepeat && password !== passwordRepeat) {
            passwordError = $text('signup.passwords_do_not_match');
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
    
    // Reactive statements using Svelte 5 runes
    $effect(() => {
        if (password) {
            debouncedCheckPasswordStrength(password);
        } else {
            passwordStrengthError = '';
            showPasswordStrengthWarning = false;
        }
    });
    
    $effect(() => {
        if (password || passwordRepeat) {
            checkPasswordsMatch();
        }
    });
    
    // Check if passwords match using Svelte 5 runes
    let passwordsMatch = $derived(!passwordRepeat || password === passwordRepeat);
    
    // Check if form is valid using Svelte 5 runes
    let isFormValid = $derived(password && 
                     passwordRepeat && 
                     passwordsMatch &&
                     !passwordStrengthError);
    
    // Export the form validity and password values to parent using Svelte 5 runes
    $effect(() => {
        dispatch('passwordChange', { 
            password, 
            passwordRepeat, 
            isValid: isFormValid 
        });
    });
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size password"></div>
        <h2 class="signup-menu-title">{@html $text('signup.password')}</h2>
    </div>

    <h3 class="advice-title">{@html $text('signup.advice')}</h3>
    <p class="advice-text">{@html $text('signup.use_your_password_manager')}</p>
    
    
    <div class="form-container">
        <form>
            <!-- Hidden email field for accessibility and password managers -->
            <input 
                type="email" 
                name="email" 
                autocomplete="email" 
                value={email} 
                style="display: none;" 
                aria-hidden="true"
            />
            <div class="input-group">
                <div class="input-wrapper">
                    <span class="clickable-icon icon_password"></span>
                    <input 
                        bind:this={passwordInput}
                        type="password" 
                        bind:value={password}
                        placeholder={$text('login.password_placeholder')}
                        required
                        autocomplete="new-password"
                        class:error={!!passwordStrengthError}
                    />
                </div>
                <!-- Persistent inline error: stays visible until the user fixes the issue. -->
                {#if showPasswordStrengthWarning && passwordStrengthError}
                    <p class="field-error" transition:fade={{ duration: 150 }}>
                        {@html passwordStrengthError}
                    </p>
                {/if}
            </div>

            <div class="input-group">
                <div class="input-wrapper">
                    <span class="clickable-icon icon_password"></span>
                    <input 
                        bind:this={passwordRepeatInput}
                        type="password" 
                        bind:value={passwordRepeat}
                        placeholder={$text('signup.repeat_password')}
                        required
                        maxlength="60"
                        autocomplete="new-password"
                        class:error={!passwordsMatch && passwordRepeat}
                    />
                </div>
                <!-- Persistent inline error for password mismatch -->
                {#if showPasswordMatchWarning && passwordError && passwordRepeat}
                    <p class="field-error" transition:fade={{ duration: 150 }}>
                        {@html passwordError}
                    </p>
                {/if}
            </div>
        </form>
    </div>
</div>

<style>
    .content {
        padding: 24px;
        height: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
    }
    
    .signup-header {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 16px;
        margin-bottom: 30px;
    }
    
    .advice-title {
        font-size: 16px;
        font-weight: 600;
        color: var(--color-grey-80);
        margin: 0;
    }
    
    .advice-text {
        font-size: 14px;
        color: var(--color-grey-60);
        margin: 0;
        line-height: 1.5;
    }
    
    .form-container {
        width: 100%;
        max-width: 400px;
        display: flex;
        flex-direction: column;
        gap: 16px;
        margin-top: 0px;
    }

    .input-group {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }
    
    .clickable-icon {
        position: absolute;
        left: 16px;
        z-index: 1;
        pointer-events: none;
    }
    
    /* Add background color for input fields */
    input[type="password"] {
        background-color: var(--color-grey-20);
    }

    /* Persistent inline error message below the input.
       Replaces the auto-hiding floating tooltip so the user always knows
       why the continue button is disabled. */
    .field-error {
        margin: 0;
        padding: 0 4px;
        font-size: 13px;
        color: #E00000;
        line-height: 1.4;
    }
</style>
