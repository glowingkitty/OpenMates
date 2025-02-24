<!--
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
tfa_app_reminder_explainer:
    type: 'text + visual'
    text:
        - $_('signup.2fa_app_reminder.text')
        - $_('signup.in_case_you_forget.text')
    visuals:
        - 'preview of 2FA interface during login, where user has to enter 2FA code.'
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
    import { text } from '../../../../utils/translations';
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size reminder"></div>
        <h2 class="menu-title">{@html $text('signup.2fa_app_reminder.text')}</h2>
    </div>

    <div class="text-block">
        {@html $text('signup.in_case_you_forget.text')}
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

</style>