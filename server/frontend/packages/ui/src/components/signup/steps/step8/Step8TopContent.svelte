<!--
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
step_8_top_content_svelte:
    mates_explainer:
        type: 'text'
        text:
            - $text('settings.mates.text')
            - $text('signup.you_can_customize_your_mates.text')
            - $text('signup.click_toggle_to_open_settings.text')
        purpose:
            - 'Explains how to customize digital team mates settings'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - 'mates'
        connected_documentation:
            - '/signup/mates'
    settings_block:
        type: 'settings_block'
        text:
            - $text('signup.default_settings.text')
            - $text('settings.mates.text')
            - $text('settings.mates.text')
        purpose:
            - 'Quick access to Mates settings.'
        processing:
            - 'If the mates button is clicked or the toggle next to it is turned off, then settings menu with the mates category is opened.'
            - 'If the toggle is turned on again or the button is clicked a second time, the settings menu is closed again.'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - 'mates'
        connected_documentation:
            - '/signup/mates'
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { settingsMenuVisible } from '../../../Settings.svelte';
    import SettingsItem from '../../../SettingsItem.svelte';
    import { settingsDeepLink } from '../../../../stores/settingsDeepLinkStore';
    
    // Track toggle states for the mates setting item
    let matesToggleOn = true;
    
    // Track which item is currently open in the settings menu
    let activeSettingsPath: string | null = null;
    
    // Handler for settings item clicks
    function handleSettingsClick(settingsPath: string) {
        // If same item is clicked and settings are visible, close the menu
        if (activeSettingsPath === settingsPath && $settingsMenuVisible) {
            settingsMenuVisible.set(false);
            activeSettingsPath = null;
            // Reset the toggle to true when closing
            if (settingsPath === 'mates') matesToggleOn = true;
            return;
        }
        
        // Otherwise, open the settings menu with the selected path
        activeSettingsPath = settingsPath;
        
        // Update toggle state when opening the settings
        // Toggle OFF when opening the settings
        if (settingsPath === 'mates') matesToggleOn = false;
        
        // Open settings menu and navigate to the specific path
        settingsDeepLink.set(settingsPath);
        settingsMenuVisible.set(true);
    }
    
    // Watch the settingsMenuVisible store to reset state when menu is closed externally
    $: if (!$settingsMenuVisible) {
        // Reset the active settings path when the menu is closed
        activeSettingsPath = null;
        // Reset toggle state to default (ON)
        matesToggleOn = true;
    }
    
    // Handler for settings toggle clicks (needs to behave the same as item click)
    function handleToggleClick(settingsPath: string, event: Event) {
        // Stop event propagation to prevent double triggering
        event.stopPropagation();
        
        // Use the same handler as the item click
        handleSettingsClick(settingsPath);
    }
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size mates"></div>
        <h2 class="menu-title">{@html $text('settings.mates.text')}</h2>
    </div>
    
    <div class="text-block">
        {@html $text('signup.you_can_customize_your_mates.text')}
        <br><br>
        <mark>{@html $text('signup.click_toggle_to_open_settings.text')}</mark>
    </div>
    
    <div class="settings-block">
        <div class="settings-header">
            <div class="default-settings-text">{@html $text('signup.default_settings.text')}</div>
        </div>

        <SettingsItem 
            type="submenu" 
            icon="mates" 
            title={$text('settings.mates.text')}
            onClick={() => handleSettingsClick('mates')}
            hasToggle={true}
            checked={matesToggleOn}
            on:toggleClick={(e) => handleToggleClick('mates', e)}
        />
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
        margin: 20px 0 20px 0;
        text-align: center;
    }
    
    .settings-block {
        width: 80%;
        background-color: var(--color-grey-20);
        border-radius: 16px;
        padding: 16px;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
    }
    
    .settings-header {
        display: flex;
        justify-content: flex-end;
        margin-bottom: 5px;
        padding-right: 10px;
    }
    
    .default-settings-text {
        font-size: 14px;
        color: var(--color-grey-80);
    }
</style>