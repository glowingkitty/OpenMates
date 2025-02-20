<script lang="ts">
    import { fade, scale } from 'svelte/transition';
    import { _ } from 'svelte-i18n';
    import AppIconGrid from './AppIconGrid.svelte';
    import InputWarning from './common/InputWarning.svelte';
    import { createEventDispatcher } from 'svelte';
    import { login, isAuthenticated, checkAuth } from '../stores/authState';
    import { onMount } from 'svelte';
    import { MOBILE_BREAKPOINT } from '../styles/constants';
    import { AuthService } from '../services/authService';
    import { isCheckingAuth } from '../stores/authCheckState';
    import { tick } from 'svelte';
    import Signup from './signup/Signup.svelte';
    
    const dispatch = createEventDispatcher();

    // Form data
    let email = '';
    let password = '';
    let isLoading = false;

    // Add state for mobile view
    let isMobile = false;
    let emailInput: HTMLInputElement; // Reference to the email input element

    // Add state for minimum loading time control
    let showLoadingUntil = 0;

    // Add state to control form visibility
    let showForm = false;

    // Add state for view management
    let currentView: 'login' | 'signup' = 'login';

    // Add touch detection
    let isTouchDevice = false;

    // Add state for showing warning
    let showWarning = false;

    // Add email validation state
    let emailError = '';
    let showEmailWarning = false;
    let isEmailValidationPending = false;
    let loginFailedWarning = false;

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

    // Clear login failed warning when either email or password changes
    $: {
        if (email || password) {
            loginFailedWarning = false;
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

    // Initialize validation state when email is empty
    $: hasValidEmail = email && !emailError && !isEmailValidationPending;
    
    // Update helper for form validation to be false by default
    $: isFormValid = hasValidEmail && 
                     password && 
                     !loginFailedWarning;

    // Force validation check on empty email
    $: {
        if (!email) {
            debouncedCheckEmail('');
        }
    }
    
    function switchToSignup() {
        currentView = 'signup';
    }
    
    async function switchToLogin() {
        currentView = 'login';
        await tick();
        // Only focus if not touch device
        if (emailInput && !isTouchDevice) {
            emailInput.focus();
        }
    }

    onMount(() => {
        (async () => {
            // Check if device is touch-enabled
            isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
            
            showLoadingUntil = Date.now() + 500;
            
            $isCheckingAuth = true;
            await checkAuth();
            
            const remainingTime = showLoadingUntil - Date.now();
            if (remainingTime > 0) {
                await new Promise(resolve => setTimeout(resolve, remainingTime));
            }
            
            await tick();
            showForm = true; // Show form before removing loading state
            await tick();
            $isCheckingAuth = false;
            
            // Set initial mobile state
            isMobile = window.innerWidth < MOBILE_BREAKPOINT;
            
            // Only focus if not touch device and not authenticated
            if (!$isAuthenticated && emailInput && !isTouchDevice) {
                emailInput.focus();
            }
        })();
        
        // Handle resize events
        const handleResize = () => {
            isMobile = window.innerWidth < MOBILE_BREAKPOINT;
        };
        
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    });

    async function handleSubmit() {
        isLoading = true;
        loginFailedWarning = false;

        try {
            await AuthService.login(email, password);
            
            // Just use the email we already have
            login({
                email: email,
            });
            
            console.log('Login successful');
            dispatch('loginSuccess', { 
                user: { email: email },
                isMobile 
            });
            
        } catch (error: any) {
            console.error('Login error details:', error);
            loginFailedWarning = true;
        } finally {
            isLoading = false;
        }
    }
</script>

{#if !$isAuthenticated}
    <div class="login-container" in:fade={{ duration: 300 }} out:fade={{ duration: 300 }}>
        <AppIconGrid side="left" />

        <div class="login-content">
            <div class="login-box" in:scale={{ duration: 300, delay: 150 }}>
                {#if currentView === 'login'}
                    <div class="content-area">
                        <h1><mark>{$_('login.login.text')}</mark></h1>
                        <h2>{$_('login.to_chat_to_your.text')}<br><mark>{$_('login.digital_team_mates.text')}</mark></h2>

                        <div class="form-container">
                            <!-- Form is always rendered but initially hidden -->
                            <form 
                                on:submit|preventDefault={handleSubmit} 
                                class:visible={showForm}
                                class:hidden={!showForm}
                            >
                                <div class="input-group">
                                    <div class="input-wrapper">
                                        <span class="clickable-icon icon_mail"></span>
                                        <input 
                                            type="email" 
                                            bind:value={email}
                                            placeholder={$_('login.email_placeholder.text')}
                                            required
                                            autocomplete="email"
                                            bind:this={emailInput}
                                            class:error={!!emailError || loginFailedWarning}
                                        />
                                        {#if showEmailWarning && emailError}
                                            <InputWarning 
                                                message={emailError}
                                                target={emailInput}
                                            />
                                        {:else if loginFailedWarning}
                                            <InputWarning 
                                                message={$_('login.login_failed.text')}
                                                target={emailInput}
                                            />
                                        {/if}
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
                                            autocomplete="current-password"
                                        />
                                    </div>
                                </div>

                                <button 
                                    type="submit" 
                                    class="login-button" 
                                    disabled={isLoading || !isFormValid}
                                >
                                    {#if isLoading}
                                        <span class="loading-spinner"></span>
                                    {:else}
                                        {$_('login.login_button.text')}
                                    {/if}
                                </button>
                            </form>

                            {#if $isCheckingAuth}
                                <div class="checking-auth" in:fade={{ duration: 200 }} out:fade={{ duration: 200 }}>
                                    <span class="loading-spinner"></span>
                                    <p>{$_('login.loading.text')}</p>
                                </div>
                            {/if}
                        </div>

                        <div class="bottom-positioned" class:visible={showForm} hidden={!showForm}>
                            <span class="color-grey-60">{$_('login.not_signed_up_yet.text')}</span><br>
                            <mark>
                                <button class="text-button" on:click={switchToSignup}>
                                    {$_('login.click_here_to_create_a_new_account.text')}
                                </button>
                            </mark>
                        </div>
                    </div>
                {:else}
                    <Signup on:switchToLogin={switchToLogin} />
                {/if}
            </div>
        </div>

        <AppIconGrid side="right" />
    </div>
{/if}
