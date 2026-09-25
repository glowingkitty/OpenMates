<script lang="ts">
  import { text } from '../../i18n/translations';
  import { getLucideIcon } from '../../utils/categoryUtils';
  import type { Schema } from './workflowBuilder';
  import { exampleValue, presentedFields, valueLabel, valueType, workflowValue } from './workflowValuePresentation';
  import { workflowFieldIcon } from './workflowFieldIcon';
  import WorkflowValueView from './WorkflowValueView.svelte';

  let { name, schema, value, appId = '', path }: { name: string; schema: Schema; value: unknown; appId?: string; path: string } = $props();
  let expanded = $state(false);
  let showAll = $state(false);
  const tr = (key: string) => $text(`workflows.builder.${key}`);
  const ChevronDown = getLucideIcon('chevron-down');
  const FieldIcon = $derived(workflowFieldIcon(name, schema));
  const data = $derived(workflowValue(value));
  const firstItem = $derived(Array.isArray(data) ? data[0] : undefined);
  const itemSchema = $derived(schema.items);
  const itemProperties = $derived(itemSchema?.properties ?? {});
  const itemFields = $derived(presentedFields(itemProperties));
  const visibleItemFields = $derived(showAll ? [...itemFields.basic, ...itemFields.advanced] : itemFields.basic);
</script>

<div class="output-field" data-testid="workflow-output-field">
  <span class="type" data-value-type={valueType(schema, value)}>{tr(`output_type_${valueType(schema, value)}`)}</span>
  <strong class="output-name"><FieldIcon size={18} strokeWidth={2.2} aria-hidden="true"/><span>{schema.title || valueLabel(name)}</span></strong>
  <div class="output-example">
    {#if schema.type === 'array' || Array.isArray(data)}
      {#if Array.isArray(data) && data.length}
        <button type="button" class="list-disclosure" data-testid="workflow-output-list-disclosure" aria-label={tr('details')} aria-expanded={expanded} onclick={() => expanded = !expanded}>
          <ChevronDown size={22} strokeWidth={2.3} aria-hidden="true"/>
        </button>
      {:else}<WorkflowValueView {value} {schema} {appId} {path}/>{/if}
    {:else}<WorkflowValueView {value} {schema} {appId} {path}/>{/if}
  </div>
  {#if expanded && firstItem !== undefined}
    <div class="list-panel" data-testid="workflow-output-list-details">
      {#if visibleItemFields.length}
        {#each visibleItemFields as [key, childSchema]}
          {@const child = firstItem && typeof firstItem === 'object' ? (firstItem as Record<string, unknown>)[key] : exampleValue(childSchema)}
          {@const ChildIcon = workflowFieldIcon(key, childSchema)}
          <div class="list-field">
            <strong><ChildIcon size={18} strokeWidth={2.2} aria-hidden="true"/><span>{childSchema.title || valueLabel(key)}</span></strong>
            <WorkflowValueView value={child} schema={childSchema} {appId} path={`${path}.0.${key}`}/>
          </div>
        {/each}
        {#if itemFields.advanced.length}
          <button type="button" class="progressive-control" data-testid="workflow-output-list-show-all" aria-expanded={showAll} onclick={() => showAll = !showAll}>{tr(showAll ? 'show_basic_fields' : 'show_all_fields')}</button>
        {/if}
      {:else}
        <div class="list-scalar"><WorkflowValueView value={firstItem} schema={itemSchema} {appId} path={`${path}.0`}/></div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .output-field{display:grid;grid-template-columns:5.5rem minmax(0,1fr) minmax(0,1fr);align-items:start;column-gap:.6rem;row-gap:.25rem;min-width:0}.type{font-size:14px;border-radius:.2rem;background:var(--color-primary);color:var(--color-font-button);padding:.1rem .3rem;width:fit-content;justify-self:start}.type[data-value-type="number"]{background:var(--color-error)}.type[data-value-type="date"]{background:var(--color-warning)}.type[data-value-type="boolean"]{background:var(--color-primary-start)}.output-name{display:flex;align-items:flex-start;gap:var(--spacing-2);min-width:0;overflow-wrap:anywhere;font-size:1rem;line-height:1.35}.output-name :global(svg){flex:0 0 auto;margin-top:.08rem;color:var(--color-font-secondary)}.output-example{min-width:0;overflow-wrap:anywhere}.output-example :global(.workflow-value .scalar){color:var(--color-font-secondary)}.list-disclosure{display:grid;place-items:center;width:2rem;height:2rem;margin:-.3rem 0 0;padding:0;border:0;border-radius:var(--radius-full);background:transparent;color:var(--color-font-secondary);cursor:pointer}.list-disclosure[aria-expanded="true"] :global(svg){transform:rotate(180deg)}.list-disclosure :global(svg){transition:transform .15s ease}.list-panel{grid-column:1/-1;display:grid;gap:.65rem;margin-top:.45rem;padding:.8rem;background:var(--color-grey-10);border-radius:var(--radius-5)}.list-field{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:.8rem;align-items:start}.list-field>strong{display:flex;align-items:flex-start;gap:var(--spacing-2);min-width:0;overflow-wrap:anywhere}.list-field>strong :global(svg){flex:0 0 auto;color:var(--color-font-secondary)}.list-scalar{min-width:0}.progressive-control{justify-self:center;border:0;padding:.2rem .4rem;background:transparent;color:var(--color-font-secondary);font:inherit;font-size:14px;cursor:pointer}.list-disclosure:focus-visible,.progressive-control:focus-visible{outline:2px solid var(--color-button-primary);outline-offset:2px}@media(max-width:730px){.output-field{grid-template-columns:minmax(0,1fr) 6.75rem;column-gap:.5rem}.type{grid-column:1;grid-row:1}.output-name{grid-column:1;grid-row:2}.output-example{grid-column:2;grid-row:1/3;align-self:center}.list-panel{grid-row:3;grid-column:1/-1}.list-field{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}}@media(prefers-reduced-motion:reduce){.list-disclosure :global(svg){transition:none}}
</style>
