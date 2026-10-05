<script lang="ts">
    import { text } from '@repo/ui';
    import type { PublishedAppMemory } from '../../types/apps';
    import { SettingsCodeBlock, SettingsInfoBox, SettingsSectionHeading, SettingsPageContainer } from './elements';

    let { memory }: { memory: PublishedAppMemory } = $props();
</script>

<SettingsPageContainer>
<SettingsSectionHeading title={memory.title} icon="settings_memories" />
<SettingsInfoBox>{$text('memories.app_loading')}</SettingsInfoBox>
<SettingsCodeBlock code={memory.body} copyable dataTestid="published-memory-body" />
</SettingsPageContainer>
