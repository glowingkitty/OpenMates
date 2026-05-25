<!-- yaml_details
# YAML file explains structure of the UI.
# The yaml structure is used as a base for auto generating & auto updating the documentations
# and to help LLMs to answer questions regarding how the UI is used.
# Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
# changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml

-->

<script lang="ts">
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import { UI_FONT_OPTIONS, setUiFont, uiFont, type UiFont } from '../../../stores/uiFont';
    import { updateProfile } from '../../../stores/userProfile';
    import { createEventDispatcher } from 'svelte';

    const dispatch = createEventDispatcher();

    async function handleFontChange(font: UiFont) {
        if (font === $uiFont) return;

        await setUiFont(font, true);
        updateProfile({ ui_font: font });
        dispatch('fontChanged', { font });
    }
</script>

<div class="settings-font-container">
    {#each UI_FONT_OPTIONS as fontOption}
        <SettingsItem
            type="quickaction"
            icon="subsetting_icon language"
            title={$text(fontOption.labelKey)}
            subtitle={$text(fontOption.descriptionKey)}
            hasToggle={true}
            checked={$uiFont === fontOption.value}
            onClick={() => handleFontChange(fontOption.value)}
        />
    {/each}
</div>

<style>
    .settings-font-container {
        display: flex;
        flex-direction: column;
        gap: 5px;
    }
</style>
