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
    import SettingsItem from '../SettingsItem.svelte';
</script>

<div class="settings-section">
    <SettingsItem 
        type="subsubmenu"
        icon="language"
        subtitle="Language"
        title="English (US)"
        onClick={() => console.log('Open language preferences')}
    />
</div>

<style>
    .settings-section {
        padding: 10px 0;
    }
</style>