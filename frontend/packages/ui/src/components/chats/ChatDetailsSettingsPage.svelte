<!--
  ChatDetailsSettingsPage.svelte
  Unified chat details surface for Tasks V1. It keeps chat-scoped task
  management, files, usage details, and sharing in one panel while reusing the
  canonical settings elements and the existing SettingsShare implementation.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import TasksPage from '../tasks/TasksPage.svelte';
  import SettingsShare from '../settings/share/SettingsShare.svelte';
  import {
    SettingsButton,
    SettingsCard,
    SettingsDetailRow,
    SettingsPageContainer,
    SettingsPageHeader,
    SettingsSectionHeading,
    SettingsTabs,
  } from '../settings/elements';
  import type { Chat, Message } from '../../types/chat';
  import { embedStore, type UploadedFileSearchResult } from '../../services/embedStore';
  import { downloadChatAsYaml } from '../../services/chatExportService';
  import { downloadChatAsZip } from '../../services/zipExportService';
  import { notificationStore } from '../../stores/notificationStore';

  type ChatDetailsTab = 'tasks' | 'files' | 'usage' | 'share';

  let {
    chat,
    messages = [],
    initialTab = 'tasks',
    onClose,
  }: {
    chat: Chat;
    messages?: Message[];
    initialTab?: ChatDetailsTab;
    onClose: () => void;
  } = $props();

  let activeTab = $state<ChatDetailsTab>('tasks');
  let lastInitialTab = $state<ChatDetailsTab | null>(null);
  let fileRows = $state<UploadedFileSearchResult[]>([]);
  let isLoadingFiles = $state(false);

  const userMessages = $derived(messages.filter((message) => message.role === 'user').length);
  const assistantMessages = $derived(messages.filter((message) => message.role === 'assistant').length);
  const usageRows = $derived(buildUsageRows(messages));
  const totalKnownTokens = $derived(usageRows.reduce((total, row) => total + row.tokens, 0));
  const fileContentRefs = $derived(extractFileContentRefs(messages));
  const fileReferenceCount = $derived(fileContentRefs.length);
  const startedAt = $derived(formatTimestamp(chat.created_at));
  const updatedAt = $derived(formatTimestamp(chat.updated_at));
  const tabs = $derived([
    { id: 'tasks', icon: 'task' },
    { id: 'files', icon: 'files', count: fileReferenceCount },
    { id: 'usage', icon: 'usage' },
    { id: 'share', icon: 'share' },
  ]);

  function formatTimestamp(value: number | null | undefined): string {
    if (!value) return 'Unknown';
    const millis = value > 10_000_000_000 ? value : value * 1000;
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(millis));
  }

  function extractFileContentRefs(items: Message[]): string[] {
    const refs = new Set<string>();
    for (const message of items) {
      const content = `${message.content ?? ''}\n${message.truncated_content ?? ''}`;
      for (const match of content.matchAll(/embed:[a-zA-Z0-9_:-]+/g)) {
        refs.add(match[0]);
      }
    }
    return [...refs];
  }

  async function loadFileRows(): Promise<void> {
    isLoadingFiles = true;
    try {
      fileRows = await embedStore.getUploadedFilesByContentRefs(fileContentRefs);
    } catch (error) {
      console.error('[ChatDetailsSettingsPage] Failed to load file rows:', error);
      fileRows = [];
    } finally {
      isLoadingFiles = false;
    }
  }

  async function copyFileRef(contentRef: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(contentRef);
      notificationStore.success('File reference copied');
    } catch (error) {
      console.error('[ChatDetailsSettingsPage] Failed to copy file reference:', error);
      notificationStore.error('Could not copy file reference');
    }
  }

  async function handleDownloadArchive(): Promise<void> {
    try {
      await downloadChatAsZip(chat, messages);
    } catch (error) {
      console.error('[ChatDetailsSettingsPage] Failed to download chat archive:', error);
      notificationStore.error('Could not download chat archive');
    }
  }

  async function handleDownloadYaml(): Promise<void> {
    try {
      await downloadChatAsYaml(chat, messages);
    } catch (error) {
      console.error('[ChatDetailsSettingsPage] Failed to download chat YAML:', error);
      notificationStore.error('Could not download chat YAML');
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

  function handleDownloadFileReference(file: UploadedFileSearchResult): void {
    const payload = {
      chat_id: chat.chat_id,
      embed_id: file.embedId,
      content_ref: file.contentRef,
      title: file.title,
      type: file.type,
      node_type: file.nodeType,
      created_at: file.createdAt,
      updated_at: file.updatedAt,
    };
    const safeName = (file.title || file.embedId).replace(/[<>:"/\\|?*]/g, '').slice(0, 80) || file.embedId;
    downloadTextFile(JSON.stringify(payload, null, 2), `${safeName}.json`, 'application/json;charset=utf-8');
  }

  function handleTabChange(tabId: string): void {
    activeTab = tabId as ChatDetailsTab;
  }

  function numericField(message: Message, key: string): number {
    const value = (message as unknown as Record<string, unknown>)[key];
    return typeof value === 'number' && Number.isFinite(value) ? value : 0;
  }

  function stringField(message: Message, key: string): string {
    const value = (message as unknown as Record<string, unknown>)[key];
    return typeof value === 'string' && value.trim() ? value.trim() : '';
  }

  function buildUsageRows(items: Message[]): Array<{ label: string; provider: string; count: number; tokens: number; credits: number }> {
    const rows = new Map<string, { label: string; provider: string; count: number; tokens: number; credits: number }>();
    for (const message of items) {
      const provider = stringField(message, 'provider_name') || (message.role === 'assistant' ? 'Unknown provider' : 'Local');
      const label = message.role === 'assistant'
        ? `${provider} responses`
        : message.role === 'user'
          ? 'User messages'
          : 'System messages';
      const existing = rows.get(label) ?? { label, provider, count: 0, tokens: 0, credits: 0 };
      existing.count += 1;
      existing.tokens += numericField(message, 'total_tokens')
        + numericField(message, 'actual_input_tokens')
        + numericField(message, 'actual_output_tokens')
        + numericField(message, 'thinking_token_count');
      existing.credits += numericField(message, 'credits_charged')
        + numericField(message, 'example_response_credits');
      rows.set(label, existing);
    }
    return [...rows.values()];
  }

  function downloadUsageCsv(): void {
    const header = 'group,provider,count,known_tokens,known_credits\n';
    const body = usageRows.map((row) => `${JSON.stringify(row.label)},${JSON.stringify(row.provider)},${row.count},${row.tokens},${row.credits}`).join('\n');
    downloadTextFile(`${header}${body}\n`, `chat-usage-${chat.chat_id}.csv`, 'text/csv;charset=utf-8');
  }

  function downloadUsageYaml(): void {
    const body = usageRows.map((row) => [
      `  - group: ${JSON.stringify(row.label)}`,
      `    provider: ${JSON.stringify(row.provider)}`,
      `    count: ${row.count}`,
      `    known_tokens: ${row.tokens}`,
      `    known_credits: ${row.credits}`,
    ].join('\n')).join('\n');
    downloadTextFile(`chat_id: ${JSON.stringify(chat.chat_id)}\nusage:\n${body}\n`, `chat-usage-${chat.chat_id}.yml`, 'text/yaml;charset=utf-8');
  }

  $effect(() => {
    if (initialTab === lastInitialTab) return;
    activeTab = initialTab;
    lastInitialTab = initialTab;
  });

  $effect(() => {
    if (activeTab === 'files') void loadFileRows();
  });

  onMount(() => {
    if (activeTab === 'files') void loadFileRows();
  });
</script>

<div class="chat-details-overlay">
  <button class="chat-details-backdrop" type="button" aria-label="Close chat details" onclick={() => onClose()}></button>
  <div class="chat-details-panel" role="dialog" aria-modal="true" aria-label="Chat details" data-testid="chat-details-settings-panel" tabindex="-1">
    <div class="chat-details-topbar">
      <span>Chat details</span>
      <button type="button" class="chat-details-close" aria-label="Close chat details" onclick={() => onClose()}>Close</button>
    </div>

    <SettingsPageContainer maxWidth="wide">
      <SettingsPageHeader
        title="Chat settings"
        description="Manage tasks, files, usage, and sharing for this chat."
      />

      <SettingsTabs bind:activeTab tabs={tabs} onChange={handleTabChange} />

      {#if activeTab === 'tasks'}
        <SettingsSectionHeading title="Tasks" icon="task" />
        <p class="section-description">Tasks linked to this chat stay encrypted and appear on the central Tasks board.</p>
        <SettingsCard>
          <TasksPage chatId={chat.chat_id} compact />
        </SettingsCard>
      {:else if activeTab === 'files'}
        <SettingsSectionHeading title="Files" icon="files" />
        <p class="section-description">Files and embeds referenced in this chat.</p>
        <SettingsCard>
          <SettingsDetailRow label="Referenced files and embeds" value={`${fileReferenceCount}`} highlight={fileReferenceCount > 0} />
          <div class="file-actions">
            <SettingsButton variant="secondary" onClick={() => void handleDownloadArchive()}>Download files archive</SettingsButton>
          </div>
          {#if isLoadingFiles}
            <p class="panel-note" data-testid="chat-files-loading">Loading file details...</p>
          {:else if fileRows.length > 0}
            <div class="file-list" data-testid="chat-files-list">
              {#each fileRows as file}
                <article class="file-row" data-testid="chat-file-row">
                  <div>
                    <strong>{file.title}</strong>
                    <span>{file.subtitle} · {file.contentRef}</span>
                  </div>
                  <div class="file-row-actions">
                    <button type="button" onclick={() => handleDownloadFileReference(file)} data-testid="chat-file-download">Download</button>
                    <button type="button" onclick={() => void copyFileRef(file.contentRef)} data-testid="chat-file-copy-ref">Copy ref</button>
                  </div>
                </article>
              {/each}
            </div>
          {:else}
            <p class="panel-note" data-testid="chat-files-empty">No local file details found for the loaded chat messages.</p>
          {/if}
        </SettingsCard>
      {:else if activeTab === 'usage'}
        <SettingsSectionHeading title="Usage" icon="usage" />
        <p class="section-description">Local usage details for this chat.</p>
        <SettingsCard>
          <SettingsDetailRow label="Messages" value={`${messages.length}`} highlight />
          <SettingsDetailRow label="Your messages" value={`${userMessages}`} />
          <SettingsDetailRow label="Assistant messages" value={`${assistantMessages}`} />
          <SettingsDetailRow label="Known local tokens" value={`${totalKnownTokens}`} highlight={totalKnownTokens > 0} />
          <SettingsDetailRow label="Started" value={startedAt} muted />
          <SettingsDetailRow label="Last updated" value={updatedAt} muted />
          <div class="usage-actions">
            <SettingsButton variant="secondary" onClick={downloadUsageCsv}>Download usage CSV</SettingsButton>
            <SettingsButton variant="secondary" onClick={downloadUsageYaml}>Download usage YAML</SettingsButton>
          </div>
          <div class="usage-list" data-testid="chat-usage-list">
            {#each usageRows as row}
              <article class="usage-row" data-testid="chat-usage-row">
                <strong>{row.label}</strong>
                <span>{row.count} entries · {row.tokens} known tokens · {row.credits} known credits</span>
              </article>
            {/each}
          </div>
        </SettingsCard>
      {:else if activeTab === 'share'}
        <SettingsSectionHeading title="Share" icon="share" />
        <p class="section-description">Create an encrypted share link for this chat.</p>
        <SettingsCard>
          <SettingsShare activeSettingsView="shared/share" />
          <div class="share-download-actions">
            <SettingsButton variant="secondary" onClick={() => void handleDownloadArchive()}>Download chat ZIP</SettingsButton>
            <SettingsButton variant="secondary" onClick={() => void handleDownloadYaml()}>Download chat YAML</SettingsButton>
          </div>
        </SettingsCard>
      {/if}

      <SettingsButton variant="secondary" fullWidth onClick={onClose}>Close</SettingsButton>
    </SettingsPageContainer>
  </div>
</div>

<style>
  .chat-details-overlay {
    position: absolute;
    inset: 0;
    z-index: var(--z-index-dropdown);
    display: flex;
    justify-content: flex-end;
  }

  .chat-details-backdrop {
    position: absolute;
    inset: 0;
    border: 0;
    background: rgba(0, 0, 0, 0.28);
    backdrop-filter: blur(6px);
    cursor: default;
  }

  .chat-details-panel {
    position: relative;
    width: min(600px, 100%);
    height: 100%;
    overflow: auto;
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    box-shadow: -16px 0 42px rgba(0, 0, 0, 0.18);
  }

  .chat-details-topbar {
    position: sticky;
    top: 0;
    z-index: 2;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 18px;
    border-bottom: 1px solid var(--color-grey-20);
    background: color-mix(in srgb, var(--color-grey-0) 92%, transparent);
    backdrop-filter: blur(14px);
    font-weight: 700;
  }

  .chat-details-close {
    width: 36px;
    height: 36px;
    border: none;
    border-radius: 999px;
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    cursor: pointer;
    font-size: 0.78rem;
    font-weight: 700;
    line-height: 1;
  }

  .panel-note {
    margin: 12px 0 0;
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
    line-height: 1.45;
  }

  .file-actions,
  .share-download-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    justify-content: flex-end;
    margin-top: 12px;
  }

  .usage-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    justify-content: flex-end;
    margin-top: 12px;
  }

  .file-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-top: 14px;
  }

  .usage-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-top: 14px;
  }

  .file-row,
  .usage-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px;
    border: 1px solid var(--color-grey-20);
    border-radius: 16px;
    background: var(--color-grey-0);
  }

  .file-row div,
  .usage-row {
    min-width: 0;
    display: flex;
  }

  .file-row div {
    flex-direction: column;
    gap: 4px;
  }

  .usage-row {
    align-items: flex-start;
    flex-direction: column;
  }

  .file-row span,
  .usage-row span {
    overflow: hidden;
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .file-row button {
    flex: 0 0 auto;
    border: 0;
    border-radius: 999px;
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    padding: 8px 11px;
    font: inherit;
    font-size: var(--font-size-small);
    font-weight: 700;
    cursor: pointer;
  }

  .file-row .file-row-actions {
    display: flex;
    flex-direction: row;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 8px;
  }

  .section-description {
    margin: -8px 22px 12px;
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
    line-height: 1.45;
  }

  :global(.chat-details-panel .tasks-page.compact) {
    max-height: none;
  }

  @media (max-width: 700px) {
    .chat-details-panel {
      width: 100%;
    }
  }
</style>
