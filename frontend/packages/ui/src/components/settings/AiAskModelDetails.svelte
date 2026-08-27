<!--
    Canonical AI model detail page used by top-level and app-skill routes.
    Presents capability, pricing, metadata, and hosting-provider controls.
    All visual composition uses the shared settings element system.
    Design reference: Figma node 5816:61037.
-->
<script lang="ts">
    import { text } from '@repo/ui';
    import { authStore } from '../../stores/authStore';
    import { modelsMetadata, type AIModelMetadata } from '../../data/modelsMetadata';
    import { updateProfile, userProfile } from '../../stores/userProfile';
    import { getAiProviderDisplay, getModelCapabilityLevel } from '../../utils/aiModelDisplay';
    import {
        SettingsCapabilityScale,
        SettingsCard,
        SettingsDetailRow,
        SettingsInfoBox,
        SettingsItem,
        SettingsLoadingState,
        SettingsPageContainer,
        SettingsSectionHeading,
    } from './elements';

    interface Props {
        modelId: string;
    }

    let { modelId }: Props = $props();
    const model = $derived<AIModelMetadata | undefined>(modelsMetadata.find((candidate) => candidate.id === modelId));
    const disabledModels = $derived($userProfile.disabled_ai_models ?? []);
    const disabledServers = $derived($userProfile.disabled_ai_servers ?? {});
    const isAuthenticated = $derived($authStore.isAuthenticated);
    const isModelEnabled = $derived(!disabledModels.includes(modelId));
    const providerDisplay = $derived(
        getAiProviderDisplay(model?.provider_id ?? '', model?.provider_name ?? '')
    );
    const capabilityLevel = $derived(model ? getModelCapabilityLevel(model) : 'medium');
    const capabilityLabel = $derived($text(`settings.ai_ask.ai_ask_settings.capability_${capabilityLevel}`));
    const formattedReleaseDate = $derived.by(() => {
        if (!model?.release_date) return '';
        const date = new Date(model.release_date);
        return Number.isNaN(date.getTime())
            ? model.release_date
            : date.toLocaleDateString(undefined, { year: 'numeric', month: 'long' });
    });
    const inputTypes = $derived(model?.input_types.map(translateInputType).join(', ') ?? '');
    const outputTypes = $derived(model?.output_types.map(translateOutputType).join(', ') ?? '');

    function translateInputType(type: AIModelMetadata['input_types'][number]): string {
        if (type === 'text') return $text('settings.ai_ask.ai_ask_model_details.input_type_text');
        if (type === 'image') return $text('common.images');
        if (type === 'video') return $text('settings.ai_ask.ai_ask_model_details.input_type_video');
        return $text('common.audio');
    }

    function translateOutputType(type: AIModelMetadata['output_types'][number]): string {
        return type === 'text'
            ? $text('settings.ai_ask.ai_ask_model_details.output_type_text')
            : $text('common.images');
    }

    function toggleModel(): void {
        updateProfile({
            disabled_ai_models: isModelEnabled
                ? [...disabledModels, modelId]
                : disabledModels.filter((id) => id !== modelId),
        });
    }

    function isServerEnabled(serverId: string): boolean {
        return !(disabledServers[modelId] ?? []).includes(serverId);
    }

    function toggleServer(serverId: string): void {
        const current = disabledServers[modelId] ?? [];
        const next = isServerEnabled(serverId)
            ? [...current, serverId]
            : current.filter((id) => id !== serverId);
        const nextDisabledServers = { ...disabledServers };
        if (next.length > 0) nextDisabledServers[modelId] = next;
        else delete nextDisabledServers[modelId];
        updateProfile({ disabled_ai_servers: nextDisabledServers });
    }

    function priceValue(tokensPerCredit: number): string {
        return `1 ${$text('common.credits')} ${$text('settings.ai_ask.ai_ask_settings.per')} ${tokensPerCredit} ${$text('settings.ai_ask.ai_ask_settings.tokens')}`;
    }
</script>

<div data-testid="ai-model-details">
<SettingsPageContainer maxWidth="wide">
    {#if !model}
        <SettingsLoadingState variant="empty" text={$text('settings.ai_ask.ai_ask_model_details.model_not_found')} />
    {:else}
        <SettingsInfoBox type="info">{model.description}</SettingsInfoBox>

        {#if isAuthenticated}
            <SettingsItem
                type="submenu"
                icon="ai"
                title={$text('settings.ai_ask.ai_ask_model_details.enable_model')}
                hasToggle={true}
                checked={isModelEnabled}
                data-testid="ai-model-enabled-toggle"
                onClick={toggleModel}
            />
        {/if}

        <SettingsSectionHeading title={$text('settings.ai_ask.ai_ask_settings.capability')} icon="insight" />
        <SettingsCard padding="sm">
            <SettingsCapabilityScale level={capabilityLevel} label={capabilityLabel} />
        </SettingsCard>

        <SettingsSectionHeading title={$text('common.details')} icon="insight" />
        <SettingsCard padding="sm">
            <SettingsDetailRow label={$text('settings.ai_ask.ai_ask_model_details.origin')} value={providerDisplay.companyName} highlight={true} />
            {#if formattedReleaseDate}
                <SettingsDetailRow label={$text('settings.ai_ask.ai_ask_model_details.release_date')} value={formattedReleaseDate} />
            {/if}
            <SettingsDetailRow label={$text('settings.ai_ask.ai_ask_model_details.input_types')} value={inputTypes} />
            <SettingsDetailRow label={$text('settings.ai_ask.ai_ask_model_details.output_types')} value={outputTypes} />
        </SettingsCard>

        {#if model.pricing}
            <SettingsSectionHeading title={$text('common.pricing')} icon="coins" />
            <SettingsCard padding="sm">
                {#if model.pricing.input_tokens_per_credit}
                    <SettingsDetailRow label={$text('settings.ai_ask.ai_ask_model_details.text_input')} value={priceValue(model.pricing.input_tokens_per_credit)} highlight={true} />
                {/if}
                {#if model.pricing.output_tokens_per_credit}
                    <SettingsDetailRow label={$text('settings.ai_ask.ai_ask_model_details.text_output')} value={priceValue(model.pricing.output_tokens_per_credit)} highlight={true} />
                {/if}
            </SettingsCard>
        {/if}

        {#if model.servers?.length}
            <section data-testid="ai-model-provider-options">
                <SettingsSectionHeading title={$text('common.provider')} icon="server" />
                {#each model.servers as server (server.id)}
                    <SettingsItem
                        type="submenu"
                        icon="server"
                        title={server.name}
                        subtitleBottom={`${server.region} ${$text('settings.ai_ask.ai_ask_model_details.servers').toLowerCase()}`}
                        hasToggle={isAuthenticated}
                        checked={isServerEnabled(server.id)}
                        data-testid={`ai-model-provider-option-${server.id}`}
                        onClick={() => toggleServer(server.id)}
                    />
                {/each}
            </section>
        {/if}
    {/if}
</SettingsPageContainer>
</div>
