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
    import SettingsItem from '../../../SettingsItem.svelte';
    import { settingsDeepLink } from '../../../../stores/settingsDeepLinkStore';
    // Removed isMobileView import as it wasn't used and was incorrectly imported
    import { panelState } from '../../../../stores/panelStateStore'; // Added panelState import
    
    // Track toggle states for each setting item using Svelte 5 runes
    let privacyToggleOn = $state(true);
    let appsToggleOn = $state(true);
    let interfaceToggleOn = $state(true);
    
    // Track which item is currently open in the settings menu using Svelte 5 runes
    let activeSettingsPath: string | null = $state(null);
    
    // Handler for settings item clicks
    function handleSettingsClick(settingsPath: string) {
        // If same item is clicked and settings are visible, close the menu using panelState
        if (activeSettingsPath === settingsPath && $panelState.isSettingsOpen) {
            panelState.closeSettings();
            activeSettingsPath = null;
            // Reset the toggle to true when closing
            if (settingsPath === 'privacy') privacyToggleOn = true;
            if (settingsPath === 'apps') appsToggleOn = true;
            if (settingsPath === 'interface') interfaceToggleOn = true;
            return;
        }
        
        // Otherwise, open the settings menu with the selected path
        activeSettingsPath = settingsPath;
        
        // Update toggle state based on which item was clicked
        // Toggle OFF when opening the settings
        if (settingsPath === 'privacy') privacyToggleOn = false;
        else if (settingsPath === 'apps') appsToggleOn = false;
        else if (settingsPath === 'interface') interfaceToggleOn = false;
        
        // First set the deep link path to navigate to specific settings
        settingsDeepLink.set(settingsPath);
        
        // Then make sure menu is visible using panelState
        setTimeout(() => {
            panelState.openSettings();
        }, 10);
    }
    
    // Watch the panelState store to reset state when menu is closed externally using Svelte 5 runes
    $effect(() => {
        if (!$panelState.isSettingsOpen) {
            // Reset the active settings path when the menu is closed
            activeSettingsPath = null;
            // Reset all toggle states to default (ON)
            privacyToggleOn = true;
            appsToggleOn = true;
            interfaceToggleOn = true;
        }
    });
    
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
        <div class="icon header_size settings"></div>
        <h2 class="signup-menu-title">{@html $text('signup.settings.text')}</h2>
    </div>
    
    <div class="text-block">
        {@html $text('signup.default_settings_balance.text')}
        <span class="break-line"></span>
        <span class="break-line mobile-hidden"></span>
        <mark>{@html $text('signup.click_toggle_to_open_settings.text')}</mark>
    </div>
    
    <div class="settings-block">
        <div class="settings-header">
            <div class="default-settings-text">{@html $text('signup.default_settings.text')}</div>
        </div>

        <SettingsItem 
            type="submenu" 
            icon="privacy" 
            title={$text('settings.privacy.text')}
            onClick={() => handleSettingsClick('privacy')}
            hasToggle={true}
            checked={privacyToggleOn}
            on:toggleClick={(e) => handleToggleClick('privacy', e.detail)}
        />
        <SettingsItem 
            type="submenu" 
            icon="apps" 
            title={$text('settings.apps.text')}
            onClick={() => handleSettingsClick('apps')}
            hasToggle={true}
            checked={appsToggleOn}
            on:toggleClick={(e) => handleToggleClick('apps', e.detail)}
        />
        <SettingsItem 
            type="submenu" 
            icon="interface" 
            title={$text('settings.interface.text')}
            onClick={() => handleSettingsClick('interface')}
            hasToggle={true}
            checked={interfaceToggleOn}
            on:toggleClick={(e) => handleToggleClick('interface', e.detail)}
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
        position: relative; /* Add position relative */
    }

    .signup-header {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 16px;
    }

    .text-block {
        margin: 20px 0 20px 0;
        text-align: center;
    }
    
    .settings-block {
        width: 80%;
        background-color: var(--color-grey-20);
        border-radius: 16px 16px 0 0;
        padding: 16px;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
    }

    .settings-header {
        display: flex;
        justify-content: flex-end;
        padding-right: 10px;
    }
    
    .default-settings-text {
        font-size: 14px;
        color: var(--color-grey-80);
    }

    .break-line {
        display: block;
        height: 8px;
    }
    
    @media (max-width: 600px) {
        .mobile-hidden {
            height: 0px;
        }

        .settings-block {
            width: 100%;
        }

        .text-block {
            margin: 10px 0 10px 0;
        }

        .content {
            padding: 12px;
        }
    }
</style>