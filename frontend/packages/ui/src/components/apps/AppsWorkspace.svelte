<script lang="ts">
  import { onMount, tick, untrack } from 'svelte';
  import type { AllAppsFilterType } from '../../stores/allAppsFilterStore';
  import { text } from '../../i18n/translations';
  import { appSkillsStore, featureAvailabilityStore, initializeFeatureAvailability } from '../../stores/appSkillsStore';
  import { authStore } from '../../stores/authStore';
  import { skillStoreExampleFullscreenStore, closeSkillStoreExampleFullscreen } from '../../stores/skillStoreExampleFullscreenStore';
  import { userProfile } from '../../stores/userProfile';
  import { activeTeamContext } from '../../stores/teamStore';
  import { anonymousFreeUsageStatus, refreshAnonymousFreeUsageStatus } from '../../stores/serverStatusStore';
  import { getAppsSkillDetails, canRunGuestAppsSkill, executeAppsSkill } from '../../services/appsWorkspaceService';
  import { retainAppsResult, listAppsResults, promoteGuestAppsResults, startAppsHistoricalDiscovery, type AppsResultItem } from '../../services/appsWorkspaceResultsService';
  import { listAppsWorkflows, type AppsWorkflowLibraryItem } from '../../services/appsWorkflowLibraryService';
  import { readAppsWorkspaceRoute, buildAppsWorkspaceHash, resolveAppsSkillId, resolveAppsAppId, type AppsWorkspaceTab } from '../../utils/appsWorkspaceRoute';
  import type { AppsSkillDetails } from '../../types/appsWorkspace';
  import WorkspaceHomeShell from '../workspace/WorkspaceHomeShell.svelte';
  import SettingsAllApps from '../settings/SettingsAllApps.svelte';
  import AppDetailsWrapper from '../settings/AppDetailsWrapper.svelte';
  import SkillDetails from '../settings/SkillDetails.svelte';
  import SettingsTabs from '../settings/elements/SettingsTabs.svelte';
  import UnifiedEmbedFullscreen from '../embeds/UnifiedEmbedFullscreen.svelte';
  import GenericAppSkillEmbedPreview from '../embeds/app_skill/GenericAppSkillEmbedPreview.svelte';
  import AppsSkillForm from './AppsSkillForm.svelte';
  import AppsResultFullscreen from './AppsResultFullscreen.svelte';

  let { hash, onNavigate, onSignup, onSettings }: {
    hash: string;
    onNavigate: (hash: string) => void;
    onSignup: () => void;
    onSettings: (path: string) => void;
  } = $props();
  const tr = (key: string) => $text(`apps_workspace.${key}`);
  const route = $derived(readAppsWorkspaceRoute(hash));
  const catalogFilter = $derived.by((): AllAppsFilterType | undefined => {
    const value = new URLSearchParams(hash.split('&').slice(1).join('&')).get('filter');
    return ['skills', 'focus_modes', 'settings_memories'].includes(value ?? '') ? value as AllAppsFilterType : undefined;
  });
  const apps = $derived.by(() => { void $featureAvailabilityStore; return appSkillsStore.getState().apps; });
  const resolvedAppId = $derived(route?.appId ? resolveAppsAppId(route.appId, Object.keys(apps)) : null);
  const app = $derived(resolvedAppId ? apps[resolvedAppId] : undefined);
  const skillId = $derived(route?.skillId && app ? resolveAppsSkillId(route.skillId, app.skills.map(skill => skill.id)) : null);
  const skill = $derived(app?.skills.find(item => item.id === skillId));
  const accountKey = $derived($authStore.isAuthenticated ? `${$userProfile.user_id ?? ''}:${$activeTeamContext.teamId ?? 'personal'}` : 'guest');
  const teamId = $derived($authStore.isAuthenticated ? $activeTeamContext.teamId ?? undefined : undefined);
  const viewer = $derived(Boolean(teamId && $activeTeamContext.team?.role === 'viewer'));
  let metadata = $state<AppsSkillDetails | null>(null);
  let metadataLoading = $state(false);
  let metadataError = $state(false);
  let submitting = $state(false);
  let requestError = $state(false);
  let libraryError = $state(false);
  let libraryLoading = $state(false);
  let results = $state<AppsResultItem[]>([]);
  let workflows = $state<AppsWorkflowLibraryItem[]>([]);
  let offset = $state(0);
  let hasMore = $state(false);
  let libraryGeneration = 0;
  let recents = $state<string[]>([]);
  let formElement = $state<HTMLDivElement | undefined>();
  let highlight = $state(false);
  let highlightTimer: ReturnType<typeof setTimeout> | undefined;
  let mounted = false;
  const pageSize = 20;
  const guestEligibility = $derived(metadata ? canRunGuestAppsSkill(metadata, $anonymousFreeUsageStatus) : undefined);
  const title = $derived(skill?.name_translation_key ? $text(skill.name_translation_key) : app?.name_translation_key ? $text(app.name_translation_key) : tr('title'));
  const description = $derived(skill?.description_translation_key ? $text(skill.description_translation_key) : app?.description_translation_key ? $text(app.description_translation_key) : '');
  const appName = $derived(app?.name_translation_key ? $text(app.name_translation_key) : app?.name ?? '');
  const heroCategory = $derived(skillId ? $text('apps_workspace.skill_label', { values: { app: appName } }) : tr('app_label'));
  const heroStats = $derived(!skillId && app ? $text('apps_workspace.app_stats', { values: { skills: app.skills.length, focusModes: app.focus_modes?.length ?? 0 } }) : '');
  const heroProviders = $derived(skillId ? skill?.providers ?? [] : []);
  const heroAppIcon = $derived(app?.icon_image?.replace(/\.svg$/i, '') ?? '');
  const heroSkillIcon = $derived(skillId ? (metadata?.icon_image ?? skill?.icon_image ?? '').replace(/\.svg$/i, '') : '');
  const detailPath = $derived.by(() => {
    if (!app || !route) return '';
    const suffix = route.settingsPath?.replace(/^memory\//, 'settings_memories/');
    return `apps/${app.id}${skillId ? `/skill/${skillId}` : ''}${suffix ? `/${suffix}` : ''}`;
  });
  const homeItems = $derived.by(() => {
    const ids = [...recents, 'web', 'news', 'health', 'travel', 'weather', 'audio'];
    return [...new Set(ids)].filter(id => apps[id]).slice(0, 6).map(id => ({
      id, title: apps[id].name_translation_key ? $text(apps[id].name_translation_key) : apps[id].name,
      summary: apps[id].description_translation_key ? $text(apps[id].description_translation_key) : '', appId: id,
      icon: 'app', iconImage: apps[id].icon_image, category: 'productivity',
    }));
  });
  const tabs = $derived(skillId ? [
    { id: 'overview', icon: 'skill', label: tr('overview') },
    { id: 'embeds', icon: 'files', label: tr('embeds') },
    { id: 'workflows', icon: 'workflow', label: tr('workflows') },
  ] : [
    { id: 'overview', icon: 'app', label: tr('skills') },
    { id: 'focus_modes', icon: 'search', label: tr('focus_modes') },
    { id: 'settings_memories', icon: 'settings', label: tr('settings_memories') },
    { id: 'embeds', icon: 'files', label: tr('embeds') },
    { id: 'workflows', icon: 'workflow', label: tr('workflows') },
  ]);

  $effect(() => {
    const context = accountKey;
    try { recents = JSON.parse(localStorage.getItem(`apps-recents:${context}`) ?? '[]'); }
    catch { recents = []; }
  });
  $effect(() => {
    const appId = resolvedAppId; const selectedSkill = skillId;
    metadata = null; metadataError = false; requestError = false;
    if (!appId || !selectedSkill || route?.settingsPath) return;
    const controller = new AbortController();
    metadataLoading = true;
    void getAppsSkillDetails(appId, selectedSkill, controller.signal).then(value => {
      if (!controller.signal.aborted) metadata = value;
    }).catch(() => { if (!controller.signal.aborted) metadataError = true; })
      .finally(() => { if (!controller.signal.aborted) metadataLoading = false; });
    if (!$authStore.isAuthenticated) void refreshAnonymousFreeUsageStatus();
    return () => controller.abort();
  });
  $effect(() => {
    const appId = resolvedAppId; const tab = route?.tab; void accountKey;
    libraryGeneration++; results = []; workflows = []; offset = 0; hasMore = false; libraryError = false;
    if (appId && (tab === 'embeds' || tab === 'workflows')) untrack(() => void loadLibrary(0));
    if (appId && tab === 'embeds' && $authStore.isAuthenticated) {
      return untrack(() => startAppsHistoricalDiscovery(appId, teamId));
    }
  });
  onMount(() => {
    mounted = true;
    const refreshResults = (event: Event) => {
      const updated = (event as CustomEvent<{ teamId: string | null }>).detail;
      if (route?.tab === 'embeds' && updated?.teamId === (teamId ?? null)) void loadLibrary(offset);
    };
    window.addEventListener('appsResultUpdated', refreshResults);
    void initializeFeatureAvailability();
    if ($authStore.isAuthenticated) void promoteGuestAppsResults().catch(() => {});
    return () => { mounted = false; clearTimeout(highlightTimer); window.removeEventListener('appsResultUpdated', refreshResults); };
  });

  function navigateSettings(event: CustomEvent<{ settingsPath: string }>): void {
    const path = event.detail.settingsPath;
    if (path === 'apps' || path.startsWith('apps/')) onNavigate(buildAppsWorkspaceHash(path));
    else onSettings(path);
  }
  function remember(appId: string, context = accountKey): void {
    let previous: string[] = [];
    try { previous = JSON.parse(localStorage.getItem(`apps-recents:${context}`) ?? '[]'); } catch { /* first visit */ }
    const next = [appId, ...previous.filter(id => id !== appId)].slice(0, 20);
    try { localStorage.setItem(`apps-recents:${context}`, JSON.stringify(next)); } catch { /* optional recency */ }
    if (accountKey === context) recents = next;
  }
  function selectTab(tab: string): void { onNavigate(buildAppsWorkspaceHash(detailPath, tab as AppsWorkspaceTab)); }
  async function useSkill(): Promise<void> {
    if (route?.tab !== 'overview') { selectTab('overview'); await tick(); }
    formElement?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    formElement?.querySelector<HTMLElement>('input,textarea,select,button')?.focus({ preventScroll: true });
    highlight = true; clearTimeout(highlightTimer); highlightTimer = setTimeout(() => { highlight = false; }, 1400);
  }
  async function submit(input: Record<string, unknown>): Promise<void> {
    if (submitting || !metadata || viewer) return;
    const selected = metadata; const submittedTeamId = teamId; const guest = !$authStore.isAuthenticated;
    const submittedContext = accountKey; const requestId = crypto.randomUUID();
    let acceptedTaskId: string | undefined;
    submitting = true; requestError = false;
    try {
      await retainAppsResult({ appId: selected.app_id, skillId: selected.skill_id, input, response: { status: 'processing' }, teamId: submittedTeamId, guest, requestId });
      const response = await executeAppsSkill(selected.app_id, selected.skill_id, input, { guest, teamId: submittedTeamId, metadata: selected, onTaskSubmitted: async taskId => { acceptedTaskId = taskId; await retainAppsResult({ appId: selected.app_id, skillId: selected.skill_id, input, response: { status: 'processing', task_id: taskId }, teamId: submittedTeamId, guest, requestId }); } });
      const embedId = await retainAppsResult({ appId: selected.app_id, skillId: selected.skill_id, input, response, teamId: submittedTeamId, guest, requestId });
      remember(selected.app_id, submittedContext);
      if (mounted && accountKey === submittedContext && resolvedAppId === selected.app_id && skillId === selected.skill_id && route?.tab === 'overview') onNavigate(`${buildAppsWorkspaceHash(detailPath, 'embeds')}&embed-id=${encodeURIComponent(embedId)}`);
    } catch {
      await retainAppsResult({ appId: selected.app_id, skillId: selected.skill_id, input, response: acceptedTaskId ? { status: 'processing', task_id: acceptedTaskId } : { status: 'error' }, teamId: submittedTeamId, guest, requestId }).catch(() => {});
      if (accountKey === submittedContext) requestError = true;
    } finally { submitting = false; if (guest) void refreshAnonymousFreeUsageStatus(); }
  }
  async function loadLibrary(nextOffset: number): Promise<void> {
    if (!resolvedAppId || !route) return;
    const generation = ++libraryGeneration; const appId = resolvedAppId; const tab = route.tab;
    const selectedTeamId = teamId; const context = accountKey;
    results = []; workflows = []; libraryLoading = true; libraryError = false;
    try {
      if (tab === 'workflows' && !$authStore.isAuthenticated) { hasMore = false; offset = 0; return; }
      const page = tab === 'workflows' ? await listAppsWorkflows(appId, selectedTeamId, nextOffset, pageSize) : await listAppsResults(appId, selectedTeamId, nextOffset, pageSize);
      if (generation !== libraryGeneration || context !== accountKey) return;
      if (tab === 'workflows') workflows = page.items as AppsWorkflowLibraryItem[];
      else results = page.items as AppsResultItem[];
      hasMore = page.hasMore; offset = page.offset;
    } catch { if (generation === libraryGeneration) libraryError = true; }
    finally { if (generation === libraryGeneration) libraryLoading = false; }
  }
  function openResult(embedId: string): void { onNavigate(`${buildAppsWorkspaceHash(detailPath, 'embeds')}&embed-id=${encodeURIComponent(embedId)}`); }
  function closeResult(): void { onNavigate(buildAppsWorkspaceHash(detailPath, 'embeds')); }
  function openExample(example: string): void { window.open(`/#new-message=${encodeURIComponent(example)}`, '_blank', 'noopener,noreferrer'); }
  async function shareDetail(): Promise<void> {
    if (!detailPath) return;
    const url = new URL(window.location.href);
    url.hash = buildAppsWorkspaceHash(detailPath);
    if (navigator.share) {
      try { await navigator.share({ title, url: url.toString() }); return; }
      catch (error) { if ((error as DOMException).name === 'AbortError') return; }
    }
    await navigator.clipboard.writeText(url.toString());
  }
</script>

<div class="apps-workspace" data-testid="apps-workspace">
  <WorkspaceHomeShell surface="apps" eyebrow={$authStore.isAuthenticated && $userProfile.username ? $text('apps_workspace.home_greeting', { values: { name: $userProfile.username } }) : tr('title')} heading={tr('home_prompt')} subtitle={tr('description')} actionItems={homeItems} actionItemsTestId="apps-home-apps" itemTestId="apps-app-card" contentSlotVisible={route?.showAll ?? false} showReportIssue showAllLabel={tr('show_all')} onShowAll={() => onNavigate('#apps/all')} onSearchAll={() => onNavigate('#apps/all')} onActionItem={item => onNavigate(buildAppsWorkspaceHash(`apps/${item.id}`))} onStartInspiration={item => onNavigate(buildAppsWorkspaceHash(item.feature?.settings_path?.startsWith('apps') ? item.feature.settings_path : 'apps/web/search'))}>
    {#if route?.showAll}
      <button class="plain-action" onclick={() => onNavigate('#apps')}>{tr('back_to_recent')}</button>
      <SettingsAllApps initialFilter={catalogFilter} on:openSettings={navigateSettings} />
    {/if}
    <svelte:fragment slot="composer">
      {#if !route?.showAll}
        <button class="apps-quick-use-affordance" data-testid="apps-quick-use-affordance" type="button" onclick={() => onNavigate('#apps/all&filter=skills')}>{tr('quick_use_hint')}</button>
      {/if}
    </svelte:fragment>
  </WorkspaceHomeShell>

  {#if route?.appId}
    <div class="apps-detail-layer">
      {#key route.appId}
        <UnifiedEmbedFullscreen appId={resolvedAppId ?? route.appId} skillId={skillId ?? undefined} onClose={() => onNavigate(skillId || route?.settingsPath ? buildAppsWorkspaceHash(`apps/${route?.appId}`) : '#apps')} onShare={() => void shareDetail()} testId="apps-detail-fullscreen" closeTestId="apps-detail-close" embedHeaderPresentation="apps" embedHeaderEyebrow={heroCategory} embedHeaderFooter={heroStats} embedHeaderProviders={heroProviders} appIconName={heroAppIcon} skillIconName={heroSkillIcon} embedHeaderTitle={title} embedHeaderSubtitle={description}>
          {#snippet embedHeaderCta()}
            {#if skillId && !route?.settingsPath}
              <button class="hero-action" data-testid="apps-use-skill" onclick={useSkill}>{tr('use_skill')}</button>
            {/if}
          {/snippet}
          {#snippet content()}
            <div class="apps-detail-content">
              {#if app}
                <div class="apps-detail-card" data-testid="apps-detail-card">
                  <div class="apps-detail-tabs" data-testid="apps-detail-tabs"><SettingsTabs {tabs} maxVisibleTabs={skillId ? 4.3 : 5} activeTab={route?.tab ?? 'overview'} testIdPrefix="apps-tab" onChange={selectTab} /></div>
                <div role="tabpanel" tabindex="0" id={`tabpanel-${route?.tab ?? 'overview'}`} aria-label={tr(route?.tab ?? 'overview')}>
                  {#if route?.tab === 'embeds' || route?.tab === 'workflows'}
                    {#if libraryLoading}<p role="status">{$text('common.loading')}</p>
                    {:else if libraryError}<p role="alert">{tr('library_error')}</p><button class="plain-action" onclick={() => void loadLibrary(offset)}>{tr('retry')}</button>
                    {:else if route.tab === 'embeds'}
                      <div class="results-grid" data-testid="apps-results-list">
                        {#each results as result (result.embedId)}
                          <div data-testid={`apps-result-open-${result.embedId}`}>
                            <GenericAppSkillEmbedPreview id={result.embedId} appId={result.appId} skillId={result.skillId} status={result.status} onFullscreen={() => openResult(result.embedId)} />
                          </div>
                        {:else}<p>{tr('no_embeds')}</p>{/each}
                      </div>
                    {:else}
                      <div data-testid="apps-workflows-list">
                        {#each workflows as workflow (workflow.id)}<a class="workflow-row" href={`/#workflow-id=${encodeURIComponent(workflow.id)}`}>{workflow.title}</a>
                        {:else}<p>{tr('no_workflows')}</p>{/each}
                      </div>
                    {/if}
                    <div class="pagination">
                      <button class="plain-action" data-testid="apps-previous-page" disabled={offset === 0 || libraryLoading} onclick={() => void loadLibrary(Math.max(0, offset - pageSize))}>{tr('previous')}</button>
                      <button class="plain-action" data-testid="apps-next-page" disabled={!hasMore || libraryLoading} onclick={() => void loadLibrary(offset + pageSize)}>{tr('next')}</button>
                    </div>
                  {:else if route?.skillId && !skillId}<p role="alert">{tr('not_found')}</p>
                  {:else if skillId && !route?.settingsPath}
                    <div class="skill-form-area" class:highlight bind:this={formElement}>
                      {#if metadataLoading}<p role="status">{$text('common.loading')}</p>
                      {:else if metadataError}<p role="alert">{tr('metadata_error')}</p>
                      {:else if metadata}<AppsSkillForm {metadata} onSubmit={submit} {submitting} disabled={viewer} guest={!$authStore.isAuthenticated} {guestEligibility} {onSignup} />{/if}
                      {#if requestError}<p role="alert">{tr('request_error')}</p>{/if}
                      {#if viewer}<p>{tr('viewer_read_only')}</p>{/if}
                    </div>
                    <SkillDetails appId={app.id} {skillId} onOpenExample={openExample} on:openSettings={navigateSettings} />
                  {:else}
                    <AppDetailsWrapper presentation="apps" section={route?.tab === 'focus_modes' || route?.tab === 'settings_memories' ? route.tab : 'skills'} onOpenExample={openExample} activeSettingsView={detailPath} on:openSettings={navigateSettings} />
                  {/if}
                </div>
                </div>
              {:else}<p role="alert">{tr('not_found')}</p>{/if}
            </div>
          {/snippet}
        </UnifiedEmbedFullscreen>
      {/key}
    </div>
  {/if}
  {#if $skillStoreExampleFullscreenStore}
    <div class="apps-result-layer">
      {#key $skillStoreExampleFullscreenStore.embedId}<AppsResultFullscreen embedId={$skillStoreExampleFullscreenStore.embedId} appId={$skillStoreExampleFullscreenStore.appId} exampleData={$skillStoreExampleFullscreenStore} onClose={closeSkillStoreExampleFullscreen} />{/key}
    </div>
  {/if}
  {#if route?.embedId && route.appId}
    <div class="apps-result-layer" data-testid="apps-result-fullscreen">
      {#key `${accountKey}:${route.embedId}`}<AppsResultFullscreen embedId={route.embedId} appId={resolvedAppId ?? route.appId} {teamId} onClose={closeResult} />{/key}
    </div>
  {/if}
</div>

<style>
  .apps-workspace { width: 100%; height: 100%; position: relative; min-width: 0; min-height: 0; }
  .apps-detail-layer,.apps-result-layer { position: absolute; inset: 0; z-index: var(--z-index-overlay, 100); }
  .apps-result-layer { z-index: calc(var(--z-index-overlay, 100) + 1); }
  .apps-detail-content { width: 100%; max-width: 75rem; min-width: 0; box-sizing: border-box; margin: 0 auto; padding: 0 var(--spacing-6) var(--spacing-8); }
  .apps-detail-card { width: 82%; min-width: 0; box-sizing: border-box; min-height: 20rem; margin: var(--spacing-9, 2.25rem) auto 0; padding: 0 var(--spacing-6) var(--spacing-8); border-radius: var(--radius-5); background: var(--color-grey-0); }
  .apps-detail-tabs { position: relative; top: -1.25rem; z-index: var(--z-index-raised-2); width: min(100%, 19rem); margin: 0 auto -0.25rem; }
  .apps-detail-card [role='tabpanel'] { min-width: 0; max-width: 100%; }
  .apps-quick-use-affordance { display: block; width: min(100% - 2rem, 32rem); min-height: 3.25rem; margin: 0 auto; border: 0; border-radius: var(--radius-full); background: var(--color-grey-0); box-shadow: var(--shadow-md); color: var(--color-grey-70); font: inherit; font-weight: 700; cursor: pointer; }
  .apps-quick-use-affordance:hover { color: var(--color-primary-start); }
  .skill-form-area { margin: var(--spacing-6) 0; border-radius: var(--border-radius-lg); transition: box-shadow .3s; }
  .skill-form-area.highlight { box-shadow: 0 0 0 .2rem var(--color-primary-start); }
  .hero-action,.plain-action { border: 0; border-radius: var(--border-radius-lg); padding: .75rem 1.25rem; font: inherit; cursor: pointer; }
  .hero-action { min-width: 11rem; border-radius: var(--radius-5); background: var(--color-button-primary); color: var(--color-font-button); font-weight: 700; box-shadow: var(--shadow-md); }
  .plain-action { background: var(--color-grey-10); color: var(--color-font-primary); }
  .plain-action:disabled { opacity: .45; cursor: default; }
  .results-grid { display: grid; grid-template-columns: repeat(auto-fill,minmax(18.75rem,1fr)); gap: var(--spacing-6); padding: var(--spacing-6) 0; }
  .pagination { display: flex; justify-content: space-between; gap: var(--spacing-4); margin-block: var(--spacing-6); }
  .workflow-row { display: block; padding: var(--spacing-4); border-bottom: 1px solid var(--color-grey-20); color: var(--color-font-primary); text-decoration: none; }
  @media(max-width: 600px) { .apps-detail-content { padding: 0 var(--spacing-3) var(--spacing-6); } .apps-detail-card { width: 100%; padding: 0 var(--spacing-3) var(--spacing-6); } .results-grid { grid-template-columns: 1fr; justify-items: center; } }
</style>
