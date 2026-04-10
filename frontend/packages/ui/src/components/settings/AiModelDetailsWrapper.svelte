<!-- frontend/packages/ui/src/components/settings/AiModelDetailsWrapper.svelte
     Thin wrapper that extracts the modelId from the ai/model/{modelId} route
     and renders AiAskModelDetails. Used for the top-level AI settings model
     detail pages (navigated from SettingsAI).
-->

<script lang="ts">
    import AiAskModelDetails from './AiAskModelDetails.svelte';
    import { createEventDispatcher } from 'svelte';

    interface Props {
        activeSettingsView?: string;
    }

    let { activeSettingsView = '' }: Props = $props();

    const dispatch = createEventDispatcher();

    /** Extract modelId from "ai/model/{modelId}" path */
    let modelId = $derived(activeSettingsView.replace('ai/model/', ''));

    /**
     * Intercept navigation events from AiAskModelDetails.
     * The back button navigates to 'app_store/ai/skill/ask' — redirect it to the
     * top-level 'ai' settings page instead, since we're in the top-level AI context.
     */
    function handleOpenSettings(event: CustomEvent) {
        const detail = { ...event.detail };
        if (detail.settingsPath === 'app_store/ai/skill/ask') {
            detail.settingsPath = 'ai';
        }
        dispatch('openSettings', detail);
    }
</script>

{#if modelId}
    <AiAskModelDetails {modelId} on:openSettings={handleOpenSettings} />
{:else}
    <div class="error">Invalid model route.</div>
{/if}

<style>
    .error {
        padding: 2rem;
        text-align: center;
        color: var(--error-color, #dc3545);
    }
</style>
