<script lang="ts">
  import { onMount, tick, untrack } from 'svelte';
  import { text } from '../../i18n/translations';
  import { appSkillsStore, featureAvailabilityStore, initializeFeatureAvailability } from '../../stores/appSkillsStore';
  import { authStore } from '../../stores/authStore';
  import { userProfile } from '../../stores/userProfile';
  import { activeTeamContext } from '../../stores/teamStore';
  import { skillStoreExampleFullscreenStore, closeSkillStoreExampleFullscreen } from '../../stores/skillStoreExampleFullscreenStore';
  import { listAppsResults, getAppsResult, startAppsHistoricalDiscovery, recoverPendingAppsResults, listPendingAppsResultItems, promoteGuestAppsResults, type AppsResultItem } from '../../services/appsWorkspaceResultsService';
  import { emptyAppsLibrary, getAppsLibrary, getPublicAppsRecommendations, setAppsDailySearches, saveAppsSearchWithNotice, freshAppsRecommendations,
    type AppsLibrary, type AppsSavedSearch, type AppsRecommendation } from '../../services/appsWorkspaceLibraryService';
  import { runAppsWorkspaceRequest, type AppsRequestContext } from '../../services/appsWorkspaceRequestService';
  import { queueAppsWorkspaceChatHandoff, queueAppsWorkspaceWorkflowHandoff } from '../../services/appsWorkspaceChatHandoffService';
  import { readAppsWorkspaceRoute, readAppsWorkspaceOrigin, buildAppsWorkspaceHash, resolveAppsAppId } from '../../utils/appsWorkspaceRoute';
  import type { AppMetadata } from '../../types/apps';
  import type { Chat } from '../../types/chat';
  import { getExampleChatsForSkill, getExampleChatsForFocusMode, getExampleChatsForContentEmbed } from '../../demo_chats';
  import { CONTENT_EMBED_CATALOG } from '../../data/embedRegistry.generated';
  import WorkspaceHomeShell from '../workspace/WorkspaceHomeShell.svelte';
  import SearchSortBar from '../settings/SearchSortBar.svelte';
  import AppDetailsWrapper from '../settings/AppDetailsWrapper.svelte';
  import ChatPreviewCard from '../settings/ChatPreviewCard.svelte';
  import { SettingsItem, SettingsCard, SettingsSectionHeading } from '../settings/elements';
  import UnifiedEmbedFullscreen from '../embeds/UnifiedEmbedFullscreen.svelte';
  import EmbedLeafletMap from '../embeds/EmbedLeafletMap.svelte';
  import EmbedsMapView from '../embeds/EmbedsMapView.svelte';
  import AppsEmbedPreview from './AppsEmbedPreview.svelte';
  import AppsSavedSearchPreview from './AppsSavedSearchPreview.svelte';
  import AppsRequestComposer from './AppsRequestComposer.svelte';
  import AppsResultFullscreen from './AppsResultFullscreen.svelte';
  import AppsSidebar from './AppsSidebar.svelte';
  import AppsResultPreviewGroup from './AppsResultPreviewGroup.svelte';
  import { recommendationPreviewItems } from '../../services/appsWorkspacePreviewService';
  import { loadAppsRecentChats } from '../../services/appsWorkspaceRecentChatsService';
  import { appSettingsMemoriesStore } from '../../stores/appSettingsMemoriesStore';

  let { hash, onNavigate, onSignup, onSettings }: {
    hash: string; onNavigate: (hash: string) => void; onSignup: () => void; onSettings: (path: string) => void;
  } = $props();
  const tr = (key: string) => $text('apps_workspace.' + key);
  const route = $derived(readAppsWorkspaceRoute(hash));
  const apps = $derived.by(() => { void $featureAvailabilityStore; return appSkillsStore.getState().apps; });
  const appId = $derived(route?.appId ? resolveAppsAppId(route.appId, Object.keys(apps)) : null);
  const app = $derived(appId ? apps[appId] : undefined);
  const appName = $derived(app?.name_translation_key ? $text(app.name_translation_key) : app?.name ?? '');
  const description = $derived(app?.description_translation_key ? $text(app.description_translation_key) : app?.description ?? '');
  const authenticatedOwner = $derived($authStore.isAuthenticated ? $userProfile.user_id : null);
  const teamId = $derived(authenticatedOwner ? $activeTeamContext.teamId ?? undefined : undefined);
  const viewer = $derived(Boolean(teamId && $activeTeamContext.team?.role === 'viewer'));
  const accountKey = $derived(authenticatedOwner ? authenticatedOwner + ':' + (teamId ?? 'personal') + ':' + $activeTeamContext.epoch : 'guest');
  let library = $state<AppsLibrary>(emptyAppsLibrary(''));
  let results = $state<AppsResultItem[]>([]);
  let recentChats = $state<Chat[]>([]);
  let resultTitles = $state<Record<string, string>>({});
  let savedEmbedSnapshot = $state<{ owner: string; items: Array<{ id: string; title: string; skillId: string }> } | null>(null);
  let hasMoreResults = $state(false);
  let resultOffset = $state(0);
  let publicRecommendations = $state<AppsRecommendation[]>([]);
  let libraryLoading = $state(false);
  let libraryError = $state(false);
  let requestError = $state(false);
  let submitting = $state(false);
  let requestText = $state('');
  let requestFiles = $state<File[]>([]);
  let composerEpoch = $state(0);
  let settingsOpen = $state(false);
  let settingsPath = $state('');
  let selectedSection = $state<'recommended' | 'saved' | 'recent'>('recommended');
  let mapView = $state(true);
  let calendarView = $state(false);
  let sidebarOpen = $state<boolean | null>(null);
  let viewportWidth = $state(0);
  let now = $state(Date.now());
  let recentAppIds = $state<string[]>([]);
  let lastHomeHash = $state('#apps');
  let catalogSearchOpen = $state(false);
  let catalogSearchQuery = $state('');
  let catalogSearchElement = $state<HTMLDivElement>();
  let catalogSort = $state('newest');
  let catalogFilter = $state('all');
  let temporaryResult = $state<AppsRecommendation | null>(null);
  let generation = 0;
  let pendingRequestToken = 0;
  let previousApp: string | null = null;
  let previousAccount = "";
  const showSidebar = $derived(Boolean(app && (sidebarOpen ?? viewportWidth > 1440)));
  const recommended = $derived(freshAppsRecommendations(library.recommendations, now).length
    ? freshAppsRecommendations(library.recommendations, now) : freshAppsRecommendations(publicRecommendations, now));
  const examples = $derived.by(() => {
    if (!app) return [];
    const chats = [
      ...app.skills.flatMap(skill => getExampleChatsForSkill(app.id, skill.id)),
      ...(app.focus_modes ?? []).flatMap(focus => getExampleChatsForFocusMode(app.id, focus.id)),
      ...CONTENT_EMBED_CATALOG.filter(item => item.appId === app.id).flatMap(item => getExampleChatsForContentEmbed(app.id, item.contentTypeId)),
    ];
    return [...new Map(chats.map(chat => [chat.chat_id, chat])).values()].slice(0, 12);
  });
  const savedEmbeds = $derived(!teamId && $authStore.isAuthenticated && savedEmbedSnapshot?.owner === accountKey
    ? savedEmbedSnapshot.items : []);
  const visibleSection = $derived(
    selectedSection === 'recommended' && !recommended.length ? (library.saved_searches.length || savedEmbeds.length ? 'saved' : 'recent') : selectedSection
  );
  $effect(() => {
    if (temporaryResult && temporaryResult.expires_at * 1000 <= now) temporaryResult = null;
    const expiry = Math.min(...recommended.map(item => item.expires_at * 1000));
    if (!Number.isFinite(expiry)) return;
    const timer = setTimeout(() => { now = Date.now(); }, Math.max(1, expiry - Date.now() + 1));
    return () => clearTimeout(timer);
  });
  function appItem(item: AppMetadata) {
    return { id: item.id, title: item.name_translation_key ? $text(item.name_translation_key) : item.name ?? item.id,
      summary: item.description_translation_key ? $text(item.description_translation_key) : item.description ?? '',
      appId: item.id, icon: 'app', iconImage: item.icon_image, category: 'productivity', appMetadata: item };
  }
  const homeItems = $derived([...new Set([...recentAppIds, 'web', 'news', 'health', 'travel', 'weather', 'audio'])]
    .filter(id => apps[id]).slice(0, 6).map(id => appItem(apps[id])));
  const catalogItems = $derived.by(() => Object.values(apps).filter(item => item.id !== 'ai'
    && (catalogFilter !== 'skills' || item.skills.length > 0)
    && (catalogFilter !== 'focus_modes' || (item.focus_modes?.length ?? 0) > 0)
    && (catalogFilter !== 'settings_memories' || (item.settings_and_memories?.length ?? 0) > 0)
    && (!catalogSearchQuery.trim() || [appItem(item).title, item.id, appItem(item).summary, ...(item.providers ?? [])]
      .join(' ').toLowerCase().includes(catalogSearchQuery.trim().toLowerCase())))
    .sort((a, b) => catalogSort === 'newest' ? (b.last_updated ? Date.parse(b.last_updated) : 0) - (a.last_updated ? Date.parse(a.last_updated) : 0)
      : catalogSort === 'name_desc' ? appItem(b).title.localeCompare(appItem(a).title) : appItem(a).title.localeCompare(appItem(b).title)).map(appItem));
  const catalogSortOptions = $derived([
    { value: 'newest', label: $text('settings.app_store.all_apps.sort_by_newest') },
    { value: 'name_asc', label: $text('settings.app_store.all_apps.sort_by_name_asc') },
    { value: 'name_desc', label: $text('settings.app_store.all_apps.sort_by_name_desc') },
  ]);
  const catalogFilterOptions = $derived([
    { value: 'all', label: $text('settings.app_store.all_apps.filter_all') },
    { value: 'skills', label: $text('settings.app_store.all_apps.filter_skills') },
    { value: 'focus_modes', label: $text('settings.app_store.all_apps.filter_focus_modes') },
    { value: 'settings_memories', label: $text('settings.app_store.all_apps.filter_settings_memories') },
  ]);
  $effect(() => {
    if (route && !route.appId) lastHomeHash = hash;
    const selected = new URLSearchParams(hash.split('&').slice(1).join('&')).get('filter');
    if (route?.showAll && selected && ['skills', 'focus_modes', 'settings_memories'].includes(selected)) {
      catalogFilter = selected; catalogSearchOpen = true;
    }
  });
  $effect(() => {
    void accountKey;
    try { recentAppIds = JSON.parse(localStorage.getItem('apps-recents:' + accountKey) ?? '[]'); } catch { recentAppIds = []; }
  });
  $effect(() => {
    if (route?.showAll && catalogSearchOpen) void tick().then(() => {
      if (route?.showAll && catalogSearchOpen) catalogSearchElement?.querySelector('input')?.focus();
    });
  });
  function showAllApps(): void {
    catalogSearchQuery = ''; catalogFilter = 'all'; catalogSearchOpen = false;
    onNavigate('#apps/all');
  }
  $effect(() => {
    const selectedApp = appId; const context = accountKey;
    // Credit, profile and auth-readiness publications must not reset a draft or
    // invalidate an accepted request. Only an app or account scope change does.
    return untrack(() => {
      if (selectedApp === previousApp && context === previousAccount) return;
      const preserveDraft = selectedApp === previousApp && previousAccount === 'guest' && context !== 'guest';
      previousApp = selectedApp; previousAccount = context;
      pendingRequestToken++;
      generation++; results = []; recentChats = []; resultTitles = {}; savedEmbedSnapshot = null; resultOffset = 0; hasMoreResults = false; publicRecommendations = []; library = emptyAppsLibrary(selectedApp ?? '');
      settingsOpen = false; temporaryResult = null; submitting = false; calendarView = false;
      if (!preserveDraft) { requestText = ''; requestFiles = []; composerEpoch++; }
      requestError = false; selectedSection = 'recommended';
      if (!selectedApp) return;
      void loadLibrary(selectedApp, context);
      if (authenticatedOwner) {
        void promoteGuestAppsResults().catch(() => {});
        void recoverPendingAppsResults(teamId, selectedApp).then(id => {
          if (id && context === accountKey && appId === selectedApp && !route?.embedId && !submitting) openResult(id);
        }).catch(() => {});
      }
      if (authenticatedOwner) return startAppsHistoricalDiscovery(selectedApp, teamId);
    });
  });
  onMount(() => {
    void initializeFeatureAvailability();
    const refresh = () => { now = Date.now(); if (appId) void loadLibrary(appId, accountKey); };
    const timer = setInterval(() => { now = Date.now(); }, 30000);
    const visible = () => { if (document.visibilityState === 'visible') refresh(); };
    window.addEventListener('appsResultUpdated', refresh);
    window.addEventListener('appsWorkspaceLibraryUpdated', refresh);
    document.addEventListener('visibilitychange', visible);
    return () => {
      generation++; clearInterval(timer);
      window.removeEventListener('appsResultUpdated', refresh);
      window.removeEventListener('appsWorkspaceLibraryUpdated', refresh);
      document.removeEventListener('visibilitychange', visible);
    };
  });
  async function loadLibrary(selectedApp = appId, context = accountKey): Promise<void> {
    if (!selectedApp || context !== accountKey || selectedApp !== appId) return;
    const current = ++generation; const selectedTeam = teamId; libraryLoading = true; libraryError = false;
    const awaitingOwner = $authStore.isAuthenticated && !authenticatedOwner;
    const page = await Promise.allSettled([
      awaitingOwner ? Promise.resolve({ items: [] as AppsResultItem[], offset: 0, limit: 20, hasMore: false }) : listAppsResults(selectedApp, selectedTeam, 0, 20),
      $authStore.isAuthenticated && $userProfile.user_id ? getAppsLibrary(selectedApp, selectedTeam) : Promise.resolve(emptyAppsLibrary(selectedApp)),
      listPendingAppsResultItems(selectedApp, selectedTeam),
      getPublicAppsRecommendations(selectedApp),
      loadAppsRecentChats(selectedApp, selectedTeam),
      authenticatedOwner && !selectedTeam ? appSettingsMemoriesStore.readEntriesForApp(selectedApp) : Promise.resolve([]),
    ]);
    if (current !== generation || context !== accountKey || selectedApp !== appId) return;
    const pending = page[2].status === 'fulfilled' ? page[2].value : [];
    const remote = page[0].status === 'fulfilled' ? page[0].value.items : results;
    results = [...pending, ...remote.filter(item => !pending.some(row => row.embedId === item.embedId))];
    if (page[0].status === 'fulfilled') {
      resultOffset = page[0].value.offset; hasMoreResults = page[0].value.hasMore;
    }
    if (page[1].status === 'fulfilled') library = page[1].value;
    if (page[3].status === 'fulfilled') publicRecommendations = page[3].value;
    if (page[4].status === 'fulfilled') recentChats = page[4].value;
    if (page[5].status === 'fulfilled') savedEmbedSnapshot = { owner: context, items: page[5].value
      .filter(entry => typeof entry.item_value.embed_id === 'string')
      .map(entry => ({ id: entry.item_value.embed_id as string,
        title: String(entry.item_value.title || entry.item_value.name || entry.item_key), skillId: String(entry.item_value.skill_id || '') })) };
    if (temporaryResult && ![...library.recommendations, ...publicRecommendations].some(item => item.id === temporaryResult?.id)) temporaryResult = null;
    libraryError = page.slice(0, 2).some(result => result.status === 'rejected');
    libraryLoading = false;
  }
  function rememberApp(): void {
    if (!appId) return;
    recentAppIds = [appId, ...recentAppIds.filter(id => id !== appId)].slice(0, 20);
    try { localStorage.setItem('apps-recents:' + accountKey, JSON.stringify(recentAppIds)); } catch { /* Optional recency cache. */ }
  }
  async function moreResults(): Promise<void> {
    if (!appId || !hasMoreResults || libraryLoading || ($authStore.isAuthenticated && !authenticatedOwner)) return;
    const identity = accountKey; const selectedApp = appId; libraryLoading = true;
    try {
      const page = await listAppsResults(selectedApp, teamId, resultOffset + 20, 20);
      if (identity !== accountKey || selectedApp !== appId) return;
      const ids = new Set(results.map(item => item.embedId));
      results = [...results, ...page.items.filter(item => !ids.has(item.embedId))];
      resultOffset = page.offset; hasMoreResults = page.hasMore;
    } catch { if (identity === accountKey && selectedApp === appId) libraryError = true; }
    finally { if (identity === accountKey && selectedApp === appId) libraryLoading = false; }
  }
  function openResult(embedId: string, rootId = embedId): void {
    if (!appId) return;
    onNavigate(buildAppsWorkspaceHash('apps/' + appId) + '&embed-id=' + encodeURIComponent(embedId) + (rootId !== embedId ? '&root-id=' + encodeURIComponent(rootId) : ''));
  }
  async function showCalendar(): Promise<void> {
    const context = accountKey; const selectedApp = appId;
    for (let offset = 0; offset < results.length; offset += 4) {
      await Promise.allSettled(results.slice(offset, offset + 4).map(result => getAppsResult(result.embedId, teamId)));
      if (context !== accountKey || selectedApp !== appId) return;
    }
    calendarView = true;
  }
  function openSavedEmbed(embedId: string): void {
    if (appId) onNavigate(buildAppsWorkspaceHash('apps/' + appId) + '&embed-id=' + encodeURIComponent(embedId) + '&source=saved');
  }
  function closeResult(): void { if (appId) onNavigate(buildAppsWorkspaceHash('apps/' + appId)); }
  function closeDetail(): void {
    onNavigate(readAppsWorkspaceOrigin(hash) ?? (route?.skillId || route?.settingsPath ? buildAppsWorkspaceHash('apps/' + route.appId) : lastHomeHash));
  }
  function openExample(chat: Chat): void { onNavigate('#chat-id=' + encodeURIComponent(chat.chat_id)); }
  function openDetailExample(chatId: string): void { window.open('/#chat-id=' + encodeURIComponent(chatId), '_blank', 'noopener,noreferrer'); }
  async function submit(value: string, attachments: File[] = [], context?: AppsRequestContext): Promise<boolean> {
    if (!appId || submitting || viewer || ($authStore.isAuthenticated && !authenticatedOwner)) return false;
    const selected = appId; const identity = accountKey; const submittedHash = hash;
    const requestToken = ++pendingRequestToken; let acceptedOpened = false;
    const stillCurrent = () => requestToken === pendingRequestToken && identity === accountKey && appId === selected && hash === submittedHash;
    submitting = true; requestError = false;
    try {
      const accepted = (result: { embedId: string; skillId: string; input: Record<string, unknown> }) => {
        if (acceptedOpened || !stillCurrent()) return;
        acceptedOpened = true;
        openResult(result.embedId);
      };
      const result = await runAppsWorkspaceRequest({ appId: selected, text: value, attachments, context,
        guest: !$authStore.isAuthenticated, teamId,
        onChat: async request => { if (stillCurrent()) await queueAppsWorkspaceChatHandoff(request); },
        onWorkflow: async request => { if (stillCurrent()) await queueAppsWorkspaceWorkflowHandoff(request); }, onAccepted: accepted });
      if (identity !== accountKey || selected !== appId) return false;
      requestText = ''; rememberApp();
      if (result.embedId && result.skillId && result.input) accepted({ embedId: result.embedId, skillId: result.skillId, input: result.input });
      void loadLibrary(); return true;
    } catch (error) {
      if (identity === accountKey) {
        const reason = error instanceof Error ? error.message : '';
        if (['signup_required', 'daily_limit_reached', 'free_usage_unavailable', 'anonymous_budget_exhausted'].some(code => reason.toLowerCase().includes(code))) onSignup();
        else requestError = true;
      }
      return false;
    } finally { if (identity === accountKey && requestToken === pendingRequestToken) submitting = false; }
  }
  async function runSaved(search: AppsSavedSearch): Promise<void> {
    await submit(search.query || search.title || tr('run_saved_search'), [], { skill_id: search.skill_id, input: search.parameters });
  }
  async function saveSearch(context: AppsRequestContext): Promise<void> {
    if (!appId) return;
    if (!$authStore.isAuthenticated) { onSignup(); return; }
    const selectedApp = appId; const owner = accountKey;
    const saved = await saveAppsSearchWithNotice(selectedApp, context, undefined, teamId);
    if (owner === accountKey && selectedApp === appId) library = saved;
  }
  async function toggleDaily(): Promise<void> {
    if (!appId || viewer) return;
    const selectedApp = appId; const owner = accountKey;
    try {
      const updated = await setAppsDailySearches(selectedApp, !library.daily_searches_enabled, teamId);
      if (owner === accountKey && selectedApp === appId) library = updated;
    } catch { if (owner === accountKey && selectedApp === appId) libraryError = true; }
  }
  function settingsNavigate(event: CustomEvent<{ settingsPath: string }>): void {
    if (event.detail.settingsPath.startsWith('apps/')) settingsPath = event.detail.settingsPath;
    else onSettings(event.detail.settingsPath);
  }
  function temporaryContent(batch: AppsRecommendation): Record<string, unknown> {
    const result = batch.result;
    const data = result.data && typeof result.data === 'object' && !Array.isArray(result.data) ? result.data as Record<string, unknown> : result;
    return { ...data, app_id: appId, skill_id: batch.skill_id, status: 'finished', input: batch.input, request_text: batch.request_text };
  }

</script>

{#snippet appMapHeader()}
  <div class="app-map-header" data-testid="apps-map-header"><EmbedLeafletMap center={{ lat: 20, lon: 0 }} zoom={2} /></div>
{/snippet}
<svelte:window bind:innerWidth={viewportWidth} />
<div class="apps-workspace" class:with-sidebar={showSidebar} data-testid="apps-workspace">
  {#if showSidebar && app}
    <AppsSidebar {appName} saved={library.saved_searches} recent={results} {resultTitles} {savedEmbeds} {recentChats} {examples}
      onSavedEmbed={openSavedEmbed}
      onSaved={search => void runSaved(search)} onRecent={result => openResult(result.embedId)}
      onExample={openExample} onClose={() => { sidebarOpen = false; }} />
  {/if}
  <div class="workspace-main">
    <WorkspaceHomeShell surface="apps" heading={tr('home_prompt')} subtitle={tr('description')} actionItems={homeItems}
      actionItemsTestId="apps-home-apps" itemTestId="apps-app-card" allItemTestId="apps-all-item"
      showAllMode={route?.showAll ?? false} allItems={catalogItems} allItemsEmptyLabel={$text('settings.app_store.all_apps.no_apps_found')}
      showReportIssue showComposer={false} showAllLabel={tr('show_all')} backLabel={tr('back_to_recent')} searchLabel={$text('common.search')}
      onShowAll={showAllApps} onSearchAll={() => { catalogSearchOpen = true; if (!route?.showAll) onNavigate('#apps/all'); }}
      onBackToRecent={() => onNavigate('#apps')} onAllItem={item => onNavigate(buildAppsWorkspaceHash('apps/' + item.id))}
      onActionItem={item => onNavigate(buildAppsWorkspaceHash('apps/' + item.id))}
      onStartInspiration={item => onNavigate(buildAppsWorkspaceHash(item.feature?.settings_path?.startsWith('apps') ? item.feature.settings_path : 'apps/web'))}>
      <div slot="all-items-controls">
        {#if catalogSearchOpen}<div data-testid="apps-catalog-controls" bind:this={catalogSearchElement}><SearchSortBar bind:searchQuery={catalogSearchQuery} bind:sortBy={catalogSort} bind:filterBy={catalogFilter}
          searchPlaceholder={$text('settings.app_store.all_apps.search_placeholder')} sortOptions={catalogSortOptions} filterOptions={catalogFilterOptions} /></div>{/if}
      </div>
    </WorkspaceHomeShell>
    {#if route?.appId}
      <div class="apps-detail-layer">
        <UnifiedEmbedFullscreen appId={appId ?? route.appId} closeOnChatSelection={false} onClose={closeDetail}
          showShare={false} testId="apps-detail-fullscreen" closeTestId="apps-detail-close"
          embedHeaderPresentation="apps" embedHeaderIconInteractive={false} embedHeaderContent={(app?.id === "travel" || app?.id === "calendar") && mapView ? appMapHeader : undefined}
          appIconName={app?.icon_image?.replace(/\.svg$/i, '') ?? ''} embedHeaderTitle={!mapView && recommended[0]?.title ? recommended[0].title : appName} embedHeaderSubtitle={!mapView && recommended[0]?.request_text ? recommended[0].request_text : description}>
          {#snippet fixedBottom()}
            {#if app && !settingsOpen && !route.settingsPath}
              <div class="apps-composer-dock">{#key composerEpoch}<AppsRequestComposer appId={app.id} bind:value={requestText} bind:files={requestFiles}
                disabled={viewer || ($authStore.isAuthenticated && !authenticatedOwner)} {submitting} onSubmit={submit} />{/key}
                {#if requestError}<p role="alert">{tr('request_error')}</p>{/if}
                {#if viewer}<p>{tr('viewer_read_only')}</p>{/if}
              </div>
            {/if}
          {/snippet}
          {#snippet content()}
            {#if !app}<p role="alert">{tr('not_found')}</p>
            {:else if route.settingsPath}
              <AppDetailsWrapper presentation="apps" activeSettingsView={'apps/' + app.id + '/' + route.settingsPath.replace(/^memory\//, 'settings_memories/')}
                onOpenExampleChat={openDetailExample} on:openSettings={settingsNavigate} />
            {:else if settingsOpen}
              <div class="app-settings" data-testid="apps-settings">
                <SettingsItem title={tr('back_to_app')} icon="back" onClick={() => { settingsOpen = false; }} />
                <SettingsSectionHeading title={tr('app_settings')} icon="settings" />
                {#if $authStore.isAuthenticated}
                  <SettingsCard><SettingsItem title={tr('daily_searches')} subtitleBottom={tr('daily_searches_description')}
                    hasToggle checked={library.daily_searches_enabled} disabled={viewer} onToggleClick={() => void toggleDaily()} data-testid="apps-daily-searches" /></SettingsCard>
                {/if}
                {#if settingsPath && settingsPath !== 'apps/' + app.id}
                  <AppDetailsWrapper activeSettingsView={settingsPath} on:openSettings={settingsNavigate} />
                {:else}
                  {#each app.skills as skill (skill.id)}
                    <SettingsItem title={$text(skill.name_translation_key)} subtitleBottom={tr('pricing_and_providers')}
                      onClick={() => { settingsPath = 'apps/' + app.id + '/skill/' + skill.id; }} />
                  {/each}
                  <AppDetailsWrapper activeSettingsView={'apps/' + app.id} section="settings_memories" on:openSettings={settingsNavigate} />
                {/if}
              </div>
            {:else}
              <div class="app-home" data-testid="apps-app-home">
                <div class="app-actions">
                  <div>
                    <button class="circle-action" data-testid="apps-sidebar-toggle" aria-label={tr('saved_and_recent')} onclick={() => { sidebarOpen = !showSidebar; }}><span class="clickable-icon icon_menu" aria-hidden="true"></span></button>
                    {#if app.id === 'travel' || app.id === 'calendar'}<button class="circle-action" data-testid="apps-map-toggle" aria-pressed={mapView} aria-label={tr('toggle_map')} onclick={() => { mapView = !mapView; calendarView = false; }}><span class="clickable-icon icon_maps" aria-hidden="true"></span></button>{/if}
                    {#if app.id === 'calendar'}<button class="circle-action" data-testid="apps-calendar-toggle" aria-pressed={calendarView} aria-label={tr('calendar_view')} onclick={() => void showCalendar()}><span class="clickable-icon icon_calendar" aria-hidden="true"></span></button>{/if}
                  </div>
                  <button class="circle-action" data-testid="apps-settings-open" aria-label={tr('app_settings')} onclick={() => { settingsOpen = true; settingsPath = ''; }}><span class="clickable-icon icon_settings" aria-hidden="true"></span></button>
                </div>
                <div class="app-greeting">
                  <h2>{$authStore.isAuthenticated && $userProfile.username ? $text('apps_workspace.app_greeting', { values: { name: $userProfile.username } }) : appName}</h2>
                  <p>{tr(visibleSection === 'recommended' ? 'recommended_for_you' : visibleSection === 'saved' ? 'your_saved_searches' : results.length || recentChats.length ? 'your_recent_results' : 'try_an_example')}</p>
                </div>
                {#if libraryLoading}<p class="library-state" role="status">{$text('common.loading')}</p>{/if}
                {#if libraryError}<p class="library-state" role="status">{tr('library_error')} <button onclick={() => void loadLibrary()}>{tr('retry')}</button></p>{/if}
                {#if calendarView}
                  <div class="app-calendar" data-testid="apps-calendar-view"><EmbedsMapView id={'apps-calendar-' + app.id} title={appName} initialVisualTab="calendar"
                    embedRefs={savedEmbeds.map(item => item.id)} sourceRefs={results.map(item => item.embedId)} /></div>
                {:else}
                <div class="app-carousel" data-testid="apps-preview-carousel">
                  {#if visibleSection === 'recommended' && recommended.length}
                    {#each recommended as batch (batch.id)}
                      {#each recommendationPreviewItems(app.id, batch) as child (child.id)}
                        <div class="preview-card"><AppsEmbedPreview embedId={child.id} appId={app.id} skillId={batch.skill_id}
                          embedType={child.type} content={child.content} onFullscreen={() => { temporaryResult = batch; }} /></div>
                      {/each}
                    {/each}
                  {:else if visibleSection === 'saved' && (library.saved_searches.length || savedEmbeds.length)}
                    {#each savedEmbeds as saved (saved.id)}<div class="preview-card"><AppsEmbedPreview embedId={saved.id} appId={app.id} skillId={saved.skillId} onFullscreen={() => openSavedEmbed(saved.id)} /></div>{/each}
                    {#each library.saved_searches as search (search.id)}<div class="preview-card"><AppsSavedSearchPreview {search} appId={app.id} onOpen={() => void runSaved(search)} /></div>{/each}
                  {:else if results.length}
                    {#each results as result (result.embedId)}<AppsResultPreviewGroup {result} appId={app.id} {teamId} onOpen={openResult} onLabel={(id, title) => { resultTitles = { ...resultTitles, [id]: title }; }} />{/each}
                    {#if hasMoreResults}<button class="more-results" data-testid="apps-next-page" disabled={libraryLoading} onclick={() => void moreResults()}>{tr('show_more')}</button>{/if}
                  {:else if recentChats.length}
                    {#each recentChats as chat (chat.chat_id)}<ChatPreviewCard {chat} appId={app.id} onOpen={openExample} />{/each}
                  {:else}
                    {#each examples as chat (chat.chat_id)}<ChatPreviewCard {chat} appId={app.id} onOpen={openExample} />{/each}
                  {/if}
                </div>
                {/if}
                <nav class="library-tabs" aria-label={tr('results')}>
                  {#if recommended.length}<button data-testid="apps-tab-recommended" aria-pressed={visibleSection === 'recommended'} onclick={() => { selectedSection = 'recommended'; }}>{tr('recommended')}</button>{/if}
                  <button data-testid="apps-tab-saved" aria-pressed={visibleSection === 'saved'} onclick={() => { selectedSection = 'saved'; }}><span class="clickable-icon icon_heart" aria-hidden="true"></span>{tr('saved')}</button>
                  <button data-testid="apps-tab-recent" aria-pressed={visibleSection === 'recent'} onclick={() => { selectedSection = 'recent'; }}><span class="clickable-icon icon_history" aria-hidden="true"></span>{tr('recent')}</button>
                </nav>
              </div>
            {/if}
          {/snippet}
        </UnifiedEmbedFullscreen>
      </div>
    {/if}
    {#if route?.embedId && appId}
      <div class="apps-result-layer" data-testid="apps-result-fullscreen">
        {#key accountKey + ':' + route.embedId}<AppsResultFullscreen embedId={route.embedId} rootEmbedId={route.rootEmbedId ?? route.embedId}
          {appId} {teamId} hydrateGraph={new URLSearchParams(hash.split("&").slice(1).join("&")).get("source") !== "saved"} onClose={closeResult} onSubmit={(value, files, context) => submit(value, files, context)}
          onSaveSearch={saveSearch} onCreateWorkflow={context => queueAppsWorkspaceWorkflowHandoff({ text: tr('create_workflow_from_search'), context })} />{/key}
      </div>
    {/if}
    {#if temporaryResult && appId}
      <div class="apps-result-layer" data-testid="apps-recommendation-fullscreen">
        <AppsResultFullscreen embedId={temporaryResult.id} {appId} onClose={() => { temporaryResult = null; }}
          exampleData={{ embedId: temporaryResult.id, appId, skillId: temporaryResult.skill_id, decodedContent: temporaryContent(temporaryResult) }}
          onSubmit={(value, files, context) => submit(value, files, context)} onSaveSearch={saveSearch}
          onCreateWorkflow={context => queueAppsWorkspaceWorkflowHandoff({ text: tr('create_workflow_from_search'), context })} />
      </div>
    {/if}
    {#if $skillStoreExampleFullscreenStore}
      <div class="apps-result-layer"><AppsResultFullscreen embedId={$skillStoreExampleFullscreenStore.embedId}
        appId={$skillStoreExampleFullscreenStore.appId} exampleData={$skillStoreExampleFullscreenStore} onClose={closeSkillStoreExampleFullscreen} /></div>
    {/if}
  </div>
</div>

<style>
  .apps-workspace { display: grid; grid-template-columns: minmax(0, 1fr); width: 100%; height: 100%; min-width: 0; min-height: 0; position: relative; }
  .apps-workspace.with-sidebar { grid-template-columns: 19rem minmax(0, 1fr); gap: var(--spacing-10); }
  .workspace-main { min-width: 0; min-height: 0; position: relative; }
  .apps-detail-layer, .apps-result-layer { position: absolute; inset: 0; z-index: var(--z-index-overlay, 100); }
  .apps-result-layer { z-index: calc(var(--z-index-overlay, 100) + 1); }
  .app-map-header { width: 100%; height: 20rem; border-radius: var(--radius-6); overflow: hidden; }
  .app-home { min-width: 0; padding: var(--spacing-8) 0 var(--spacing-16); }
  .app-actions { display: flex; justify-content: space-between; padding: 0 var(--spacing-8); }
  .app-actions > div { display: flex; gap: var(--spacing-6); }
  .circle-action { border: 0; border-radius: var(--radius-full); width: 2.5rem; height: 2.5rem; background: var(--color-grey-0); box-shadow: var(--shadow-md); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
  .icon_calendar { mask-image: url('@openmates/ui/static/icons/calendar.svg'); -webkit-mask-image: url('@openmates/ui/static/icons/calendar.svg'); }
  .icon_heart { mask-image: url('@openmates/ui/static/icons/heart.svg'); -webkit-mask-image: url('@openmates/ui/static/icons/heart.svg'); }
  .icon_history { mask-image: url('@openmates/ui/static/icons/time.svg'); -webkit-mask-image: url('@openmates/ui/static/icons/time.svg'); }
  .app-greeting { text-align: center; margin: var(--spacing-6) var(--spacing-12) var(--spacing-12); }
  .app-greeting h2, .app-greeting p { margin: var(--spacing-2) 0; font-size: var(--font-size-p); }
  .app-carousel { display: flex; align-items: center; gap: var(--spacing-12); overflow-x: auto; overflow-y: clip; padding: var(--spacing-8) max(var(--spacing-12), calc(50% - 9.375rem)) var(--spacing-12); scrollbar-width: none; }
  .app-carousel::-webkit-scrollbar { display: none; }
  .preview-card { flex: 0 0 18.75rem; width: 18.75rem; }
  .more-results { flex: 0 0 auto; font: inherit; color: var(--color-primary); background: var(--color-grey-0); border: 0; padding: var(--spacing-8); border-radius: var(--radius-5); cursor: pointer; }
  .library-tabs { display: flex; justify-content: center; gap: var(--spacing-12); padding: var(--spacing-4) var(--spacing-8); }
  .library-tabs button { display: inline-flex; align-items: center; gap: var(--spacing-4); font: inherit; color: var(--color-font-secondary); background: transparent; border: 0; cursor: pointer; padding: var(--spacing-4); }
  .library-tabs .clickable-icon { background-color: currentColor; }
  .library-tabs button[aria-pressed='true'] { color: var(--color-primary); }
  .apps-composer-dock { width: min(100%, 42rem); margin: 0 auto; box-sizing: border-box; padding: var(--spacing-8) var(--spacing-12); }
  .apps-composer-dock p { text-align: center; font-size: var(--font-size-small); }
  .app-settings { width: min(100%, 44rem); margin: 0 auto; padding: var(--spacing-12); box-sizing: border-box; }
  .library-state { text-align: center; color: var(--color-font-secondary); font-size: var(--font-size-small); }
  @media (max-width: 730px) {
    .apps-workspace.with-sidebar { grid-template-columns: minmax(0, 1fr); }
    .with-sidebar > :global(.apps-sidebar) { position: absolute; inset: 0 12% 0 0; z-index: calc(var(--z-index-overlay, 100) + 3); box-shadow: var(--shadow-lg); }
    .preview-card { flex-basis: 18.75rem; }
    .app-map-header { height: 15rem; }
  }
</style>
