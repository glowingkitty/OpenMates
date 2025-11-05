<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
step_6_top_content_svelte:
    tfa_app_reminder_explainer:
        type: 'text + visual'
        text:
            - $text('signup.2fa_app_reminder.text')
            - $text('signup.in_case_you_forget.text')
        visuals:
            - 'none interactive preview of 'login_2fa_svelte' 2FA interface during login, where user would usually enter 2FA code.'
        purpose:
            - 'Explains how saving the name of the used 2FA app can help the user in case they forget which app they used'
            - 'Shows the user where this is relevant (every time 2FA is required)'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - '2fa'
        connected_documentation:
            - '/signup/2fa-reminder'
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import PasswordAndTfaOtp from '../../../PasswordAndTfaOtp.svelte';
    import { signupStore } from '../../../../stores/signupStore';
    import { get } from 'svelte/store';
    import * as cryptoService from '../../../../services/cryptoService';

    // Props using Svelte 5 runes mode
    let { selectedAppName = null }: { selectedAppName?: string | null } = $props();
    
    // Email state - initialized from store, then updated from encrypted storage if needed
    // After password setup, email is encrypted and stored, so we need to decrypt it asynchronously
    let email = $state<string>('');
    
    // Load email asynchronously using $effect
    // This handles the async nature of getEmailDecryptedWithMasterKey()
    $effect(() => {
        // First try to get from signup store (for early steps before password setup)
        const storeEmail = get(signupStore)?.email;
        if (storeEmail) {
            email = storeEmail;
            return;
        }
        
        // If not in store, try to decrypt from encrypted storage asynchronously
        // This is needed after password setup when email is encrypted
        cryptoService.getEmailDecryptedWithMasterKey().then((decryptedEmail) => {
            if (decryptedEmail) {
                email = decryptedEmail;
            } else {
                // Fallback to example email if decryption fails
                email = 'example@openmates.org';
            }
        }).catch((error) => {
            console.error('[TfaAppReminder] Error retrieving email from encrypted storage:', error);
            // Fallback to example email on error
            email = 'example@openmates.org';
        });
    });
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size reminder"></div>
        <h2 class="signup-menu-title">{@html $text('signup.2fa_app_reminder.text')}</h2>
    </div>

    <div class="text-block">
        {@html $text('signup.in_case_you_forget.text')}
    </div>

    <div class="preview-container">
        <div class="preview-wrapper">
            <PasswordAndTfaOtp
                {email}
                previewMode
                previewTfaAppName="Google Authenticator"
                highlight={['check-2fa', 'app-name']}
                tfaAppName={selectedAppName}
                tfa_required={true}
            />
        </div>
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
    }

    .text-block {
        margin: 20px 0 30px 0;
        text-align: center;
    }

    .preview-container {
        background: var(--color-grey-10);
        padding: 10px;
        border-radius: 20px 20px 0 0;
        width: 80%;
        display: flex;
        justify-content: center;
        pointer-events: none;
        user-select: none;
        -webkit-user-select: none;
        -moz-user-select: none;
        -ms-user-select: none;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }

    

    .preview-wrapper {
        transform: scale(0.8);
        transform-origin: top center;
        margin-top: 20px;
    }

    @media (max-width: 600px) {
        .preview-container {
            width: 100%;
        }

        .text-block {
            margin: 15px 0 15px 0;
        }

        .preview-wrapper {
            margin-top: 5px;
        }
    }
</style>