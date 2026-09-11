<!--
  Specification fullscreen reader, built on the shared embed shell.
  Renders Outcome, boundaries and ordered custom chapters from typed view data.
  Requirement proof is separate from authored content and expands for inspection.
  Flows open the shared fullscreen renderer using parent-owned Spec data.
  No independent flow embed, storage lookup or chat history is involved.
  Contract: specifications/features/specifications/specification.yml.
-->
<script lang="ts">
  import { resolveIconName } from '../../../utils/iconNameResolver';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import type { SpecificationDocument, SpecFlow, SpecCheckPreview } from './SpecificationDocument';
  interface Props { data: { decodedContent: { document: SpecificationDocument } }; onClose: () => void }
  let { data, onClose }: Props = $props();
  const document = $derived(data.decodedContent.document);
  let selectedFlow = $state<SpecFlow | null>(null);
  let selectedCheck = $state<SpecCheckPreview | null>(null);
  const requirements = $derived(new Map(document.requirements.map(item => [item.id, item])));
  const models = $derived(new Map(document.models.map(item => [item.id, item])));
  function flows(ids: string[], kind: SpecFlow['kind']) {
    return document.flows.filter(item => ids.includes(item.id) && item.kind === kind);
  }
</script>

{#snippet icon(name: string)}
  <span class="spec-icon" style={`--spec-icon: var(--icon-url-${resolveIconName(name)})`} aria-hidden="true"></span>
{/snippet}

{#snippet flowCards(items: SpecFlow[])}
  <div class="flow-grid">
    {#each items as flow (flow.id)}
      <div data-testid={`spec-flow-${flow.id}`}>
        <UnifiedEmbedPreview id={`spec-flow-${flow.id}`} presentationOnly
          appId="design" appIconName="design" skillId="specification-flow" skillIconName="design"
          skillName={flow.title} status="finished" showStatus={false} showSkillIcon={false}
          onFullscreen={() => { selectedFlow = flow; }}>
          {#snippet details()}
            <div class="flow-preview">
              <span class="flow-state"><span></span>Draft</span>
              <ul>{#each flow.steps.slice(0, 3) as step}<li>{step}</li>{/each}</ul>
            </div>
          {/snippet}
        </UnifiedEmbedPreview>
      </div>
    {/each}
  </div>
{/snippet}

<div class="specification-view" style:--spec-cover={selectedCheck ? 'var(--color-app-plans)' : selectedFlow ? 'var(--color-app-design)' : 'var(--color-grey-90)'}>
  {#if selectedCheck}
    <UnifiedEmbedFullscreen appId="plans" skillIconName="task" showShare={false}
      testId="spec-check-fullscreen" closeTestId="spec-check-close"
      embedHeaderTitle={selectedCheck.title} embedHeaderSubtitle={`Check · ${selectedCheck.method}`}
      onClose={() => { selectedCheck = null; }}>
      {#snippet content()}
        <article class="flow-document">
          <p class="flow-parent">Linked from {document.title} / {selectedFlow?.title}</p>
          <p>{selectedCheck.description}</p>
          <h2>Evidence</h2><p>{selectedCheck.evidence}</p>
          <p class="flow-parent">Design preview · illustrative Check · styling proposed</p>
        </article>
      {/snippet}
    </UnifiedEmbedFullscreen>
  {:else if selectedFlow}
    <UnifiedEmbedFullscreen appId="design" skillIconName="design" showShare={false}
      testId="spec-flow-fullscreen" closeTestId="spec-flow-close"
      embedHeaderTitle={selectedFlow.title}
      embedHeaderSubtitle={`${selectedFlow.kind === 'edge_case' ? 'Edge case' : 'User flow'} · ${document.title}`}
      onClose={() => { selectedFlow = null; }}>
      {#snippet content()}
        <article class="flow-document">
          <p class="flow-parent">Part of {document.project} / {document.title}</p>
          <ol>{#each selectedFlow.steps as step}<li>{step}</li>{/each}</ol>
          <h2 class="checks-heading">Checks</h2>
          {#if selectedFlow.requiredCheckRefs?.length}
            <p class="flow-parent">Illustrative links · evidence must match this flow’s revision.</p>
            <div class="flow-grid">
              {#each selectedFlow.requiredCheckRefs as checkId}
                {@const check = document.linkedChecks?.find(item => item.id === checkId)}
                {#if check}
                  <div data-testid={`spec-check-${check.id}`}>
                    <UnifiedEmbedPreview id={`spec-check-${check.id}`} presentationOnly
                      appId="plans" appIconName="task" skillId="check" skillIconName="task"
                      skillName={check.title} status="finished" showStatus={false} showSkillIcon={false}
                      onFullscreen={() => { selectedCheck = check; }}>
                      {#snippet details()}
                        <div class="check-preview"><span>{check.method} · sample</span><p>{check.description}</p><strong>No proof recorded</strong></div>
                      {/snippet}
                    </UnifiedEmbedPreview>
                  </div>
                {/if}
              {/each}
            </div>
          {:else}<p class="flow-parent">No Checks linked in this example yet.</p>{/if}
        </article>
      {/snippet}
    </UnifiedEmbedFullscreen>
  {:else}
  <UnifiedEmbedFullscreen appId="code" skillIconName="design" {onClose} showShare={false}
    testId="specification-fullscreen" embedHeaderTitle={document.title}
    embedHeaderSubtitle={`${document.category} · Specification for ${document.project}`}>
    {#snippet content()}
      <article class="spec-document" aria-label={`${document.title} Specification`}>
        <div class="document-intro">
          <p class="summary">{document.summary}</p>
          <p class="preview-notice">{document.previewNotice}</p>
        </div>

        <section aria-labelledby="spec-outcome" class="major-section">
          <h2 id="spec-outcome">{@render icon('calendar')}Outcome</h2>
          <p class="outcome">{document.outcome}</p>
          {#if document.outcomeReference}<details class="architecture-card">
            <summary>
              <span class="architecture-diagram" aria-hidden="true">{#each document.outcomeReference.labels as label, index}{#if index}<i></i>{/if}<span>{label}</span>{/each}</span>
              <span class="flow-footer"><span class="architecture-icon">{@render icon('workflow')}</span><strong>{document.outcomeReference.title}</strong><span class="expand" aria-hidden="true">+</span></span>
            </summary>
            <p>{document.outcomeReference.description}</p>
          </details>{/if}
        </section>

        <section aria-labelledby="spec-boundaries" class="major-section">
          <h2 id="spec-boundaries">{@render icon('calendar')}Scope & boundaries</h2>
          <div class="boundaries">
            <div><h3>Included</h3><ul>{#each document.scope.included as item}<li>{item}</li>{/each}</ul></div>
            <div><h3>Outside this scope</h3><ul>{#each document.scope.excluded as item}<li>{item}</li>{/each}</ul></div>
          </div>
        </section>

        {#each document.chapters as chapter (chapter.id)}
          {@const userFlows = flows(chapter.flowIds, 'user_flow')}
          {@const edgeCases = flows(chapter.flowIds, 'edge_case')}
          <section class="major-section" aria-labelledby={`chapter-${chapter.id}`} data-testid="spec-chapter">
            <h2 id={`chapter-${chapter.id}`}>{@render icon('files')}{chapter.title}</h2>
            {#if chapter.introduction}<p class="chapter-introduction">{chapter.introduction}</p>{/if}

            {#if chapter.requirementIds.length}
              <h3 class="subheading">{@render icon('check')}Requirements</h3>
              <div class="requirements">
                {#each chapter.requirementIds as id (id)}
                  {@const requirement = requirements.get(id)}
                  {#if requirement}
                    <div class="requirement" data-testid="spec-requirement">
                      <div class="applicability"><span>Applies to:</span>{#each requirement.appliesTo as surface}<strong>{surface}</strong>{/each}</div>
                      <div class="requirement-line">
                        <span class="proof-mark" class:passed={requirement.proof.state === 'passed'} aria-label={requirement.proof.state === 'passed' ? 'Illustrative proven requirement' : 'Requirement not proven'}>{#if requirement.proof.state === 'passed'}{@render icon('check')}{/if}</span>
                        <div class="requirement-body">
                          <p class="statement">{requirement.statement}</p>
                          <details class="proof-detail" data-testid="spec-proof">
                            <summary><span class="proof-label">{requirement.proof.state === 'passed' ? 'Proven in check' : requirement.proof.state === 'stale' ? 'Proof needs refresh' : 'To be proven in'}</span><span class="check-pill">{requirement.proof.title}</span></summary>
                            <p>{requirement.proof.explanation}</p>
                          </details>
                          <details class="requirement-details">
                            <summary>Example & requirement ID</summary>
                            <p>{requirement.example}</p><code>{requirement.id}</code>
                          </details>
                        </div>
                      </div>
                    </div>
                  {/if}
                {/each}
              </div>
            {/if}

            {#if userFlows.length}<h3 class="subheading">{@render icon('user')}User flows</h3>{@render flowCards(userFlows)}{/if}
            {#if edgeCases.length}<h3 class="subheading">{@render icon('warning')}Edge cases</h3>{@render flowCards(edgeCases)}{/if}
            {#if chapter.modelIds.length}
              <h3 class="subheading">{@render icon('search')}Relevant models</h3>
              <div class="model-list">
                {#each chapter.modelIds as id (id)}
                  {@const model = models.get(id)}
                  {#if model}
                    <details class="model-detail" data-testid={`spec-model-${id}`}>
                      <summary>{@render icon('code')} {model.id}</summary>
                      <div class="model-content"><p>{model.description}</p><dl>{#each model.fields as field}<dt><code>{field.name}</code><span>{field.type}</span></dt><dd>{field.description}</dd>{/each}</dl></div>
                    </details>
                  {/if}
                {/each}
              </div>
            {/if}
          </section>
        {/each}
      </article>
    {/snippet}
  </UnifiedEmbedFullscreen>
  {/if}
</div>

<style>
  .specification-view { --spec-accent: var(--color-primary-start); --spec-cover: var(--color-grey-90); color: var(--color-font-primary); }
  .specification-view :global(.embed-header) { height: 300px; }
  .specification-view :global(.header-inner) { background: var(--spec-cover) !important; border-radius: 0; box-shadow: none; }
  .specification-view :global(.embed-header-orbs), .specification-view :global(.deco-icon) { display: none; }
  .specification-view :global(.header-title-text), .specification-view :global(.header-subtitle) { color: var(--color-grey-0); }
  .specification-view :global(.header-skill-icon) { background-color: var(--color-grey-0); }
  .spec-document { container-type: inline-size; padding: 0 max(24px, calc((100% - 760px) / 2)) 88px; background: var(--color-grey-10); min-height: 100%; }
  .document-intro { text-align: center; padding: 28px 0 12px; }
  .summary { max-width: 540px; margin: 0 auto 12px; font-size: var(--font-size-lg); font-weight: 600; line-height: 1.6; }
  .preview-notice { color: var(--color-font-secondary); font-size: var(--font-size-xxs); margin: 0; }
  .major-section { margin-top: 44px; }
  h2 { display: flex; align-items: center; gap: 18px; border-bottom: 3px solid var(--spec-accent); padding: 0 8px 13px; font-size: var(--font-size-h3); font-weight: 700; margin: 0 0 18px; line-height: 1.4; }
  .spec-icon { display: inline-block; flex-shrink: 0; width: 24px; height: 24px; background: currentColor; mask: var(--spec-icon) center / contain no-repeat; -webkit-mask: var(--spec-icon) center / contain no-repeat; color: var(--spec-accent); }
  .outcome { font-size: var(--font-size-lg); font-weight: 600; line-height: 1.6; margin: 0 8px 24px; }
  .chapter-introduction { margin: 0 8px 28px; color: var(--color-font-secondary); line-height: 1.65; }
  .boundaries { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; padding: 0 8px; }
  .boundaries h3 { font-size: var(--font-size-small); margin: 4px 0 8px; }
  .boundaries ul { padding-left: 18px; margin: 0; color: var(--color-font-secondary); line-height: 1.6; font-size: var(--font-size-small); }
  .boundaries li + li { margin-top: 7px; }
  .subheading { display: flex; align-items: center; gap: 18px; font-size: var(--font-size-lg); margin: 34px 8px 18px; }
  .requirement { margin: 24px 8px; }
  .applicability { display: flex; flex-wrap: wrap; gap: 8px 18px; font-size: var(--font-size-xxs); margin: 0 0 11px 36px; }
  .applicability > span { color: var(--color-font-secondary); }
  .requirement-line { display: flex; gap: 12px; align-items: flex-start; }
  .proof-mark { flex: 0 0 24px; width: 24px; height: 24px; border: 2px solid var(--color-grey-50); border-radius: 50%; margin-top: 1px; display: grid; place-items: center; box-sizing: border-box; }
  .proof-mark.passed { background: var(--color-chat-rainbow-green); border-color: var(--color-chat-rainbow-green); }
  .proof-mark .spec-icon { width: 16px; height: 16px; color: var(--color-font-button); }
  .requirement-body { min-width: 0; flex: 1; }
  .statement { font-size: var(--font-size-p); font-weight: 650; line-height: 1.5; margin: 0 0 7px; }
  summary { cursor: pointer; list-style: none; }
  summary::-webkit-details-marker { display: none; }
  summary:focus-visible { outline: 3px solid var(--spec-accent); outline-offset: 5px; border-radius: 4px; }
  .proof-detail summary { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; font-size: var(--font-size-xxs); }
  .proof-label { color: var(--color-font-secondary); font-weight: 600; }
  .check-pill { background: var(--color-app-ai); color: var(--color-font-button); border-radius: 20px; padding: 3px 12px; font-weight: 650; }
  .proof-detail p, .requirement-details p { font-size: var(--font-size-xs); line-height: 1.6; padding: 12px; background: var(--color-grey-0); border-radius: 10px; margin: 10px 0; }
  .requirement-details { margin-top: 9px; color: var(--color-font-secondary); font-size: var(--font-size-xxs); }
  .requirement-details summary:hover { color: var(--color-font-primary); }
  code { overflow-wrap: anywhere; font-size: var(--font-size-xxs); }
  .flow-grid { align-items: start; display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 22px; }
  .architecture-card { background: var(--color-grey-0); border-radius: 24px; box-shadow: 0 3px 3px var(--color-grey-30); min-width: 0; overflow: hidden; }
  .flow-preview { padding: 12px 14px; }
  .flow-preview ul { margin: 8px 0 0; padding-left: 18px; color: var(--color-font-secondary); font-size: var(--font-size-small); line-height: 1.45; }
  .flow-document { max-width: 700px; margin: 0 auto; padding: 28px 24px 60px; }
  .flow-parent { color: var(--color-font-secondary); font-size: var(--font-size-small); }
  .flow-document ol { padding-left: 24px; line-height: 1.7; }
  .flow-document li + li { margin-top: 16px; }
  .flow-state { display: inline-flex; align-items: center; align-self: flex-start; gap: 7px; margin: 12px 16px 8px; font-size: var(--font-size-xxs); color: var(--color-font-secondary); }
  .flow-state > span { width: 10px; height: 10px; border-radius: 50%; background: var(--color-warning); }
  .flow-footer { display: flex; align-items: center; gap: 12px; background: var(--color-grey-10); border-top: 1px solid var(--color-grey-20); min-height: 58px; padding: 0 14px 0 0; border-radius: 28px; font-size: var(--font-size-p); }
  .architecture-icon { width: 58px; height: 58px; border-radius: 50%; display: grid; place-items: center; flex-shrink: 0; background: var(--color-grey-90); }
  .architecture-icon { background: var(--color-app-ai); }
  .architecture-icon .spec-icon { color: var(--color-font-button); }
  .expand { margin-left: auto; color: var(--color-font-secondary); font-size: var(--font-size-h3); }
  details[open] > summary .expand { transform: rotate(45deg); }
  .architecture-card { width: min(340px, 100%); }
  .architecture-card p { padding: 0 20px 8px; font-size: var(--font-size-small); line-height: 1.6; }
  .architecture-diagram { display: flex; align-items: center; justify-content: center; min-height: 126px; padding: 14px 20px; font-size: var(--font-size-xxs); font-weight: 650; }
  .architecture-diagram > span { border: 1px solid var(--color-grey-30); border-radius: 10px; padding: 12px; background: var(--color-grey-10); }
  .architecture-diagram i { width: 28px; border-top: 1px dashed var(--color-grey-50); margin: 0 8px; }
  .model-list { display: flex; align-items: flex-start; flex-wrap: wrap; gap: 10px; padding: 0 8px; }
  .model-detail { min-width: 0; max-width: 100%; }
  .model-detail > summary { display: flex; align-items: center; gap: 6px; border-radius: 18px; background: var(--color-app-code); color: var(--color-font-button); padding: 5px 12px; font-size: var(--font-size-xxs); font-weight: 650; overflow-wrap: anywhere; }
  .model-detail > summary .spec-icon { width: 16px; height: 16px; color: var(--color-font-button); }
  .check-preview { padding: 16px; font-size: var(--font-size-small); }
  .check-preview > span { color: var(--color-font-secondary); font-size: var(--font-size-xxs); }
  .check-preview p { line-height: 1.45; margin: 10px 0; }
  .check-preview strong { font-size: var(--font-size-xxs); }
  .checks-heading { margin-top: 36px; }
  .model-detail[open] { flex-basis: 100%; }
  .model-detail[open] > summary { width: fit-content; }
  .model-content { padding: 14px 18px; margin-top: 12px; border: 1px solid var(--color-grey-25); border-radius: 14px; background: var(--color-grey-0); font-size: var(--font-size-xs); }
  .model-content p { line-height: 1.6; margin: 0; }
  dt { display: flex; flex-wrap: wrap; gap: 6px 12px; margin-top: 16px; font-weight: 600; }
  dt > span { color: var(--color-font-secondary); font-size: var(--font-size-xxs); font-weight: 400; }
  dd { margin: 4px 0 0; color: var(--color-font-secondary); line-height: 1.5; }
  @container (max-width: 480px) {
    .flow-grid, .boundaries { grid-template-columns: 1fr; gap: 18px; }
    h2 { font-size: var(--font-size-h3-mobile); gap: 12px; padding-left: 0; }
    .subheading { margin-left: 0; gap: 12px; }
    .requirement { margin-left: 0; margin-right: 0; }
    .applicability { gap: 7px 12px; font-size: var(--font-size-tiny); }
    .statement, .outcome { font-size: var(--font-size-p); }
  }
</style>
