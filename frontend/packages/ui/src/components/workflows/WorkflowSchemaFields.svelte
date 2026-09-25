<script lang="ts">
  import { text } from '../../i18n/translations';
  import SettingsDropdown from '../settings/elements/SettingsDropdown.svelte';
  import WorkflowDateRangeField from './WorkflowDateRangeField.svelte';
  import WorkflowLocationField from './WorkflowLocationField.svelte';
  import { record, label, schemaDefault, type Schema, type Output } from './workflowBuilder';

  type UiMetadata = { control?: string; start_field?: string; end_field?: string; max_offset_days?: number; hidden?: boolean };
  type LocationConfig = { mode: 'weather' | 'events' | 'home'; text: string; latitude?: string; longitude?: string };
  let { schema, value, onChange, outputs = [], path = 'input', appId = '', timezone }: {
    schema: Schema; value: unknown; onChange: (value: unknown) => void; outputs?: Output[]; path?: string; appId?: string; timezone: string;
  } = $props();

  let expanded = $state<Record<string, boolean>>({});
  const tr = (key: string) => $text(`workflows.builder.${key}`);
  const ui = (field: Schema): UiMetadata => record((field as Schema & { 'x-ui'?: UiMetadata })['x-ui']) as UiMetadata;
  const visibleEntries = (properties: Record<string, Schema>) => Object.entries(properties).filter(([, field]) => !ui(field).hidden);
  function scalarValue(raw: string, field: Schema): unknown { return raw === '' ? undefined : ['number', 'integer'].includes(field.type ?? '') ? Number(raw) : raw; }
  function displayType(field: Schema): string {
    if (field.format === 'date') return 'date';
    if (field.type === 'integer') return 'number';
    return field.type === 'string' || !field.type ? 'text' : field.type;
  }
  function typeLabel(field: Schema): string { return tr(`output_type_${displayType(field)}`); }
  function compatibleOutputs(field: Schema): Output[] { return outputs.filter(output => output.schema.type === field.type || (['integer', 'number'].includes(field.type ?? '') && ['integer', 'number'].includes(output.schema.type ?? ''))); }

  function locationConfig(properties: Record<string, Schema>, id: string): LocationConfig | null {
    if (appId === 'weather' && properties.location && properties.latitude && properties.longitude) return { mode: 'weather', text: 'location', latitude: 'latitude', longitude: 'longitude' };
    if (appId === 'events' && properties.location && properties.lat && properties.lon) return { mode: 'events', text: 'location', latitude: 'lat', longitude: 'lon' };
    if (appId === 'home' && properties.query && id.includes('requests')) return { mode: 'home', text: 'query' };
    return null;
  }

  function dateRangeConfig(container: Schema): { start: string; end: string; maxOffsetDays: number } | null {
    const metadata = ui(container);
    const properties = container.properties ?? {};
    const start = metadata.start_field ?? 'start_date';
    const end = metadata.end_field ?? 'end_date';
    if (metadata.control !== 'date-range' && !(appId === 'weather' && properties[start] && properties[end])) return null;
    if (!properties[start] || !properties[end]) return null;
    return { start, end, maxOffsetDays: metadata.max_offset_days ?? 13 };
  }

  function isBasic(name: string, field: Schema, required: string[], index: number): boolean {
    if (required.includes(name)) return true;
    if (appId === 'weather') return ['location', 'start_date', 'end_date'].includes(name);
    if (appId === 'events') return ['requests', 'query', 'location', 'start_date', 'end_date', 'event_type'].includes(name);
    if (appId === 'home') return ['requests', 'query', 'listing_type', 'property_type', 'max_price_eur'].includes(name);
    return field.default !== undefined || index < 3;
  }
</script>

{#snippet fieldLabel(title: string, field: Schema, required = false)}
  <span class="type-badge" data-type={displayType(field)}>{typeLabel(field)}</span>
  <span class="field-title">{title}{required ? ' *' : ''}</span>
{/snippet}

{#snippet objectFields(container: Schema, current: unknown, change: (value: unknown) => void, id: string)}
  {@const properties = container.properties ?? {}}
  {@const entries = visibleEntries(properties)}
  {@const location = locationConfig(properties, id)}
  {@const dateRange = dateRangeConfig(container)}
  {@const handled = new Set([location?.text, location?.latitude, location?.longitude, dateRange?.start, dateRange?.end].filter(Boolean))}
  {@const remaining = entries.filter(([name]) => !handled.has(name))}
  {@const basics = remaining.filter(([name, field], index) => isBasic(name, field, container.required ?? [], index))}
  {@const advanced = remaining.filter(entry => !basics.includes(entry))}
  {#if location}
    {@const locationRequired = container.required?.includes(location.text) ?? false}
    <div class="schema-field schema-field--specialized" data-testid="workflow-schema-field-location" role="group" aria-labelledby={`${id}-location-label`}>
      <div class="field-label" id={`${id}-location-label`}>
        {@render fieldLabel(tr('location'), properties[location.text], locationRequired)}
      </div>
      <WorkflowLocationField
        mode={location.mode}
        value={String(record(current)[location.text] ?? '')}
        required={locationRequired}
        onChange={selection => change({
          ...record(current),
          [location.text]: selection.text,
          ...(location.latitude ? { [location.latitude]: selection.latitude } : {}),
          ...(location.longitude ? { [location.longitude]: selection.longitude } : {})
        })}
      />
    </div>
  {/if}
  {#if dateRange}
    <div class="schema-field schema-field--specialized" data-testid="workflow-schema-field-date-range" role="group" aria-labelledby={`${id}-date-range-label`}>
      <div class="field-label" id={`${id}-date-range-label`}>
        {@render fieldLabel(tr('date_range'), { ...properties[dateRange.start], type: 'string', format: 'date' })}
      </div>
      <WorkflowDateRangeField
        start={record(current)[dateRange.start]}
        end={record(current)[dateRange.end]}
        {timezone}
        maxOffsetDays={dateRange.maxOffsetDays}
        onChange={(start, end) => change({ ...record(current), [dateRange.start]: start, [dateRange.end]: end })}
      />
    </div>
  {/if}
  {#each basics as [name, field]}
    {@render fieldControl(name, field, record(current)[name], next => change({ ...record(current), [name]: next }), `${id}-${name}`, container.required?.includes(name))}
  {/each}
  {#if expanded[id]}
    {#each advanced as [name, field]}
      {@render fieldControl(name, field, record(current)[name], next => change({ ...record(current), [name]: next }), `${id}-${name}`, container.required?.includes(name))}
    {/each}
  {/if}
  {#if advanced.length}
    <button type="button" class="show-all" aria-expanded={expanded[id] ?? false} onclick={() => expanded = { ...expanded, [id]: !expanded[id] }}>
      {tr(expanded[id] ? 'show_basic_fields' : 'show_all_fields')}
    </button>
  {/if}
{/snippet}

{#snippet fieldControl(name: string, spec: Schema, current: unknown, change: (value: unknown) => void, id: string, required = false)}
  {#if spec.type === 'object' || spec.properties}
    <fieldset class="object"><legend><span class="field-label">{@render fieldLabel(spec.title || label(name), spec, required)}</span></legend>
      {@render objectFields(spec, current, change, id)}
    </fieldset>
  {:else if spec.type === 'array'}
    <fieldset class="object"><legend><span class="field-label">{@render fieldLabel(spec.title || label(name), spec, required)}</span></legend>
      {#each (Array.isArray(current) ? current : []) as entry, index}
        <div class="array-entry">
          {@render fieldControl(`${name} ${index + 1}`, spec.items ?? { type: 'string' }, entry, next => change((current as unknown[]).map((old, i) => i === index ? next : old)), `${id}-${index}`)}
          <button type="button" class="quiet" aria-label={tr('remove')} onclick={() => change((current as unknown[]).filter((_, i) => i !== index))}>×</button>
        </div>
      {/each}
      <button type="button" class="quiet" onclick={() => change([...(Array.isArray(current) ? current : []), schemaDefault(spec.items ?? { type: 'string' })])}>+ {tr('add_item')}</button>
    </fieldset>
  {:else}
    {@const dynamic = typeof record(current).$date === 'string'}
    {@const compatible = compatibleOutputs(spec)}
    <div class="schema-field field">
      <label class="field-label" for={id}>{@render fieldLabel(spec.title || label(name), spec, required)}</label>
      {#if spec.enum}
        <SettingsDropdown value={String(current ?? '')} options={spec.enum.map(option => ({ value: String(option), label: String(option) }))} placeholder={tr('choose')} ariaLabel={spec.title || label(name)} onChange={value => change(spec.enum?.find(item => String(item) === value))}/>
      {:else if spec.type === 'boolean'}
        <SettingsDropdown value={String(current ?? false)} options={[{ value: 'true', label: tr('true') }, { value: 'false', label: tr('false') }]} ariaLabel={spec.title || label(name)} onChange={value => change(value === 'true')}/>
      {:else if dynamic}
        <SettingsDropdown value={String(record(current).$date)} options={[{ value: 'today', label: tr('today') }, { value: 'next_week_start', label: tr('next_week_start') }, { value: 'next_week_end', label: tr('next_week_end') }]} ariaLabel={spec.title || label(name)} onChange={value => change({ $date: value, format: spec.format === 'date-time' ? 'datetime' : 'date' })}/>
      {:else}
        <input {id} type={['number', 'integer'].includes(spec.type ?? '') && !String(current ?? '').startsWith('$') ? 'number' : spec.format === 'date' ? 'date' : 'text'} value={String(current ?? '')} min={spec.minimum} max={spec.maximum} step={spec.type === 'integer' ? 1 : 'any'} oninput={event => change(scalarValue(event.currentTarget.value, spec))} />
      {/if}
      {#if spec.format?.includes('date') || /(^date|_date|date_|start_time|end_time)/.test(name)}
        <button type="button" class="variable" onclick={() => change({ $date: name.includes('end') ? 'next_week_end' : name.includes('start') ? 'next_week_start' : 'today', format: spec.format === 'date-time' ? 'datetime' : 'date' })}>⌘ {tr('dynamic_date')}</button>
      {/if}
      {#if compatible.length}
        <SettingsDropdown value="" options={compatible.map(output => ({ value: output.reference, label: output.label }))} placeholder={`@ ${tr('use_output')}`} ariaLabel={`${tr('use_output')} ${label(name)}`} onChange={value => { if (value) change(value); }}/>
      {/if}
    </div>
  {/if}
{/snippet}

<div class="schema-fields">
  {@render objectFields(schema, value, onChange, path)}
</div>

<style>
  .schema-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:var(--spacing-8); font-size:max(16px, 1rem); }
  .schema-field { display:grid; align-content:start; gap:var(--spacing-4); min-width:0; text-align:start; }
  .field-label { display:flex; align-items:center; gap:var(--spacing-2); min-width:0; font-size:max(16px, 1rem); font-weight:650; line-height:1.35; }
  .field-title { min-width:0; overflow-wrap:anywhere; }
  .type-badge { flex:0 0 auto; padding:var(--spacing-2) var(--spacing-4); border-radius:var(--radius-2); background:var(--color-primary); color:var(--color-font-button); font-size:var(--font-size-xxs); font-weight:700; line-height:1; }
  .type-badge[data-type="number"] { background:var(--color-error); }
  .schema-field--specialized :global(.location-field > .label),
  .schema-field--specialized :global(.date-range > .label) { display:none; }
  .schema-field--specialized :global(.location-field),
  .schema-field--specialized :global(.date-range) { grid-column:auto; }
  input { width:100%; box-sizing:border-box; min-height:2.5rem; border:1px solid var(--color-grey-25); border-radius:.8rem; padding:.5rem .7rem; background:var(--color-grey-0); color:var(--color-font-primary); font:inherit; font-size:max(16px, 1rem); box-shadow:var(--shadow-sm); }
  .field :global(.settings-dropdown-wrapper) { padding:0; }
  .field :global(.settings-dropdown) { min-height:3.375rem; }
  .object { grid-column:1/-1; min-width:0; border:1px solid var(--color-grey-20); border-radius:.8rem; padding:.75rem; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.8rem; }
  .object legend { padding:0 var(--spacing-2); }
  .array-entry { grid-column:1/-1; display:grid; grid-template-columns:minmax(0,1fr) auto; gap:.5rem; }
  .array-entry>.object { grid-column:auto; }
  .quiet, .variable, .show-all { background:transparent; color:var(--color-primary); border:0; box-shadow:none; font:inherit; font-size:max(16px, 1rem); cursor:pointer; min-height:2rem; }
  .quiet { align-self:start; }
  .variable { padding:0; text-align:start; min-height:1.5rem; }
  .show-all { grid-column:1/-1; justify-self:start; padding:0; text-align:start; }
  input:focus-visible, button:focus-visible { outline:2px solid var(--color-button-primary); outline-offset:2px; }
  @media(max-width:730px) {
    .schema-fields, .object { grid-template-columns:1fr; }
    .field-label { flex-direction:column; align-items:flex-start; text-align:start; }
  }
</style>
