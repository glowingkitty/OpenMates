<!--
  WorkflowDetailPage.svelte
  Shared Workflow detail header composition for Automation Vault records.
  The owning route supplies the loaded workflow and approved mutation callbacks.
-->

<script lang="ts">
  import WorkspaceDetailHeader from '../workspace/WorkspaceDetailHeader.svelte';
  import WorkspaceReportIssueButton from '../workspace/WorkspaceReportIssueButton.svelte';

  let { title, description, createdAt, onSaveTitle, onSaveDescription }: {
    title: string;
    description: string;
    createdAt?: number | null;
    onSaveTitle: (title: string) => void | Promise<void>;
    onSaveDescription: (description: string) => void | Promise<void>;
  } = $props();
</script>

<div class="workflow-detail-header">
  <div class="report-action"><WorkspaceReportIssueButton /></div>
  <WorkspaceDetailHeader {title} {description} category="productivity" icon="workflow" writable={true} {onSaveTitle} {onSaveDescription} metadata={createdAt ? new Date(createdAt * 1000).toLocaleDateString() : ''} />
</div>

<style>
  .workflow-detail-header { position: relative; }
  .report-action { position: absolute; z-index: var(--z-index-raised-3); top: var(--spacing-5); right: var(--spacing-5); }
</style>
