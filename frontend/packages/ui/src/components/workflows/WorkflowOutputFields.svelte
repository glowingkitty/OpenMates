<script lang="ts">
  import { text } from '../../i18n/translations';
  import type { Schema } from './workflowBuilder';
  import { exampleValue, presentedFields } from './workflowValuePresentation';
  import WorkflowOutputField from './WorkflowOutputField.svelte';

  let { properties, values, appId = '', path }: { properties: Record<string, Schema>; values?: Record<string, unknown>; appId?: string; path: string } = $props();
  let showAll = $state(false);
  const tr = (key: string) => $text(`workflows.builder.${key}`);
  const fields = $derived(presentedFields(properties));
  const visible = $derived(showAll ? [...fields.basic, ...fields.advanced] : fields.basic);
</script>

<div class="output-fields" data-testid="workflow-output-fields">
  {#each visible as [key, schema]}
    <WorkflowOutputField name={key} {schema} value={values ? values[key] : exampleValue(schema)} {appId} path={`${path}.${key}`}/>
  {/each}
  {#if fields.advanced.length}
    <button type="button" class="progressive-control" data-testid="workflow-output-show-all" aria-expanded={showAll} onclick={() => showAll = !showAll}>{tr(showAll ? 'show_basic_fields' : 'show_all_fields')}</button>
  {/if}
</div>

<style>
  .output-fields{display:grid;grid-template-columns:minmax(0,1fr);row-gap:1rem;text-align:start}.progressive-control{justify-self:center;border:0;padding:.2rem .4rem;background:transparent;color:var(--color-font-secondary);font:inherit;font-size:14px;cursor:pointer}.progressive-control:focus-visible{outline:2px solid var(--color-button-primary);outline-offset:2px}
</style>
