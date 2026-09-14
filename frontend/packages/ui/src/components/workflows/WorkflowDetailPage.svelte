<!-- Compact category identity and Workflow/Runs boundary. Each node saves independently. -->
<script lang="ts">
  import { text } from '../../i18n/translations';
  import AppIcon from '../Icon.svelte';
  import HeaderActionMenu from '../HeaderActionMenu.svelte';
  import { headerOverlayControls } from '../../actions/headerOverlayControls';
  import { tooltip } from '../../actions/tooltip';
  import WorkspaceReportIssueButton from '../workspace/WorkspaceReportIssueButton.svelte';
  import { getCategoryGradientColors, getLucideIcon, getValidIconName } from '../../utils/categoryUtils';
  let { title, description, category, icon, createdAt, nextRunAt, enabled, canEnable, canRun, lastStartedRunId = null, activeTab, saving, onTabChange, onToggleEnabled, onRunWorkflow, onDeleteWorkflow, onOpenHome, onUpdateIdentity }: {
    title: string; description: string; category: string; icon: string; createdAt?: number | null; nextRunAt?: number | null;
    enabled: boolean; canEnable: boolean; canRun: boolean; lastStartedRunId?: string | null; activeTab: 'template' | 'runs'; saving: boolean;
    onTabChange: (tab: 'template' | 'runs') => void; onToggleEnabled: () => void | Promise<void>; onRunWorkflow: () => void | Promise<void>; onDeleteWorkflow: () => void | Promise<void>; onOpenHome: () => void; onOpenRuns: () => void; runsHref: string;
    onUpdateIdentity: (title: string, description: string) => Promise<void>;
  } = $props();
  let editing = $state(false); let draftTitle = $state(''); let draftDescription = $state('');
  const tr = (key: string) => $text(`workflows.builder.${key}`);
  const Identity = $derived(getLucideIcon(getValidIconName(icon, category)));
  const gradient = $derived(getCategoryGradientColors(category) ?? getCategoryGradientColors('general_knowledge'));
  const headerStyle = $derived(`--workflow-gradient-start:${gradient?.start};--workflow-gradient-end:${gradient?.end}`);
  function metadata(): string {
    if (enabled && nextRunAt && nextRunAt > Date.now() / 1000) return `${tr('next_run')} ${new Intl.DateTimeFormat(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' }).format(new Date(nextRunAt * 1000))}`;
    if (!createdAt) return '';
    const minutes = Math.round((createdAt * 1000 - Date.now()) / 60000);
    return `${tr('created')} ${new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' }).format(Math.abs(minutes) < 60 ? minutes : Math.round(minutes / 1440), Math.abs(minutes) < 60 ? 'minute' : 'day')}`;
  }
  function editIdentity(): void { draftTitle = title; draftDescription = description; editing = true; }
  function openShare(): void { const panel = document.querySelector<HTMLDetailsElement>('[data-testid="workflow-more-options"]'); if (panel) panel.open = true; document.querySelector<HTMLElement>('[data-testid="workflow-template-share"]')?.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
</script>

<section class="workflow-detail-header" data-testid="workspace-detail-header" data-header-system="workflow-detail" data-category={category} data-icon={getValidIconName(icon, category)} style={headerStyle}>
  <div class="header-toolbar" data-testid="workflow-detail-actions" use:headerOverlayControls>
    <HeaderActionMenu resetKey={title} hasShare actionCount={2}>
      {#snippet report()}<WorkspaceReportIssueButton toolbar/>{/snippet}
      {#snippet share()}<div class="new-chat-button-wrapper"><button type="button" class="header-action" data-testid="workflow-share" aria-label={tr('share')} onclick={openShare} use:tooltip><span class="clickable-icon icon_share top-button" aria-hidden="true"></span><span class="action-label">{tr('share')}</span></button></div>{/snippet}
      {#snippet actions()}
        <div class="new-chat-button-wrapper"><button type="button" class="header-action" data-testid="run-workflow" aria-label={tr('run_now')} disabled={saving || !canRun} onclick={() => void onRunWorkflow()} use:tooltip><AppIcon name="play" size="25px" color="currentColor" noMargin ariaHidden/><span class="action-label">{tr('run_now')}</span></button></div>
        <div class="new-chat-button-wrapper"><button type="button" class="header-action" data-testid="delete-workflow" aria-label={tr('delete_workflow')} disabled={saving} onclick={() => void onDeleteWorkflow()} use:tooltip><span class="clickable-icon icon_delete top-button" aria-hidden="true"></span><span class="action-label">{tr('delete_workflow')}</span></button></div>
      {/snippet}
      {#snippet close()}<div class="new-chat-button-wrapper"><button type="button" class="header-action" data-testid="workflow-detail-back" aria-label={tr('back')} onclick={onOpenHome} use:tooltip><span class="clickable-icon icon_close top-button" aria-hidden="true"></span><span class="action-label">{tr('back')}</span></button></div>{/snippet}
    </HeaderActionMenu>
  </div>
  <span class="kicker">{tr('workflow')}</span>
  <div class="identity">
    <div data-testid="workflow-identity-icon" aria-hidden="true"><Identity size={38}/></div>
    {#if editing}
      <form onsubmit={async event => { event.preventDefault(); await onUpdateIdentity(draftTitle, draftDescription); editing = false; }}>
        <input aria-label={tr('workflow_name')} bind:value={draftTitle} required/>
        <input aria-label={tr('description')} bind:value={draftDescription}/>
        <button class="save" type="submit" disabled={saving}>{tr('save')}</button>
      </form>
    {:else}
      <button type="button" class="identity-edit" onclick={editIdentity}><h1 data-testid="workspace-detail-title">{title}</h1></button>
    {/if}
    <button type="button" class="toggle" role="switch" aria-checked={enabled} aria-label={tr('workflow_on')} data-testid="toggle-workflow" disabled={saving || (!enabled && !canEnable)} onclick={() => void onToggleEnabled()}>
      <AppIcon name="workflow" size="16px" color="currentColor" noMargin ariaHidden/><span data-testid="workflow-enabled-state" data-enabled={enabled ? 'true' : 'false'}>{tr(enabled ? 'workflow_on' : 'workflow_off')}</span><i class:enabled></i>
    </button>
    {#if !editing}<button type="button" class="identity-edit description-edit" onclick={editIdentity}><p data-testid="workspace-detail-description">{description || tr('add_description')}</p></button>{/if}
  </div>
  <span class="metadata" data-testid="workflow-detail-metadata">{metadata()}</span>
  {#if lastStartedRunId}<span class="run-started" data-testid="workflow-run-started" data-run-id={lastStartedRunId}>{tr('run_started')}</span>{/if}
</section>
<div class="workflow-tabs" data-testid="workflow-view-tabs" role="tablist" aria-label={tr('workflow')}><button type="button" role="tab" aria-selected={activeTab === 'template'} aria-label={tr('workflow')} class:active={activeTab === 'template'} data-testid="workflow-tab-template" onclick={() => onTabChange('template')}><AppIcon name="workflow" size="20px" color="currentColor" noMargin ariaHidden/></button><button type="button" role="tab" aria-selected={activeTab === 'runs'} aria-label={tr('run_history')} class:active={activeTab === 'runs'} data-testid="workflow-tab-runs" onclick={() => onTabChange('runs')}><AppIcon name="projectmanagement" size="20px" color="currentColor" noMargin ariaHidden/></button></div>

<style>
  .workflow-detail-header { position:relative; min-height:19rem; font-size:var(--font-size-p); box-sizing:border-box; border-radius:0 0 1rem 1rem; color:var(--color-font-button); background:linear-gradient(135deg,var(--workflow-gradient-start),var(--workflow-gradient-end)); display:flex; flex-direction:column; align-items:center; justify-content:center; padding:4.8rem 4rem 3.6rem; }
  .header-toolbar { position:absolute; top:15px; left:15px; right:15px; z-index:var(--z-index-raised-2); pointer-events:none; }
  .new-chat-button-wrapper { background-color:var(--color-grey-10); border-radius:40px; padding:var(--spacing-4); box-shadow:var(--shadow-md); display:flex; align-items:center; justify-content:center; cursor:pointer; pointer-events:auto; }
  .kicker { position:absolute; top:1.25rem; font-size:var(--font-size-small); font-weight:650; }
  .identity { display:grid; justify-items:center; gap:.6rem; width:100%; }
  .identity-edit { padding:0; background:transparent; border:0; color:inherit; font:inherit; cursor:pointer; text-align:center; max-width:100%; }
  h1 { margin:.15rem 0 0; font-size:var(--font-size-h2-mobile); line-height:1.3; overflow-wrap:anywhere; }
  .description-edit { max-width:26rem; } p { margin:.2rem 0 0; font-size:var(--font-size-p); line-height:1.4; opacity:.95; }
  .metadata { position:absolute; bottom:1rem; font-size:var(--font-size-small); opacity:.8; }
  .toggle { display:flex; align-items:center; gap:.4rem; margin:0; padding:.25rem .4rem .25rem .6rem; min-height:2rem; border:0; border-radius:2rem; font:inherit; font-size:var(--font-size-small); font-weight:650; background:var(--color-primary); color:var(--color-font-button); cursor:pointer; box-shadow:var(--shadow-sm); }
  .toggle i { position:relative; width:2rem; height:1.2rem; border-radius:1rem; background:color-mix(in srgb,var(--color-font-button) 35%,transparent); }
  .toggle i::after { content:''; position:absolute; left:.12rem; top:.12rem; width:.96rem; height:.96rem; border-radius:50%; background:var(--color-font-button); transition:transform .2s; box-shadow:0 1px 3px #0002; }
  .toggle i.enabled::after { transform:translateX(.8rem); }
  .workflow-tabs { display:flex; position:relative; box-sizing:border-box; width:7.5rem; height:2.5rem; margin:1.5rem auto -1.25rem; padding:.1rem; border-radius:2rem; box-shadow:var(--shadow-sm); background:var(--color-grey-0); z-index:3; }
  .workflow-tabs button { display:grid; place-items:center; flex:1; min-width:0; padding:0; border:0; border-radius:2rem; background:transparent; color:var(--color-font-secondary); cursor:pointer; }
  .workflow-tabs button.active { color:var(--color-font-button); background:var(--color-primary); }
  button:disabled { opacity:.5; cursor:default; }
  .identity form { display:grid; gap:.4rem; max-width:25rem; width:100%; }
  .identity input { box-sizing:border-box; width:100%; border:0; border-radius:.7rem; padding:.45rem .65rem; background:var(--color-grey-0); color:var(--color-font-primary); font:inherit; font-size:var(--font-size-p); }
  .save { justify-self:center; border:0; border-radius:.7rem; padding:.4rem 1.2rem; background:var(--color-button-primary); color:var(--color-font-button); cursor:pointer; }
  .run-started { position:absolute; bottom:2.1rem; font-size:var(--font-size-small); }
  button:focus-visible,input:focus-visible { outline:2px solid var(--color-button-primary); outline-offset:2px; }
  @media(max-width:730px) { .workflow-detail-header { min-height:19rem; padding:4.9rem 1.25rem 3.6rem; } .kicker { top:3.4rem; } h1 { font-size:var(--font-size-xl); } .description-edit { max-width:23rem; } .workflow-tabs { margin-top:1.25rem; } }
  @media(prefers-reduced-motion:reduce) { .toggle i::after { transition:none; } }
</style>
