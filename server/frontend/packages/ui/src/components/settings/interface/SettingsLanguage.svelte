<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml

-->

<script lang="ts">
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import { createEventDispatcher } from 'svelte';

    const dispatch = createEventDispatcher();

    // Languages list example
    const languages = [
        { code: 'en-US', name: 'English (US)' },
        { code: 'en-GB', name: 'English (UK)' },
        { code: 'es', name: 'Español' },
        { code: 'fr', name: 'Français' },
        { code: 'de', name: 'Deutsch' },
        { code: 'ja', name: '日本語' },
        { code: 'zh-CN', name: '简体中文' }
    ];

    // Current language
    let currentLanguage = 'en-US';

    function selectLanguage(code: string) {
        currentLanguage = code;
    }
</script>

<div class="language-settings">
    {#each languages as language}
        <SettingsItem 
            type="submenu"
            icon={language.code === currentLanguage ? 'subsetting_icon subsetting_icon_check' : 'language'}
            title={language.name}
            onClick={() => selectLanguage(language.code)}
        />
    {/each}
</div>

<style>
    .language-settings {
        padding: 10px 0;
    }
</style>