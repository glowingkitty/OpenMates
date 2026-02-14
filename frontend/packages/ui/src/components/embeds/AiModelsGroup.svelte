<!--
  frontend/packages/ui/src/components/embeds/AiModelsGroup.svelte
  
  A horizontal scrollable container displaying available AI Ask models
  as compact cards with provider logos.
  
  This component is rendered within demo chat messages when the
  [[ai_models_group]] placeholder is encountered.
  
  Features:
  - Shows only AI Ask models (for_app_skill === 'ai.ask')
  - Sorted by tier (premium first, then standard, then economy)
  - Compact card design: provider logo + model name + provider name
  - Clicking a card opens the App Store to that model's detail page
  
  Uses modelsMetadata (generated at build time from backend provider YAMLs)
  and providerIcons for resolved icon URLs.
-->

<script lang="ts">
  import { tick } from 'svelte';
  import { modelsMetadata, type AIModelMetadata } from '../../data/modelsMetadata';
  import { getProviderIconUrl } from '../../data/providerIcons';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import { settingsMenuVisible } from '../Settings.svelte';
  
  /**
   * Get AI Ask models sorted by tier (premium > standard > economy),
   * then alphabetically by name within each tier.
   */
  let aiAskModels = $derived((() => {
    const tierOrder: Record<string, number> = { premium: 3, standard: 2, economy: 1 };
    
    return modelsMetadata
      .filter(model => model.for_app_skill === 'ai.ask')
      .sort((a, b) => {
        const tierDiff = (tierOrder[b.tier] || 0) - (tierOrder[a.tier] || 0);
        if (tierDiff !== 0) return tierDiff;
        return a.name.localeCompare(b.name);
      });
  })());
  
  /**
   * Handle model card click - open the App Store to the AI Ask model's detail page.
   * Uses the mobile-aware deep link sequencing pattern:
   * 1. settingsMenuVisible.set(true) - tell Settings.svelte to sync isMenuVisible
   * 2. panelState.openSettings() - track panel state
   * 3. await tick() + delay - wait for DOM propagation on mobile
   * 4. settingsDeepLink.set(path) - navigate after menu is visible
   */
  async function handleModelSelect(model: AIModelMetadata) {
    console.debug('[AiModelsGroup] Model selected:', model.id);
    
    // CRITICAL: Set settingsMenuVisible to true FIRST
    settingsMenuVisible.set(true);
    
    const { panelState } = await import('../../stores/panelStateStore');
    panelState.openSettings();
    
    // Wait for store update to propagate and DOM to update
    await tick();
    await new Promise(resolve => setTimeout(resolve, 100));
    
    // Navigate to the AI Ask skill's model detail page
    settingsDeepLink.set(`app_store/ai/skill/ask/model/${model.id}`);
  }
</script>

{#if aiAskModels.length > 0}
  <div class="ai-models-group-wrapper">
    <div class="ai-models-group">
      {#each aiAskModels as model (model.id)}
        <button
          class="model-card"
          onclick={() => handleModelSelect(model)}
          type="button"
          aria-label={`${model.name} - ${model.provider_name}`}
        >
          <div class="model-logo">
            <img 
              src={getProviderIconUrl(model.logo_svg)} 
              alt={model.provider_name}
              class="provider-icon"
            />
          </div>
          <div class="model-text">
            <span class="model-name">{model.name}</span>
            <span class="model-provider">{model.provider_name}</span>
          </div>
        </button>
      {/each}
    </div>
  </div>
{/if}

<style>
  .ai-models-group-wrapper {
    /* Full width of the message content area */
    width: 100%;
    margin: 16px 0;
    /* Needed for proper overflow handling */
    overflow: hidden;
  }
  
  /* Horizontal scrollable container matching the standard embed group scroll pattern */
  .ai-models-group {
    display: flex;
    gap: 10px;
    align-items: flex-start;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 4px 0;
    scrollbar-width: thin;
    scrollbar-color: var(--color-grey-60) transparent;
  }
  
  /* Custom scrollbar styling for WebKit browsers */
  .ai-models-group::-webkit-scrollbar {
    height: 4px;
  }
  
  .ai-models-group::-webkit-scrollbar-track {
    background: transparent;
  }
  
  .ai-models-group::-webkit-scrollbar-thumb {
    background-color: var(--color-grey-60);
    border-radius: 2px;
  }
  
  /* Compact model card: provider logo + model name + provider name */
  .model-card {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 16px 10px 12px;
    min-width: 180px;
    max-width: 240px;
    background-color: var(--color-grey-20);
    border: 1px solid var(--color-grey-30);
    border-radius: 12px;
    cursor: pointer;
    flex-shrink: 0;
    transition: background-color 0.2s ease, transform 0.2s ease, border-color 0.2s ease;
  }
  
  .model-card:hover {
    background-color: var(--color-grey-25);
    border-color: var(--color-grey-40);
    transform: translateY(-2px);
  }
  
  .model-card:active {
    transform: scale(0.97);
  }
  
  /* Provider logo container */
  .model-logo {
    flex-shrink: 0;
    width: 36px;
    height: 36px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  .provider-icon {
    width: 32px;
    height: 32px;
    border-radius: 8px;
    object-fit: contain;
    background: var(--color-grey-10);
    padding: 3px;
  }
  
  /* Model name and provider text */
  .model-text {
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
  }
  
  .model-name {
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--color-grey-100);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    text-align: left;
  }
  
  .model-provider {
    font-size: 0.75rem;
    color: var(--color-grey-60);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    text-align: left;
  }
  
  /* Ensure cards don't shrink in the flex container */
  .ai-models-group > :global(*) {
    flex-shrink: 0;
  }
</style>
