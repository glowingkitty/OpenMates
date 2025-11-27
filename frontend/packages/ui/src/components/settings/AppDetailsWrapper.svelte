<!-- frontend/packages/ui/src/components/settings/AppDetailsWrapper.svelte
     Wrapper component that extracts appId and sub-route info from activeSettingsView and renders appropriate component.
     
     This component handles dynamic app_store routes:
     - app_store/{app_id} -> AppDetails
     - app_store/{app_id}/skill/{skill_id} -> SkillDetails
     - app_store/{app_id}/focus/{focus_mode_id} -> FocusModeDetails
     - app_store/{app_id}/settings_memories -> AppSettingsMemories
     
     It receives activeSettingsView as a prop from CurrentSettingsPage.
-->

<script lang="ts">
    import AppDetails from './AppDetails.svelte';
    import SkillDetails from './SkillDetails.svelte';
    import FocusModeDetails from './FocusModeDetails.svelte';
    import AppSettingsMemoriesCategory from './AppSettingsMemoriesCategory.svelte';
    import { createEventDispatcher } from 'svelte';
    
    interface Props {
        activeSettingsView?: string;
    }
    
    let { activeSettingsView = '' }: Props = $props();
    
    // Parse route to extract appId and sub-route info
    let routeInfo = $derived.by(() => {
        if (!activeSettingsView.startsWith('app_store/')) {
            return { type: 'invalid', appId: '' };
        }
        
        const path = activeSettingsView.replace('app_store/', '');
        const parts = path.split('/');
        
        if (parts.length === 1) {
            // app_store/{app_id}
            return { type: 'app_details', appId: parts[0] };
        } else if (parts.length === 3 && parts[1] === 'skill') {
            // app_store/{app_id}/skill/{skill_id}
            return { type: 'skill_details', appId: parts[0], skillId: parts[2] };
        } else if (parts.length === 3 && parts[1] === 'focus') {
            // app_store/{app_id}/focus/{focus_mode_id}
            return { type: 'focus_details', appId: parts[0], focusModeId: parts[2] };
        } else if (parts.length === 3 && parts[1] === 'settings_memories') {
            // app_store/{app_id}/settings_memories/{category_id}
            return { type: 'settings_memories_category', appId: parts[0], categoryId: parts[2] };
        }
        
        return { type: 'invalid', appId: '' };
    });
    
    // Create event dispatcher to forward events
    const dispatch = createEventDispatcher();
    
    /**
     * Forward openSettings events from child components.
     */
    function handleOpenSettings(event: CustomEvent) {
        dispatch('openSettings', event.detail);
    }
</script>

{#if routeInfo.type === 'app_details'}
    <AppDetails appId={routeInfo.appId} on:openSettings={handleOpenSettings} />
{:else if routeInfo.type === 'skill_details'}
    <SkillDetails appId={routeInfo.appId} skillId={routeInfo.skillId} on:openSettings={handleOpenSettings} />
{:else if routeInfo.type === 'focus_details'}
    <FocusModeDetails appId={routeInfo.appId} focusModeId={routeInfo.focusModeId} on:openSettings={handleOpenSettings} />
{:else if routeInfo.type === 'settings_memories_category'}
    <AppSettingsMemoriesCategory appId={routeInfo.appId} categoryId={routeInfo.categoryId} on:openSettings={handleOpenSettings} />
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

