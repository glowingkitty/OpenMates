<!--
  frontend/packages/ui/src/components/embeds/workflows/WorkflowEmbedFullscreen.svelte
  Child fullscreen for workflow result embeds.
  It attempts live workflow store loading for editable title/description and
  uses the decoded snapshot in preview/example contexts.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import WorkspaceDetailHeader from '../../workspace/WorkspaceDetailHeader.svelte';
  import { workflowDetailAdapter } from '../../workspace/detailMetadataAdapters';
  import type { WorkflowDetail } from '../../../stores/workflowWorkspaceStore';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { normalizeWorkflowResult, workflowStatusLabel } from './workflowEmbedData';

  interface Props {
    data: EmbedFullscreenRawData;
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }

  let { data, embedId, onClose, hasPreviousEmbed = false, hasNextEmbed = false, onNavigatePrevious, onNavigateNext }: Props = $props();

  let snapshot = $derived(normalizeWorkflowResult(embedId || 'workflow', data.decodedContent ?? {}));
  let workflow = $state<WorkflowDetail | null>(null);
  let liveLoadFailed = $state(false);
  let workflowId = $derived(snapshot.workflow_id || snapshot.embed_id);
  let title = $derived(workflow?.title || snapshot.title || 'Untitled workflow');
  let description = $derived(workflow?.description || snapshot.description || '');
  let metadata = $derived(workflow?.trigger_summary || snapshot.trigger_summary || workflowStatusLabel(workflow?.status || snapshot.status, workflow?.enabled ?? snapshot.enabled));

  onMount(() => {
    if (!workflowId || workflowId.startsWith('legacy-')) return;
    void workflowDetailAdapter.load(workflowId).then((loaded) => {
      workflow = loaded;
    }).catch((error) => {
      liveLoadFailed = true;
      console.debug('[WorkflowEmbedFullscreen] Live workflow load unavailable, using snapshot:', error);
    });
  });

  async function saveTitle(value: string): Promise<void> {
    if (!workflow) throw new Error('Workflow is not available for editing.');
    workflow = await workflowDetailAdapter.saveTitle(workflow, value);
  }

  async function saveDescription(value: string): Promise<void> {
    if (!workflow) throw new Error('Workflow is not available for editing.');
    workflow = await workflowDetailAdapter.saveDescription(workflow, value);
  }
</script>

<UnifiedEmbedFullscreen
  testId="workflow-embed-fullscreen"
  appId="workflows"
  skillId="workflow"
  skillIconName="workflow"
  embedHeaderTitle={title}
  embedHeaderSubtitle={metadata}
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
>
  {#snippet content()}
    <div class="workflow-detail-shell" data-testid="workflow-embed-fullscreen-content">
      <WorkspaceDetailHeader
        {title}
        {description}
        {metadata}
        category="productivity"
        icon="workflow"
        writable={!!workflow}
        embedded={true}
        alignment="start"
        titleTestId="workflow-embed-title"
        descriptionTestId="workflow-embed-description"
        onSaveTitle={saveTitle}
        onSaveDescription={saveDescription}
      />
      {#if liveLoadFailed}
        <p class="snapshot-note">Snapshot preview. Open the Workflows workspace to edit this workflow.</p>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .workflow-detail-shell {
    width: min(860px, calc(100% - 32px));
    margin: 0 auto;
    padding: var(--spacing-12) 0 120px;
  }

  .snapshot-note {
    margin: var(--spacing-8) 0 0;
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }
</style>
