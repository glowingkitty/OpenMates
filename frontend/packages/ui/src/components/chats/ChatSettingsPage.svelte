<!--
  ChatSettingsPage.svelte

  Deep-linked Settings-shell page for a single chat. The chat identity banner is
  rendered by Settings.svelte; this page owns the light content area, summary,
  tabs, and local-first Plan/Tasks/Files/Usage/Share sections.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { chatSettingsStore, normalizeChatSettingsTab, type ChatSettingsTab } from '../../stores/chatSettingsStore';
  import { SettingsTabs, SettingsCard, SettingsButton, SettingsInfoBox, SettingsProgressBar } from '../settings/elements';
  import ChatSettingsShareSection from './ChatSettingsShareSection.svelte';
  import { loadChatFileRows, type ChatFileRow } from './chatSettingsFiles';
  import { buildChatUsageRows, totalKnownCredits, usageRowsToCsv, usageRowsToYaml, type ChatUsageRow } from './chatUsageRows';
  import { downloadChatAsZip } from '../../services/zipExportService';
  import { notificationStore } from '../../stores/notificationStore';

  let { activeSettingsView = '' }: { activeSettingsView?: string } = $props();

  const tabs = [
    { id: 'plan', icon: 'task' },
    { id: 'tasks', icon: 'tasks' },
    { id: 'files', icon: 'files' },
    { id: 'usage', icon: 'usage' },
    { id: 'share', icon: 'share' },
  ];

  let activeTab = $state<ChatSettingsTab>('plan');
  let files = $state<ChatFileRow[]>([]);
  let isLoadingFiles = $state(false);
  let usageRows = $state<ChatUsageRow[]>([]);

  let context = $derived($chatSettingsStore);
  let chat = $derived(context?.chat ?? null);
  let messages = $derived(context?.messages ?? []);
  let title = $derived(
    chat?.title || [...messages].reverse().find((message) => message.current_chat_title)?.current_chat_title || 'Untitled chat'
  );
  let summary = $derived(
    chat?.chat_summary ||
    messages.find((message) => message.role === 'user')?.content ||
    'No summary available yet.'
  );
  let totalCredits = $derived(chat?.budget_spent ?? totalKnownCredits(usageRows));

  $effect(() => {
    activeTab = normalizeChatSettingsTab(context?.activeTab);
  });

  $effect(() => {
    usageRows = buildChatUsageRows(messages);
    void refreshFiles();
  });

  onMount(() => {
    const requestedTab = activeSettingsView.split('/')[2];
    if (requestedTab) {
      chatSettingsStore.setTab(requestedTab);
    }
  });

  function setTab(tabId: string): void {
    const nextTab = normalizeChatSettingsTab(tabId);
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
</script>

{#if chat}
  <section class="chat-settings-page" data-testid="chat-settings-page">
    <p class="chat-summary" data-testid="chat-settings-summary">{summary}</p>

    <div class="tabs-shell" data-testid="chat-settings-tabs">
      <SettingsTabs tabs={tabs} bind:activeTab testIdPrefix="chat-settings-tab" onChange={setTab} />
    </div>

    {#if activeTab === 'plan'}
      <div class="tabpanel" data-testid="chat-settings-tabpanel-plan" role="tabpanel" aria-labelledby="chat-settings-tab-plan">
        <SettingsCard>
          <div class="coming-soon">
            <strong>No plan active</strong>
            <p>Coming soon.</p>
          </div>
        </SettingsCard>
      </div>
    {:else if activeTab === 'tasks'}
      <div class="tabpanel" data-testid="chat-settings-tabpanel-tasks" role="tabpanel" aria-labelledby="chat-settings-tab-tasks">
        <SettingsCard>
          <h2>Tasks</h2>
          <SettingsProgressBar value={25} label="25% complete" />
          <div class="task-actions">
            <SettingsButton variant="danger" size="sm">Stop</SettingsButton>
            <SettingsButton variant="secondary" size="sm">Add</SettingsButton>
          </div>
          <ul class="task-list">
            <li>Research Whisper usecases & answer user questions</li>
            <li>Implement Whisper code</li>
            <li>Debug code</li>
          </ul>
          <SettingsInfoBox type="info">Task editing UI is coming with the full Plans feature.</SettingsInfoBox>
        </SettingsCard>
      </div>
    {:else if activeTab === 'files'}
      <div class="tabpanel" data-testid="chat-settings-tabpanel-files" role="tabpanel" aria-labelledby="chat-settings-tab-files">
        <div class="section-action">
          <SettingsButton variant="secondary" onClick={() => void downloadAllFiles()} disabled={files.length === 0}>Download files</SettingsButton>
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
                <button type="button" data-testid="chat-settings-file-download" onclick={() => downloadFileReference(file)}>Download</button>
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
          <SettingsButton variant="secondary" onClick={() => downloadUsage('csv')}>Download usage data</SettingsButton>
          <SettingsButton variant="ghost" onClick={() => downloadUsage('yaml')}>YAML</SettingsButton>
        </div>
        <SettingsCard>
          <h2>Today</h2>
          <p class="usage-total" data-testid="chat-settings-usage-total">{totalCredits} credits</p>
          {#if usageRows.length > 0}
            <div data-testid="chat-settings-usage-list">
              {#each usageRows as row (row.id)}
                <article class="usage-row" data-testid="chat-settings-usage-row">
                  <span class="row-icon icon_ai"></span>
                  <div>
                    <strong>{row.label}</strong>
                    <small>via {row.provider}</small>
                  </div>
                  <b>{row.credits ?? 'Unknown'}</b>
                </article>
              {/each}
            </div>
          {:else}
            <SettingsInfoBox type="info">No local usage data is available yet.</SettingsInfoBox>
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
    font-size: clamp(1.35rem, 4vw, 1.9rem);
    line-height: 1.2;
    font-weight: var(--font-weight-bold);
  }

  .tabs-shell {
    margin: var(--spacing-1) 0;
  }

  .tabpanel {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
  }

  .coming-soon {
    min-height: 10rem;
    display: grid;
    place-items: center;
    text-align: center;
    color: var(--color-grey-60);
  }

  .coming-soon strong {
    color: var(--color-grey-60);
    font-size: 1.25rem;
  }

  .task-actions,
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
    padding: 0 0 0 var(--spacing-5);
    color: var(--color-primary);
    font-weight: var(--font-weight-bold);
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

  .file-row button {
    border: 0;
    border-radius: var(--radius-full);
    background: var(--color-primary);
    color: var(--color-white);
    padding: var(--spacing-2) var(--spacing-3);
    cursor: pointer;
  }

  .row-icon {
    width: 3rem;
    height: 3rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-primary);
  }

  .usage-total {
    margin: 0 0 var(--spacing-3);
    color: var(--color-grey-70);
    font-weight: var(--font-weight-bold);
  }
</style>
