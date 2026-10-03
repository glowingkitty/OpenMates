<script lang="ts">
  import { text } from '@repo/ui';
  import type { ProjectItemViewModel } from '../../services/projectService';
  import type { ProjectChatPresentation } from '../../services/projectChatPreviewService';
  import ProjectChatPreview from './ProjectChatPreview.svelte';
  let { items, presentations }: { items: ProjectItemViewModel[]; presentations?: Record<string, ProjectChatPresentation | null> } = $props();
  let limit = $state(24);
  let chats = $derived(items.filter(item => item.item_type === 'chat'));
</script>

{#if chats.length}
  <section class="project-chats" data-testid="project-chats-section" aria-label={$text('common.chats')}>
    <h2>{$text('common.chats')}</h2>
    <div class="chat-grid">
      {#each chats.slice(0, limit) as item (item.project_item_id)}
        <ProjectChatPreview {item} presentation={presentations?.[item.target_id]} />
      {/each}
    </div>
    {#if limit < chats.length}<button type="button" onclick={() => limit += 24}>{$text('chats.loadMore.button')}</button>{/if}
  </section>
{/if}

<style>
  .project-chats { display: flex; flex-direction: column; gap: var(--spacing-8); margin-top: var(--spacing-10); min-width: 0; }
  h2 { margin: 0; font-size: var(--font-size-h3); color: var(--color-font-primary); }
  .chat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 300px)); justify-content: start; gap: var(--spacing-8); }
</style>
