<!-- frontend/packages/ui/src/components/enter_message/ComposerModelSelector.svelte -->
<!-- Always-visible Auto or exact-model selector for the message composer. -->
<!-- Groups exact models by provider while preserving compact mobile layout. -->
<!-- Selection is owned by MessageInput and applied to the outgoing request. -->
<!-- Design reference: Figma node 5815:59169. -->

<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount } from 'svelte';
    import Toggle from '../Toggle.svelte';
    import { SettingsCapabilityScale } from '../settings/elements';
    import { modelsMetadata, type AIModelMetadata } from '../../data/modelsMetadata';
    import { getProviderIconUrl } from '../../data/providerIcons';
    import { isProviderHealthy } from '../../stores/appHealthStore';
    import { userProfile } from '../../stores/userProfile';
    import { compareAiProviders, getAiProviderDisplay, getModelCapabilityLevel } from '../../utils/aiModelDisplay';
    import { aiModelSelectionValue } from '../../utils/aiModelSelection';

    interface Props {
        selection: string;
        ready?: boolean;
        onSelect: (selection: string) => void;
        onOpenDetails: (modelId: string) => void;
    }

    let { selection, ready = true, onSelect, onOpenDetails }: Props = $props();
    let isOpen = $state(false);
    let activeProvider = $state<string | null>(null);
    let showAllProviders = $state(false);
    let selectorElement: HTMLDivElement;
    let selectorTrigger = $state<HTMLButtonElement>();
    let selectorMenu = $state<HTMLDivElement>();
    const models = $derived(modelsMetadata.filter((model) =>
        model.for_app_skill === 'ai.ask'
        && !$userProfile.disabled_ai_models?.includes(model.id)
        && !!model.servers?.some((server) =>
            !$userProfile.disabled_ai_servers?.[model.id]?.includes(server.id)
            && $isProviderHealthy(server.id)
        )
    ));
    const selectedModel = $derived(models.find((model) => aiModelSelectionValue(model) === selection) ?? null);
    const selectedLabel = $derived(ready
        ? selectedModel?.name ?? $text('settings.ai_ask.ai_ask_settings.model_auto')
        : $text('common.loading'));
    const selectorAriaLabel = $derived(`${$text('enter_message.model_selector.model_selection')}: ${selectedLabel}`);
    const providers = $derived.by(() => {
        const entries = new Map<string, AIModelMetadata>();
        for (const model of models) {
            if (!entries.has(model.provider_id)) entries.set(model.provider_id, model);
        }
        return [...entries.values()].sort(compareAiProviders);
    });
    const visibleProviders = $derived(showAllProviders ? providers : providers.slice(0, 4));
    const providerModels = $derived(activeProvider ? models.filter((model) => model.provider_id === activeProvider) : []);

    function select(selectionValue: string): void {
        onSelect(selectionValue);
        isOpen = false;
        activeProvider = null;
        showAllProviders = false;
    }

    function openDetails(modelId: string): void {
        isOpen = false;
        activeProvider = null;
        showAllProviders = false;
        onOpenDetails(modelId);
    }

    function toggleModel(model: AIModelMetadata): void {
        const modelSelection = aiModelSelectionValue(model);
        select(selection === modelSelection ? 'auto' : modelSelection);
    }

    function capabilityLabel(model: AIModelMetadata): string {
        return $text(`settings.ai_ask.ai_ask_settings.capability_${getModelCapabilityLevel(model)}`);
    }

    function toggleSelector(): void {
        isOpen = !isOpen;
    }

    $effect(() => {
        if (isOpen && selectorMenu) selectorMenu.focus();
    });

    onMount(() => {
        const handlePointerDown = (event: PointerEvent) => {
            if (!selectorElement.contains(event.target as Node)) {
                isOpen = false;
                activeProvider = null;
                showAllProviders = false;
            }
        };
        document.addEventListener('pointerdown', handlePointerDown);
        return () => document.removeEventListener('pointerdown', handlePointerDown);
    });

    function closeOnKeydown(event: KeyboardEvent): void {
        if (event.key === 'Escape') {
            event.preventDefault();
            isOpen = false;
            activeProvider = null;
            showAllProviders = false;
            selectorTrigger?.focus();
        } else if (event.key === 'ArrowDown' && !isOpen) {
            event.preventDefault();
            isOpen = true;
        }
    }
</script>

<div class="model-selector" bind:this={selectorElement} data-preserve-composer-focus="true">
    <button
        type="button"
        class="model-selector-trigger"
        bind:this={selectorTrigger}
        data-testid="composer-model-selector"
        aria-label={selectorAriaLabel}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        disabled={!ready}
        data-loading={!ready}
        onclick={toggleSelector}
        onkeydown={closeOnKeydown}
    >
        {#if selectedModel}
            <img src={getProviderIconUrl(selectedModel.logo_svg)} alt="" />
        {:else}
            <span class="clickable-icon icon_ai"></span>
        {/if}
        <span class="model-selector-label" data-testid="composer-model-selector-label">{selectedLabel}</span>
    </button>

    {#if isOpen}
        <div
            class="model-selector-menu"
            bind:this={selectorMenu}
            data-testid="composer-model-selector-menu"
            role="dialog"
            aria-label={$text('enter_message.model_selector.model_selection')}
            tabindex="-1"
            onkeydown={closeOnKeydown}
        >
            {#if activeProvider}
                <button type="button" class="menu-heading" onclick={() => activeProvider = null}>
                    <span class="clickable-icon icon_back"></span>
                    {$text('enter_message.model_selector.model_selection')}
                </button>
                {#each providerModels as model (model.id)}
                    {@const isSelected = selection === aiModelSelectionValue(model)}
                    <div class="model-menu-row" data-testid="composer-model-row">
                        <button
                            type="button"
                            class="menu-item"
                            data-testid="composer-model-name"
                            aria-label={`${$text('enter_message.model_selector.model_details')}: ${model.name}`}
                            onclick={() => openDetails(model.id)}
                        >
                            <span class="model-icon" data-testid="composer-model-icon" aria-hidden="true">
                                <img src={getProviderIconUrl(model.logo_svg)} alt="" />
                                <span class="model-capability">
                                    <SettingsCapabilityScale
                                        level={getModelCapabilityLevel(model)}
                                        label={capabilityLabel(model)}
                                        compact={true}
                                        data-testid="composer-model-capability"
                                    />
                                </span>
                            </span>
                            <strong>{model.name}</strong>
                        </button>
                        <Toggle
                            checked={isSelected}
                            ariaLabel={model.name}
                            testId="composer-model-toggle"
                            on:change={() => toggleModel(model)}
                        />
                    </div>
                {/each}
            {:else}
                <button type="button" class="menu-item" data-testid="composer-model-auto" onclick={() => select('auto')}>
                    <span class="clickable-icon icon_ai"></span>
                    <span><strong>{$text('settings.ai_ask.ai_ask_settings.model_auto')}</strong><small>{$text('settings.ai_ask.ai_ask_settings.auto_description')}</small></span>
                </button>
                {#each visibleProviders as provider (provider.provider_id)}
                    {@const display = getAiProviderDisplay(provider.provider_id, provider.provider_name)}
                    <button type="button" class="menu-item" data-testid={`composer-model-provider-${provider.provider_id}`} onclick={() => activeProvider = provider.provider_id}>
                        <img src={getProviderIconUrl(provider.logo_svg)} alt="" />
                        <span>
                            <strong>{display.brandName}</strong>
                            {#if display.brandName !== display.companyName}
                                <small>{$text('enter_message.mention_dropdown.from_provider').replace('{provider}', display.companyName)}</small>
                            {/if}
                        </span>
                    </button>
                {/each}
                {#if !showAllProviders && providers.length > visibleProviders.length}
                    <button type="button" class="show-more" data-testid="composer-model-show-more" onclick={() => showAllProviders = true}>
                        {$text('enter_message.mention_dropdown.show_more')}
                    </button>
                {/if}
            {/if}
        </div>
    {/if}
</div>

<style>
    .model-selector { position: relative; }
    .model-selector-trigger { display: flex; align-items: center; gap: var(--spacing-2); min-width: 0; padding: var(--spacing-2); border: 0; color: var(--color-primary-start); background: transparent; cursor: pointer; }
    .model-selector-trigger:disabled { opacity: 0.65; cursor: wait; }
    .model-selector-trigger img, .menu-item > img, .model-icon > img { width: 1.75rem; height: 1.75rem; object-fit: contain; border-radius: var(--radius-2); }
    .model-selector-label { max-width: 8rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
    .model-selector-menu { position: absolute; z-index: var(--z-index-dropdown); bottom: calc(100% + var(--spacing-4)); left: 0; width: min(18rem, calc(100vw - 2rem)); max-height: 22rem; overflow-y: auto; padding: var(--spacing-2); background: var(--color-grey-0); border-radius: var(--radius-8); box-shadow: var(--shadow-lg); }
    .menu-item, .menu-heading { display: flex; align-items: center; justify-content: flex-start; gap: var(--spacing-4); width: 100%; padding: var(--spacing-4); border: 0; border-radius: var(--radius-3); color: var(--color-font-primary); text-align: start; background: transparent; cursor: pointer; }
    .menu-item:hover, .menu-heading:hover { background: var(--color-grey-10); }
    .menu-item span { display: flex; flex-direction: column; min-width: 0; }
    .menu-item strong { color: var(--color-primary-start); }
    .menu-item small { color: var(--color-font-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .model-menu-row { display: flex; align-items: center; gap: var(--spacing-2); width: 100%; }
    .model-menu-row .menu-item { flex: 1; min-width: 0; }
    .model-icon { position: relative; display: inline-flex; flex: 0 0 auto; }
    .model-capability { position: absolute; right: -0.25rem; bottom: -0.25rem; display: inline-flex; }
    .model-capability :global(.capability-scale) { line-height: 1; }
    .model-capability :global(.bars) { width: 1rem; height: 1rem; padding: 0.1875rem; }
    .model-menu-row :global(.toggle) { width: 3.0625rem; min-width: 3.0625rem; height: 1.8125rem; margin-left: auto; }
    .model-menu-row :global(.toggle .slider:before) { width: 1.5625rem; height: 1.5625rem; left: 0.125rem; bottom: 0.125rem; }
    .model-menu-row :global(.toggle input:checked + .slider:before) { transform: translateX(1.25rem); }
    .show-more { width: 100%; padding: var(--spacing-3) var(--spacing-4); border: 0; color: var(--color-font-secondary); text-align: center; background: transparent; cursor: pointer; }
    @media (max-width: 34rem) { .model-selector-label { display: none; } }
</style>
