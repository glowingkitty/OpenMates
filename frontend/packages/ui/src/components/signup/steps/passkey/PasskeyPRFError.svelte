<script lang="ts">
    /**
     * Passkey PRF Error Component
     * 
     * Displays an error message when PRF extension is not supported by the user's
     * password manager or device. Provides a "Continue" button to return to the
     * login method selection screen.
     */
    import { text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import { createEventDispatcher } from 'svelte';
    
    const dispatch = createEventDispatcher();
    
    /**
     * Handle continue button click - return to login method selection
     */
    function handleContinue() {
        dispatch('step', { step: 'secure_account' });
    }
</script>

<div class="content" in:fade={{ duration: 300 }}>
    <div class="signup-header">
        <div class="icon header_size warning"></div>
        <h2 class="signup-menu-title">{@html $text('signup.passkey_prf_error_title')}</h2>
    </div>

    <div class="error-container">
        <p class="error-message">{@html $text('signup.passkey_prf_error_message')}</p>
        
        <button 
            class="continue-button" 
            onclick={handleContinue}
        >
            {@html $text('common.continue')}
        </button>
    </div>
</div>

<style>
    .content {
        padding: var(--spacing-12);
        height: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
    }
    
    .signup-header {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: var(--spacing-8);
        margin-bottom: 30px;
    }
    
    .error-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: var(--spacing-12);
        max-width: 400px;
        text-align: center;
    }
    
    .error-message {
        font-size: var(--font-size-small);
        color: var(--color-grey-70);
        line-height: 1.6;
        margin: 0;
    }
    
    .continue-button {
        padding: var(--spacing-6) var(--spacing-12);
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: var(--radius-3);
        font-size: var(--font-size-p);
        font-weight: 600;
        cursor: pointer;
        transition: background var(--duration-normal) var(--easing-default);
    }
    
    .continue-button:hover {
        background: var(--color-primary-dark);
    }
    
    .continue-button:active {
        transform: scale(0.98);
    }
</style>

