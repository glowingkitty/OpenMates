<!-- frontend/packages/ui/src/components/settings/AiProviderDetailsWrapper.svelte
     Top-level AI provider detail page.
     Shows all AI Ask models hosted on a given server provider as an
     informational list (no toggles, no links). Extracts the provider id
     from the `ai/provider/{providerId}` route.
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { modelsMetadata } from '../../data/modelsMetadata';
    import { providersMetadata } from '../../data/providersMetadata';
    import { getProviderIconUrl } from '../../data/providerIcons';
    import { SettingsSectionHeading } from './elements';
    import { simplifyProviderName } from '../../utils/providerDisplay';

    interface Props {
        activeSettingsView?: string;
    }

    let { activeSettingsView = '' }: Props = $props();

    let providerId = $derived(activeSettingsView.replace('ai/provider/', ''));

    let providerMeta = $derived(providersMetadata[providerId]);

    /** Resolve the display name for this provider from the first matching
     *  model server entry, falling back to providersMetadata. Simplified
     *  for the UI (strip " API" suffix). */
    let providerDisplayName = $derived.by(() => {
        for (const model of modelsMetadata) {
            for (const server of model.servers ?? []) {
                if (server.id === providerId) return simplifyProviderName(server.name);
            }
        }
        return providerMeta?.name ?? providerId;
    });

    /** Models that are hosted on this server provider. */
    let providerModels = $derived(
        modelsMetadata.filter(model =>
            model.for_app_skill === 'ai.ask' &&
            (model.servers ?? []).some(s => s.id === providerId)
        )
    );
</script>

<div class="ai-provider-details" data-testid="ai-provider-details">
    <div class="section">
        <SettingsSectionHeading
            title={$text('settings.ai.provider_models_heading').replace('{provider}', providerDisplayName)}
            icon="ai"
        />
        <p class="description">
            {$text('settings.ai.provider_models_description').replace('{provider}', providerDisplayName)}
        </p>

        <div class="models-list">
            {#each providerModels as model (model.id)}
                <div class="model-item" data-testid="provider-model-item">
                    <div class="model-icon">
                        <img
                            src={getProviderIconUrl(model.logo_svg)}
                            alt={model.provider_name}
                            class="provider-logo"
                        />
                    </div>
                    <div class="model-info">
                        <span class="model-name">{model.name}</span>
                        <span class="model-provider">{simplifyProviderName(model.provider_name)}</span>
                    </div>
                </div>
            {/each}

            {#if providerModels.length === 0}
                <div class="no-results">
                    <p>{$text('settings.ai_ask.ai_ask_settings.no_models_found')}</p>
                </div>
            {/if}
        </div>
    </div>
</div>

<style>
    .ai-provider-details {
        padding: 14px;
        max-width: 1400px;
        margin: 0 auto;
    }

    .section {
        margin-top: 0.5rem;
    }

    .description {
        margin: 0.35rem 0 1rem 0;
        padding: 0;
        font-size: 0.875rem;
        line-height: 1.5;
        color: var(--color-grey-60);
    }

    .models-list {
        display: flex;
        flex-direction: column;
        gap: 0;
        margin-left: var(--spacing-5);
    }

    .model-item {
        display: flex;
        align-items: center;
        gap: var(--spacing-6);
        padding: var(--spacing-6) var(--spacing-8);
        border-radius: var(--radius-3);
    }

    .model-icon {
        flex-shrink: 0;
        width: 40px;
        height: 40px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .provider-logo {
        width: 36px;
        height: 36px;
        border-radius: var(--radius-3);
        object-fit: contain;
        background: var(--color-grey-10);
        padding: var(--spacing-2);
    }

    .model-info {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: var(--spacing-1);
    }

    .model-name {
        font-size: 1rem;
        font-weight: 500;
        color: var(--color-grey-100);
    }

    .model-provider {
        font-size: 0.875rem;
        color: var(--color-grey-60);
    }

    .no-results {
        padding: 2rem;
        text-align: center;
    }

    .no-results p {
        margin: 0;
        color: var(--color-grey-50);
        font-size: 0.875rem;
    }

    :global(.dark) .provider-logo {
        background: var(--color-grey-20);
    }
</style>
