<script lang="ts">
  import Icon from './Icon.svelte';
  import { appSkillsStore } from '../stores/appSkillsStore';
  import { text } from '../i18n/translations';
  import { loadedMemoryName } from '../utils/loadedMemoryDisplay';
  import type { AppliedMemory } from '../utils/loadedMemoryReceipt';

  let { memories }: { memories: readonly AppliedMemory[] } = $props();
  const iconName = (memory: AppliedMemory) => memory.app_id
    ? appSkillsStore.getApp(memory.app_id)?.icon_image?.replace(/\.svg$/i, '') || memory.app_id
    : 'project';
</script>

<div class="loaded-memories" data-testid="loaded-memory-pills">
  {#each memories as memory (`${memory.id}:${memory.revision}`)}
    <details class="memory" data-testid="loaded-memory-details">
      <summary class="memory-pill" data-testid="loaded-memory-pill">
        <span class="memory-icon" aria-hidden="true"><Icon name={iconName(memory)} type="app" appId={memory.app_id || 'ai'} size="18px" noAnimation noMargin ariaHidden /></span>
        <span>{loadedMemoryName(memory)}</span>
      </summary>
      <section class="memory-guide" data-testid="applied-memory">
        <h3>{memory.title}</h3>
        <p class="provenance">{$text(`memories.source_${memory.source}`)}{memory.app_id ? ` · ${memory.app_id}` : ''}{memory.project_id ? ` · ${memory.project_id}` : ''}</p>
        <p class="revision" data-testid="applied-rule-revision">{$text('rules.revision')} {memory.revision}</p>
        <pre data-testid="applied-memory-body">{memory.body}</pre>
      </section>
    </details>
  {/each}
</div>

<style>
  .loaded-memories { display: flex; flex-wrap: wrap; align-items: flex-start; gap: var(--spacing-3); min-width: 0; margin-block-end: var(--spacing-4); }
  .memory { min-width: 0; max-width: 100%; }
  .memory-pill { display: inline-flex; align-items: center; gap: var(--spacing-3); max-width: 100%; min-height: 2rem; padding: var(--spacing-2) var(--spacing-4) var(--spacing-2) var(--spacing-2); border: 1px solid var(--color-grey-30); border-radius: 999px; background: var(--color-grey-0); color: var(--color-font-primary); cursor: pointer; font-size: var(--font-size-small); overflow-wrap: anywhere; list-style: none; }
  .memory-pill::-webkit-details-marker { display: none; }
  .memory-pill:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  .memory-icon { display: inline-flex; flex: none; border-radius: 50%; overflow: hidden; }
  .memory-guide { min-width: 0; max-width: min(34rem, 100%); margin-top: var(--spacing-3); padding: var(--spacing-4); border: 1px solid var(--color-grey-25); border-radius: var(--radius-4); background: var(--color-grey-10); }
  h3 { margin: 0; color: var(--color-font-primary); font-size: var(--font-size-small); overflow-wrap: anywhere; }
  .provenance, .revision { overflow-wrap: anywhere; }
  .revision { font-family: var(--font-family-mono); }
  pre { white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; color: var(--color-font-primary); max-height: 32rem; overflow-y: auto; padding: var(--spacing-4); background: var(--color-grey-0); border-radius: var(--radius-4); }
</style>
