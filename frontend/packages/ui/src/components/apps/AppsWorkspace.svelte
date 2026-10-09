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
  import { retainAppsResult, listAppsResults, listPendingAppsResultItems, promoteGuestAppsResults, startAppsHistoricalDiscovery,
    appsResultSaveStates, recoverPendingAppsResults, retryAppsResultSave, AppsResultSavePendingError, type AppsResultItem } from '../../services/appsWorkspaceResultsService';
  import { listAppsWorkflows, type AppsWorkflowLibraryItem } from '../../services/appsWorkflowLibraryService';
  import { readAppsWorkspaceRoute, buildAppsWorkspaceHash, resolveAppsSkillId, resolveAppsAppId, type AppsWorkspaceTab } from '../../utils/appsWorkspaceRoute';
  import type { AppsSkillDetails } from '../../types/appsWorkspace';
  import type { AppMetadata } from '../../types/apps';
  import { CONTENT_EMBED_CATALOG } from '../../data/embedRegistry.generated';
  import WorkspaceHomeShell from '../workspace/WorkspaceHomeShell.svelte';
  import SearchSortBar from '../settings/SearchSortBar.svelte';
  import AppDetailsWrapper from '../settings/AppDetailsWrapper.svelte';
  import SkillDetails from '../settings/SkillDetails.svelte';
  import SettingsTabs from '../settings/elements/SettingsTabs.svelte';
  import UnifiedEmbedFullscreen from '../embeds/UnifiedEmbedFullscreen.svelte';
  import AppsEmbedPreview from './AppsEmbedPreview.svelte';
  import AppsInlineResults from './AppsInlineResults.svelte';
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
  let skillContextOpen = $state(false);
  let submitting = $state(false);
  let requestError = $state(false);
  let inlineResultId = $state<string | null>(null);
  let pendingResultId = $state<string | null>(null);
  let libraryError = $state(false);
  let libraryLoading = $state(false);
  let results = $state<AppsResultItem[]>([]);
  let pendingResults = $state<AppsResultItem[]>([]);
  const resultSaveId = $derived(inlineResultId ?? pendingResultId);
  const inlineSaveState = $derived(resultSaveId ? $appsResultSaveStates[`${accountKey}:${resultSaveId}`] : undefined);
  let workflows = $state<AppsWorkflowLibraryItem[]>([]);
  let offset = $state(0);
  let hasMore = $state(false);
  let libraryGeneration = 0;
  let recents = $state<string[]>([]);
  let lastHomeHash = $state('#apps');
  let catalogSearchOpen = $state(false);
  let catalogSearchQuery = $state('');
  let catalogSort = $state('newest');
  let activeCatalogFilter = $state<AllAppsFilterType>('all');
  let catalogSearchElement = $state<HTMLDivElement | undefined>();
  let formElement = $state<HTMLDivElement | undefined>();
  let highlight = $state(false);
  let highlightTimer: ReturnType<typeof setTimeout> | undefined;
  let mounted = false;
  const pageSize = 20;
  // Private provider admission must refresh when the account changes. Public
  // schemas keep their form mounted through login so guest input survives.
  const privateMetadataContext = $derived(resolvedAppId === 'mail' && skillId === 'search'
    ? `${$authStore.isAuthenticated}:${$userProfile.user_id ?? ''}` : '');
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
  function appItem(metadata: AppMetadata) {
    return {
      id: metadata.id,
      title: metadata.name_translation_key ? $text(metadata.name_translation_key) : metadata.name ?? metadata.id,
      summary: metadata.description_translation_key ? $text(metadata.description_translation_key) : metadata.description ?? '',
      appId: metadata.id, icon: 'app', iconImage: metadata.icon_image, category: 'productivity',
      appMetadata: metadata,
    };
  }
  const homeItems = $derived.by(() => {
    const ids = [...recents, 'web', 'news', 'health', 'travel', 'weather', 'audio'];
    return [...new Set(ids)].filter(id => apps[id]).slice(0, 6).map(id => appItem(apps[id]));
  });
  const catalogItems = $derived.by(() => {
    const query = catalogSearchQuery.trim().toLowerCase();
    const list = Object.values(apps).filter(item => {
      if (item.id === 'ai') return false;
      if (activeCatalogFilter === 'skills' && !item.skills?.length) return false;
      if (activeCatalogFilter === 'focus_modes' && !item.focus_modes?.length) return false;
      if (activeCatalogFilter === 'settings_memories' && !item.settings_and_memories?.length) return false;
      if (!query) return true;
      const name = item.name_translation_key ? $text(item.name_translation_key) : item.name ?? item.id;
      const description = item.description_translation_key ? $text(item.description_translation_key) : item.description ?? '';
      return `${name} ${description} ${(item.providers ?? []).join(' ')}`.toLowerCase().includes(query);
    });
    list.sort((a, b) => {
      if (catalogSort === 'newest') {
        return (b.last_updated ? Date.parse(b.last_updated) : 0) - (a.last_updated ? Date.parse(a.last_updated) : 0);
      }
      const aName = a.name_translation_key ? $text(a.name_translation_key) : a.name ?? a.id;
      const bName = b.name_translation_key ? $text(b.name_translation_key) : b.name ?? b.id;
      return catalogSort === 'name_desc' ? bName.localeCompare(aName) : aName.localeCompare(bName);
    });
    return list.map(appItem);
  });
  const catalogSortOptions = $derived([
    { value: 'newest', label: $text('settings.app_store.all_apps.sort_by_newest') },
    { value: 'name_asc', label: $text('settings.app_store.all_apps.sort_by_name_asc') },
    { value: 'name_desc', label: $text('settings.app_store.all_apps.sort_by_name_desc') },
  ]);
  const catalogFilterOptions = $derived([
    { value: 'all', label: $text('settings.app_store.all_apps.filter_all') },
    { value: 'settings_memories', label: $text('settings.app_store.all_apps.filter_settings_memories') },
    { value: 'focus_modes', label: $text('settings.app_store.all_apps.filter_focus_modes') },
    { value: 'skills', label: $text('settings.app_store.all_apps.filter_skills') },
  ]);
  const tabs = $derived(skillId ? [
    { id: 'overview', icon: 'skill', label: tr('overview') },
    { id: 'embeds', icon: 'files', label: tr('embeds') },
    { id: 'workflows', icon: 'workflow', label: tr('workflows') },
  ] : [
    ...(app && (app.skills.length > 0 || CONTENT_EMBED_CATALOG.some(item => item.appId === app.id)) ? [{ id: 'overview', icon: 'app', label: tr('skills') }] : []),
    ...(app?.focus_modes?.length ? [{ id: 'focus_modes', icon: 'search', label: tr('focus_modes') }] : []),
    ...(app && ((app.memories?.length ?? 0) > 0 || app.settings_and_memories?.some(category => $authStore.isAuthenticated || (category.example_entries?.length ?? 0) > 0 || (category.example_translation_keys?.length ?? 0) > 0)) ? [{ id: 'settings_memories', icon: 'settings', label: tr('settings_memories') }] : []),
    { id: 'embeds', icon: 'files', label: tr('embeds') },
    { id: 'workflows', icon: 'workflow', label: tr('workflows') },
  ]);
  const activeTab = $derived((tabs.some(tab => tab.id === route?.tab) ? route?.tab : tabs[0]?.id ?? 'embeds') as AppsWorkspaceTab);

  $effect(() => {
    if (route && !route.appId) lastHomeHash = hash;
    if (route?.showAll && catalogFilter) {
      activeCatalogFilter = catalogFilter;
      catalogSearchOpen = true;
    }
  });
  $effect(() => {
    if (route?.showAll && catalogSearchOpen) {
      void tick().then(() => {
        if (route?.showAll && catalogSearchOpen) catalogSearchElement?.querySelector('input')?.focus();
      });
    }
  });
  function showAllApps(): void {
    catalogSearchQuery = '';
    activeCatalogFilter = 'all';
    catalogSearchOpen = false;
    onNavigate('#apps/all');
  }
  function searchAllApps(): void {
    catalogSearchOpen = true;
    if (!route?.showAll) onNavigate('#apps/all');
  }

  $effect(() => {
    const context = accountKey;
    try { recents = JSON.parse(localStorage.getItem(`apps-recents:${context}`) ?? '[]'); }
    catch { recents = []; }
  });
  $effect(() => {
    void resolvedAppId; void skillId; void accountKey;
    skillContextOpen = false;
    inlineResultId = null;
    pendingResultId = null;
  });
  $effect(() => {
    const context = accountKey; const appId = resolvedAppId; const selectedSkill = skillId; const selectedTeamId = teamId;
    if (!$authStore.isAuthenticated || !$userProfile.user_id) return;
    let cancelled = false;
    const recover = () => { void recoverPendingAppsResults(selectedTeamId, appId, selectedSkill).then(embedId => {
      if (!cancelled && context === accountKey && !submitting && !inlineResultId && embedId) inlineResultId = embedId;
    }).catch(() => {}); };
    recover();
    window.addEventListener('online', recover);
    return () => { cancelled = true; window.removeEventListener('online', recover); };
  });
  $effect(() => {
    const appId = resolvedAppId; const selectedSkill = skillId;
    void privateMetadataContext;
    metadata = null; metadataError = false; requestError = false;
    if (!appId || !selectedSkill || route?.settingsPath) return;
    const controller = new AbortController();
    metadataLoading = true;
    void getAppsSkillDetails(appId, selectedSkill, controller.signal).then(value => {
      if (!controller.signal.aborted) metadata = value;
    }).catch(() => { if (!controller.signal.aborted) metadataError = true; })
      .finally(() => { if (!controller.signal.aborted) metadataLoading = false; });
    return () => controller.abort();
  });
  $effect(() => {
    if (resolvedAppId && skillId && !$authStore.isAuthenticated) void refreshAnonymousFreeUsageStatus();
  });
  $effect(() => {
    const appId = resolvedAppId; const tab = activeTab; void accountKey;
    libraryGeneration++; results = []; pendingResults = []; workflows = []; offset = 0; hasMore = false; libraryError = false;
    if (appId && (tab === 'embeds' || tab === 'workflows')) untrack(() => void loadLibrary(0));
    if (appId && tab === 'embeds' && $authStore.isAuthenticated) {
      return untrack(() => startAppsHistoricalDiscovery(appId, teamId));
    }
  });
  onMount(() => {
    mounted = true;
    const refreshResults = (event: Event) => {
      const updated = (event as CustomEvent<{ teamId: string | null; userId?: string; embedId?: string; appId?: string; skillId?: string; status?: string }>).detail;
      if (updated?.userId && updated.userId !== $userProfile.user_id) return;
      if (route?.tab === 'embeds' && updated?.teamId === (teamId ?? null)) void loadLibrary(offset);
      else if (!submitting && route?.tab === 'overview' && updated?.teamId === (teamId ?? null)
        && updated.appId === resolvedAppId && updated.skillId === skillId && updated.status === 'finished' && updated.embedId) inlineResultId = updated.embedId;
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
    submitting = true; requestError = false; inlineResultId = null; pendingResultId = null;
    try {
      await retainAppsResult({ appId: selected.app_id, skillId: selected.skill_id, input, response: { status: 'processing' }, teamId: submittedTeamId, guest, requestId, newRequest: true, persistence: 'background' });
      const response = await executeAppsSkill(selected.app_id, selected.skill_id, input, { guest, teamId: submittedTeamId, metadata: selected, onTaskSubmitted: async taskId => { acceptedTaskId = taskId; await retainAppsResult({ appId: selected.app_id, skillId: selected.skill_id, input, response: { status: 'processing', task_id: taskId }, teamId: submittedTeamId, guest, requestId, persistence: 'background' }); } });
      const embedId = await retainAppsResult({ appId: selected.app_id, skillId: selected.skill_id, input, response, teamId: submittedTeamId, guest, requestId, persistence: 'background' });
      remember(selected.app_id, submittedContext);
      if (mounted && accountKey === submittedContext && resolvedAppId === selected.app_id && skillId === selected.skill_id) inlineResultId = embedId;
    } catch (error) {
      if (error instanceof AppsResultSavePendingError) {
        if (accountKey === submittedContext) pendingResultId = error.embedId;
      } else {
        await retainAppsResult({ appId: selected.app_id, skillId: selected.skill_id, input, response: acceptedTaskId ? { status: 'processing', task_id: acceptedTaskId } : { status: 'error' }, teamId: submittedTeamId, guest, requestId, persistence: 'background' }).catch(() => {});
        if (accountKey === submittedContext) requestError = true;
      }
    } finally { submitting = false; if (guest) void refreshAnonymousFreeUsageStatus(); }
  }
  async function loadLibrary(nextOffset: number): Promise<void> {
    if (!resolvedAppId || !route) return;
    const generation = ++libraryGeneration; const appId = resolvedAppId; const tab = activeTab;
    const selectedTeamId = teamId; const context = accountKey;
    results = []; pendingResults = []; workflows = []; libraryLoading = true; libraryError = false;
    try {
      if (tab === 'workflows' && !$authStore.isAuthenticated) { hasMore = false; offset = 0; return; }
      const pending = tab === 'embeds' && nextOffset === 0 ? await listPendingAppsResultItems(appId, selectedTeamId) : [];
      if (generation !== libraryGeneration || context !== accountKey) return;
      pendingResults = pending;
      const page = tab === 'workflows' ? await listAppsWorkflows(appId, selectedTeamId, nextOffset, pageSize) : await listAppsResults(appId, selectedTeamId, nextOffset, pageSize);
      if (generation !== libraryGeneration || context !== accountKey) return;
      if (tab === 'workflows') workflows = page.items as AppsWorkflowLibraryItem[];
      else {
        pendingResults = pending;
        const pendingIds = new Set(pending.map(item => item.embedId));
        results = (page.items as AppsResultItem[]).filter(item => !pendingIds.has(item.embedId));
      }
      hasMore = page.hasMore; offset = page.offset;
    } catch { if (generation === libraryGeneration) libraryError = true; }
    finally { if (generation === libraryGeneration) libraryLoading = false; }
  }
  function openResult(embedId: string, rootEmbedId?: string): void {
    onNavigate(`${buildAppsWorkspaceHash(detailPath, route?.tab ?? 'overview')}&embed-id=${encodeURIComponent(embedId)}${rootEmbedId && rootEmbedId !== embedId ? `&root-id=${encodeURIComponent(rootEmbedId)}` : ''}`);
  }
  function closeResult(): void { onNavigate(buildAppsWorkspaceHash(detailPath, route?.tab ?? 'overview')); }
  function openNewMessage(message: string): void { window.open(`/#new-message=${encodeURIComponent(message)}`, '_blank', 'noopener,noreferrer'); }
  function openExampleChat(chatId: string): void { window.open(`/#chat-id=${encodeURIComponent(chatId)}`, '_blank', 'noopener,noreferrer'); }
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
  <WorkspaceHomeShell surface="apps" eyebrow={$authStore.isAuthenticated && $userProfile.username ? $text('apps_workspace.home_greeting', { values: { name: $userProfile.username } }) : ''} heading={tr('home_prompt')} subtitle={tr('description')} actionItems={homeItems} actionItemsTestId="apps-home-apps" itemTestId="apps-app-card" allItemTestId="apps-all-item" showAllMode={route?.showAll ?? false} allItems={catalogItems} allItemsEmptyLabel={$text('settings.app_store.all_apps.no_apps_found')} showReportIssue showComposer={false} showAllLabel={tr('show_all')} backLabel={tr('back_to_recent')} searchLabel={$text('common.search')} onShowAll={showAllApps} onSearchAll={searchAllApps} onBackToRecent={() => onNavigate('#apps')} onAllItem={item => onNavigate(buildAppsWorkspaceHash(`apps/${item.id}`))} onActionItem={item => onNavigate(buildAppsWorkspaceHash(`apps/${item.id}`))} onStartInspiration={item => onNavigate(buildAppsWorkspaceHash(item.feature?.settings_path?.startsWith('apps') ? item.feature.settings_path : 'apps/web/search'))}>
    <div slot="all-items-controls">
      {#if catalogSearchOpen}
        <div class="catalog-controls" data-testid="apps-catalog-controls" bind:this={catalogSearchElement}>
          <SearchSortBar bind:searchQuery={catalogSearchQuery} bind:sortBy={catalogSort} bind:filterBy={activeCatalogFilter} searchPlaceholder={$text('settings.app_store.all_apps.search_placeholder')} sortOptions={catalogSortOptions} filterOptions={catalogFilterOptions} />
        </div>
      {/if}
    </div>
  </WorkspaceHomeShell>

  {#if route?.appId}
    <div class="apps-detail-layer">
      {#key route.appId}
        <UnifiedEmbedFullscreen appId={resolvedAppId ?? route.appId} skillId={skillId ?? undefined} closeOnChatSelection={false} onClose={() => onNavigate(skillId || route?.settingsPath ? buildAppsWorkspaceHash(`apps/${route?.appId}`) : lastHomeHash)} onShare={() => void shareDetail()} testId="apps-detail-fullscreen" closeTestId="apps-detail-close" embedHeaderPresentation="apps" embedHeaderIconInteractive={false} embedHeaderEyebrow={heroCategory} embedHeaderFooter={heroStats} embedHeaderProviders={heroProviders} appIconName={heroAppIcon} skillIconName={heroSkillIcon} embedHeaderTitle={title} embedHeaderSubtitle={description}>
          {#snippet embedHeaderCta()}
            {#if skillId && !route?.settingsPath}
              <button class="hero-action" data-testid="apps-use-skill" onclick={useSkill}>{tr('use_skill')}</button>
            {/if}
          {/snippet}
          {#snippet content()}
            <div class="apps-detail-content">
              {#if app}
                <div class="apps-detail-card" data-testid="apps-detail-card">
                  <div class="apps-detail-tabs" data-testid="apps-detail-tabs"><SettingsTabs {tabs} maxVisibleTabs={skillId ? 4.3 : 5} {activeTab} testIdPrefix="apps-tab" onChange={selectTab} /></div>
                <div role="tabpanel" tabindex="0" id={`tabpanel-${activeTab}`} aria-label={tr(activeTab)}>
                  {#if activeTab === 'embeds' || activeTab === 'workflows'}
                    {#if activeTab === 'embeds' && pendingResults.length}
                      <p role="status">{tr('saving_results')}</p>
                      <div class="results-grid" data-testid="apps-pending-results-list">
                        {#each pendingResults as result (result.embedId)}
                          <div data-testid={`apps-result-open-${result.embedId}`}>
                            <AppsEmbedPreview embedId={result.embedId} appId={result.appId} skillId={result.skillId} status={result.status} {teamId} hydrate onFullscreen={() => openResult(result.embedId)} />
                            {#if $appsResultSaveStates[`${accountKey}:${result.embedId}`] === 'error'}
                              <p>{tr('save_failed')}</p>
                              <button class="plain-action" data-testid={`apps-result-save-retry-${result.embedId}`} onclick={() => void retryAppsResultSave(result.embedId, teamId).catch(() => {})}>{tr('retry_save')}</button>
                            {/if}
                          </div>
                        {/each}
                      </div>
                    {/if}
                    {#if libraryLoading}<p role="status">{$text('common.loading')}</p>
                    {:else if libraryError}<p role="alert">{tr('library_error')}</p><button class="plain-action" onclick={() => void loadLibrary(offset)}>{tr('retry')}</button>
                    {:else if activeTab === 'embeds'}
                      <div class="results-grid" data-testid="apps-results-list">
                        {#each results as result (result.embedId)}
                          <div data-testid={`apps-result-open-${result.embedId}`}>
                            <AppsEmbedPreview embedId={result.embedId} appId={result.appId} skillId={result.skillId} status={result.status} {teamId} hydrate onFullscreen={() => openResult(result.embedId)} />
                          </div>
                        {:else}{#if !pendingResults.length}<p>{tr('no_embeds')}</p>{/if}{/each}
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
                    <details class="skill-context" data-testid="apps-skill-context" bind:open={skillContextOpen}>
                      <summary data-testid="apps-skill-context-toggle">
                        <span class="skill-context-icon" aria-hidden="true"></span>
                        <span>{tr('skill_context_intro')}</span>
                        <span>{tr('skill_context_chat')}</span>
                        <span class="skill-context-action">{tr(skillContextOpen ? 'skill_context_collapse' : 'skill_context_expand')}<span class="skill-context-caret" aria-hidden="true"></span></span>
                      </summary>
                      {#if skillContextOpen}
                        <div class="skill-context-details" data-testid="apps-skill-context-details">
                          <SkillDetails appId={app.id} {skillId} onOpenExample={openNewMessage} onOpenExampleChat={openExampleChat} on:openSettings={navigateSettings} />
                        </div>
                      {/if}
                    </details>
                    <div class="skill-form-area" class:highlight bind:this={formElement}>
                      {#if metadataLoading}<p role="status">{$text('common.loading')}</p>
                      {:else if metadataError}<p role="alert">{tr('metadata_error')}</p>
                      {:else if metadata}<AppsSkillForm {metadata} showManualIntro={false} onSubmit={submit} {submitting} disabled={viewer} guest={!$authStore.isAuthenticated} {guestEligibility} {onSignup} />{/if}
                      {#if requestError}<p role="alert">{tr('request_error')}</p>{/if}
                      {#if viewer}<p>{tr('viewer_read_only')}</p>{/if}
                      {#if inlineSaveState && resultSaveId}
                          <div class="result-save-state" data-testid="apps-result-save-state" data-save-state={inlineSaveState} aria-live="polite">
                            <span>{tr(inlineSaveState === 'error' ? 'save_failed' : inlineSaveState === 'saved' ? 'saved' : 'saving')}</span>
                            {#if inlineSaveState === 'error'}<button class="plain-action" data-testid="apps-result-save-retry" onclick={() => void retryAppsResultSave(resultSaveId!, teamId).catch(() => {})}>{tr('retry_save')}</button>{/if}
                          </div>
                      {/if}
                      {#if inlineResultId}
                        {#key `${accountKey}:${inlineResultId}`}<AppsInlineResults embedId={inlineResultId} appId={app.id} {skillId} onOpen={openResult} />{/key}
                      {/if}
                    </div>
                  {:else}
                    <AppDetailsWrapper presentation="apps" section={activeTab === 'focus_modes' || activeTab === 'settings_memories' ? activeTab : 'skills'} onOpenExample={openNewMessage} onOpenExampleChat={openExampleChat} activeSettingsView={detailPath} on:openSettings={navigateSettings} />
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
      {#key `${accountKey}:${route.embedId}`}<AppsResultFullscreen embedId={route.embedId} rootEmbedId={route.rootEmbedId ?? route.embedId} appId={resolvedAppId ?? route.appId} {teamId} onClose={closeResult} />{/key}
    </div>
  {/if}
</div>

<style>
  .result-save-state { display: flex; align-items: center; justify-content: center; gap: var(--spacing-3); margin-top: var(--spacing-4); color: var(--color-font-secondary); font-size: var(--font-size-small); }
  .apps-workspace { width: 100%; height: 100%; position: relative; min-width: 0; min-height: 0; }
  .apps-detail-layer,.apps-result-layer { position: absolute; inset: 0; z-index: var(--z-index-overlay, 100); }
  .apps-result-layer { z-index: calc(var(--z-index-overlay, 100) + 1); }
  .apps-detail-content { width: 100%; max-width: 75rem; min-width: 0; box-sizing: border-box; margin: 0 auto; padding: 0 var(--spacing-6) var(--spacing-8); }
  .apps-detail-card { width: 82%; min-width: 0; box-sizing: border-box; min-height: 20rem; margin: var(--spacing-9, 2.25rem) auto 0; padding: 0 var(--spacing-6) var(--spacing-8); border-radius: var(--radius-5); background: var(--color-grey-0); }
  .apps-detail-tabs { position: relative; top: -1.25rem; z-index: var(--z-index-raised-2); width: min(100%, 19rem); margin: 0 auto -0.25rem; }
  .apps-detail-card [role='tabpanel'] { min-width: 0; max-width: 100%; }
  .skill-form-area { margin: var(--spacing-6) 0; border-radius: var(--border-radius-lg); transition: box-shadow .3s; }
  .skill-form-area.highlight { box-shadow: 0 0 0 .2rem var(--color-primary-start); }
  .skill-context { padding-top: var(--spacing-6); color: var(--color-font-secondary); font-size: var(--font-size-small); }
  .skill-context summary { display: flex; flex-direction: column; align-items: center; gap: var(--spacing-1); text-align: center; list-style: none; cursor: pointer; }
  .skill-context summary::-webkit-details-marker { display: none; }
  .skill-context summary:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 4px; border-radius: var(--radius-4); }
  .skill-context-icon { width: 1.25rem; height: 1.25rem; margin-bottom: var(--spacing-2); background: var(--color-primary); -webkit-mask: url('@openmates/ui/static/icons/chat.svg') center/contain no-repeat; mask: url('@openmates/ui/static/icons/chat.svg') center/contain no-repeat; }
  .skill-context-action { display: inline-flex; align-items: center; gap: var(--spacing-2); font-weight: 700; margin-top: var(--spacing-1); }
  .skill-context-caret { width: .35rem; height: .35rem; border-right: 2px solid currentColor; border-bottom: 2px solid currentColor; transform: translateY(-2px) rotate(45deg); }
  .skill-context[open] .skill-context-caret { transform: translateY(2px) rotate(225deg); }
  .skill-context-details { text-align: left; margin-top: var(--spacing-6); }
  .hero-action,.plain-action { border: 0; border-radius: var(--border-radius-lg); padding: .75rem 1.25rem; font: inherit; cursor: pointer; }
  .hero-action { min-width: 11rem; border-radius: var(--radius-5); background: var(--color-button-primary); color: var(--color-font-button); font-weight: 700; box-shadow: var(--shadow-md); }
  .plain-action { background: var(--color-grey-10); color: var(--color-font-primary); }
  .plain-action:disabled { opacity: .45; cursor: default; }
  .catalog-controls { margin-bottom: var(--spacing-5); }
  .results-grid { display: grid; grid-template-columns: repeat(auto-fill,minmax(18.75rem,1fr)); gap: var(--spacing-6); padding: var(--spacing-6) 0; }
  .pagination { display: flex; justify-content: space-between; gap: var(--spacing-4); margin-block: var(--spacing-6); }
  .workflow-row { display: block; padding: var(--spacing-4); border-bottom: 1px solid var(--color-grey-20); color: var(--color-font-primary); text-decoration: none; }
  @media(max-width: 600px) { .apps-detail-content { padding: 0 var(--spacing-3) var(--spacing-6); } .apps-detail-card { width: 100%; padding: 0 var(--spacing-3) var(--spacing-6); } .results-grid { grid-template-columns: 1fr; justify-items: center; } }
</style>
