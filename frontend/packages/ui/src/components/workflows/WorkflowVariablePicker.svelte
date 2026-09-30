<script lang="ts">
  import { text } from '../../i18n/translations';
  import { presentedItems } from './workflowValuePresentation';
  import { workflowVariableGradient } from './workflowVariableGradient';
  import { matchesWorkflowVariableQuery } from './workflowMentionQuery';
  import { outputCanonicalName } from './workflowMessageTokens';
  import type { Output } from './workflowBuilder';

  export interface VariableSource {
    nodeId: string;
    label: string;
    appId: string;
    iconStyle: string;
  }

  let { outputs, sources, selectedSourceId, query = '', suggestedReferences = [], disabled = false, onSelectSource, onInsert }: {
    outputs: Output[];
    sources: VariableSource[];
    selectedSourceId: string | null;
    query?: string;
    suggestedReferences?: string[];
    disabled?: boolean;
    onSelectSource: (nodeId: string) => void;
    onInsert: (output: Output) => void;
  } = $props();
  let showAll = $state(false);
  let previousSource = $state<string | null>(null);
  const tr = (key: string) => $text(`workflows.builder.${key}`);
  const visibleSources = $derived(sources.filter(source => !query || outputs.some(output =>
    !output.listProjection && output.nodeId === source.nodeId && matchesWorkflowVariableQuery(`${source.label} ${output.label}`, query, outputCanonicalName(output)))));
  const selectedSource = $derived(visibleSources.find(source => source.nodeId === selectedSourceId));
  const sourceOutputs = $derived(outputs.filter(output => !output.listProjection && output.nodeId === selectedSource?.nodeId));
  const groups = $derived(presentedItems(sourceOutputs));
  const filteredOutputs = $derived(sourceOutputs.filter(output => matchesWorkflowVariableQuery(`${selectedSource?.label ?? ''} ${output.label}`, query, outputCanonicalName(output))));
  const suggestions = $derived(sourceOutputs.filter(output => groups.basic.includes(output) || suggestedReferences.includes(output.reference))
    .toSorted((a, b) => Number(b.reference.endsWith('.output.results')) - Number(a.reference.endsWith('.output.results'))
      || Number(suggestedReferences.includes(b.reference)) - Number(suggestedReferences.includes(a.reference))).slice(0, 5));
  const shownOutputs = $derived(showAll || query ? filteredOutputs : suggestions);

  $effect(() => {
    if (selectedSourceId !== previousSource) { previousSource = selectedSourceId; showAll = false; }
  });

  function fieldLabel(output: Output): string {
    return output.label.split(' · ').slice(1).join(' · ') || output.label;
  }
</script>

{#if sources.length}
  <div class="workflow-variable-picker" data-testid="workflow-variable-picker">
    <div class="source-row" data-testid="workflow-variable-sources" aria-label={tr('select_variable_source')}>
      <span class="add-label">{tr('variable_add')}</span>
      <div class="source-scroll" data-testid="workflow-variable-source-scroll">
      {#each visibleSources as source (source.nodeId)}
        <button type="button" class="chip source-chip" class:selected={source.nodeId === selectedSourceId}
          style={workflowVariableGradient(source)} aria-pressed={source.nodeId === selectedSourceId}
          data-source-node-id={source.nodeId} disabled={disabled} onclick={() => onSelectSource(source.nodeId)}>
          <span class="source-icon" style={source.iconStyle} aria-hidden="true"></span>@ {source.label}
        </button>
      {/each}
      {#if !visibleSources.length}<span class="no-match" role="status">{tr('no_matching_variables')}</span>{/if}
      </div>
    </div>
    {#if selectedSource}
      <div class="field-row" data-testid="workflow-ai-suggestions" aria-label={tr('select_output')}>
        {#each shownOutputs as output (output.reference)}
          <button type="button" class="chip" style={workflowVariableGradient(output)}
            data-variable-reference={output.reference} disabled={disabled} onclick={() => onInsert(output)}>
            <span class="source-icon" style={selectedSource.iconStyle} aria-hidden="true"></span>{fieldLabel(output)}
          </button>
        {/each}
        {#if !shownOutputs.length}<span class="no-match" role="status">{tr('no_matching_variables')}</span>{/if}
        {#if filteredOutputs.length > suggestions.length || showAll}
          <button type="button" class="show-all" aria-expanded={showAll} disabled={disabled} onclick={() => showAll = !showAll}>
            {tr(showAll ? 'variable_show_less' : 'variable_show_all')}
          </button>
        {/if}
      </div>
    {/if}
  </div>
{/if}

<style>
  .workflow-variable-picker{min-width:0;text-align:start;display:grid;gap:.5rem}
  .source-row,.field-row{display:flex;align-items:center;gap:.45rem;min-width:0}
  .field-row{flex-wrap:wrap}
  .source-scroll{display:flex;align-items:center;gap:.45rem;flex:1 1 0;min-width:0;overflow-x:auto;scrollbar-width:none;padding:.2rem .65rem .35rem;scroll-padding-inline:.65rem;mask-image:linear-gradient(to right,transparent,#000 .65rem,#000 calc(100% - .65rem),transparent)}
  .source-scroll::-webkit-scrollbar{display:none}
  .source-scroll .source-chip{flex:0 0 auto;max-width:none;white-space:nowrap}
  .add-label{color:var(--color-font-secondary);font-size:var(--font-size-small);font-weight:500;flex:0 0 auto}
  .field-row{padding-inline-start:2.5rem}
  .chip{display:inline-flex;align-items:center;justify-content:flex-start;gap:.25rem;max-width:100%;border:0;border-radius:var(--radius-full);padding:.15rem .5rem;background:linear-gradient(135deg,var(--variable-start,var(--color-primary-start)),var(--variable-end,var(--color-primary-end)));color:var(--color-font-button);font:inherit;font-size:var(--font-size-small);font-weight:500;line-height:1.3;text-align:left;white-space:normal;overflow-wrap:anywhere;box-shadow:var(--shadow-sm);cursor:pointer}
  .source-chip.selected{opacity:.6}
  .source-icon{display:inline-block;flex:0 0 auto;width:.875rem;height:.875rem;background:currentColor;-webkit-mask:var(--workflow-icon) center/contain no-repeat;mask:var(--workflow-icon) center/contain no-repeat}
  .show-all{border:0;padding:.2rem .3rem;background:transparent;color:var(--color-primary-start);font:inherit;font-size:var(--font-size-small);cursor:pointer}
  .no-match{color:var(--color-font-secondary);font-size:var(--font-size-small)}
  button:focus-visible{outline:2px solid var(--color-button-primary);outline-offset:2px}
  button:disabled{cursor:default;opacity:.5}
  @media(pointer:coarse){.chip,.show-all{min-height:2.75rem}}
  @media(max-width:420px){.field-row{padding-inline-start:0}}
</style>
