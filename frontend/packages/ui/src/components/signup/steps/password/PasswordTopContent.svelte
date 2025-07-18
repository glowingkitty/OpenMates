<script lang="ts">
    import { text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import { createEventDispatcher } from 'svelte';
    import InputWarning from '../../../common/InputWarning.svelte';
    import { signupStore } from '../../../../stores/signupStore';
    import { get } from 'svelte/store';
    import { onMount } from 'svelte';
    
    const dispatch = createEventDispatcher();
    
    let password = '';
    let passwordRepeat = '';
    let passwordInput: HTMLInputElement;
    let passwordRepeatInput: HTMLInputElement;
    
    // Get email from the signup store for the hidden email field
    let email = '';
    
    // Password validation states
    let passwordError = '';
    let passwordStrengthError = '';
    let showPasswordStrengthWarning = false;
    let showPasswordMatchWarning = false;
    
    // Touch device detection
    let isTouchDevice = false;
    
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
    
    // Password strength validation
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
    
    // Password match validation
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
    
    // Reactive statements
    $: {
        if (password) {
            debouncedCheckPasswordStrength(password);
        } else {
            passwordStrengthError = '';
            showPasswordStrengthWarning = false;
        }
    }
    
    $: {
        if (password || passwordRepeat) {
            checkPasswordsMatch();
        }
    }
    
    // Check if passwords match
    $: passwordsMatch = !passwordRepeat || password === passwordRepeat;
    
    // Check if form is valid
    $: isFormValid = password && 
                     passwordRepeat && 
                     passwordsMatch &&
                     !passwordStrengthError;
    
    // Export the form validity and password values to parent
    $: {
        dispatch('passwordChange', { 
            password, 
            passwordRepeat, 
            isValid: isFormValid 
        });
    }
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size password"></div>
        <h2 class="signup-menu-title">{@html $text('signup.password.text')}</h2>
    </div>

    <h3 class="advice-title">{@html $text('signup.advice.text')}</h3>
    <p class="advice-text">{@html $text('signup.use_your_password_manager.text')}</p>
    
    
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
                    <span class="clickable-icon icon_secret"></span>
                    <input 
                        bind:this={passwordInput}
                        type="password" 
                        bind:value={password}
                        placeholder={$text('login.password_placeholder.text')}
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
                        placeholder={$text('signup.repeat_password.text')}
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
        margin-top: 24px;
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

    .form-container {
        margin-top: 0px;
    }
    
</style>
