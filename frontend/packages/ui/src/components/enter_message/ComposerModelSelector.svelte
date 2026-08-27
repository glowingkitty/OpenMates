<!-- frontend/packages/ui/src/components/enter_message/ComposerModelSelector.svelte -->
<!-- Always-visible Auto or exact-model selector for the message composer. -->
<!-- Groups exact models by provider while preserving compact mobile layout. -->
<!-- Selection is owned by MessageInput and applied to the outgoing request. -->
<!-- Design reference: Figma node 5815:59169. -->

<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount } from 'svelte';
    import { modelsMetadata, type AIModelMetadata } from '../../data/modelsMetadata';
    import { getProviderIconUrl } from '../../data/providerIcons';
    import { simplifyProviderName } from '../../utils/providerDisplay';

    interface Props {
        selection: string;
        onSelect: (selection: string) => void;
        onOpenDetails: (modelId: string) => void;
    }

    let { selection, onSelect, onOpenDetails }: Props = $props();
    let isOpen = $state(false);
    let activeProvider = $state<string | null>(null);
    let selectorElement: HTMLDivElement;
    const models = $derived(modelsMetadata.filter((model) => model.for_app_skill === 'ai.ask'));
    const selectedModel = $derived(models.find((model) => `${model.default_server}/${model.id}` === selection) ?? null);
    const providers = $derived.by(() => {
        const entries = new Map<string, AIModelMetadata>();
        for (const model of models) {
            if (!entries.has(model.provider_id)) entries.set(model.provider_id, model);
        }
        return [...entries.values()];
    });
    const providerModels = $derived(activeProvider ? models.filter((model) => model.provider_id === activeProvider) : []);

    function select(selectionValue: string): void {
        onSelect(selectionValue);
        isOpen = false;
        activeProvider = null;
    }

    function openDetails(modelId: string): void {
        isOpen = false;
        activeProvider = null;
        onOpenDetails(modelId);
    }

    onMount(() => {
        const handlePointerDown = (event: PointerEvent) => {
            if (!selectorElement.contains(event.target as Node)) {
                isOpen = false;
                activeProvider = null;
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
        } else if (event.key === 'ArrowDown' && !isOpen) {
            event.preventDefault();
            isOpen = true;
        }
    }
</script>

<div class="model-selector" bind:this={selectorElement}>
    <button
        class="model-selector-trigger"
        data-testid="composer-model-selector"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        onclick={() => isOpen = !isOpen}
        onkeydown={closeOnKeydown}
    >
        {#if selectedModel}
            <img src={getProviderIconUrl(selectedModel.logo_svg)} alt="" />
        {:else}
            <span class="clickable-icon icon_ai"></span>
        {/if}
        <span class="model-selector-label">{selectedModel?.name ?? $text('settings.ai_ask.ai_ask_settings.model_auto')}</span>
    </button>

    {#if isOpen}
        <div class="model-selector-menu" data-testid="composer-model-selector-menu" role="menu" tabindex="-1" onkeydown={closeOnKeydown}>
            {#if activeProvider}
                <button class="menu-heading" onclick={() => activeProvider = null}>
                    <span class="clickable-icon icon_back"></span>
                    {$text('enter_message.model_selector.model_selection')}
                </button>
                {#each providerModels as model (model.id)}
                    <div class="model-menu-row">
                        <button class="menu-item" role="menuitem" data-testid={`composer-model-${model.id}`} onclick={() => select(`${model.default_server}/${model.id}`)}>
                            <img src={getProviderIconUrl(model.logo_svg)} alt="" />
                            <span><strong>{model.name}</strong><small>{model.tier}</small></span>
                        </button>
                        <button class="model-details" aria-label={$text('enter_message.model_selector.model_details')} onclick={() => openDetails(model.id)}>?</button>
                    </div>
                {/each}
            {:else}
                <button class="menu-item" role="menuitem" data-testid="composer-model-auto" onclick={() => select('auto')}>
                    <span class="clickable-icon icon_ai"></span>
                    <span><strong>{$text('settings.ai_ask.ai_ask_settings.model_auto')}</strong><small>{$text('settings.ai_ask.ai_ask_settings.auto_description')}</small></span>
                </button>
                {#each providers as provider (provider.provider_id)}
                    <button class="menu-item" role="menuitem" data-testid={`composer-model-provider-${provider.provider_id}`} onclick={() => activeProvider = provider.provider_id}>
                        <img src={getProviderIconUrl(provider.logo_svg)} alt="" />
                        <span><strong>{simplifyProviderName(provider.provider_name)}</strong><small>{$text('settings.ai_ask.ai_ask_settings.view_provider_models')}</small></span>
                    </button>
                {/each}
            {/if}
        </div>
    {/if}
</div>

<style>
    .model-selector { position: relative; }
    .model-selector-trigger { display: flex; align-items: center; gap: var(--spacing-2); min-width: 0; padding: var(--spacing-2); border: 0; color: var(--color-primary-start); background: transparent; cursor: pointer; }
    .model-selector-trigger img, .menu-item img { width: 1.75rem; height: 1.75rem; object-fit: contain; border-radius: var(--radius-2); }
    .model-selector-label { max-width: 8rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
    .model-selector-menu { position: absolute; z-index: var(--z-index-dropdown); bottom: calc(100% + var(--spacing-4)); left: 0; width: min(18rem, calc(100vw - 2rem)); max-height: 22rem; overflow-y: auto; padding: var(--spacing-4); background: var(--color-grey-0); border-radius: var(--radius-8); box-shadow: var(--shadow-lg); }
    .menu-item, .menu-heading { display: flex; align-items: center; gap: var(--spacing-4); width: 100%; padding: var(--spacing-4); border: 0; border-radius: var(--radius-3); color: var(--color-font-primary); text-align: start; background: transparent; cursor: pointer; }
    .menu-item:hover, .menu-heading:hover { background: var(--color-grey-10); }
    .menu-item span { display: flex; flex-direction: column; min-width: 0; }
    .menu-item strong { color: var(--color-primary-start); }
    .menu-item small { color: var(--color-font-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .model-menu-row { display: flex; align-items: center; }
    .model-menu-row .menu-item { flex: 1; }
    .model-details { width: 2rem; height: 2rem; border: 0; border-radius: var(--radius-full); color: var(--color-font-button); background: var(--color-primary); cursor: pointer; }
    @media (max-width: 34rem) { .model-selector-label { display: none; } }
</style>
