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
    import { onMount, onDestroy } from 'svelte';
    import { settingsMenuVisible } from '../../../Settings.svelte';
    import { isSignupSettingsStep } from '../../../../stores/signupState';
    
    // Auto-set the settings step state when this step is mounted
    // but DON'T auto-open the menu - let the user click to open it
    onMount(() => {
        // Set the settings step state
        isSignupSettingsStep.set(true);
        
        // Do NOT auto-open settings menu anymore
        // settingsMenuVisible.set(true);
    });
    
    onDestroy(() => {
        // Clean up when component is unmounted
        settingsMenuVisible.set(false);
        isSignupSettingsStep.set(false);
    });
    
    // Handle click on one of the settings options
    function handleSettingClick() {
        // When user clicks any setting, open the menu
        settingsMenuVisible.set(true);
    }
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size settings"></div>
        <h2 class="menu-title">{@html $text('signup.settings.text')}</h2>
    </div>
    
    <div class="text-block">
        {@html $text('signup.default_settings_balance.text')}
        <br><br>
        {@html $text('signup.click_toggle_to_open_settings.text')}
    </div>
    
    <div class="settings-block">
        <h3>{@html $text('signup.default_settings.text')}</h3>
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
    
    .settings-block {
        width: 90%;
        background-color: var(--color-grey-20);
        border-radius: 16px;
        padding: 16px;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
    }
    
    .settings-block h3 {
        margin-top: 0;
        margin-bottom: 16px;
        color: var(--color-grey-80);
    }
    
    .settings-options {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }
    
    .setting-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 0;
        border-bottom: 1px solid var(--color-grey-30);
        cursor: pointer;
        transition: background-color 0.2s;
    }
    
    .setting-item:hover {
        background-color: var(--color-grey-30);
        border-radius: 6px;
        padding-left: 8px;
        padding-right: 8px;
    }
    
    .setting-toggle {
        width: 36px;
        height: 20px;
        background-color: var(--color-primary-light);
        border-radius: 10px;
        position: relative;
    }
    
    .setting-toggle::after {
        content: "";
        position: absolute;
        width: 18px;
        height: 18px;
        background-color: white;
        border-radius: 50%;
        top: 1px;
        right: 1px;
        transition: transform 0.2s;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
    }
    
    .setting-label {
        color: var(--color-grey-80);
        font-weight: 500;
    }
</style>