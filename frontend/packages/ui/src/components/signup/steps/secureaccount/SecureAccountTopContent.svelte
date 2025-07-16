<script lang="ts">
    import { text } from '@repo/ui';
    import { theme } from '../../../../stores/theme';
    import { createEventDispatcher } from 'svelte';
    
    const dispatch = createEventDispatcher();
    
    // For now, only password option is available
    let selectedOption: string | null = null;
    
    function selectOption(option: string) {
        selectedOption = option;
        // For now, only password is available, so immediately proceed to password step
        if (option === 'password') {
            dispatch('step', { step: 'password' });
        }
    }
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size secret"></div>
        <h2 class="signup-menu-title">{@html $text('signup.secure_your_account.text')}</h2>
    </div>

    <div class="options-container">
        <p class="instruction-text">{@html $text('signup.click_on_an_option.text')}</p>
        
        <!-- Password Option -->
        <button 
            class="option-button" 
            class:selected={selectedOption === 'password'}
            on:click={() => selectOption('password')}
        >
            <div class="option-icon">
                <div class="icon medium password"></div>
            </div>
            <div class="option-content">
                <h3 class="option-title">{@html $text('signup.password.text')}</h3>
                <p class="option-description">{@html $text('signup.password_descriptor.text')}</p>
            </div>
        </button>

        <!-- Additional options like Passkey and security keys will be added later -->

        <p class="additional-options-text">{@html $text('signup.additional_options_follow_soon.text')}</p>
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
    
    .options-container {
        width: 100%;
        max-width: 400px;
        display: flex;
        flex-direction: column;
        gap: 16px;
    }
    
    .instruction-text {
        color: var(--color-grey-60);
        font-size: 16px;
        text-align: center;
        margin-bottom: 8px;
    }
    
    .option-button {
        display: flex;
        align-items: center;
        gap: 16px;
        padding: 20px;
        background: var(--color-grey-5);
        border: 2px solid var(--color-grey-20);
        border-radius: 12px;
        cursor: pointer;
        transition: all 0.2s ease;
        text-align: left;
        width: 100%;
    }
    
    .option-button:hover:not(.disabled) {
        border-color: var(--color-primary);
        background: var(--color-grey-10);
    }
    
    .option-button.selected {
        border-color: var(--color-primary);
        background: var(--color-primary-10);
    }
    
    .option-button.disabled {
        opacity: 0.5;
        cursor: not-allowed;
        background: var(--color-grey-5);
        border-color: var(--color-grey-15);
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
    
    .option-button.disabled .option-icon {
        background: var(--color-grey-10);
    }
    
    .option-content {
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    
    .option-title {
        font-size: 18px;
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
    
    .option-button.disabled .option-title,
    .option-button.disabled .option-description {
        color: var(--color-grey-40);
    }
    
    .additional-options-text {
        font-size: 14px;
        color: var(--color-grey-50);
        text-align: center;
        margin-top: 16px;
        font-style: italic;
    }
</style>
