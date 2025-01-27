<script lang="ts">
    import { fade, scale } from 'svelte/transition';
    import { _ } from 'svelte-i18n';
    import AppIconGrid from './AppIconGrid.svelte';
    import { createEventDispatcher } from 'svelte';

    const dispatch = createEventDispatcher();

    // Form data
    let email = '';
    let password = '';
    let isLoading = false;
    let errorMessage = '';

    async function handleSubmit() {
        isLoading = true;
        errorMessage = '';

        try {
            // TODO: Implement actual login logic here
            await new Promise(resolve => setTimeout(resolve, 1000)); // Simulate API call

            // Dispatch success event
            dispatch('loginSuccess');
        } catch (error: any) {
            errorMessage = error.message || 'Login failed. Please try again.';
        } finally {
            isLoading = false;
        }
    }
</script>

<div class="login-container" in:fade={{ duration: 300 }} out:fade={{ duration: 300 }}>
    <AppIconGrid side="left" />

    <div class="login-content">
        <div class="login-box" in:scale={{ duration: 300, delay: 150 }}>
            <h1>{$_('login.login.text')}</h1>
            <h2>{$_('login.to_chat_to_your.text')}</h2>
            <h2><mark>{$_('login.digital_team_mates.text')}</mark></h2>

            <p>{$_('login.not_signed_up_yet.text')}</p>
            <a href="/signup"><mark>{$_('login.click_here_to_create_a_new_account.text')}</mark></a>

            <form on:submit|preventDefault={handleSubmit}>
                {#if errorMessage}
                    <div class="error-message" in:fade>
                        {errorMessage}
                    </div>
                {/if}

                <div class="input-group">
                    <div class="input-wrapper">
                        <span class="icon icon_mail"></span>
                        <input 
                            type="email" 
                            bind:value={email}
                            placeholder={$_('login.email_placeholder.text')}
                            required
                        />
                    </div>
                </div>

                <div class="input-group">
                    <div class="input-wrapper">
                        <span class="icon icon_lock"></span>
                        <input 
                            type="password" 
                            bind:value={password}
                            placeholder={$_('login.password_placeholder.text')}
                            required
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

                <div class="links">
                    <a href="/forgot-password">{$_('login.forgot_password.text')}</a>
                </div>
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
        background: var(--color-grey-0);
        padding: 2.5rem;
        border-radius: 1rem;
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.1);
        width: 100%;
        max-width: 440px;
        text-align: center;
    }

    h1 {
        margin: 0 0 0.5rem;
        font-size: 2rem;
    }

    h2 {
        margin: 0 0 1.5rem;
        font-size: 1.25rem;
        color: var(--color-grey-60);
    }

    .input-group {
        margin-bottom: 1rem;
    }

    .input-wrapper {
        position: relative;
        display: flex;
        align-items: center;
    }

    .input-wrapper .icon {
        position: absolute;
        left: 1rem;
        color: var(--color-grey-60);
    }

    input {
        width: 100%;
        padding: 0.75rem 1rem 0.75rem 2.5rem;
        border: 1px solid var(--color-grey-40);
        border-radius: 0.5rem;
        font-size: 1rem;
        transition: border-color 0.2s;
    }

    input:focus {
        border-color: var(--color-primary);
        outline: none;
    }

    .login-button {
        width: 100%;
        padding: 0.75rem;
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: 0.5rem;
        font-size: 1rem;
        cursor: pointer;
        transition: opacity 0.2s;
        margin: 1.5rem 0 1rem;
    }

    .login-button:disabled {
        opacity: 0.7;
        cursor: not-allowed;
    }

    .links {
        display: flex;
        justify-content: center;
        gap: 0.5rem;
        font-size: 0.9rem;
    }

    .links a {
        color: var(--color-primary);
        text-decoration: none;
    }

    .links a:hover {
        text-decoration: underline;
    }

    .separator {
        color: var(--color-grey-40);
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

    @media (max-width: 768px) {
        .login-box {
            padding: 2rem;
        }
    }
</style>
