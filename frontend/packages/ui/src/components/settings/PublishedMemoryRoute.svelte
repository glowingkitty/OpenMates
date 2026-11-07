<!-- frontend/packages/ui/src/components/settings/PublishedMemoryRoute.svelte
     Route page for one public app Memory: apps/{app_id}/settings_memories/published_{id}.
     Typed (app-specific) memory category pages were removed; only published documents remain. -->
<script lang="ts">
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import PublishedMemoryDetail from './PublishedMemoryDetail.svelte';

    let { appId, categoryId }: { appId: string; categoryId: string } = $props();
    let storeState = $state(appSkillsStore.getState());
    let memory = $derived(storeState.apps[appId]?.memories?.find(item => categoryId === `published_${item.id.split(':').at(-1)}`));
</script>

{#if memory}
    <div data-testid="published-memory-route" data-app-id={appId} data-category-id={categoryId}>
        <PublishedMemoryDetail {memory} />
    </div>
{:else}
    <div class="error" data-testid="published-memory-not-found">Memory not found.</div>
{/if}

<style>
    .error { padding: 2rem; text-align: center; color: var(--color-font-secondary); }
</style>
