<script lang="ts">
    import { fade, scale } from 'svelte/transition';
    import { _ } from 'svelte-i18n';
    import AppIconGrid from './AppIconGrid.svelte';
    import { createEventDispatcher } from 'svelte';
    import { login } from '../../lib/stores/authState';
    import { onMount } from 'svelte';
    import { MOBILE_BREAKPOINT } from '../../lib/constants';

    const dispatch = createEventDispatcher();

    // Form data
    let email = '';
    let password = '';
    let isLoading = false;
    let errorMessage = '';

    // Add state for mobile view
    let isMobile = false;
    
    onMount(() => {
        // Set initial mobile state
        isMobile = window.innerWidth < MOBILE_BREAKPOINT;
        
        // Update mobile state on resize
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
            // TODO: Replace with actual API call
            await new Promise(resolve => setTimeout(resolve, 1000));
            
            // Create a mock token that will pass validation
            const mockToken = createMockToken();
            const userData = { email };
            
            // Update auth state with the token and user data
            login(mockToken, userData, isMobile);
            
            console.log('Login successful');
            dispatch('loginSuccess', { user: userData });
            
        } catch (error: any) {
            console.error('Login failed:', error);
            errorMessage = error.message || 'Login failed. Please try again.';
        } finally {
            isLoading = false;
        }
    }

    // Helper function to create a mock JWT token for testing
    function createMockToken(): string {
        const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
        const payload = btoa(JSON.stringify({
            sub: '123',
            email: email,
            exp: Math.floor(Date.now() / 1000) + (60 * 60) // 1 hour from now
        }));
        const signature = btoa('mock_signature');
        return `${header}.${payload}.${signature}`;
    }
</script>

<div class="login-container" in:fade={{ duration: 300 }} out:fade={{ duration: 300 }}>
    <AppIconGrid side="left" />

    <div class="login-content">
        <div class="login-box" in:scale={{ duration: 300, delay: 150 }}>
            <h1><mark>{$_('login.login.text')}</mark></h1>
            <h3>{$_('login.to_chat_to_your.text')}<br><mark>{$_('login.digital_team_mates.text')}</mark></h3>

            <!-- <p>{$_('login.not_signed_up_yet.text')}</p>
            <a href="/signup"><mark>{$_('login.click_here_to_create_a_new_account.text')}</mark></a> -->

            <form on:submit|preventDefault={handleSubmit}>
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

                <!-- <div class="links">
                    <a href="/forgot-password">{$_('login.forgot_password.text')}</a>
                </div> -->
            </form>
        </div>
    </div>

    <AppIconGrid side="right" />
</div>

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
        width: 100%;
        padding: 12px 16px 12px 45px; /* Adjust padding to accommodate the icon in px */
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
</style>
