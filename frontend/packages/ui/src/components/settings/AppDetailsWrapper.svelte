<!-- frontend/packages/ui/src/components/settings/AppDetailsWrapper.svelte
     Wrapper component that extracts appId and sub-route info from activeSettingsView and renders appropriate component.
     
     This component handles dynamic app_store routes:
     - app_store/{app_id} -> AppDetails
     - app_store/{app_id}/skill/{skill_id} -> SkillDetails (or AiAskSkillSettings for ai/ask)
     - app_store/{app_id}/skill/{skill_id}/model/{model_id} -> AiAskModelDetails (for ai/ask skill only)
     - app_store/{app_id}/focus/{focus_mode_id} -> FocusModeDetails
     - app_store/{app_id}/settings_memories/{category_id} -> AppSettingsMemoriesCategory
     - app_store/{app_id}/settings_memories/{category_id}/create -> AppSettingsMemoriesCreateEntry
     - app_store/{app_id}/settings_memories/{category_id}/entry/{entry_id} -> AppSettingsMemoriesEntryDetail
     
     It receives activeSettingsView as a prop from CurrentSettingsPage.
-->

<script lang="ts">
    import AppDetails from './AppDetails.svelte';
    import SkillDetails from './SkillDetails.svelte';
    import FocusModeDetails from './FocusModeDetails.svelte';
    import AppSettingsMemoriesCategory from './AppSettingsMemoriesCategory.svelte';
    import AppSettingsMemoriesCreateEntry from './AppSettingsMemoriesCreateEntry.svelte';
    import AppSettingsMemoriesEntryDetail from './AppSettingsMemoriesEntryDetail.svelte';
    import AiAskSkillSettings from './AiAskSkillSettings.svelte';
    import AiAskModelDetails from './AiAskModelDetails.svelte';
    import { createEventDispatcher } from 'svelte';
    
    interface Props {
        activeSettingsView?: string;
    }
    
    // Define route info types for type safety
    type RouteInfo = 
        | { type: 'invalid'; appId: '' }
        | { type: 'app_details'; appId: string }
        | { type: 'skill_details'; appId: string; skillId: string }
        | { type: 'ai_ask_skill_settings'; appId: string; skillId: string }
        | { type: 'ai_ask_model_details'; appId: string; skillId: string; modelId: string }
        | { type: 'focus_details'; appId: string; focusModeId: string }
        | { type: 'settings_memories_category'; appId: string; categoryId: string }
        | { type: 'settings_memories_create'; appId: string; categoryId: string }
        | { type: 'settings_memories_entry_detail'; appId: string; categoryId: string; entryId: string };
    
    let { activeSettingsView = '' }: Props = $props();
    
    // Parse route to extract appId and sub-route info
    let routeInfo = $derived.by((): RouteInfo => {
        if (!activeSettingsView.startsWith('app_store/')) {
            return { type: 'invalid', appId: '' };
        }
        
        const path = activeSettingsView.replace('app_store/', '');
        const parts = path.split('/');
        
        if (parts.length === 1) {
            // app_store/{app_id}
            return { type: 'app_details', appId: parts[0] };
        } else if (parts.length === 5 && parts[1] === 'skill' && parts[3] === 'model') {
            // app_store/{app_id}/skill/{skill_id}/model/{model_id}
            // Special route for AI Ask skill model details
            if (parts[0] === 'ai' && parts[2] === 'ask') {
                return { type: 'ai_ask_model_details', appId: parts[0], skillId: parts[2], modelId: parts[4] };
            }
            // For other apps/skills, fall through to invalid
            return { type: 'invalid', appId: '' };
        } else if (parts.length === 3 && parts[1] === 'skill') {
            // app_store/{app_id}/skill/{skill_id}
            // Special route for AI Ask skill settings page
            if (parts[0] === 'ai' && parts[2] === 'ask') {
                return { type: 'ai_ask_skill_settings', appId: parts[0], skillId: parts[2] };
            }
            return { type: 'skill_details', appId: parts[0], skillId: parts[2] };
        } else if (parts.length === 3 && parts[1] === 'focus') {
            // app_store/{app_id}/focus/{focus_mode_id}
            return { type: 'focus_details', appId: parts[0], focusModeId: parts[2] };
        } else if (parts.length === 3 && parts[1] === 'settings_memories') {
            // app_store/{app_id}/settings_memories/{category_id}
            return { type: 'settings_memories_category', appId: parts[0], categoryId: parts[2] };
        } else if (parts.length === 4 && parts[1] === 'settings_memories' && parts[3] === 'create') {
            // app_store/{app_id}/settings_memories/{category_id}/create
            return { type: 'settings_memories_create', appId: parts[0], categoryId: parts[2] };
        } else if (parts.length === 5 && parts[1] === 'settings_memories' && parts[3] === 'entry') {
            // app_store/{app_id}/settings_memories/{category_id}/entry/{entry_id}
            return { type: 'settings_memories_entry_detail', appId: parts[0], categoryId: parts[2], entryId: parts[4] };
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
    
    // Extract create route info for type safety
    // TypeScript has issues narrowing discriminated unions in Svelte templates, so we use a helper
    let createRouteInfo = $derived.by((): { appId: string; categoryId: string } | null => {
        if (routeInfo.type === 'settings_memories_create') {
            console.log('[AppDetailsWrapper] Create route detected:', routeInfo);
            return { appId: routeInfo.appId, categoryId: routeInfo.categoryId };
        }
        return null;
    });
    
    // Extract entry detail route info for type safety
    let entryDetailRouteInfo = $derived.by((): { appId: string; categoryId: string; entryId: string } | null => {
        if (routeInfo.type === 'settings_memories_entry_detail') {
            console.log('[AppDetailsWrapper] Entry detail route detected:', routeInfo);
            return { appId: routeInfo.appId, categoryId: routeInfo.categoryId, entryId: routeInfo.entryId };
        }
        return null;
    });
    
    // Extract AI Ask model details route info for type safety
    let aiAskModelRouteInfo = $derived.by((): { modelId: string } | null => {
        if (routeInfo.type === 'ai_ask_model_details') {
            console.log('[AppDetailsWrapper] AI Ask model details route detected:', routeInfo);
            return { modelId: routeInfo.modelId };
        }
        return null;
    });
    
    // Debug logging for route parsing
    $effect(() => {
        console.log('[AppDetailsWrapper] activeSettingsView:', activeSettingsView);
        console.log('[AppDetailsWrapper] routeInfo:', routeInfo);
    });
</script>

{#if routeInfo.type === 'app_details'}
    <AppDetails appId={routeInfo.appId} on:openSettings={handleOpenSettings} />
{:else if routeInfo.type === 'ai_ask_skill_settings'}
    <AiAskSkillSettings on:openSettings={handleOpenSettings} />
{:else if aiAskModelRouteInfo}
    {@const route = aiAskModelRouteInfo}
    <!-- @ts-ignore - TypeScript limitation with discriminated unions in Svelte templates -->
    <AiAskModelDetails modelId={route.modelId} on:openSettings={handleOpenSettings} />
{:else if routeInfo.type === 'skill_details'}
    <SkillDetails appId={routeInfo.appId} skillId={routeInfo.skillId} on:openSettings={handleOpenSettings} />
{:else if routeInfo.type === 'focus_details'}
    <FocusModeDetails appId={routeInfo.appId} focusModeId={routeInfo.focusModeId} on:openSettings={handleOpenSettings} />
{:else if routeInfo.type === 'settings_memories_category'}
    <AppSettingsMemoriesCategory appId={routeInfo.appId} categoryId={routeInfo.categoryId} on:openSettings={handleOpenSettings} />
{:else if createRouteInfo}
    {@const route = createRouteInfo}
    <!-- @ts-ignore - TypeScript limitation with discriminated unions in Svelte templates -->
    <AppSettingsMemoriesCreateEntry appId={route.appId} categoryId={route.categoryId} on:openSettings={handleOpenSettings} />
{:else if entryDetailRouteInfo}
    {@const route = entryDetailRouteInfo}
    <!-- @ts-ignore - TypeScript limitation with discriminated unions in Svelte templates -->
    <AppSettingsMemoriesEntryDetail appId={route.appId} categoryId={route.categoryId} entryId={route.entryId} on:openSettings={handleOpenSettings} />
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

