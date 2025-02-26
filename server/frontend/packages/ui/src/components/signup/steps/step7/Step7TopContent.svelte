<!--
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
step_7_top_content_svelte:
    settings_explainer:
        type: 'text'
        text:
            - $text('signup.settings.text')
            - $text('signup.default_settings_balance.text')
            - $text('signup.click_toggle_to_open_settings.text')
        purpose:
            - 'Explains how the default settings balance is set and how to modify the settings.'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - 'settings'
        connected_documentation:
            - '/signup/settings'
    settings_block:
        type: 'settings_block'
        text:
            - $text('signup.default_settings.text')
            - $text('settings.privacy.text')
            - $text('settings.apps.text')
            - $text('settings.interface.text')
        purpose:
            - 'Quick access to Privacy, Apps and Interface settings.'
        processing:
            - 'On load, the user icon in the top right is loaded, which opens on click the settings menu.'
            - 'If any of the three buttons Privacy, Apps or Interface is clicked or the toggle next to them is turned off, then settings menu with this category is opened.'
            - 'Or if the user clicks on the user icon, the full settings menu is opened.'
            - 'If the toggle is turned on again or the button is clicked a second time, the settings menu is closed again.'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - 'settings'
        connected_documentation:
            - '/signup/settings'
-->

<script lang="ts">
    import { text } from '@repo/ui';
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size settings"></div>
        <h2 class="menu-title">{@html $text('signup.settings.text')}</h2>
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
</style>