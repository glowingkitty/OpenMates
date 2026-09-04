<!--
    Canonical AI model detail page used by top-level and app-skill routes.
    Presents capability, pricing, metadata, and hosting-provider controls.
    All visual composition uses the shared settings element system.
    Design reference: Figma node 5816:61037.
-->
<script lang="ts">
    import { text } from '@repo/ui';
    import { getProviderIconUrl } from '../../data/providerIcons';
    import { authStore } from '../../stores/authStore';
    import { modelsMetadata, type AIModelMetadata } from '../../data/modelsMetadata';
    import { updateProfile, userProfile } from '../../stores/userProfile';
    import { getAiProviderDisplay, getModelCapabilityLevel } from '../../utils/aiModelDisplay';
    import {
        SettingsCapabilityScale,
        SettingsInfoBox,
        SettingsItem,
        SettingsLoadingState,
        SettingsPageContainer,
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
        <div class="ai-model-body">
            <SettingsInfoBox type="info" plain={true} tone="muted" data-testid="ai-model-description">
                {model.description}
            </SettingsInfoBox>

            {#if isAuthenticated}
                <SettingsItem
                    type="ai-row"
                    icon={model.provider_id}
                    iconSrc={getProviderIconUrl(model.logo_svg)}
                    iconAlt=""
                    title={$text('settings.ai_ask.ai_ask_model_details.enable_model')}
                    subtitleBottom={model.name}
                    hasToggle={true}
                    checked={isModelEnabled}
                    data-testid="ai-model-enabled-toggle"
                    onClick={toggleModel}
                />
            {/if}

            <section class="ai-section" data-testid="ai-model-summary-section">
                <h3 class="ai-section-title">{$text('common.details')}</h3>
                <div class="ai-row-list">
                    <div class="capability-row" data-testid="ai-model-capability-row">
                        <SettingsCapabilityScale level={capabilityLevel} label={capabilityLabel} compact={true} />
                        <div class="capability-copy">
                            <span class="capability-title">{$text('settings.ai_ask.ai_ask_settings.capability')}</span>
                            <span class="capability-value">{capabilityLabel}</span>
                        </div>
                    </div>
                    <SettingsItem type="ai-price-row" icon="openmates" title={$text('settings.ai_ask.ai_ask_model_details.origin')} subtitleBottom={providerDisplay.companyName} data-testid="ai-model-origin-row" />
                    {#if formattedReleaseDate}
                        <SettingsItem type="ai-price-row" icon="time" title={$text('settings.ai_ask.ai_ask_model_details.release_date')} subtitleBottom={formattedReleaseDate} data-testid="ai-model-release-row" />
                    {/if}
                    <SettingsItem type="ai-price-row" icon="text" title={$text('settings.ai_ask.ai_ask_model_details.input_types')} subtitleBottom={inputTypes} data-testid="ai-model-input-types-row" />
                    <SettingsItem type="ai-price-row" icon="document" title={$text('settings.ai_ask.ai_ask_model_details.output_types')} subtitleBottom={outputTypes} data-testid="ai-model-output-types-row" />
                </div>
            </section>

            {#if model.pricing}
                <section class="ai-section" data-testid="ai-model-pricing-section">
                    <h3 class="ai-section-title">{$text('common.pricing')}</h3>
                    <div class="ai-row-list">
                        {#if model.pricing.input_tokens_per_credit}
                            <SettingsItem type="ai-price-row" icon="coins" title={$text('settings.ai_ask.ai_ask_model_details.text_input')} subtitleBottom={priceValue(model.pricing.input_tokens_per_credit)} data-testid="ai-model-pricing-input-row" />
                        {/if}
                        {#if model.pricing.output_tokens_per_credit}
                            <SettingsItem type="ai-price-row" icon="coins" title={$text('settings.ai_ask.ai_ask_model_details.text_output')} subtitleBottom={priceValue(model.pricing.output_tokens_per_credit)} data-testid="ai-model-pricing-output-row" />
                        {/if}
                    </div>
                </section>
            {/if}

            <section class="ai-section" data-testid="ai-model-example-chats">
                <h3 class="ai-section-title">{$text('settings.app_store.skills.examples')}</h3>
                <div class="ai-example-list">
                    <SettingsItem type="ai-example-card" icon="chat" title={$text('settings.ai_ask.ai_ask_settings.simple_requests')} subtitleBottom={$text('settings.ai_ask.ai_ask_settings.simple_requests_description')} data-testid="ai-model-example-card" />
                    <SettingsItem type="ai-example-card" icon="chat" title={$text('settings.ai_ask.ai_ask_settings.complex_requests')} subtitleBottom={$text('settings.ai_ask.ai_ask_settings.complex_requests_description')} data-testid="ai-model-example-card" />
                </div>
            </section>

            {#if model.servers?.length}
                <section class="ai-section" data-testid="ai-model-provider-options">
                    <h3 class="ai-section-title">{$text('common.provider')}</h3>
                    <div class="ai-row-list">
                        {#each model.servers as server (server.id)}
                            <SettingsItem
                                type="ai-row"
                                icon="server"
                                title={server.name}
                                subtitleBottom={`${server.region} ${$text('settings.ai_ask.ai_ask_model_details.servers').toLowerCase()}`}
                                hasToggle={isAuthenticated}
                                checked={isServerEnabled(server.id)}
                                data-testid={`ai-model-provider-option-${server.id}`}
                                onClick={() => toggleServer(server.id)}
                            />
                        {/each}
                    </div>
                </section>
            {/if}
        </div>
    {/if}
</SettingsPageContainer>
</div>

<style>
    .ai-model-body {
        display: flex;
        flex-direction: column;
        gap: 1.25rem;
        width: min(100%, 20.1875rem);
        margin: 0 auto;
    }

    .ai-section,
    .ai-row-list,
    .ai-example-list {
        display: flex;
        flex-direction: column;
    }

    .ai-section {
        gap: var(--spacing-5);
    }

    .ai-row-list {
        gap: var(--spacing-4);
    }

    .ai-example-list {
        gap: var(--spacing-6);
    }

    .ai-section-title {
        margin: 0 var(--spacing-10);
        color: var(--color-font-primary);
        font-size: var(--font-size-p);
        font-weight: 700;
        line-height: 1.25;
    }

    .capability-row {
        display: flex;
        align-items: center;
        gap: 0.8125rem;
        min-height: 2.73125rem;
        padding: 0 var(--spacing-10);
        border-radius: 0.559rem;
    }

    .capability-copy {
        display: flex;
        min-width: 0;
        flex-direction: column;
        gap: 0.0625rem;
    }

    .capability-title {
        color: var(--color-ai-settings-muted, var(--color-font-secondary));
        font-size: var(--font-size-small);
        font-weight: 700;
        line-height: 1.25;
    }

    .capability-value {
        color: transparent;
        background: var(--color-primary);
        -webkit-background-clip: text;
        background-clip: text;
        font-size: var(--font-size-p);
        font-weight: 700;
        line-height: 1.25;
    }
</style>
