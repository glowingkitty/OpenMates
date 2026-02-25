<!-- frontend/packages/ui/src/components/settings/MateDetailsWrapper.svelte
     Wrapper component that extracts mateId from the activeSettingsView path
     and renders MateDetails.

     Handles dynamic mates routes:
       mates/{mate_id} -> MateDetails

     Receives activeSettingsView as a prop from CurrentSettingsPage.
     Mirrors the pattern used by AppDetailsWrapper.svelte.
-->

<script lang="ts">
    import MateDetails from './MateDetails.svelte';
    import { createEventDispatcher } from 'svelte';

    interface Props {
        activeSettingsView?: string;
    }

    let { activeSettingsView = '' }: Props = $props();

    // Parse the mateId from the path "mates/{mateId}"
    let mateId = $derived.by((): string => {
        if (!activeSettingsView.startsWith('mates/')) {
            return '';
        }
        const parts = activeSettingsView.replace('mates/', '').split('/');
        return parts[0] ?? '';
    });

    // Create event dispatcher to forward navigation events from MateDetails
    const dispatch = createEventDispatcher();

    /**
     * Forward openSettings events from MateDetails up to Settings.svelte.
     */
    function handleOpenSettings(event: CustomEvent) {
        dispatch('openSettings', event.detail);
    }
</script>

{#if mateId}
    <MateDetails {mateId} on:openSettings={handleOpenSettings} />
{:else}
    <div class="error">Invalid mates route.</div>
{/if}

<style>
    .error {
        padding: 2rem;
        text-align: center;
        color: var(--error-color, #dc3545);
    }
</style>
