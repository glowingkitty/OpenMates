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
        <h2 class="signup-menu-title">{@html $text('signup.passkey_prf_error_title.text')}</h2>
    </div>

    <div class="error-container">
        <p class="error-message">{@html $text('signup.passkey_prf_error_message.text')}</p>
        
        <button 
            class="continue-button" 
            onclick={handleContinue}
        >
            {@html $text('signup.continue.text')}
        </button>
    </div>
</div>

<style>
    .content {
        padding: 24px;
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
        gap: 16px;
        margin-bottom: 30px;
    }
    
    .error-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 24px;
        max-width: 400px;
        text-align: center;
    }
    
    .error-message {
        font-size: 14px;
        color: var(--color-grey-70);
        line-height: 1.6;
        margin: 0;
    }
    
    .continue-button {
        padding: 12px 24px;
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 16px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.2s ease;
    }
    
    .continue-button:hover {
        background: var(--color-primary-dark);
    }
    
    .continue-button:active {
        transform: scale(0.98);
    }
</style>

