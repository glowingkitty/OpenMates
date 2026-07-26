<!--
  ChatSettingsPage.svelte

  Deep-linked Settings-shell page for a single chat. The chat identity banner is
  rendered by Settings.svelte; this page owns the light content area, summary,
  tabs, and local-first Plan/Tasks/Files/Usage/Share sections.
-->
<script lang="ts">
  import { chatSettingsRouteFor, chatSettingsStore, normalizeChatSettingsTab, type ChatSettingsTab } from '../../stores/chatSettingsStore';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import { SettingsTabs, SettingsCard, SettingsButton, SettingsInfoBox, SettingsProgressBar, SettingsBadge } from '../settings/elements';
  import ChatSettingsShareSection from './ChatSettingsShareSection.svelte';
  import { loadChatFileRows, type ChatFileRow } from './chatSettingsFiles';
  import { buildChatUsageRows, loadChatUsageRows, loadChatUsageTotal, totalKnownCredits, usageRowsToCsv, usageRowsToYaml, type ChatUsageRow } from './chatUsageRows';
  import { downloadChatAsZip } from '../../services/zipExportService';
  import { notificationStore } from '../../stores/notificationStore';
  import { listUserTasks, type UserTaskViewModel } from '../../services/userTaskService';
  import { listUserPlans, type UserPlanViewModel } from '../../services/userPlanService';
  import { loadSharedChatDetails } from '../../services/sharedChatDetailsService';

  const USAGE_REFRESH_INTERVAL_MS = 5000;

  let { activeSettingsView = '' }: { activeSettingsView?: string } = $props();

  const tabs = [
    { id: 'plan', icon: 'planning' },
    { id: 'tasks', icon: 'task' },
    { id: 'files', icon: 'files' },
    { id: 'usage', icon: 'usage' },
    { id: 'share', icon: 'share' },
  ];

  let activeTab = $state<ChatSettingsTab>('plan');
  let files = $state<ChatFileRow[]>([]);
  let isLoadingFiles = $state(false);
  let tasks = $state<UserTaskViewModel[]>([]);
  let plans = $state<UserPlanViewModel[]>([]);
  let isLoadingPlanning = $state(false);
  let usageRows = $state<ChatUsageRow[]>([]);
  let usageTotalCredits = $state<number | null>(null);
  let isLoadingUsage = $state(false);
  let usageError = $state<string | null>(null);
  let lastUsageTotalKey = $state('');
  let lastUsageRowsKey = $state('');

  let context = $derived($chatSettingsStore);
  let chat = $derived(context?.chat ?? null);
  let messages = $derived(context?.messages ?? []);
  let display = $derived(context?.display ?? null);
  let title = $derived(
    display?.title || chat?.title || [...messages].reverse().find((message) => message.current_chat_title)?.current_chat_title || 'Untitled chat'
  );
  let summary = $derived(
    cleanDisplaySummary(display?.summary || chat?.chat_summary || null) || 'No summary available yet.'
  );
  let totalCredits = $derived(usageTotalCredits ?? display?.credits ?? chat?.budget_spent ?? totalKnownCredits(usageRows));
  let isSharedViewer = $derived(!!chat?.is_shared_by_others);
  let doneTaskCount = $derived(tasks.filter((task) => task.status === 'done').length);
  let taskProgressPercent = $derived(tasks.length > 0 ? Math.round((doneTaskCount / tasks.length) * 100) : 0);
  let activePlans = $derived(plans.filter((plan) => !['completed', 'archived'].includes(plan.status)));
  let usageRefreshKey = $derived.by(() => {
    const assistantSignature = messages
      .filter((message) => message.role === 'assistant')
      .map((message) => `${message.message_id}:${message.status}`)
      .join('|');
    return `${chat?.chat_id ?? ''}:${chat?.budget_spent ?? ''}:${assistantSignature}`;
  });

  $effect(() => {
    activeTab = normalizeChatSettingsTab(context?.activeTab);
  });

  $effect(() => {
    const requestedTab = activeSettingsView.split('/')[2];
    if (!requestedTab) return;
    const nextTab = normalizeChatSettingsTab(requestedTab);
    if (nextTab !== context?.activeTab) {
      chatSettingsStore.setTab(nextTab);
    }
    activeTab = nextTab;
  });

  $effect(() => {
    if (!chat?.chat_id || isSharedViewer) {
      usageTotalCredits = null;
      return;
    }
    if (usageRefreshKey === lastUsageTotalKey) return;
    lastUsageTotalKey = usageRefreshKey;
    void refreshUsageTotal(chat.chat_id);
  });

  $effect(() => {
    const chatId = chat?.chat_id;
    if (!chatId || isSharedViewer) return;
    const interval = window.setInterval(() => void refreshUsageTotal(chatId), USAGE_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(interval);
  });

  $effect(() => {
    if (normalizeChatSettingsTab(context?.activeTab) !== 'usage') return;
    const chatId = chat?.chat_id;
    if (!chatId || isSharedViewer) {
      usageRows = buildChatUsageRows(messages);
      return;
    }
    if (usageRefreshKey === lastUsageRowsKey) return;
    lastUsageRowsKey = usageRefreshKey;
    void refreshUsageRows(chatId);
  });

  $effect(() => {
    if (normalizeChatSettingsTab(context?.activeTab) !== 'usage') return;
    const chatId = chat?.chat_id;
    if (!chatId || isSharedViewer) return;
    const interval = window.setInterval(() => void refreshUsageRows(chatId), USAGE_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(interval);
  });

  $effect(() => {
    if (normalizeChatSettingsTab(context?.activeTab) !== 'files') return;
    void refreshFiles();
  });

  $effect(() => {
    const tab = normalizeChatSettingsTab(context?.activeTab);
    if (!chat?.chat_id || (tab !== 'plan' && tab !== 'tasks')) return;
    void refreshPlanningData(chat.chat_id, isSharedViewer);
  });

  function setTab(tabId: string): void {
    const nextTab = normalizeChatSettingsTab(tabId);
    activeTab = nextTab;
    chatSettingsStore.setTab(nextTab);
    if (chat?.chat_id) {
      settingsDeepLink.set(chatSettingsRouteFor(chat.chat_id, nextTab));
    }
  }

  async function refreshFiles(): Promise<void> {
    isLoadingFiles = true;
    try {
      files = await loadChatFileRows(messages);
    } catch (error) {
      console.error('[ChatSettingsPage] Failed to load chat files:', error);
      files = [];
    } finally {
      isLoadingFiles = false;
    }
  }

  function cleanDisplaySummary(value: string | null | undefined): string {
    const trimmed = value?.trim() ?? '';
    if (!trimmed) return '';
    const lower = trimmed.toLowerCase();
    if (
      lower.includes('[!](embed:') ||
      lower.includes('```json') ||
      lower.includes('"embed_id"') ||
      (lower.includes('"type"') && lower.includes('"content"'))
    ) {
      return '';
    }
    return trimmed;
  }

  async function refreshPlanningData(chatId: string, sharedViewer: boolean): Promise<void> {
    isLoadingPlanning = true;
    try {
      const [nextTasks, nextPlans] = sharedViewer
        ? await loadSharedChatDetails(chatId).then((details) => [details.tasks, details.plans] as const)
        : await Promise.all([
            listUserTasks({ chatId }),
            listUserPlans({ chatId, limit: 6 }),
          ]);
      tasks = nextTasks;
      plans = nextPlans;
    } catch (error) {
      console.error('[ChatSettingsPage] Failed to load chat plans/tasks:', error);
      tasks = [];
      plans = [];
    } finally {
      isLoadingPlanning = false;
    }
  }

  async function refreshUsageTotal(chatId: string): Promise<void> {
    try {
      const total = await loadChatUsageTotal(chatId);
      if (chat?.chat_id !== chatId) return;
      usageTotalCredits = total;
      chatSettingsStore.setCredits(total);
    } catch (error) {
      console.error('[ChatSettingsPage] Failed to load chat usage total:', error);
      usageTotalCredits = null;
    }
  }

  async function refreshUsageRows(chatId: string): Promise<void> {
    isLoadingUsage = true;
    usageError = null;
    try {
      const rows = await loadChatUsageRows(chatId);
      if (chat?.chat_id !== chatId) return;
      usageRows = rows;
    } catch (error) {
      console.error('[ChatSettingsPage] Failed to load chat usage rows:', error);
      usageError = error instanceof Error ? error.message : 'Could not load usage data.';
      usageRows = buildChatUsageRows(messages);
    } finally {
      if (chat?.chat_id === chatId) isLoadingUsage = false;
    }
  }

  function statusBadgeVariant(status: string): 'info' | 'success' | 'warning' | 'danger' | 'neutral' {
    if (status === 'done' || status === 'completed') return 'success';
    if (status === 'blocked') return 'warning';
    if (status === 'in_progress' || status === 'executing' || status === 'active') return 'info';
    return 'neutral';
  }

  function formatStatus(status: string): string {
    return status.replaceAll('_', ' ');
  }

  function downloadTextFile(content: string, filename: string, type: string): void {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  function downloadFileReference(file: ChatFileRow): void {
    downloadTextFile(JSON.stringify(file, null, 2), `${file.title || file.embedId}.json`, 'application/json');
  }

  async function downloadAllFiles(): Promise<void> {
    if (!chat) return;
    try {
      await downloadChatAsZip(chat, messages);
    } catch (error) {
      console.error('[ChatSettingsPage] Failed to download chat files:', error);
      notificationStore.error('Could not download files.');
    }
  }

  function downloadUsage(format: 'csv' | 'yaml'): void {
    const filename = `chat-usage.${format === 'csv' ? 'csv' : 'yml'}`;
    const content = format === 'csv' ? usageRowsToCsv(usageRows) : usageRowsToYaml(usageRows);
    downloadTextFile(content, filename, format === 'csv' ? 'text/csv' : 'text/yaml');
  }

  function formatCredits(value: number | null | undefined): string {
    if (typeof value !== 'number') return 'Unknown';
    return String(Math.round(value)).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  }

  function formatUsageTimestamp(timestamp: number): string {
    if (!timestamp) return '';
    const milliseconds = timestamp > 10_000_000_000 ? timestamp : timestamp * 1000;
    return new Date(milliseconds).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
  }
</script>

{#if chat}
  <section class="chat-settings-page" data-testid="chat-settings-page">
    <p class="chat-summary" data-testid="chat-settings-summary">{summary}</p>
    {#if isSharedViewer}
      <SettingsInfoBox type="info">This is a shared chat. Details are read-only for everyone except the owner.</SettingsInfoBox>
    {/if}

    <div class="tabs-shell" data-testid="chat-settings-tabs">
      <SettingsTabs tabs={tabs} bind:activeTab maxVisibleTabs={tabs.length} testIdPrefix="chat-settings-tab" onChange={setTab} />
    </div>

    {#if activeTab === 'plan'}
      <div class="tabpanel" data-testid="chat-settings-tabpanel-plan" role="tabpanel" aria-labelledby="chat-settings-tab-plan">
        {#if isLoadingPlanning}
          <SettingsInfoBox type="info">Loading chat plans...</SettingsInfoBox>
        {:else if activePlans.length > 0}
          <div class="plan-list" data-testid="chat-settings-plan-list">
            {#each activePlans as plan (plan.plan_id)}
              <SettingsCard>
                <article class="planning-row" data-testid="chat-settings-plan-row">
                  <div>
                    <div class="row-heading">
                      <strong>{plan.title || 'Untitled plan'}</strong>
                      <SettingsBadge variant={statusBadgeVariant(plan.status)} text={formatStatus(plan.status)} />
                    </div>
                    {#if plan.summary || plan.goal}
                      <p>{plan.summary || plan.goal}</p>
                    {/if}
                  </div>
                </article>
              </SettingsCard>
            {/each}
          </div>
        {:else}
          <SettingsInfoBox type="info">{isSharedViewer ? 'No shared plan is available for this chat.' : 'No plan is linked to this chat yet.'}</SettingsInfoBox>
        {/if}
      </div>
    {:else if activeTab === 'tasks'}
      <div class="tabpanel" data-testid="chat-settings-tabpanel-tasks" role="tabpanel" aria-labelledby="chat-settings-tab-tasks">
        {#if isLoadingPlanning}
          <SettingsInfoBox type="info">Loading chat tasks...</SettingsInfoBox>
        {:else if tasks.length > 0}
          <SettingsCard>
            <h2>Tasks</h2>
            <SettingsProgressBar value={taskProgressPercent} label={`${taskProgressPercent}% complete`} />
            <div class="task-list" data-testid="chat-settings-task-list">
              {#each tasks as task (task.task_id)}
                <article class="planning-row" data-testid="chat-settings-task-row">
                  <div>
                    <div class="row-heading">
                      <strong>{task.title || 'Untitled task'}</strong>
                      <SettingsBadge variant={statusBadgeVariant(task.status)} text={formatStatus(task.status)} />
                    </div>
                    {#if task.description || task.latestInstruction}
                      <p>{task.description || task.latestInstruction}</p>
                    {/if}
                  </div>
                </article>
              {/each}
            </div>
          </SettingsCard>
        {:else}
          <SettingsInfoBox type="info">{isSharedViewer ? 'No shared tasks are available for this chat.' : 'No tasks are linked to this chat yet.'}</SettingsInfoBox>
        {/if}
      </div>
    {:else if activeTab === 'files'}
      <div class="tabpanel" data-testid="chat-settings-tabpanel-files" role="tabpanel" aria-labelledby="chat-settings-tab-files">
        <div class="section-action">
          <SettingsButton variant="secondary" dataTestid="chat-settings-download-files" onClick={() => void downloadAllFiles()} disabled={files.length === 0}>Download files</SettingsButton>
        </div>
        {#if isLoadingFiles}
          <SettingsInfoBox type="info">Loading file details...</SettingsInfoBox>
        {:else if files.length > 0}
          <div class="file-list" data-testid="chat-settings-files-list">
            {#each files as file (file.contentRef)}
              <article class="file-row" data-testid="chat-settings-file-row">
                <span class="row-icon icon_{file.iconName || 'files'}"></span>
                <div>
                  <strong>{file.title}</strong>
                  <small>{file.metadata}</small>
                </div>
                <SettingsButton variant="primary" size="sm" dataTestid="chat-settings-file-download" onClick={() => downloadFileReference(file)}>Download</SettingsButton>
              </article>
            {/each}
          </div>
        {:else}
          <SettingsInfoBox type="info">No downloadable files found for this chat yet.</SettingsInfoBox>
        {/if}
      </div>
    {:else if activeTab === 'usage'}
      <div class="tabpanel" data-testid="chat-settings-tabpanel-usage" role="tabpanel" aria-labelledby="chat-settings-tab-usage">
        <div class="section-action">
          <SettingsButton variant="secondary" dataTestid="chat-settings-download-usage-csv" onClick={() => downloadUsage('csv')} disabled={usageRows.length === 0}>Download usage data</SettingsButton>
          <SettingsButton variant="ghost" dataTestid="chat-settings-download-usage-yaml" onClick={() => downloadUsage('yaml')} disabled={usageRows.length === 0}>YAML</SettingsButton>
        </div>
        <SettingsCard>
          <h2>Usage</h2>
          <p class="usage-total" data-testid="chat-settings-usage-total">{formatCredits(totalCredits)} credits</p>
          {#if usageError}
            <SettingsInfoBox type="warning">{usageError}</SettingsInfoBox>
          {/if}
          {#if isLoadingUsage}
            <SettingsInfoBox type="info">Loading usage data...</SettingsInfoBox>
          {:else if usageRows.length > 0}
            <div data-testid="chat-settings-usage-list">
              {#each usageRows as row (row.id)}
                {@const timestampLabel = formatUsageTimestamp(row.timestamp)}
                <article class="usage-row" data-testid="chat-settings-usage-row">
                  <span class="clickable-icon row-icon icon_{row.iconName || 'chat'}"></span>
                  <div>
                    <strong>{row.label}</strong>
                    <small>{row.provider}{timestampLabel ? ` - ${timestampLabel}` : ''}</small>
                  </div>
                  <b>{formatCredits(row.credits)}</b>
                </article>
              {/each}
            </div>
          {:else}
            <SettingsInfoBox type="info">No usage data is available for this chat yet.</SettingsInfoBox>
          {/if}
        </SettingsCard>
      </div>
    {:else if activeTab === 'share'}
      <div class="tabpanel" data-testid="chat-settings-tabpanel-share" role="tabpanel" aria-labelledby="chat-settings-tab-share">
        <ChatSettingsShareSection {chat} {messages} {title} {summary} />
      </div>
    {/if}
  </section>
{:else}
  <section class="chat-settings-page" data-testid="chat-settings-page">
    <SettingsInfoBox type="warning">Open a chat before viewing chat settings.</SettingsInfoBox>
  </section>
{/if}

<style>
  .chat-settings-page {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-5);
    padding: var(--spacing-5) var(--spacing-4) var(--spacing-8);
    background: var(--color-grey-10);
    min-height: 100%;
  }

  .chat-summary {
    margin: 0;
    color: var(--color-text-primary);
    font-size: var(--font-size-p);
    line-height: 1.5;
    font-weight: var(--font-weight-regular);
  }

  .tabs-shell {
    margin: var(--spacing-1) 0;
  }

  .tabpanel {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
  }

  .section-action {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-3);
    align-items: center;
  }

  .task-list {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
    margin: 0;
    padding: 0;
  }

  .plan-list {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
  }

  .planning-row {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
  }

  .row-heading {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-2);
    align-items: center;
    justify-content: space-between;
  }

  .planning-row strong {
    color: var(--color-primary);
    font-weight: var(--font-weight-bold);
  }

  .planning-row p {
    margin: var(--spacing-2) 0 0;
    color: var(--color-grey-70);
    line-height: 1.45;
  }

  .file-list,
  [data-testid="chat-settings-usage-list"] {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
  }

  .file-row,
  .usage-row {
    display: grid;
    grid-template-columns: 3.25rem 1fr auto;
    align-items: center;
    gap: var(--spacing-3);
    padding: var(--spacing-3);
    border-radius: var(--radius-lg);
    background: var(--color-white);
    box-shadow: var(--shadow-xs);
  }

  .file-row strong,
  .usage-row strong {
    display: block;
    color: var(--color-primary);
  }

  .file-row small,
  .usage-row small {
    color: var(--color-grey-60);
    font-weight: var(--font-weight-bold);
  }

  .row-icon {
    width: 3rem;
    height: 3rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-primary);
    cursor: default;
  }

  .usage-total {
    margin: 0 0 var(--spacing-3);
    color: var(--color-grey-70);
    font-weight: var(--font-weight-bold);
  }
</style>
