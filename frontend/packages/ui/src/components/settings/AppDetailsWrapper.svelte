<!-- frontend/packages/ui/src/components/settings/AppDetailsWrapper.svelte
     Wrapper component that extracts appId from activeSettingsView and renders AppDetails.
     
     This component is used for dynamic app_store/{app_id} routes.
     It receives activeSettingsView as a prop from CurrentSettingsPage.
-->

<script lang="ts">
    import AppDetails from './AppDetails.svelte';
    import { createEventDispatcher } from 'svelte';
    
    interface Props {
        activeSettingsView?: string;
    }
    
    let { activeSettingsView = '' }: Props = $props();
    
    // Extract appId from route path (e.g., "app_store/ai" -> "ai")
    let appId = $derived(
        activeSettingsView.startsWith('app_store/')
            ? activeSettingsView.replace('app_store/', '')
            : ''
    );
    
    // Create event dispatcher to forward events
    const dispatch = createEventDispatcher();
    
    /**
     * Forward openSettings events from AppDetails.
     */
    function handleOpenSettings(event: CustomEvent) {
        dispatch('openSettings', event.detail);
    }
</script>

{#if appId}
    <AppDetails appId={appId} on:openSettings={handleOpenSettings} />
{:else}
    <div class="error">Invalid app route.</div>
{/if}

<style>
    .error {
        padding: 2rem;
        text-align: center;
        color: var(--error-color, #dc3545);
    }
</style>

