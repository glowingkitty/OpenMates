<!--
  Public Workflow template import route.
  Reads the template key only from #key, fetches opaque ciphertext, and decrypts
  and validates it locally before sending the portable import payload.
  The server never receives the fragment key or template plaintext on retrieval.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import {
    Header,
    WorkflowTemplateShare,
    completeWorkflowTemplateBinding,
    importWorkflowTemplate,
    initialize,
    loadSharedWorkflowTemplate,
    workflowWorkspaceStore,
    type ImportedWorkflowTemplate,
    type WorkflowTemplateBindingRequirement,
    type WorkflowTemplatePayload,
  } from '@repo/ui';

  let template = $state<WorkflowTemplatePayload | null>(null);
  let importedWorkflow = $state<ImportedWorkflowTemplate | null>(null);
  let error = $state<string | null>(null);
  let loading = $state(true);
  let templateId = $derived(page.params.templateId);

  onMount(() => {
    void loadTemplate();
  });

  function templateKeyFromFragment(): string | null {
    const params = new URLSearchParams(window.location.hash.slice(1));
    return params.get('key');
  }

  async function loadTemplate(): Promise<void> {
    loading = true;
    error = null;
    try {
      const templateKey = templateKeyFromFragment();
      if (!templateKey) throw new Error('This template link is missing its decryption key.');
      template = await loadSharedWorkflowTemplate(templateId, templateKey);
      await initialize();
    } catch (loadError) {
      error = loadError instanceof Error ? loadError.message : 'Could not open this workflow template.';
    } finally {
      loading = false;
    }
  }

  async function importTemplate(): Promise<ImportedWorkflowTemplate | null> {
    if (!template) return null;
    importedWorkflow = await importWorkflowTemplate(template);
    workflowWorkspaceStore.upsertWorkflow(importedWorkflow);
    return importedWorkflow;
  }

  async function completeBinding(requirement: WorkflowTemplateBindingRequirement): Promise<void> {
    if (!importedWorkflow) throw new Error('Import the workflow before completing its bindings.');
    await completeWorkflowTemplateBinding(importedWorkflow.id, requirement);
  }

  async function enableImportedWorkflow(): Promise<void> {
    if (!importedWorkflow) throw new Error('Import the workflow before enabling it.');
    const enabledWorkflow = await workflowWorkspaceStore.setWorkflowEnabled(importedWorkflow.id, true);
    workflowWorkspaceStore.upsertWorkflow(enabledWorkflow);
    await goto(`/workflows/${encodeURIComponent(importedWorkflow.id)}`);
  }
</script>

<Header context="webapp" />
<main class="workflow-template-route" data-testid="workflow-template-share-page">
  {#if loading}
    <p data-testid="workflow-template-loading">Decrypting workflow template...</p>
  {:else if error}
    <section class="error" data-testid="workflow-template-load-error">
      <h1>Workflow template unavailable</h1>
      <p>{error}</p>
    </section>
  {:else if template}
    <WorkflowTemplateShare {template} {importedWorkflow} onImport={importTemplate} onCompleteBinding={completeBinding} onEnable={enableImportedWorkflow} />
  {/if}
</main>

<style>
  .workflow-template-route { width: min(680px, calc(100% - 32px)); margin: 112px auto 48px; }
  .error { display: grid; gap: var(--spacing-4); padding: var(--spacing-8); border: 1px solid var(--color-grey-30); border-radius: var(--radius-8); background: var(--color-grey-0); }
  h1, p { margin: 0; color: var(--color-font-primary); }
  p { color: var(--color-font-secondary); }
</style>
