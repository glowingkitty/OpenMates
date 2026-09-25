<script lang="ts">
  import { tick } from 'svelte';
  import { text } from '../../i18n/translations';
  import SettingsDropdown from '../settings/elements/SettingsDropdown.svelte';
  import SettingsInput from '../settings/elements/SettingsInput.svelte';
  import WorkflowDateRangeField from './WorkflowDateRangeField.svelte';
  import WorkflowLocationField from './WorkflowLocationField.svelte';
  import WorkflowMessageEditor from './WorkflowMessageEditor.svelte';
  import { workflowFieldIcon } from './workflowFieldIcon';
  import { record, label, schemaDefault, type Schema, type Output } from './workflowBuilder';
  import { outputTemplateSyntax } from './workflowMessageTokens';
  import { presentedItems } from './workflowValuePresentation';

  type UiMetadata = { control?: string; start_field?: string; end_field?: string; max_offset_days?: number; hidden?: boolean; basic?: boolean };
  type LocationConfig = { mode: 'weather' | 'events' | 'home'; text: string; latitude?: string; longitude?: string };
  let { schema, value, onChange, outputs = [], path = 'input', appId = '', timezone }: {
    schema: Schema; value: unknown; onChange: (value: unknown) => void; outputs?: Output[]; path?: string; appId?: string; timezone: string;
  } = $props();

  let expanded = $state<Record<string, boolean>>({});
  let expandedVariables = $state<Record<string, boolean>>({});
  let stringEditors = $state<Record<string, { insertReference: (output: Output) => void } | undefined>>({});
  const tr = (key: string) => $text(`workflows.builder.${key}`);
  const ui = (field: Schema): UiMetadata => record((field as Schema & { 'x-ui'?: UiMetadata })['x-ui']) as UiMetadata;
  const visibleEntries = (properties: Record<string, Schema>) => Object.entries(properties).filter(([, field]) => !ui(field).hidden);
  function scalarValue(raw: string, field: Schema): unknown { return raw === '' ? undefined : ['number', 'integer'].includes(field.type ?? '') ? Number(raw) : raw; }
  function editableScalarValue(raw: string, field: Schema): unknown {
    if (raw === '') return undefined;
    if (!['number', 'integer'].includes(field.type ?? '')) return raw;
    const number = Number(raw);
    return Number.isFinite(number) ? number : raw;
  }
  function displayType(field: Schema): string {
    if (field.format === 'date') return 'date';
    if (field.type === 'integer') return 'number';
    if (field.type === 'array') return 'list';
    return field.type === 'string' || !field.type ? 'text' : field.type;
  }
  function typeLabel(field: Schema): string { return tr(`output_type_${displayType(field)}`); }
  type VariableCategory = 'location' | 'date-time' | 'url' | 'number' | 'text';
  type LocationRole = 'origin' | 'destination' | null;
  function semanticTokens(name: string, field: Schema): Set<string> {
    const descriptor = `${name} ${field.title ?? ''}`.replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase();
    return new Set(descriptor.split(/[^a-z0-9]+/).filter(Boolean));
  }
  function variableCategory(name: string, field: Schema): VariableCategory {
    if (['integer', 'number'].includes(field.type ?? '')) return 'number';
    const format = String(field.format ?? '').toLowerCase();
    const tokens = semanticTokens(name, field);
    if (format.includes('uri') || format.includes('url') || ['url', 'uri', 'link', 'website', 'webpage'].some(token => tokens.has(token))) return 'url';
    if (format.includes('date') || format.includes('time') || ['date', 'time', 'datetime', 'timestamp', 'timezone'].some(token => tokens.has(token))) return 'date-time';
    if (['location', 'city', 'address', 'place', 'country', 'postal', 'zipcode', 'airport', 'station', 'origin', 'destination', 'departure', 'arrival'].some(token => tokens.has(token))) return 'location';
    return 'text';
  }
  function locationRole(name: string, field: Schema): LocationRole {
    const tokens = semanticTokens(name, field);
    if (['origin', 'departure'].some(token => tokens.has(token)) || (tokens.has('from') && tokens.has('location'))) return 'origin';
    if (['destination', 'arrival'].some(token => tokens.has(token)) || (tokens.has('to') && tokens.has('location'))) return 'destination';
    return null;
  }
  function semanticallyCompatible(name: string, field: Schema, output: Output): boolean {
    const outputName = output.reference.split('.').at(-1) ?? output.label;
    if (field.enum?.length) {
      const sameField = outputName === name || output.schema.title?.toLowerCase() === (field.title ?? label(name)).toLowerCase();
      const sameOptions = Boolean(output.schema.enum?.length && output.schema.enum.every(option => field.enum?.includes(option)));
      return sameField || sameOptions;
    }
    const destinationCategory = variableCategory(name, field);
    if (destinationCategory === 'text' || destinationCategory === 'number') return true;
    if (variableCategory(outputName, output.schema) !== destinationCategory) return false;
    if (destinationCategory !== 'location') return true;
    const destinationRole = locationRole(name, field);
    const outputRole = locationRole(outputName, output.schema);
    return !destinationRole || !outputRole || destinationRole === outputRole;
  }
  function compatibleOutputs(name: string, field: Schema): Output[] {
    return outputs.filter(output => {
      const typeCompatible = output.schema.type === field.type || (['integer', 'number'].includes(field.type ?? '') && ['integer', 'number'].includes(output.schema.type ?? ''));
      return typeCompatible && semanticallyCompatible(name, field, output);
    });
  }
  function isTemplateValue(value: unknown): boolean { return typeof value === 'string' && (/^\{\{[^{}]+\}\}$/.test(value.trim()) || /^\$nodes\.[^.]+\.output\./.test(value.trim())); }
  function stringEditorValue(value: unknown): string {
    return String(value ?? '').replace(/\$nodes\.[A-Za-z0-9_-]+\.output\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*/g, reference => outputTemplateSyntax(reference));
  }

  async function replaceVariable(output: Output, change: (value: unknown) => void, id: string): Promise<void> {
    const template = outputTemplateSyntax(output.reference);
    change(template);
    await tick();
    const replacement = document.getElementById(id) as HTMLInputElement | null;
    replacement?.focus();
    replacement?.setSelectionRange(template.length, template.length);
  }

  function locationConfig(properties: Record<string, Schema>, id: string): LocationConfig | null {
    if (appId === 'weather' && properties.location && properties.latitude && properties.longitude) return { mode: 'weather', text: 'location', latitude: 'latitude', longitude: 'longitude' };
    if (appId === 'events' && properties.location && properties.lat && properties.lon) return { mode: 'events', text: 'location', latitude: 'lat', longitude: 'lon' };
    if (appId === 'home' && properties.query && id.includes('request')) return { mode: 'home', text: 'query' };
    return null;
  }

  function coordinateValue(current: unknown, key?: string): number | undefined {
    if (!key) return undefined;
    const raw = record(current)[key];
    if (raw === null || raw === undefined || (typeof raw === 'string' && !raw.trim())) return undefined;
    const coordinate = Number(raw);
    return Number.isFinite(coordinate) ? coordinate : undefined;
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

  function isBasic(name: string, field: Schema, required: string[], index: number, id: string): boolean {
    if (ui(field).basic !== undefined) return ui(field).basic === true;
    if (required.includes(name)) return true;
    if (appId === 'weather') return ['location', 'start_date', 'end_date'].includes(name);
    if (appId === 'events' && id.endsWith('-outer')) return false;
    if (appId === 'events' && id.includes('-request-')) return ['query', 'location'].includes(name);
    if (appId === 'home' && id.includes('-request-')) return ['query', 'listing_type', 'property_type', 'max_price_eur'].includes(name);
    return field.default !== undefined || index < 3;
  }
</script>

{#snippet fieldLabel(name: string, title: string, field: Schema, required = false)}
  {@const FieldIcon = workflowFieldIcon(name, field)}
  <span class="type-badge" data-type={displayType(field)}>{typeLabel(field)}</span>
  <span class="field-name"><FieldIcon size={18} strokeWidth={2.2} aria-hidden="true" /><span class="field-title">{title}{required ? ' *' : ''}</span></span>
{/snippet}

{#snippet objectFields(container: Schema, current: unknown, change: (value: unknown) => void, id: string, expandedId = id, showAdvancedToggle = true)}
  {@const properties = container.properties ?? {}}
  {@const entries = visibleEntries(properties)}
  {@const location = locationConfig(properties, id)}
  {@const locationAdvanced = Boolean(location && ui(properties[location.text]).basic === false)}
  {@const dateRange = dateRangeConfig(container)}
  {@const dateRangeAdvanced = Boolean(dateRange && (ui(container).basic === false || (ui(properties[dateRange.start]).basic === false && ui(properties[dateRange.end]).basic === false)))}
  {@const handled = new Set([location?.text, location?.latitude, location?.longitude, dateRange?.start, dateRange?.end].filter(Boolean))}
  {@const remaining = entries.filter(([name]) => !handled.has(name))}
  {@const basics = remaining.filter(([name, field], index) => isBasic(name, field, container.required ?? [], index, id))}
  {@const advanced = remaining.filter(entry => !basics.includes(entry))}
  {#if location && (!locationAdvanced || expanded[expandedId])}
    {@const locationRequired = container.required?.includes(location.text) ?? false}
    <div class="schema-field schema-field--specialized" data-testid="workflow-schema-field-location" role="group" aria-labelledby={`${id}-location-label`}>
      <div class="field-label" id={`${id}-location-label`}>
        {@render fieldLabel(location.text, tr('location'), properties[location.text], locationRequired)}
      </div>
      <WorkflowLocationField
        mode={location.mode}
        value={String(record(current)[location.text] ?? '')}
        latitude={coordinateValue(current, location.latitude)}
        longitude={coordinateValue(current, location.longitude)}
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
  {#if dateRange && !dateRangeAdvanced}
    <div class="schema-field schema-field--specialized" data-testid="workflow-schema-field-date-range" role="group" aria-labelledby={`${id}-date-range-label`}>
      <div class="field-label" id={`${id}-date-range-label`}>
        {@render fieldLabel('date_range', tr('date_range'), { ...properties[dateRange.start], type: 'string', format: 'date' })}
      </div>
      <WorkflowDateRangeField
        start={record(current)[dateRange.start]}
        end={record(current)[dateRange.end]}
        {timezone}
        maxOffsetDays={dateRange.maxOffsetDays}
        dateTimeBounds={appId === 'events'}
        onChange={(start, end) => change({ ...record(current), [dateRange.start]: start, [dateRange.end]: end })}
      />
    </div>
  {/if}
  {#each basics as [name, field]}
    {@render fieldControl(name, field, record(current)[name], next => change({ ...record(current), [name]: next }), `${id}-${name}`, container.required?.includes(name))}
  {/each}
  {#if expanded[expandedId]}
    {#if dateRange && dateRangeAdvanced}
      <div class="schema-field schema-field--specialized" data-testid="workflow-schema-field-date-range" role="group" aria-labelledby={`${id}-date-range-label`}>
        <div class="field-label" id={`${id}-date-range-label`}>
          {@render fieldLabel('date_range', tr('date_range'), { ...properties[dateRange.start], type: 'string', format: 'date' })}
        </div>
        <WorkflowDateRangeField
          start={record(current)[dateRange.start]}
          end={record(current)[dateRange.end]}
          {timezone}
          maxOffsetDays={dateRange.maxOffsetDays}
          dateTimeBounds={appId === 'events'}
          onChange={(start, end) => change({ ...record(current), [dateRange.start]: start, [dateRange.end]: end })}
        />
      </div>
    {/if}
    {#each advanced as [name, field]}
      {@render fieldControl(name, field, record(current)[name], next => change({ ...record(current), [name]: next }), `${id}-${name}`, container.required?.includes(name))}
    {/each}
  {/if}
  {#if showAdvancedToggle && (advanced.length || locationAdvanced || dateRangeAdvanced)}
    <button type="button" class="show-all" data-testid="workflow-show-all-fields" aria-expanded={expanded[expandedId] ?? false} onclick={() => expanded = { ...expanded, [expandedId]: !expanded[expandedId] }}>
      {tr(expanded[expandedId] ? 'show_basic_fields' : 'show_all_fields')}
    </button>
  {/if}
{/snippet}

{#snippet fieldControl(name: string, spec: Schema, current: unknown, change: (value: unknown) => void, id: string, required = false)}
  {#if spec.type === 'object' || spec.properties}
    <fieldset class="object"><legend><span class="field-label">{@render fieldLabel(name, spec.title || label(name), spec, required)}</span></legend>
      {@render objectFields(spec, current, change, id)}
    </fieldset>
  {:else if spec.type === 'array'}
    <fieldset class="object"><legend><span class="field-label">{@render fieldLabel(name, spec.title || label(name), spec, required)}</span></legend>
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
    {@const compatible = compatibleOutputs(name, spec)}
    {@const variableGroups = presentedItems(compatible)}
    {@const visibleVariables = expandedVariables[id] ? [...variableGroups.basic, ...variableGroups.advanced] : variableGroups.basic}
    {@const templateValue = isTemplateValue(current)}
    {@const stringVariableInput = (spec.type === 'string' || !spec.type) && !spec.enum && !spec.format?.includes('date') && compatible.length > 0}
    <div class="schema-field field">
      <label class="field-label" for={id}>{@render fieldLabel(name, spec.title || label(name), spec, required)}</label>
      {#if stringVariableInput}
        <WorkflowMessageEditor
          bind:this={stringEditors[id]}
          compact
          {id}
          value={stringEditorValue(current)}
          {outputs}
          placeholder={spec.title || label(name)}
          ariaLabel={spec.title || label(name)}
          dataTestid={`workflow-input-template-${id}`}
          onChange={change}
          onMentionTrigger={() => {}}
        />
      {:else if templateValue}
        <SettingsInput
          {id}
          type="text"
          value={String(current)}
          ariaLabel={spec.title || label(name)}
          onInput={raw => change(editableScalarValue(raw, spec))}
        />
      {:else if spec.enum}
        <SettingsDropdown value={String(current ?? '')} options={spec.enum.map(option => ({ value: String(option), label: String(option) }))} placeholder={tr('choose')} ariaLabel={spec.title || label(name)} onChange={value => change(spec.enum?.find(item => String(item) === value))}/>
      {:else if spec.type === 'boolean'}
        <SettingsDropdown value={String(current ?? false)} options={[{ value: 'true', label: tr('true') }, { value: 'false', label: tr('false') }]} ariaLabel={spec.title || label(name)} onChange={value => change(value === 'true')}/>
      {:else if dynamic}
        <SettingsDropdown value={String(record(current).$date)} options={[{ value: 'today', label: tr('today') }, { value: 'next_week_start', label: tr('next_week_start') }, { value: 'next_week_end', label: tr('next_week_end') }]} ariaLabel={spec.title || label(name)} onChange={value => change({ $date: value, format: spec.format === 'date-time' ? 'datetime' : 'date' })}/>
      {:else}
        <SettingsInput
          {id}
          type={['number', 'integer'].includes(spec.type ?? '') ? 'number' : spec.format === 'date' ? 'date' : 'text'}
          value={String(current ?? '')}
          min={spec.minimum === undefined ? undefined : String(spec.minimum)}
          max={spec.maximum === undefined ? undefined : String(spec.maximum)}
          ariaLabel={spec.title || label(name)}
          onInput={raw => change(scalarValue(raw, spec))}
        />
      {/if}
      {#if spec.format?.includes('date') || /(^date|_date|date_|start_time|end_time)/.test(name)}
        <button type="button" class="variable" onclick={() => change({ $date: name.includes('end') ? 'next_week_end' : name.includes('start') ? 'next_week_start' : 'today', format: spec.format === 'date-time' ? 'datetime' : 'date' })}>⌘ {tr('dynamic_date')}</button>
      {/if}
      {#if compatible.length}
        <div class="variable-picker">
          <div class="variable-chips" data-testid={`workflow-input-variable-chips-${id}`} aria-label={`${tr('use_output')} ${label(name)}`}>
            {#each visibleVariables as output}
              <button type="button" class="chip" onclick={() => stringVariableInput ? stringEditors[id]?.insertReference(output) : void replaceVariable(output, change, id)}>+ {output.label}</button>
            {/each}
          </div>
          {#if variableGroups.advanced.length}
            <button type="button" class="variable-toggle" aria-expanded={expandedVariables[id] ?? false} onclick={() => expandedVariables = { ...expandedVariables, [id]: !expandedVariables[id] }}>
              {tr(expandedVariables[id] ? 'show_basic_variables' : 'show_all_variables')}
            </button>
          {/if}
        </div>
      {/if}
    </div>
  {/if}
{/snippet}

{#snippet rootFields()}
  {@const rootProperties = schema.properties ?? {}}
  {@const requestsSchema = rootProperties.requests}
  {@const batchItems = requestsSchema?.type === 'array' && (requestsSchema.items?.type === 'object' || requestsSchema.items?.properties) ? requestsSchema.items : null}
  {#if batchItems}
    {@const currentRecord = record(value)}
    {@const storedRequests = Array.isArray(currentRecord.requests) ? currentRecord.requests : []}
    {@const requests = storedRequests.length ? storedRequests : [schemaDefault(batchItems)]}
    {@const outerSchema = { ...schema, properties: Object.fromEntries(Object.entries(rootProperties).filter(([name]) => name !== 'requests')), required: (schema.required ?? []).filter(name => name !== 'requests') }}
    {#if appId === 'events'}
      {@const eventsExpandedId = `${path}-events-advanced`}
      {#each requests as request, index}
        <section class="batch-request" aria-label={`${label('request')} ${index + 1}`}>
          {#if requests.length > 1}<h5>{label('request')} {index + 1}</h5>{/if}
          {@render objectFields(batchItems, request, next => onChange({ ...currentRecord, requests: requests.map((entry, itemIndex) => itemIndex === index ? next : entry) }), `${path}-request-${index}`, eventsExpandedId, false)}
        </section>
      {/each}
      {@render objectFields(outerSchema, value, onChange, `${path}-outer`, eventsExpandedId, false)}
      <button type="button" class="show-all" data-testid="workflow-show-all-fields" aria-expanded={expanded[eventsExpandedId] ?? false} onclick={() => expanded = { ...expanded, [eventsExpandedId]: !expanded[eventsExpandedId] }}>
        {tr(expanded[eventsExpandedId] ? 'show_basic_fields' : 'show_all_fields')}
      </button>
    {:else}
      {@render objectFields(outerSchema, value, onChange, `${path}-outer`)}
      {#each requests as request, index}
        <section class="batch-request" aria-label={`${label('request')} ${index + 1}`}>
          {#if requests.length > 1}<h5>{label('request')} {index + 1}</h5>{/if}
          {@render objectFields(batchItems, request, next => onChange({ ...currentRecord, requests: requests.map((entry, itemIndex) => itemIndex === index ? next : entry) }), `${path}-request-${index}`)}
        </section>
      {/each}
    {/if}
  {:else}
    {@render objectFields(schema, value, onChange, path)}
  {/if}
{/snippet}

<div class="schema-fields">
  {@render rootFields()}
</div>

<style>
  .schema-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:var(--spacing-8); font-size:max(16px, 1rem); }
  .schema-field { display:grid; align-content:start; gap:var(--spacing-4); min-width:0; text-align:start; }
  .field-label { display:flex; align-items:center; gap:var(--spacing-2); min-width:0; font-size:max(16px, 1rem); font-weight:650; line-height:1.35; }
  .field-name { display:inline-flex; align-items:center; gap:var(--spacing-2); min-width:0; }
  .field-name :global(svg) { flex:0 0 auto; color:var(--color-font-secondary); }
  .field-title { min-width:0; overflow-wrap:anywhere; }
  .type-badge { flex:0 0 auto; padding:var(--spacing-2) var(--spacing-4); border-radius:var(--radius-2); background:var(--color-primary); color:var(--color-font-button); font-size:var(--font-size-xxs); font-weight:700; line-height:1; }
  .type-badge[data-type="number"] { background:var(--color-error); }
  .schema-field--specialized :global(.location-field > .label),
  .schema-field--specialized :global(.date-range > .label) { display:none; }
  .schema-field--specialized { grid-column:1/-1; }
  .schema-field--specialized :global(.location-field),
  .schema-field--specialized :global(.date-range) { grid-column:auto; }
  .field :global(.settings-input-wrapper) { padding:0; }
  .field :global(.settings-dropdown-wrapper) { padding:0; }
  .field :global(.settings-input),
  .field :global(.settings-dropdown) { background:var(--workflow-input-surface, var(--color-grey-10)); }
  .field :global(.settings-dropdown) { min-height:3.375rem; }
  .variable-picker { display:grid; min-width:0; gap:var(--spacing-2); }
  .variable-chips { display:flex; flex-wrap:nowrap; min-width:0; max-width:100%; gap:var(--spacing-2); justify-content:flex-start; overflow-x:auto; padding:var(--spacing-2); }
  .chip { flex:0 0 auto; border:0; border-radius:var(--radius-full); padding:var(--spacing-2) var(--spacing-4); background:var(--color-primary); color:var(--color-font-button); font:inherit; font-size:max(16px, 1rem); cursor:pointer; }
  .variable-toggle { justify-self:center; border:0; padding:var(--spacing-2) var(--spacing-4); background:transparent; color:var(--color-font-secondary); font:inherit; font-size:var(--font-size-small); cursor:pointer; }
  .object { grid-column:1/-1; min-width:0; border:1px solid var(--color-grey-20); border-radius:.8rem; padding:.75rem; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.8rem; }
  .object legend { padding:0 var(--spacing-2); }
  .array-entry { grid-column:1/-1; display:grid; grid-template-columns:minmax(0,1fr) auto; gap:.5rem; }
  .array-entry>.object { grid-column:auto; }
  .batch-request { grid-column:1/-1; display:grid; grid-template-columns:subgrid; gap:var(--spacing-8); min-width:0; }
  .batch-request h5 { grid-column:1/-1; margin:var(--spacing-4) 0 0; color:var(--color-font-secondary); font-size:var(--font-size-small); text-align:start; }
  .quiet, .variable, .show-all { background:transparent; color:var(--color-primary); border:0; box-shadow:none; font:inherit; font-size:max(16px, 1rem); cursor:pointer; min-height:2rem; }
  .quiet { align-self:start; }
  .variable { padding:0; text-align:start; min-height:1.5rem; }
  .show-all { grid-column:1/-1; justify-self:center; padding:0; text-align:center; color:var(--color-font-secondary); font-size:var(--font-size-small); }
  button:focus-visible { outline:2px solid var(--color-button-primary); outline-offset:2px; }
  @media(max-width:730px) {
    .schema-fields, .object { grid-template-columns:1fr; }
    .field-label { flex-direction:column; align-items:flex-start; text-align:start; }
  }
</style>
