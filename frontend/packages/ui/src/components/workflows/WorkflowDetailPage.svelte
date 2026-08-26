<!--
  WorkflowDetailPage.svelte
  Stable category-identity header and shared Template/Runs tab boundary.
  The owning route retains Workflow selection, persistence, and navigation.
  Dirty graph actions stay contextual below the header instead of remounting it.
-->

<script lang="ts">
  import { SettingsTabs } from '../settings/elements';
  import WorkspaceReportIssueButton from '../workspace/WorkspaceReportIssueButton.svelte';
  import { getCategoryGradientColors, getLucideIcon, getValidIconName } from '../../utils/categoryUtils';

  let {
    title,
    description,
    category,
    icon,
    createdAt,
    nextRunAt,
    enabled,
    canEnable,
    lastStartedRunId = null,
    activeTab,
    dirty,
    saving,
    onTabChange,
    onToggleEnabled,
    onSaveWorkflow,
    onUndoWorkflow,
    onCreateWorkflow,
    onRunWorkflow,
    onDeleteWorkflow,
    onOpenHome,
    onOpenRuns,
    runsHref,
  }: {
    title: string;
    description: string;
    category: string;
    icon: string;
    createdAt?: number | null;
    nextRunAt?: number | null;
    enabled: boolean;
    canEnable: boolean;
    lastStartedRunId?: string | null;
    activeTab: 'template' | 'runs';
    dirty: boolean;
    saving: boolean;
    onTabChange: (tab: 'template' | 'runs') => void;
    onToggleEnabled: () => void | Promise<void>;
    onSaveWorkflow: () => void | Promise<void>;
    onUndoWorkflow: () => void;
    onCreateWorkflow: () => void | Promise<void>;
    onRunWorkflow: () => void | Promise<void>;
    onDeleteWorkflow: () => void | Promise<void>;
    onOpenHome: () => void;
    onOpenRuns: () => void;
    runsHref: string;
  } = $props();

  const BackIcon = getLucideIcon('arrow-left');
  const NewIcon = getLucideIcon('plus');
  const ShareIcon = getLucideIcon('share-2');
  const PlayIcon = getLucideIcon('play');
  const TrashIcon = getLucideIcon('trash-2');
  const HistoryIcon = getLucideIcon('history');
  const WorkflowIcon = $derived(getLucideIcon(getValidIconName(icon, category)));
  const tabs = [
    { id: 'template', icon: 'workflow', label: 'Workflow template' },
    { id: 'runs', icon: 'history', label: 'Workflow runs' },
  ];
  const gradient = $derived(getCategoryGradientColors(category) ?? getCategoryGradientColors('general_knowledge'));
  const headerStyle = $derived(`--workflow-gradient-start: ${gradient?.start ?? '#DE1E66'}; --workflow-gradient-end: ${gradient?.end ?? '#FF763B'};`);
  const metadataLabel = $derived(nextRunAt ? `Next run ${relativeTime(nextRunAt)}` : createdAt ? `Created ${relativeTime(createdAt)}` : 'Manual workflow');

  function relativeTime(timestampSeconds: number): string {
    const diffSeconds = Math.round(timestampSeconds - Date.now() / 1000);
    const absoluteSeconds = Math.abs(diffSeconds);
    if (absoluteSeconds < 60) return diffSeconds >= 0 ? 'soon' : 'just now';
    const minutes = Math.round(absoluteSeconds / 60);
    if (minutes < 60) return diffSeconds >= 0 ? `in ${minutes} min` : `${minutes} min ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return diffSeconds >= 0 ? `in ${hours} hr` : `${hours} hr ago`;
    const days = Math.round(hours / 24);
    return diffSeconds >= 0 ? `in ${days} day${days === 1 ? '' : 's'}` : `${days} day${days === 1 ? '' : 's'} ago`;
  }

  function changeTab(tabId: string): void {
    if (tabId === 'template' || tabId === 'runs') onTabChange(tabId);
  }

  function focusSharePanel(): void {
    document.querySelector<HTMLElement>('[data-testid="workflow-template-share"]')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
</script>

<section
  class="workflow-detail-header"
  data-testid="workspace-detail-header"
  data-header-system="workflow-detail"
  data-category={category}
  data-icon={getValidIconName(icon, category)}
  style={headerStyle}
>
  <div class="header-orbs" aria-hidden="true"><span></span><span></span><span></span></div>
  <div class="header-actions" data-testid="workflow-detail-actions" aria-label="Workflow actions">
    <button type="button" class="icon-action" data-testid="workflow-detail-back" aria-label="Back to workflows" onclick={onOpenHome}><BackIcon size={20} /></button>
    <button type="button" class="new-action" data-testid="create-blank-workflow" disabled={saving} onclick={() => void onCreateWorkflow()}><NewIcon size={18} />New workflow</button>
    <button type="button" class="icon-action" data-testid="workflow-share" aria-label="Share Workflow" onclick={focusSharePanel}><ShareIcon size={19} /></button>
    <WorkspaceReportIssueButton />
  </div>

  <div class="context-actions">
    <a class="icon-action" data-testid="workflow-run-history" href={runsHref} aria-label="Workflow run history" onclick={(event) => { event.preventDefault(); onOpenRuns(); }}><HistoryIcon size={19} /></a>
    <button type="button" class="icon-action" data-testid="run-workflow" aria-label="Run Workflow now" disabled={saving} onclick={() => void onRunWorkflow()}><PlayIcon size={19} /></button>
    <button type="button" class="icon-action danger" data-testid="delete-workflow" aria-label="Delete Workflow" disabled={saving} onclick={() => void onDeleteWorkflow()}><TrashIcon size={19} /></button>
  </div>

  <div class="header-content">
    <span class="workflow-kicker">Workflow</span>
    <div class="identity-icon" data-testid="workflow-identity-icon" aria-hidden="true"><WorkflowIcon size={42} /></div>
    <h1 data-testid="workspace-detail-title">{title}</h1>
    <button type="button" class="toggle-pill" data-testid="toggle-workflow" disabled={saving || (!enabled && !canEnable)} onclick={() => void onToggleEnabled()}>
      <span>{enabled ? 'Workflow on' : 'Workflow off'}</span><i class:enabled aria-hidden="true"></i>
    </button>
    <span class="state-marker" data-testid="workflow-enabled-state" data-enabled={enabled ? 'true' : 'false'}>{enabled ? 'Enabled' : canEnable ? 'Ready to enable' : 'Definition incomplete'}</span>
    {#if lastStartedRunId}<span class="state-marker" data-testid="workflow-run-started" data-run-id={lastStartedRunId}>Run started</span>{/if}
    <p class="description" data-testid="workspace-detail-description">{description}</p>
    <span class="metadata" data-testid="workflow-detail-metadata">{metadataLabel}</span>
  </div>
</section>

<div class="workflow-tabs" data-testid="workflow-view-tabs">
  <SettingsTabs {tabs} activeTab={activeTab} maxVisibleTabs={2} testIdPrefix="workflow-tab" onChange={changeTab} />
</div>

{#if dirty}
  <section class="dirty-panel" data-testid="workflow-dirty-panel" aria-live="polite">
    <span>Unsaved changes</span>
    <div>
      <button type="button" class="undo" data-testid="undo-workflow" disabled={saving} onclick={onUndoWorkflow}>Undo</button>
      <button type="button" class="save" data-testid="save-workflow" disabled={saving} aria-busy={saving} onclick={() => void onSaveWorkflow()}>Save</button>
    </div>
  </section>
{/if}

<style>
  .workflow-detail-header { position: relative; min-height: 310px; overflow: hidden; border-radius: 14px; color: var(--color-grey-0); background: linear-gradient(135deg, var(--workflow-gradient-start), var(--workflow-gradient-end)); box-shadow: var(--shadow-xl); isolation: isolate; }
  .header-orbs, .header-orbs span { position: absolute; }
  .header-orbs { inset: 0; opacity: 0.45; }
  .header-orbs span { width: 45%; aspect-ratio: 1; border-radius: 50%; background: radial-gradient(circle, color-mix(in srgb, var(--color-grey-0) 30%, transparent), transparent 70%); filter: blur(24px); }
  .header-orbs span:nth-child(1) { inset: -35% auto auto -10%; }
  .header-orbs span:nth-child(2) { inset: auto -5% -50% auto; }
  .header-orbs span:nth-child(3) { inset: 15% auto auto 40%; opacity: 0.55; }
  .header-actions, .context-actions { position: absolute; z-index: 3; top: var(--spacing-5); display: flex; align-items: center; gap: var(--spacing-3); }
  .header-actions { inset-inline-start: var(--spacing-5); }
  .context-actions { inset-inline-end: var(--spacing-5); }
  .header-actions button, .context-actions button, .context-actions a { min-width: 42px; min-height: 42px; border: 0; color: var(--color-grey-0); cursor: pointer; text-decoration: none; }
  .icon-action { display: inline-grid; place-items: center; border-radius: var(--radius-full); background: color-mix(in srgb, var(--color-grey-0) 18%, transparent); }
  .new-action { display: inline-flex; align-items: center; gap: var(--spacing-3); padding-inline: var(--spacing-6); border-radius: var(--radius-full); background: var(--color-button-primary); font: inherit; font-weight: 800; }
  .icon-action.danger { background: color-mix(in srgb, var(--color-danger) 78%, transparent); }
  button:disabled { opacity: 0.58; cursor: wait; }
  .header-content { position: relative; z-index: 2; display: grid; min-height: inherit; place-items: center; align-content: center; gap: var(--spacing-4); padding: var(--spacing-20) var(--spacing-16) var(--spacing-12); text-align: center; }
  .workflow-kicker { font-size: var(--font-size-xs); font-weight: 800; letter-spacing: 0.1em; text-transform: uppercase; opacity: 0.78; }
  .identity-icon { display: grid; width: 64px; height: 64px; place-items: center; border-radius: var(--radius-10); background: color-mix(in srgb, var(--color-grey-0) 18%, transparent); }
  h1, .description { margin: 0; }
  h1 { max-width: 780px; overflow-wrap: anywhere; font-size: clamp(1.8rem, 3.5vw, 3rem); line-height: 1.05; }
  .description { max-width: 660px; font-size: clamp(0.95rem, 1.8vw, 1.2rem); opacity: 0.88; }
  .metadata { font-size: var(--font-size-small); font-weight: 700; opacity: 0.8; }
  .state-marker { font-size: var(--font-size-xs); font-weight: 800; opacity: 0.85; }
  .toggle-pill { display: inline-flex; align-items: center; gap: var(--spacing-4); border: 0; border-radius: var(--radius-full); padding: var(--spacing-3) var(--spacing-5); color: var(--color-font-primary); background: var(--color-grey-0); font: inherit; font-weight: 800; cursor: pointer; }
  .toggle-pill i { position: relative; width: 34px; height: 20px; border-radius: var(--radius-full); background: var(--color-grey-30); }
  .toggle-pill i::after { content: ''; position: absolute; top: 3px; left: 3px; width: 14px; height: 14px; border-radius: 50%; background: var(--color-grey-0); transition: transform 0.2s ease; }
  .toggle-pill i.enabled { background: var(--color-button-primary); }
  .toggle-pill i.enabled::after { transform: translateX(14px); }
  .workflow-tabs { position: relative; z-index: 4; width: 150px; margin: -22px auto var(--spacing-6); }
  .dirty-panel { display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-5); margin: 0 var(--spacing-8) var(--spacing-5); padding: var(--spacing-4) var(--spacing-5); border-radius: var(--radius-8); color: var(--color-font-primary); background: var(--color-grey-10); box-shadow: var(--shadow-sm); font-weight: 700; }
  .dirty-panel div { display: flex; gap: var(--spacing-3); }
  .dirty-panel button { border: 0; border-radius: var(--radius-full); padding: var(--spacing-3) var(--spacing-6); font: inherit; font-weight: 800; cursor: pointer; }
  .dirty-panel .undo { color: var(--color-font-primary); background: var(--color-grey-20); }
  .dirty-panel .save { color: var(--color-font-button); background: var(--color-button-primary); }
  @media (max-width: 720px) { .workflow-detail-header { min-height: 330px; } .header-actions { max-width: calc(100% - 100px); flex-wrap: wrap; } .new-action { padding-inline: var(--spacing-4); } .header-content { padding: 108px var(--spacing-6) var(--spacing-10); } .context-actions { flex-direction: column; } .dirty-panel { align-items: flex-start; flex-direction: column; margin-inline: var(--spacing-4); } .dirty-panel div { width: 100%; } .dirty-panel button { flex: 1; } }
  @media (prefers-reduced-motion: reduce) { .toggle-pill i::after { transition: none; } }
</style>
