<script lang="ts">
    /**
     * Passkey Registration Top Content Component
     * 
     * Displays instructions for passkey registration.
     * The actual WebAuthn registration is handled in PasskeyRegistrationBottomContent.
     */
    import { text } from '@repo/ui';
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size secret"></div>
        <h2 class="signup-menu-title">{@html $text('signup.passkey')}</h2>
    </div>

    <h3 class="advice-title">{@html $text('signup.passkey_instruction_title')}</h3>
    <p class="advice-text">{@html $text('signup.passkey_instruction_text')}</p>
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
        text-align: center;
        max-width: 400px;
    }
</style>

