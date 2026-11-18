<!--
  Project section listing the Specifications of a Project as embed previews.
  Props-driven; the parent supplies items from the client core and opens fullscreen.
  Shows an empty state when the Project has no Specification.
-->
<script lang="ts">
  import { text } from '../../i18n/translations';
  import SpecificationEmbedPreview from '../embeds/specifications/SpecificationEmbedPreview.svelte';
  import type { SpecificationListItem } from '../embeds/specifications/SpecificationRevision';
  let { items, onOpen }: { items: SpecificationListItem[]; onOpen: (id: string) => void } = $props();
</script>

<section class="project-specifications" data-testid="project-specifications-section" aria-label={$text('specifications.project.heading')}>
  <h2>{$text('specifications.project.heading')}</h2>
  {#if items.length}
    <div class="spec-grid">
      {#each items as item (item.id)}
        <div data-testid={`project-specification-${item.id}`}>
          <SpecificationEmbedPreview id={`project-spec-${item.id}`} {item} onFullscreen={() => onOpen(item.id)} />
        </div>
      {/each}
    </div>
  {:else}
    <p class="empty" data-testid="project-specifications-empty">{$text('specifications.project.empty')}</p>
  {/if}
</section>

<style>
  .project-specifications { display: flex; flex-direction: column; gap: var(--spacing-8); margin-top: var(--spacing-10); min-width: 0; }
  h2 { margin: 0; font-size: var(--font-size-h3); color: var(--color-font-primary); }
  .spec-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 300px)); justify-content: start; gap: var(--spacing-8); }
  .empty { margin: 0; color: var(--color-font-secondary); }
</style>
