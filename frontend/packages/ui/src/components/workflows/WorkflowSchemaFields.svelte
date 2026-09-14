<script lang="ts">
  import { text } from '../../i18n/translations';
  import { record, label, schemaDefault, type Schema, type Output } from './workflowBuilder';
  let { schema, value, onChange, outputs = [], path = 'input' }: { schema: Schema; value: unknown; onChange: (value: unknown) => void; outputs?: Output[]; path?: string } = $props();
  const tr = (key: string) => $text(`workflows.builder.${key}`);
  function scalarValue(raw: string, field: Schema): unknown { return raw === '' ? undefined : ['number', 'integer'].includes(field.type ?? '') ? Number(raw) : raw; }
</script>

{#snippet field(name: string, spec: Schema, current: unknown, change: (value: unknown) => void, id: string, required = false)}
  {#if spec.type === 'object' || spec.properties}
    <fieldset class="object"><legend>{label(name)}</legend>
      {#each Object.entries(spec.properties ?? {}) as [key, child]}
        {@render field(key, child, record(current)[key], next => change({ ...record(current), [key]: next }), `${id}-${key}`, spec.required?.includes(key))}
      {/each}
    </fieldset>
  {:else if spec.type === 'array'}
    <fieldset class="object"><legend><span class="type">{tr('list')}</span>{label(name)}{required ? ' *' : ''}</legend>
      {#each (Array.isArray(current) ? current : []) as entry, index}
        <div class="array-entry">
          {@render field(`${name} ${index + 1}`, spec.items ?? { type: 'string' }, entry, next => change((current as unknown[]).map((old, i) => i === index ? next : old)), `${id}-${index}`)}
          <button type="button" class="quiet" aria-label={tr('remove')} onclick={() => change((current as unknown[]).filter((_, i) => i !== index))}>×</button>
        </div>
      {/each}
      <button type="button" class="quiet" onclick={() => change([...(Array.isArray(current) ? current : []), schemaDefault(spec.items ?? { type: 'string' })])}>+ {tr('add_item')}</button>
    </fieldset>
  {:else}
    {@const dynamic = typeof record(current).$date === 'string'}
    <div class="field">
      <label for={id}><span class="type" data-type={spec.type}>{spec.type ?? 'text'}</span>{spec.title || label(name)}{required ? ' *' : ''}</label>
      {#if spec.enum}
        <select {id} value={String(current ?? '')} onchange={event => change(spec.enum?.find(item => String(item) === event.currentTarget.value))}><option value="">{tr('choose')}</option>{#each spec.enum as option}<option value={String(option)}>{String(option)}</option>{/each}</select>
      {:else if spec.type === 'boolean'}
        <select {id} value={String(current ?? false)} onchange={event => change(event.currentTarget.value === 'true')}><option value="true">{tr('true')}</option><option value="false">{tr('false')}</option></select>
      {:else if dynamic}
        <select {id} value={String(record(current).$date)} onchange={event => change(event.currentTarget.value ? { $date: event.currentTarget.value, format: spec.format === 'date-time' ? 'datetime' : 'date' } : '')}>
          <option value="today">{tr('today')}</option><option value="next_week_start">{tr('next_week_start')}</option><option value="next_week_end">{tr('next_week_end')}</option><option value="">{tr('custom_date')}</option>
        </select>
      {:else}
        <input {id} data-testid={name === 'location' ? 'workflow-node-location-input' : undefined} type={['number', 'integer'].includes(spec.type ?? '') && !String(current ?? '').startsWith('$') ? 'number' : spec.format === 'date' ? 'date' : 'text'} value={String(current ?? '')} min={spec.minimum} max={spec.maximum} step={spec.type === 'integer' ? 1 : 'any'} oninput={event => change(scalarValue(event.currentTarget.value, spec))} />
      {/if}
      {#if spec.format?.includes('date') || /(^date|_date|date_|start_time|end_time)/.test(name)}
        <button type="button" class="variable" onclick={() => change({ $date: name.includes('end') ? 'next_week_end' : name.includes('start') ? 'next_week_start' : 'today', format: spec.format === 'date-time' ? 'datetime' : 'date' })}>⌘ {tr('dynamic_date')}</button>
      {/if}
      {#if outputs.some(output => output.schema.type === spec.type || (['integer', 'number'].includes(spec.type ?? '') && ['integer', 'number'].includes(output.schema.type ?? '')))}
        <select class="variable" aria-label={`${tr('use_output')} ${label(name)}`} value="" onchange={event => { if (event.currentTarget.value) change(event.currentTarget.value); }}><option value="">@ {tr('use_output')}</option>{#each outputs.filter(output => output.schema.type === spec.type || (['integer', 'number'].includes(spec.type ?? '') && ['integer', 'number'].includes(output.schema.type ?? ''))) as output}<option value={output.reference}>{output.label}</option>{/each}</select>
      {/if}
      {#if spec.description}<details><summary>{tr('details')}</summary><p>{spec.description}</p></details>{/if}
    </div>
  {/if}
{/snippet}

<div class="schema-fields">
  {#each Object.entries(schema.properties ?? {}) as [name, spec]}
    {@render field(name, spec, record(value)[name], next => onChange({ ...record(value), [name]: next }), `${path}-${name}`, schema.required?.includes(name))}
  {/each}
</div>

<style>
  .schema-fields { font-size: max(16px, 1rem); }
  .schema-fields { display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem; }
  .field{display:grid;align-content:start;gap:.4rem;min-width:0;text-align:start}.field label,legend{font-size:max(16px, 1rem);font-weight:650}.type{font-size:max(14px, .875rem);background:var(--color-primary);color:var(--color-font-button);border-radius:.2rem;padding:.1rem .3rem;margin-inline-end:.3rem}.type[data-type="number"],.type[data-type="integer"]{background:var(--color-error)}
  input,select{width:100%;box-sizing:border-box;min-height:2.5rem;border:1px solid var(--color-grey-25);border-radius:.8rem;padding:.5rem .7rem;background:var(--color-grey-0);color:var(--color-font-primary);font:inherit;font-size:max(16px, 1rem);box-shadow:var(--shadow-sm)}
  .object{grid-column:1/-1;min-width:0;border:1px solid var(--color-grey-20);border-radius:.8rem;padding:.75rem;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.8rem}.object legend{padding:0 .3rem}.array-entry{grid-column:1/-1;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:.5rem}.array-entry>.object{grid-column:auto}.quiet,.variable{background:transparent;color:var(--color-primary);border:0;box-shadow:none;font:inherit;font-size:max(16px, 1rem);cursor:pointer;min-height:2rem}.quiet{align-self:start}.variable{padding:0;text-align:start;min-height:1.5rem}details{font-size:max(14px, .875rem);color:var(--color-font-secondary)}summary{cursor:pointer}p{margin:.4rem 0;white-space:pre-wrap;user-select:text}input:focus-visible,select:focus-visible,button:focus-visible{outline:2px solid var(--color-button-primary);outline-offset:2px}
  @media(max-width:730px){.schema-fields,.object{grid-template-columns:1fr}}
</style>
