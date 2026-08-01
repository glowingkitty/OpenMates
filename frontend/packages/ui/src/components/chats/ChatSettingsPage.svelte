<!--
  ChatSettingsPage.svelte

  Deep-linked Settings-shell page for a single chat. The chat identity banner is
  rendered by Settings.svelte; this page owns the light content area, summary,
  tabs, and local-first Plan/Tasks/Files/Usage/Share sections.
-->
<script lang="ts">
  import { chatSettingsStore, normalizeChatSettingsTab, type ChatSettingsTab } from '../../stores/chatSettingsStore';
  import { SettingsTabs, SettingsCard, SettingsButton, SettingsInfoBox, SettingsProgressBar, SettingsBadge, SettingsInput, SettingsTextarea } from '../settings/elements';
  import SettingsItem from '../SettingsItem.svelte';
  import ChatSettingsShareSection from './ChatSettingsShareSection.svelte';
  import { loadChatFileRows, type ChatFileRow } from './chatSettingsFiles';
  import { buildChatUsageRows, loadChatUsageRows, loadChatUsageTotal, totalKnownCredits, usageEntriesToChatUsageRows, usageRowsToCsv, usageRowsToYaml, type ChatUsageRow } from './chatUsageRows';
  import { downloadChatAsZip } from '../../services/zipExportService';
  import { notificationStore } from '../../stores/notificationStore';
  import { completeUserTask, createUserTask, listUserTasks, reorderUserTasks, type UserTaskViewModel } from '../../services/userTaskService';
  import { listUserPlans, type UserPlanViewModel } from '../../services/userPlanService';
  import { loadSharedChatDetails } from '../../services/sharedChatDetailsService';
  import { getExampleChatUsageEntries, isExampleChat } from '../../demo_chats';

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
  let isCreatingTask = $state(false);
  let taskActionId = $state<string | null>(null);
  let taskTitle = $state('');
  let taskDescription = $state('');
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
  let isSharedViewer = $derived(!!chat?.is_shared_by_others);
  let isExampleChatSettings = $derived(!!chat?.chat_id && isExampleChat(chat.chat_id));
  let staticUsageEntries = $derived(chat?.chat_id && isExampleChatSettings ? getExampleChatUsageEntries(chat.chat_id) : []);
  let localUsageRows = $derived.by(() => {
    const staticRows = usageEntriesToChatUsageRows(staticUsageEntries);
    return staticRows.length > 0 ? staticRows : buildChatUsageRows(messages);
  });
  let hasStaticUsageData = $derived(localUsageRows.length > 0 && localUsageRows.some((row) => typeof row.credits === 'number'));
  let totalCredits = $derived(usageTotalCredits ?? display?.credits ?? chat?.budget_spent ?? totalKnownCredits(isExampleChatSettings ? localUsageRows : usageRows));
  let visibleTabs = $derived(isExampleChatSettings
    ? tabs.filter((tab) => tab.id === 'share' || (tab.id === 'usage' && hasStaticUsageData))
    : tabs);
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

  function normalizeVisibleChatSettingsTab(tabId: string | null | undefined): ChatSettingsTab {
    const nextTab = normalizeChatSettingsTab(tabId);
    if (!isExampleChatSettings) return nextTab;
    if (nextTab === 'usage' && hasStaticUsageData) return 'usage';
    return 'share';
  }

  $effect(() => {
    const nextTab = normalizeVisibleChatSettingsTab(context?.activeTab);
    activeTab = nextTab;
    if (isExampleChatSettings && context?.activeTab !== nextTab) {
      chatSettingsStore.setTab(nextTab);
    }
  });

  $effect(() => {
    const requestedTab = activeSettingsView.split('/')[2];
    if (!requestedTab) return;
    const nextTab = normalizeVisibleChatSettingsTab(requestedTab);
    if (nextTab !== context?.activeTab) {
      chatSettingsStore.setTab(nextTab);
    }
    activeTab = nextTab;
  });

  $effect(() => {
    if (!chat?.chat_id || isSharedViewer || isExampleChatSettings) {
      usageTotalCredits = null;
      return;
    }
    if (usageRefreshKey === lastUsageTotalKey) return;
    lastUsageTotalKey = usageRefreshKey;
    void refreshUsageTotal(chat.chat_id);
  });

  $effect(() => {
    const chatId = chat?.chat_id;
    if (!chatId || isSharedViewer || isExampleChatSettings) return;
    const interval = window.setInterval(() => void refreshUsageTotal(chatId), USAGE_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(interval);
  });

  $effect(() => {
    if (normalizeChatSettingsTab(context?.activeTab) !== 'usage') return;
    const chatId = chat?.chat_id;
    if (!chatId || isSharedViewer || isExampleChatSettings) {
      usageError = null;
      usageRows = localUsageRows;
      isLoadingUsage = false;
      return;
    }
    if (usageRefreshKey === lastUsageRowsKey) return;
    lastUsageRowsKey = usageRefreshKey;
    void refreshUsageRows(chatId);
  });

  $effect(() => {
    if (normalizeChatSettingsTab(context?.activeTab) !== 'usage') return;
    const chatId = chat?.chat_id;
    if (!chatId || isSharedViewer || isExampleChatSettings) return;
    const interval = window.setInterval(() => void refreshUsageRows(chatId), USAGE_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(interval);
  });

  $effect(() => {
    if (normalizeChatSettingsTab(context?.activeTab) !== 'files') return;
    void refreshFiles();
  });

  $effect(() => {
    const tab = normalizeChatSettingsTab(context?.activeTab);
    if (!chat?.chat_id || isExampleChatSettings || (tab !== 'plan' && tab !== 'tasks')) return;
    void refreshPlanningData(chat.chat_id, isSharedViewer);
  });

  function setTab(tabId: string): void {
    const nextTab = normalizeVisibleChatSettingsTab(tabId);
    activeTab = nextTab;
    chatSettingsStore.setTab(nextTab);
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

  function broadcastTasksChanged(chatId: string): void {
    window.dispatchEvent(new CustomEvent('openmates-user-tasks-changed', { detail: { chatId } }));
  }

  async function createChatTask(): Promise<void> {
    if (!chat?.chat_id || isSharedViewer) return;
    const trimmedTitle = taskTitle.trim();
    if (!trimmedTitle || isCreatingTask) return;
    isCreatingTask = true;
    try {
      const task = await createUserTask({
        title: trimmedTitle,
        description: taskDescription.trim(),
        primaryChatId: chat.chat_id,
      });
      tasks = [task, ...tasks];
      taskTitle = '';
      taskDescription = '';
      broadcastTasksChanged(chat.chat_id);
      notificationStore.success('Task linked to chat');
    } catch (error) {
      console.error('[ChatSettingsPage] Failed to create chat task:', error);
      notificationStore.error('Could not create task.');
    } finally {
      isCreatingTask = false;
    }
  }

  async function toggleTaskDone(task: UserTaskViewModel): Promise<void> {
    if (!chat?.chat_id || isSharedViewer || taskActionId) return;
    const nextStatus = task.status === 'done' ? 'todo' : 'done';
    const previous = tasks;
    taskActionId = task.task_id;
    tasks = tasks.map((candidate) => candidate.task_id === task.task_id ? { ...candidate, status: nextStatus } : candidate);
    try {
      const updated = nextStatus === 'done'
        ? await completeUserTask(task)
        : (await reorderUserTasks([{ task, status: nextStatus }]))[0];
      if (!updated) throw new Error('Task update returned no task');
      tasks = tasks.map((candidate) => candidate.task_id === updated.task_id ? updated : candidate);
      broadcastTasksChanged(chat.chat_id);
    } catch (error) {
      tasks = previous;
      console.error('[ChatSettingsPage] Failed to update chat task:', error);
      notificationStore.error('Could not update task.');
    } finally {
      taskActionId = null;
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

  function downloadUsageData(): void {
    downloadUsage('csv');
    downloadUsage('yaml');
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
      <SettingsTabs tabs={visibleTabs} bind:activeTab maxVisibleTabs={visibleTabs.length} testIdPrefix="chat-settings-tab" onChange={setTab} />
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
        {#if !isSharedViewer}
          <SettingsCard>
            <h2>Create task</h2>
            <div class="task-create-grid" data-testid="chat-settings-task-create-form">
              <SettingsInput
                bind:value={taskTitle}
                placeholder="What should happen next?"
                ariaLabel="Task title"
                dataTestid="chat-settings-task-title-input"
                disabled={isCreatingTask}
              />
              <SettingsTextarea
                bind:value={taskDescription}
                placeholder="Optional task context"
                ariaLabel="Task description"
                rows={3}
                dataTestid="chat-settings-task-description-input"
                disabled={isCreatingTask}
              />
              <div class="section-action">
                <SettingsButton dataTestid="chat-settings-task-create-button" onClick={() => void createChatTask()} disabled={isCreatingTask || !taskTitle.trim()}>
                  {isCreatingTask ? 'Creating...' : 'Create task'}
                </SettingsButton>
              </div>
            </div>
          </SettingsCard>
        {/if}
        {#if isLoadingPlanning}
          <SettingsInfoBox type="info">Loading chat tasks...</SettingsInfoBox>
        {:else}
          <SettingsCard>
            <h2>Tasks</h2>
            <div data-testid="chat-settings-task-progress">
              <SettingsProgressBar value={taskProgressPercent} label={`${taskProgressPercent}% complete`} />
            </div>
            {#if tasks.length > 0}
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
                    {#if !isSharedViewer}
                      <label class="task-complete-toggle">
                        <input
                          type="checkbox"
                          checked={task.status === 'done'}
                          disabled={taskActionId === task.task_id}
                          onchange={() => void toggleTaskDone(task)}
                          data-testid="chat-settings-task-done-toggle"
                          aria-label={`Mark ${task.title || 'task'} done`}
                        />
                        <span>Done</span>
                      </label>
                    {/if}
                  </article>
                {/each}
              </div>
            {:else}
              <SettingsInfoBox type="info">{isSharedViewer ? 'No shared tasks are available for this chat.' : 'No tasks are linked to this chat yet.'}</SettingsInfoBox>
            {/if}
          </SettingsCard>
        {/if}
      </div>
    {:else if activeTab === 'files'}
      <div class="tabpanel" data-testid="chat-settings-tabpanel-files" role="tabpanel" aria-labelledby="chat-settings-tab-files">
        <SettingsItem
          type="quickaction"
          icon="download"
          iconBackground="none"
          title="Download files"
          subtitleBottom={files.length > 0 ? `${files.length} downloadable ${files.length === 1 ? 'item' : 'items'}` : 'No downloadable files yet'}
          disabled={files.length === 0}
          data-testid="chat-settings-download-files"
          onClick={() => void downloadAllFiles()}
        />
        {#if isLoadingFiles}
          <SettingsInfoBox type="info">Loading file details...</SettingsInfoBox>
        {:else if files.length > 0}
          <div class="file-list" data-testid="chat-settings-files-list">
            {#each files as file (file.contentRef)}
              <SettingsItem
                type="quickaction"
                icon={file.iconName || 'files'}
                iconBackground="none"
                title={file.title}
                subtitleBottom={file.metadata}
                data-testid="chat-settings-file-row"
                onClick={() => downloadFileReference(file)}
              />
            {/each}
          </div>
        {:else}
          <SettingsInfoBox type="info">No downloadable files found for this chat yet.</SettingsInfoBox>
        {/if}
      </div>
    {:else if activeTab === 'usage'}
      <div class="tabpanel" data-testid="chat-settings-tabpanel-usage" role="tabpanel" aria-labelledby="chat-settings-tab-usage">
        <SettingsItem
          type="quickaction"
          icon="download"
          iconBackground="none"
          title="Download usage data"
          subtitleBottom="CSV & YAML"
          disabled={usageRows.length === 0}
          data-testid="chat-settings-download-usage"
          onClick={downloadUsageData}
        />
        <SettingsCard>
          <SettingsItem
            type="heading"
            icon="usage"
            iconBackground="none"
            title="Usage"
            creditsDisplay={formatCredits(totalCredits)}
            data-testid="chat-settings-usage-total"
          />
          {#if usageError}
            <SettingsInfoBox type="warning">{usageError}</SettingsInfoBox>
          {/if}
          {#if isLoadingUsage}
            <SettingsInfoBox type="info">Loading usage data...</SettingsInfoBox>
          {:else if usageRows.length > 0}
            <div data-testid="chat-settings-usage-list">
              {#each usageRows as row (row.id)}
                {@const timestampLabel = formatUsageTimestamp(row.timestamp)}
                <SettingsItem
                  type="quickaction"
                  icon={row.iconName || 'chat'}
                  iconBackground="none"
                  title={row.label}
                  subtitleBottom={`${row.provider}${timestampLabel ? ` - ${timestampLabel}` : ''}`}
                  creditsDisplay={formatCredits(row.credits)}
                  data-testid="chat-settings-usage-row"
                />
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

  .task-create-grid {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
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

  .task-complete-toggle {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-2);
    width: fit-content;
    color: var(--color-grey-70);
    font-weight: var(--font-weight-bold);
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
    gap: var(--spacing-1);
  }

  @media (max-width: 730px) {
    .chat-settings-page {
      padding-inline: var(--spacing-1);
    }

    .chat-settings-page :global(.settings-card) {
      margin-inline: var(--spacing-1);
      padding-inline: var(--spacing-3);
    }

    .chat-settings-page :global(.settings-tabs-wrapper) {
      padding-inline: var(--spacing-1);
    }
  }
</style>
