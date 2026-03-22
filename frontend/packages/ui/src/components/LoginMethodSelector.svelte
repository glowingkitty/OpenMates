<script lang="ts">
    /**
     * Login Method Selector Component
     * 
     * Reusable component for selecting login method (password or passkey).
     * Used in both signup (SecureAccountTopContent) and account recovery flows.
     * 
     * When passkey is selected, this component handles the full WebAuthn registration
     * process including PRF extension for zero-knowledge encryption.
     */
    import { text } from '@repo/ui';
    import { createEventDispatcher } from 'svelte';
    
    const dispatch = createEventDispatcher();
    
    // Props
    let { 
        isLoading = false,
        showPasskey = true,  // Whether to show the passkey option
        showRecommendedBadge = true,  // Whether to show "Recommended" badge on passkey
        disabled = false
    }: { 
        isLoading?: boolean;
        showPasskey?: boolean;
        showRecommendedBadge?: boolean;
        disabled?: boolean;
    } = $props();
    
    // Internal state
    let selectedOption = $state<string | null>(null);
    
    /**
     * Handle selection of login method
     */
    function selectOption(option: string) {
        if (disabled || isLoading) return;
        
        selectedOption = option;
        dispatch('select', { method: option });
    }
</script>

<div class="options-container">
    <p class="instruction-text">{@html $text('signup.how_to_login')}</p>
    
    {#if showPasskey}
        <!-- Passkey Option -->
        <div class="option-wrapper">
            {#if showRecommendedBadge}
                <div class="recommended-badge">
                    <div class="thumbs-up-icon"></div>
                    <span>{@html $text('signup.recommended')}</span>
                </div>
            {/if}
            <button
                class="option-button"
                class:selected={selectedOption === 'passkey'}
                class:loading={isLoading && selectedOption === 'passkey'}
                class:recommended={showRecommendedBadge}
                disabled={disabled || isLoading}
                onclick={() => selectOption('passkey')}
            >
                <div class="option-header">
                    <div class="option-icon">
                        <div class="clickable-icon icon_passkey" style="width: 30px; height: 30px"></div>
                    </div>
                    <div class="option-content">
                        <h3 class="option-title">{@html $text('signup.passkey')}</h3>
                    </div>
                </div>
                <p class="option-description">
                    {isLoading && selectedOption === 'passkey'
                        ? $text('login.loading')
                        : $text('signup.passkey_descriptor')}
                </p>
            </button>
        </div>
    {/if}

    <!-- Password Option -->
    <button
        class="option-button"
        class:selected={selectedOption === 'password'}
        class:loading={isLoading && selectedOption === 'password'}
        disabled={disabled || isLoading}
        onclick={() => selectOption('password')}
    >
        <div class="option-header">
            <div class="option-icon">
                <div class="clickable-icon icon_password" style="width: 30px; height: 30px"></div>
            </div>
            <div class="option-content">
                <h3 class="option-title">{@html $text('signup.password')}</h3>
            </div>
        </div>
        <p class="option-description">{@html $text('signup.password_descriptor')}</p>
    </button>
</div>

<style>
    .options-container {
        width: 100%;
        max-width: 400px;
        display: flex;
        flex-direction: column;
        gap: 16px;
        position: relative;
    }
    
    .instruction-text {
        color: var(--color-grey-60);
        font-size: 16px;
        text-align: center;
        margin-bottom: 8px;
    }
    
    .option-wrapper {
        position: relative;
        width: 100%;
        margin-top: 10px; /* Space for badge */
    }

    .recommended-badge {
        position: absolute;
        top: 0;
        left: 50%;
        transform: translate(-50%, -50%);
        background: var(--color-primary);
        border-radius: 19px;
        padding: 4px 10px;
        display: flex;
        align-items: center;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
        z-index: 2;
        white-space: nowrap;
    }

    .thumbs-up-icon {
        width: 12px;
        height: 12px;
        background-image: url('@openmates/ui/static/icons/thumbsup.svg');
        background-size: contain;
        background-repeat: no-repeat;
        filter: invert(1);
        margin-right: 5px;
    }
    
    .recommended-badge span {
        color: white;
        font-size: 12px;
        font-weight: 600;
    }

    .option-button {
        display: flex;
        flex-direction: column;
        gap: 5px;
        padding: 15px;
        background: var(--color-grey-20);
        border-radius: 16px;
        cursor: pointer;
        transition: all 0.2s ease;
        text-align: center;
        width: 100%;
        height: auto;
        border: none;
        position: relative;
    }

    /* Add recommended style for passkey option */
    .option-button.recommended {
        border: 3px solid transparent;
        background: linear-gradient(var(--color-grey-20), var(--color-grey-20)) padding-box,
                    var(--color-primary) border-box;
    }
    
    .option-button:disabled {
        cursor: not-allowed;
        opacity: 0.6;
    }
    
    .option-button.loading {
        cursor: wait;
    }
    
    .option-button:hover:not(:disabled) {
        background: var(--color-grey-25);
    }
    
    .option-button.recommended:hover:not(:disabled) {
        background: linear-gradient(var(--color-grey-25), var(--color-grey-25)) padding-box,
                    var(--color-primary) border-box;
    }
    
    .option-header {
        display: flex;
        align-items: center;
        gap: 16px;
    }
    
    .option-icon {
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        width: 48px;
        height: 48px;
        background: var(--color-grey-15);
        border-radius: 8px;
    }
    
    .option-button.selected .option-icon {
        background: var(--color-primary-20);
    }
    
    .option-content {
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    
    .option-title {
        font-size: 16px;
        font-weight: 600;
        color: var(--color-grey-80);
        margin: 0;
    }
    
    .option-description {
        font-size: 14px;
        color: var(--color-grey-60);
        margin: 0;
        line-height: 1.4;
    }
</style>

