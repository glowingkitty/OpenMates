<script lang="ts">
  import WorkspaceHomeShell from './WorkspaceHomeShell.svelte';
  import WorkspacePromptComposer from './WorkspacePromptComposer.svelte';

  let { surface = 'tasks', outcome = 'success' }: { surface?: 'tasks' | 'workflows' | 'editor'; outcome?: 'success' | 'false' | 'reject' | 'pending-success' | 'pending-false' } = $props();
  let value = $state('');
  let focused = $state(false);
  let cardClicks = $state(0);
  let micClicks = $state(0);
  let sends = $state(0);
  let submitting = $state(false);
  let settlePending: (() => void) | null = null;

  async function send(): Promise<boolean> {
    sends += 1;
    if (outcome === 'pending-success' || outcome === 'pending-false') {
      submitting = true;
      await new Promise<void>((resolve) => { settlePending = resolve; });
      settlePending = null;
      submitting = false;
      if (outcome === 'pending-false') return false;
    }
    if (outcome === 'false') return false;
    if (outcome === 'reject') throw new Error('Synthetic submit failure');
    value = '';
    return true;
  }
</script>

<div class="fixture" data-testid="composer-focus-fixture">
  {#if surface === 'editor'}
    <section class="editor-surface">
      <div class="editor-graph" data-testid="fixture-editor-graph" inert={focused} class:dimmed={focused}>
        <button type="button" data-testid="fixture-card" onclick={() => cardClicks += 1}>Graph control</button>
      </div>
      {#if focused}<button type="button" class="editor-backdrop" data-testid="fixture-editor-backdrop" aria-label="Dismiss editor" onpointerdown={(event) => event.preventDefault()} onclick={() => focused = false}></button>{/if}
      <div class="editor-composer"><WorkspacePromptComposer surface="workflows" bind:value bind:focusActive={focused} placeholder="Describe an edit" submitLabel="Send" submittingLabel="Sending" disabled={false} {submitting} onSubmit={send} onMicClick={() => micClicks += 1} /></div>
    </section>
  {:else}
    <WorkspaceHomeShell surface={surface} heading="A focused workspace" subtitle="Describe your next step" contentSlotVisible composerFocused={focused} onComposerDismiss={() => focused = false}>
      <button type="button" data-testid="fixture-card" onclick={() => cardClicks += 1}>Board control</button>
      <button type="button" data-testid="fixture-prefill" onclick={() => { value = 'An inspired task'; focused = true; }}>Use inspiration</button>
      <svelte:fragment slot="composer"><WorkspacePromptComposer {surface} bind:value bind:focusActive={focused} placeholder="Describe your next step" submitLabel="Send" submittingLabel="Sending" disabled={false} {submitting} onSubmit={send} onMicClick={() => micClicks += 1} /></svelte:fragment>
    </WorkspaceHomeShell>
  {/if}
  {#if submitting}<button type="button" class="fixture-settle" data-testid="fixture-settle" onpointerdown={(event) => event.preventDefault()} onclick={() => settlePending?.()}>Settle pending send</button>{/if}
  <output data-testid="fixture-card-clicks">{cardClicks}</output>
  <output data-testid="fixture-mic-clicks">{micClicks}</output>
  <output data-testid="fixture-sends">{sends}</output>
</div>

<style>
  .fixture { height: min(720px, 100dvh); min-height: 500px; width: min(900px, 100%); position: relative; }
  .editor-surface { position: relative; height: 100%; background: var(--color-grey-20); }
  .editor-graph { height: 100%; padding: 60px; visibility: visible; transition: opacity .18s ease, visibility 0s; }
  .editor-graph.dimmed { opacity: 0; visibility: hidden; transition-delay: 0s, .18s; }
  @media (prefers-reduced-motion: reduce) {
    .editor-graph, .editor-graph.dimmed { transition: none; }
  }
  .editor-backdrop { position: absolute; inset: 0; z-index: 2; width: 100%; height: 100%; min-width: 0; margin: 0; padding: 0; border: 0; border-radius: 0; box-shadow: none; filter: none; scale: none; transform: none; transition: none; background: transparent; cursor: default; }
  .editor-backdrop:hover, .editor-backdrop:active { background: transparent; scale: none; transform: none; filter: none; }
  .editor-composer { position: absolute; inset: auto 16px 16px; z-index: 3; }
  output { position: absolute; top: -1000px; }
  .fixture-settle { position: absolute; top: 8px; right: 8px; z-index: 10; }
</style>
