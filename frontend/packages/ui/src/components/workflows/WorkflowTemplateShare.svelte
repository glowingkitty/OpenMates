<!--
  WorkflowTemplateShare.svelte
  Owns the small, explicit share/import states for portable Workflow templates.
  The encrypted projection is created locally; this UI never handles runtime
  credentials, connected-account IDs, or URL fragment keys outside copying links.
  Import binding completion must finish before the imported workflow is enabled.
-->

<script lang="ts">
  import type { WorkflowDetail } from '../../stores/workflowWorkspaceStore';
  import {
    createWorkflowTemplateShare,
    revokeWorkflowTemplateShare,
    unrevokeWorkflowTemplateShare,
    type ImportedWorkflowTemplate,
    type WorkflowTemplateBindingRequirement,
    type WorkflowTemplatePayload,
  } from '../../services/workflowTemplateService';
  import { workflowTemplateProjectionStore } from '../../stores/workflowTemplateProjectionStore';

  let {
    ownerWorkflow = null,
    template = null,
    importedWorkflow = null,
    disabled = false,
    onImport,
    onCompleteBinding,
    onEnable,
  }: {
    ownerWorkflow?: WorkflowDetail | null;
    template?: WorkflowTemplatePayload | null;
    importedWorkflow?: ImportedWorkflowTemplate | null;
    disabled?: boolean;
    onImport: () => Promise<ImportedWorkflowTemplate | null>;
    onCompleteBinding: (requirement: WorkflowTemplateBindingRequirement) => Promise<void>;
    onEnable: () => Promise<void>;
  } = $props();

  let shareUrl = $state<string | null>(null);
  let longUrl = $state<string | null>(null);
  let message = $state<string | null>(null);
  let error = $state<string | null>(null);
  let sharing = $state(false);
  let importing = $state(false);
  let completingBindingId = $state<string | null>(null);
  let enabling = $state(false);
  let completedBindingIds = $state<Set<string>>(new Set());
  let projection = $derived(ownerWorkflow ? $workflowTemplateProjectionStore[ownerWorkflow.id] ?? null : null);
  let revoked = $derived(projection?.revokedAt !== null && projection?.revokedAt !== undefined);

  async function createShare(): Promise<void> {
    if (!ownerWorkflow || disabled || sharing) return;
    sharing = true;
    error = null;
    message = null;
    try {
      const result = await createWorkflowTemplateShare(ownerWorkflow);
      shareUrl = result.shortUrl;
      longUrl = result.longUrl;
      message = 'Short template link created.';
    } catch (shareError) {
      error = shareError instanceof Error ? shareError.message : 'Could not create a template link.';
    } finally {
      sharing = false;
    }
  }

  async function copyLink(url: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(url);
      message = 'Link copied.';
    } catch (copyError) {
      error = copyError instanceof Error ? copyError.message : 'Could not copy the link.';
    }
  }

  async function toggleRevocation(): Promise<void> {
    if (!ownerWorkflow || sharing) return;
    sharing = true;
    error = null;
    try {
      if (revoked) {
        await unrevokeWorkflowTemplateShare(ownerWorkflow.id);
        message = 'Template access restored. Create a new short link to share it again.';
      } else {
        await revokeWorkflowTemplateShare(ownerWorkflow.id);
        shareUrl = null;
        message = 'Template access revoked.';
      }
    } catch (revokeError) {
      error = revokeError instanceof Error ? revokeError.message : 'Could not update template access.';
    } finally {
      sharing = false;
    }
  }

  async function importTemplate(): Promise<void> {
    if (importing || importedWorkflow) return;
    importing = true;
    error = null;
    try {
      const result = await onImport();
      if (!result) throw new Error('Could not import this workflow template.');
      message = 'Workflow imported disabled. Complete its binding requirements before enabling it.';
    } catch (importError) {
      error = importError instanceof Error ? importError.message : 'Could not import this workflow template.';
    } finally {
      importing = false;
    }
  }

  function bindingId(requirement: WorkflowTemplateBindingRequirement): string {
    return `${requirement.type}-${requirement.node_id}`;
  }

  async function completeBinding(requirement: WorkflowTemplateBindingRequirement): Promise<void> {
    const id = bindingId(requirement);
    if (!importedWorkflow || completingBindingId || completedBindingIds.has(id)) return;
    completingBindingId = id;
    error = null;
    try {
      await onCompleteBinding(requirement);
      completedBindingIds = new Set([...completedBindingIds, id]);
      message = 'Binding requirement completed.';
    } catch (bindingError) {
      error = bindingError instanceof Error ? bindingError.message : 'Could not complete this workflow binding requirement.';
    } finally {
      completingBindingId = null;
    }
  }

  async function enableImportedWorkflow(): Promise<void> {
    if (!importedWorkflow || enabling || !bindingsComplete) return;
    enabling = true;
    error = null;
    try {
      await onEnable();
      message = 'Binding requirements completed and workflow enabled.';
    } catch (enableError) {
      error = enableError instanceof Error ? enableError.message : 'Could not enable the imported workflow.';
    } finally {
      enabling = false;
    }
  }

  function bindingLabel(requirement: { type: string; app_id?: string; skill_id?: string }): string {
    if (requirement.type === 'schedule') return 'Choose your schedule and timezone';
    if (requirement.type === 'app_skill') return `Connect ${requirement.app_id ?? 'the required'} ${requirement.skill_id ?? 'app skill'}`;
    if (requirement.type === 'notification_preferences') return 'Choose notification preferences';
    return `Complete ${requirement.type}`;
  }

  let bindingsComplete = $derived(importedWorkflow !== null && importedWorkflow.binding_requirements.every((requirement) => completedBindingIds.has(bindingId(requirement))));
</script>

{#if ownerWorkflow}
  <section class="template-share-panel" data-testid="workflow-template-share">
    <div>
      <h2>Share as template</h2>
      <p>Recipients import a disabled copy and reconnect their own accounts, schedules, permissions, and notification preferences.</p>
    </div>
    <div class="actions">
      <button type="button" data-testid="workflow-template-create-share" disabled={disabled || sharing} onclick={() => void createShare()}>
        {sharing ? 'Preparing...' : 'Create template link'}
      </button>
      {#if shareUrl}
        <button type="button" class="secondary" data-testid="workflow-template-copy-short-link" onclick={() => void copyLink(shareUrl)}>Copy short link</button>
        <button type="button" class="secondary" data-testid="workflow-template-copy-long-link" onclick={() => longUrl && void copyLink(longUrl)}>Copy offline link</button>
      {/if}
      {#if projection}
        <button type="button" class="secondary" data-testid="workflow-template-toggle-revocation" disabled={sharing} onclick={() => void toggleRevocation()}>
          {revoked ? 'Restore template access' : 'Revoke template access'}
        </button>
      {/if}
    </div>
  </section>
{:else if template}
  <section class="template-share-panel" data-testid="workflow-template-preview">
    <div>
      <p class="eyebrow">Workflow template</p>
      <h1 data-testid="workflow-template-title">{template.title}</h1>
      {#if template.description}<p>{template.description}</p>{/if}
      <p>{template.node_templates.length + 1} steps. Imported workflows start disabled.</p>
    </div>
    {#if !importedWorkflow}
      <button type="button" data-testid="workflow-template-import" disabled={importing} onclick={() => void importTemplate()}>{importing ? 'Importing...' : 'Import template'}</button>
    {:else}
      <div class="bindings" data-testid="workflow-template-bindings">
        <h2>Complete before enabling</h2>
        <p>This imported workflow remains disabled until these recipient-owned bindings are confirmed.</p>
        <ul>
          {#each importedWorkflow.binding_requirements as requirement (`${requirement.type}-${requirement.node_id}`)}
            {@const requirementId = bindingId(requirement)}
            <li data-testid="workflow-template-binding-requirement">
              <span>{bindingLabel(requirement)}</span>
              {#if completedBindingIds.has(requirementId)}
                <strong data-testid="workflow-template-binding-complete">Completed</strong>
              {:else}
                <button
                  type="button"
                  class="secondary"
                  data-testid="workflow-template-complete-binding"
                  disabled={completingBindingId !== null}
                  onclick={() => void completeBinding(requirement)}
                >
                  {completingBindingId === requirementId ? 'Completing...' : 'Mark complete'}
                </button>
              {/if}
            </li>
          {/each}
        </ul>
        <button type="button" data-testid="workflow-template-enable" disabled={enabling || !bindingsComplete} onclick={() => void enableImportedWorkflow()}>
          {enabling ? 'Enabling...' : 'Enable workflow'}
        </button>
      </div>
    {/if}
  </section>
{/if}

{#if message}<p class="template-message" data-testid="workflow-template-message">{message}</p>{/if}
{#if error}<p class="template-error" data-testid="workflow-template-error">{error}</p>{/if}

<style>
  .template-share-panel { display: grid; gap: var(--spacing-5); padding: var(--spacing-8); border: 1px solid var(--color-grey-30); border-radius: var(--radius-8); background: var(--color-grey-0); color: var(--color-font-primary); }
  h1, h2, p { margin: 0; }
  h1, h2 { font-size: 1.1rem; }
  p { color: var(--color-font-secondary); line-height: 1.45; }
  .eyebrow { font-size: var(--font-size-small); font-weight: 800; text-transform: uppercase; }
  .actions { display: flex; flex-wrap: wrap; gap: var(--spacing-4); }
  button { border: 0; border-radius: var(--radius-8); padding: var(--spacing-4) var(--spacing-6); background: var(--color-button-primary); color: var(--color-font-button); font: inherit; font-weight: 800; cursor: pointer; }
  button.secondary { background: var(--color-grey-20); color: var(--color-font-primary); }
  button:disabled { cursor: wait; opacity: 0.6; }
  .bindings { display: grid; gap: var(--spacing-4); }
  ul { display: grid; gap: var(--spacing-3); margin: 0; padding-inline-start: var(--spacing-8); }
  li { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--spacing-3); }
  li strong { color: var(--color-success, #067647); font-size: var(--font-size-small); }
  .template-message, .template-error { margin: var(--spacing-4) 0; }
  .template-error { color: var(--color-error, #b42318); }
</style>
