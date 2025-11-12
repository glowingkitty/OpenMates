<!-- frontend/packages/ui/src/components/settings/AppSkillsList.svelte
     Component for displaying skills for a specific app.
     
     **Backend Implementation**:
     - API endpoint: `backend/core/api/app/routes/apps.py:get_apps_metadata()`
     - Store: `frontend/packages/ui/src/stores/appSkillsStore.ts`
     - Types: `frontend/packages/ui/src/types/apps.ts`
-->

<script lang="ts">
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import SkillCard from './SkillCard.svelte';
    import type { AppMetadata } from '../../types/apps';
    
    /**
     * Props for AppSkillsList component.
     */
    interface Props {
        appId: string;
        isAuthenticated?: boolean; // Whether user is authenticated (for future modification features)
    }
    
    let { appId, isAuthenticated = false }: Props = $props();
    
    // Get store state reactively (Svelte 5)
    let storeState = $state(appSkillsStore.getState());
    
    // Get app metadata from store
    let app = $derived<AppMetadata | undefined>(storeState.apps[appId]);
    let skills = $derived(app?.skills || []);
</script>

<div class="app-skills-list">
    {#if !app}
        <div class="error">App not found.</div>
    {:else}
        <div class="app-header">
            <h2>{app.name}</h2>
            <p class="app-description">{app.description}</p>
        </div>
        
        {#if skills.length === 0}
            <div class="no-skills">No skills available for this app.</div>
        {:else}
            <div class="skills-grid">
                {#each skills as skill (skill.id)}
                    <SkillCard {skill} {appId} />
                {/each}
            </div>
        {/if}
    {/if}
</div>

<style>
    .app-skills-list {
        padding: 1rem 0;
    }
    
    .app-header {
        margin-bottom: 2rem;
    }
    
    .app-header h2 {
        margin: 0 0 0.5rem 0;
        font-size: 1.75rem;
        font-weight: 700;
        color: var(--text-primary, #000000);
    }
    
    .app-description {
        margin: 0;
        color: var(--text-secondary, #666666);
        font-size: 1rem;
        line-height: 1.6;
    }
    
    .no-skills,
    .error {
        padding: 3rem;
        text-align: center;
        color: var(--text-secondary, #666666);
    }
    
    .error {
        color: var(--error-color, #dc3545);
    }
    
    .skills-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: 1.5rem;
    }
</style>
