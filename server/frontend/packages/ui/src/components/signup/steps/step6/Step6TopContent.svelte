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
    import Login2FA from '../../../Login2FA.svelte';

    export let selectedAppName: string | null = null;
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size reminder"></div>
        <h2 class="menu-title">{@html $text('signup.2fa_app_reminder.text')}</h2>
    </div>

    <div class="text-block">
        {@html $text('signup.in_case_you_forget.text')}
    </div>

    <div class="preview-container">
        <div class="preview-wrapper">
            <Login2FA 
                previewMode 
                previewTfaAppName="Google Authenticator" 
                highlight={['check-2fa', 'app-name']} 
                {selectedAppName}
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

    .icon.header_size {
        width: 65px;
        height: 65px;
        border-radius: 14px;
        transition: none;
        animation: none;
        opacity: 1;
    }

    .menu-title {
        font-size: 24px;
        color: var(--color-grey-100);
        margin: 0;
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
</style>