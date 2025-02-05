<script lang="ts">
    import { fade, scale } from 'svelte/transition';
    import { _ } from 'svelte-i18n';
    import AppIconGrid from './AppIconGrid.svelte';
    import { createEventDispatcher } from 'svelte';
    import { login, isAuthenticated, checkAuth } from '../stores/authState';
    import { onMount } from 'svelte';
    import { MOBILE_BREAKPOINT } from '../styles/constants';
    import { AuthService } from '../services/authService';
    import { isCheckingAuth } from '../stores/authCheckState';
    import { tick } from 'svelte';

    const dispatch = createEventDispatcher();

    // Form data
    let email = '';
    let password = '';
    let isLoading = false;
    let errorMessage = '';

    // Add state for mobile view
    let isMobile = false;
    let emailInput: HTMLInputElement; // Reference to the email input element

    // Add state for minimum loading time control
    let showLoadingUntil = 0;

    // Add state to control form visibility
    let showForm = false;

    onMount(() => {
        (async () => {
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
            
            if (!$isAuthenticated && emailInput) {
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
        errorMessage = '';

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
            // More user-friendly error message
            errorMessage = error.message === 'Failed to fetch' 
                ? 'Unable to connect to the server. Please check your connection and try again.'
                : error.message || 'Login failed. Please check your credentials and try again.';
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
                <h1><mark>{$_('login.login.text')}</mark></h1>
                <h3>{$_('login.to_chat_to_your.text')}<br><mark>{$_('login.digital_team_mates.text')}</mark></h3>

                <div class="form-container">
                    <!-- Form is always rendered but initially hidden -->
                    <form 
                        on:submit|preventDefault={handleSubmit} 
                        class:visible={showForm}
                        class:hidden={!showForm}
                    >
                        {#if errorMessage}
                            <div class="error-message" in:fade>
                                {errorMessage}
                            </div>
                        {/if}

                        <div class="input-group" style="margin-top: 35px">
                            <div class="input-wrapper">
                                <span class="clickable-icon icon_mail"></span>
                                <input 
                                    type="email" 
                                    bind:value={email}
                                    placeholder={$_('login.email_placeholder.text')}
                                    required
                                    autocomplete="email"
                                    bind:this={emailInput}
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
                                    autocomplete="current-password"
                                />
                            </div>
                        </div>

                        <button type="submit" class="login-button" disabled={isLoading}>
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
                            <p>{$_('login.checking_auth.text', { default: 'Loading...' })}</p>
                        </div>
                    {/if}
                </div>
            </div>
        </div>

        <AppIconGrid side="right" />
    </div>
{/if}

<style>
    .login-container {
        display: flex;
        width: 100%;
        height: 100%;
        position: relative;
        background-color: var(--color-grey-20);
        display: flex;
        justify-content: center;
        align-items: center;
        overflow: hidden;
        position: relative;
        max-width: 100%;
    }

    .login-content {
        flex: 1;
        display: flex;
        justify-content: center;
        align-items: center;
        padding: 2rem;
        z-index: 1;
    }

    .login-box {
        max-width: 440px;
        text-align: center;
    }
    
    .input-group {
        margin-bottom: 1rem;
    }

    .input-wrapper {
        position: relative;
        display: flex;
        align-items: center;
        background-color: var(--color-grey-20);
    }

    /* Adjust the icon to be inside the input field */
    .input-wrapper .clickable-icon {
        position: absolute; /* Keep it absolute */
        left: 1rem; /* Position it inside the input */
        color: var(--color-grey-60);
        z-index: 1; /* Ensure it appears above the input */
    }

    input {
        width: 100% !important;
        padding: 12px 16px 12px 45px !important; /* Adjust padding to accommodate the icon in px */
        border: 2px solid var(--color-grey-0) !important;
        border-radius: 24px !important;
        font-size: 16px !important;
        transition: border-color 0.2s !important;
        background-color: var(--color-grey-0) !important;
        color: var(--color-grey-100) !important;
        box-shadow: 0 0 12px rgba(0, 0, 0, 0.25) !important;
    }

    input:focus {
        border-color: var(--color-grey-50) !important;
        outline: none !important;
    }

    .login-button {
        width: 100%;
        margin: 1.5rem 0 1rem;
    }

    .login-button:disabled {
        opacity: 0.7;
        cursor: not-allowed;
    }

    .error-message {
        background: var(--color-error-light);
        color: var(--color-error);
        padding: 0.75rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
    }

    .loading-spinner {
        display: inline-block;
        width: 1.25rem;
        height: 1.25rem;
        border: 2px solid rgba(255, 255, 255, 0.3);
        border-radius: 50%;
        border-top-color: white;
        animation: spin 1s linear infinite;
    }

    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }

    /* Add media query for small screens */
    @media (max-width: 370px) {
        .login-content {
            max-width: 100%;
        }

        .login-box {
            max-width: calc(100% - 20px);
        }
    }

    .form-container {
        position: relative;
        min-height: 250px; /* Adjust based on your form height */
        margin-top: 35px;
    }

    form {
        opacity: 0;
        transition: opacity 0.2s ease-in-out;
    }

    form.visible {
        opacity: 1;
    }

    form.hidden {
        opacity: 0;
    }

    .checking-auth {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 1rem;
        background-color: var(--color-grey-20); /* Match parent background */
        z-index: 1;
    }

    .checking-auth p {
        color: var(--color-grey-80);
        font-size: 1.1rem;
    }
</style>
