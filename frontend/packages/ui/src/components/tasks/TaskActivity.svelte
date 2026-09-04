<!--
  TaskActivity.svelte
  Final Task-detail Activity stream with a Task-scoped rich composer.
  Reuses the normal message editor, upload, recording, embed serialization,
  and send-gating primitives while persisting through encrypted Task Activity.
  Plan: docs/plans/task-activity-comments/plan.yml.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { Editor, type JSONContent } from '@tiptap/core';
  import ChatMessage from '../ChatMessage.svelte';
  import RecordAudio from '../enter_message/RecordAudio.svelte';
  import { getEditorExtensions } from '../enter_message/editorConfig';
  import { insertRecording } from '../enter_message/embedHandlers';
  import { processFiles } from '../enter_message/fileHandlers';
  import { tipTapToCanonicalMarkdown } from '../../message_parsing/serializers';
  import { extractEmbedReferences } from '../../services/embedResolver';
  import { embedStore } from '../../services/embedStore';
  import { base64ToUint8Array, uint8ArrayToBase64 } from '../../services/cryptoService';
  import {
    canSubmitUserTaskActivity,
    createUserTaskActivity,
    deleteUserTaskActivity,
    listUserTaskActivity,
    type CreateUserTaskActivityInput,
    type UserTaskActivityEntry,
    type UserTaskViewModel,
  } from '../../services/userTaskService';
  import { text } from '../../i18n/translations';

  type ProcessingState = 'idle' | 'uploading' | 'transcribing' | 'error';
  type CreateHandler = (input: CreateUserTaskActivityInput) => Promise<UserTaskActivityEntry>;
  type DeleteHandler = (entryId: string) => Promise<UserTaskActivityEntry>;

  let {
    task,
    teamId,
    initialEntries,
    previewProcessingState = 'idle',
    onCreate,
    onDelete,
  }: {
    task: UserTaskViewModel;
    teamId?: string;
    initialEntries?: UserTaskActivityEntry[];
    previewProcessingState?: ProcessingState;
    onCreate?: CreateHandler;
    onDelete?: DeleteHandler;
  } = $props();

  let entries = $state<UserTaskActivityEntry[]>([]);
  let editorElement = $state<HTMLDivElement>();
  let fileInput = $state<HTMLInputElement>();
  let editor = $state<Editor | null>(null);
  let composerMarkdown = $state('');
  let embedStatuses = $state<string[]>([]);
  let loading = $state(true);
  let submitting = $state(false);
  let errorMessage = $state('');
  let recording = $state(false);
  let pendingDeleteId = $state<string | null>(null);
  let deletingId = $state<string | null>(null);
  let canSubmit = $derived(!submitting && canSubmitUserTaskActivity(composerMarkdown, [previewProcessingState, ...embedStatuses]));

  onMount(() => {
    editor = new Editor({
      element: editorElement,
      extensions: getEditorExtensions().filter((extension) => extension.name !== 'placeholder'),
      content: { type: 'doc', content: [{ type: 'paragraph' }] },
      onUpdate: ({ editor: activeEditor }) => updateComposerState(activeEditor),
    });
    if (initialEntries === undefined) void loadEntries();
    else {
      entries = sortEntries(initialEntries);
      loading = false;
      restoreEntryEmbedKeys(initialEntries);
    }
    return () => editor?.destroy();
  });

  function collectEmbedStatuses(node: JSONContent, statuses: string[]): void {
    if (node.type === 'embed' && typeof node.attrs?.status === 'string') statuses.push(node.attrs.status);
    node.content?.forEach((child) => collectEmbedStatuses(child, statuses));
  }

  function updateComposerState(activeEditor: Editor): void {
    const content = activeEditor.getJSON();
    composerMarkdown = tipTapToCanonicalMarkdown(content);
    const statuses: string[] = [];
    collectEmbedStatuses(content, statuses);
    embedStatuses = statuses;
  }

  function sortEntries(activityEntries: UserTaskActivityEntry[]): UserTaskActivityEntry[] {
    return [...activityEntries].sort((left, right) => left.createdAt - right.createdAt || left.entryId.localeCompare(right.entryId));
  }

  async function loadEntries(): Promise<void> {
    loading = true;
    errorMessage = '';
    try {
      const loaded = await listUserTaskActivity(task, teamId);
      entries = sortEntries(loaded);
      restoreEntryEmbedKeys(loaded);
    } catch (error) {
      console.error('[TaskActivity] Failed to load Activity:', error);
      errorMessage = $text('tasks.activity.load_error');
    } finally {
      loading = false;
    }
  }

  function restoreEntryEmbedKeys(activityEntries: UserTaskActivityEntry[]): void {
    for (const entry of activityEntries) {
      if (!entry.embedKeyMaterial) continue;
      try {
        const keys = JSON.parse(entry.embedKeyMaterial) as Record<string, unknown>;
        for (const [embedId, encodedKey] of Object.entries(keys)) {
          if (typeof encodedKey === 'string') embedStore.setEmbedKeyInCache(embedId, base64ToUint8Array(encodedKey));
        }
      } catch (error) {
        console.error(`[TaskActivity] Failed to restore embed keys for ${entry.entryId}:`, error);
        errorMessage = $text('tasks.activity.key_error');
      }
    }
  }

  async function buildEmbedKeyMaterial(embedIds: string[]): Promise<string | undefined> {
    if (embedIds.length === 0) return undefined;
    const keys: Record<string, string> = {};
    for (const embedId of embedIds) {
      const embedKey = await embedStore.getEmbedKey(embedId);
      if (!embedKey) throw new Error(`Embed ${embedId} is missing its encryption key`);
      keys[embedId] = uint8ArrayToBase64(embedKey);
    }
    return JSON.stringify(keys);
  }

  async function submit(): Promise<void> {
    if (!editor || !canSubmit) return;
    submitting = true;
    errorMessage = '';
    try {
      const refs = extractEmbedReferences(composerMarkdown).map((reference) => reference.embed_id);
      const input: CreateUserTaskActivityInput = {
        message: composerMarkdown,
        embedRefs: refs,
        embedKeyMaterial: await buildEmbedKeyMaterial(refs),
        teamId,
      };
      const created = onCreate
        ? { ...await onCreate(input), message: editor.getText() }
        : await createUserTaskActivity(task, input);
      entries = sortEntries([...entries, created]);
      restoreEntryEmbedKeys([created]);
      editor.commands.clearContent();
      updateComposerState(editor);
    } catch (error) {
      console.error('[TaskActivity] Failed to create Activity entry:', error);
      errorMessage = $text('tasks.activity.create_error');
    } finally {
      submitting = false;
    }
  }

  async function handleFiles(files: File[]): Promise<void> {
    if (!editor || files.length === 0) return;
    errorMessage = '';
    try {
      await processFiles(files, editor, true);
      updateComposerState(editor);
    } catch (error) {
      console.error('[TaskActivity] Failed to process attachment:', error);
      errorMessage = $text('tasks.activity.attachment_error');
    }
  }

  async function handleAudioRecorded(event: CustomEvent<{ blob: Blob; duration: number; mimeType: string; waveform?: { samples: number[]; duration: number } }>): Promise<void> {
    if (!editor) return;
    const { blob, duration, mimeType, waveform } = event.detail;
    const minutes = Math.floor(duration / 60);
    const seconds = Math.floor(duration % 60).toString().padStart(2, '0');
    await insertRecording(editor, blob, mimeType, `${minutes}:${seconds}`, true, undefined, waveform);
    updateComposerState(editor);
  }

  async function removeEntry(entry: UserTaskActivityEntry): Promise<void> {
    deletingId = entry.entryId;
    errorMessage = '';
    try {
      const tombstone = onDelete
        ? await onDelete(entry.entryId)
        : await deleteUserTaskActivity(task, entry.entryId, teamId);
      entries = sortEntries(entries.map((candidate) => candidate.entryId === entry.entryId ? tombstone : candidate));
      pendingDeleteId = null;
    } catch (error) {
      console.error('[TaskActivity] Failed to delete Activity entry:', error);
      errorMessage = $text('tasks.activity.delete_error');
    } finally {
      deletingId = null;
    }
  }

  function actorLabel(entry: UserTaskActivityEntry): string {
    return entry.actorType === 'user' ? (entry.actorDisplayName || $text('tasks.activity.user')) : 'OpenMates';
  }

  function sourceLabel(entry: UserTaskActivityEntry): string {
    if (entry.sourceSurface === 'cli') return $text('tasks.activity.via_cli');
    if (entry.sourceSurface === 'sdk_npm' || entry.sourceSurface === 'sdk_pip') return $text('tasks.activity.via_sdk');
    return '';
  }

  function formatTime(timestamp: number): string {
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(timestamp * 1000));
  }

  function tombstoneText(entry: UserTaskActivityEntry): string {
    return $text('tasks.activity.tombstone', {
      values: {
        author: actorLabel(entry),
        deleter: entry.deletedByDisplayName || $text('tasks.activity.user'),
      },
    });
  }

  function initials(label: string): string {
    return label.split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase();
  }
</script>

<section class="task-activity" data-testid="task-activity">
  <header>
    <div><span class="activity-icon" aria-hidden="true"></span><h2>{$text('tasks.activity.title')}</h2></div>
    <span>{entries.length}</span>
  </header>

  <form class="composer" data-testid="task-activity-composer" onsubmit={(event) => { event.preventDefault(); void submit(); }}>
    <div
      class="editor prose"
      class:processing={previewProcessingState === 'uploading' || previewProcessingState === 'transcribing'}
      bind:this={editorElement}
      data-testid="task-activity-editor"
      role="textbox"
      tabindex="0"
      aria-multiline="true"
      aria-label={$text('tasks.activity.placeholder')}
      ondrop={(event) => { event.preventDefault(); void handleFiles(Array.from(event.dataTransfer?.files ?? [])); }}
      onpaste={(event) => { const files = Array.from(event.clipboardData?.files ?? []); if (files.length > 0) { event.preventDefault(); void handleFiles(files); } }}
      onkeydown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit(); } }}
    ></div>
    {#if !composerMarkdown}<span class="placeholder" aria-hidden="true">{$text('tasks.activity.placeholder')}</span>{/if}
    <input bind:this={fileInput} data-testid="task-activity-file-input" type="file" hidden multiple onchange={(event) => void handleFiles(Array.from(event.currentTarget.files ?? []))} />
    <div class="composer-actions">
      <button type="button" class="icon-button attach" data-testid="task-activity-attach" aria-label={$text('tasks.activity.attach')} onclick={() => fileInput?.click()}></button>
      <button type="button" class="icon-button mic" data-testid="task-activity-voice" aria-label={$text('tasks.activity.voice')} onclick={() => recording = true}></button>
      <button type="submit" class="send" data-testid="task-activity-submit" disabled={!canSubmit}>{submitting ? $text('tasks.activity.sending') : $text('tasks.activity.send')}</button>
    </div>
    {#if previewProcessingState === 'uploading' || previewProcessingState === 'transcribing'}
      <p class="processing-state" data-testid="task-activity-processing">{previewProcessingState === 'uploading' ? $text('tasks.activity.uploading') : $text('tasks.activity.transcribing')}</p>
    {:else if previewProcessingState === 'error' || embedStatuses.includes('error')}
      <p class="embed-error" data-testid="task-activity-embed-error">{$text('tasks.activity.processing_error')}</p>
    {/if}
    {#if recording}
      <RecordAudio initialPosition={{ x: 0, y: 0 }} on:audiorecorded={handleAudioRecorded} on:close={() => recording = false} on:cancel={() => recording = false} />
    {/if}
  </form>

  {#if errorMessage}<p class="error" role="alert">{errorMessage}</p>{/if}

  <div class="stream" data-testid="task-activity-stream" aria-live="polite">
    {#if loading}
      <p class="state">{$text('tasks.activity.loading')}</p>
    {:else if entries.length === 0}
      <p class="state">{$text('tasks.activity.empty')}</p>
    {:else}
      {#each entries as entry (entry.entryId)}
        <article class:tombstone={entry.kind === 'tombstone'} data-testid={`task-activity-entry-${entry.entryId}`}>
          {#if entry.kind === 'tombstone'}
            <div class="message-wrapper system">
              <ChatMessage role="system" content={tombstoneText(entry)} canAnnotate={false} />
              <time datetime={new Date((entry.deletedAt ?? entry.createdAt) * 1000).toISOString()}>{formatTime(entry.deletedAt ?? entry.createdAt)}</time>
            </div>
          {:else if entry.kind === 'lifecycle_update'}
            <div class="message-wrapper system">
              <ChatMessage role="system" content={entry.eventType.replaceAll('_', ' ')} canAnnotate={false} />
              <time datetime={new Date(entry.createdAt * 1000).toISOString()}>{formatTime(entry.createdAt)}</time>
            </div>
          {:else}
            <div class="message-wrapper" class:user={entry.actorType === 'user'} class:assistant={entry.actorType !== 'user'}>
              {#if entry.actorType === 'user'}
                <div class="user-attribution">
                  <span class="avatar" aria-hidden="true">{#if entry.actorProfileImageUrl}<img src={entry.actorProfileImageUrl} alt="" />{:else}{initials(actorLabel(entry))}{/if}</span>
                  <strong>{actorLabel(entry)}</strong>
                  {#if sourceLabel(entry)}<span class="source">{sourceLabel(entry)}</span>{/if}
                </div>
                <ChatMessage role="user" content={entry.message ?? ''} canAnnotate={false} />
              {:else}
                <ChatMessage role="assistant" category="openmates_official" sender_name="OpenMates" content={entry.message ?? ''} canAnnotate={false} />
              {/if}
              <div class="message-footer">
                <time datetime={new Date(entry.createdAt * 1000).toISOString()}>{formatTime(entry.createdAt)}</time>
                {#if pendingDeleteId === entry.entryId}
                  <div class="delete-confirmation" data-testid="task-activity-delete-confirmation">
                    <span>{$text('tasks.activity.delete_confirm')}</span>
                    <button type="button" disabled={deletingId === entry.entryId} onclick={() => void removeEntry(entry)}>{$text('common.delete')}</button>
                    <button type="button" onclick={() => pendingDeleteId = null}>{$text('common.cancel')}</button>
                  </div>
                {:else}
                  <button class="delete" type="button" aria-label={$text('tasks.activity.delete')} data-testid="task-activity-delete" onclick={() => pendingDeleteId = entry.entryId}></button>
                {/if}
              </div>
            </div>
          {/if}
        </article>
      {/each}
    {/if}
  </div>
</section>

<style>
  .task-activity { margin-top: 48px; padding-top: 32px; border-top: 1px solid var(--color-grey-25); }
  header, header > div, .composer-actions, .delete-confirmation { display: flex; align-items: center; }
  header { justify-content: space-between; margin-bottom: 18px; }
  header > div { gap: 10px; }
  h2 { margin: 0; font-size: var(--font-size-h3); }
  header > span { min-width: 28px; padding: 5px 9px; border-radius: var(--radius-full); background: var(--color-grey-20); color: var(--color-font-secondary); font-size: var(--font-size-xs); font-weight: 800; text-align: center; }
  .activity-icon { width: 24px; height: 24px; background: var(--color-primary); mask: var(--icon-url-chat) center / contain no-repeat; }
  .composer { position: relative; overflow: hidden; margin-bottom: 26px; border: 1px solid var(--color-grey-25); border-radius: 22px; background: var(--color-grey-blue); box-shadow: 0 8px 24px color-mix(in srgb, var(--color-grey-100) 8%, transparent); }
  .editor { min-height: 88px; max-height: 260px; overflow-y: auto; padding: 18px 20px 8px; }
  .editor.processing { opacity: 0.7; }
  .editor :global(.ProseMirror) { min-height: 62px; outline: none; }
  .placeholder { position: absolute; top: 19px; left: 20px; color: var(--color-font-secondary); pointer-events: none; }
  .composer-actions { justify-content: flex-end; gap: 8px; padding: 8px 12px 12px; }
  .icon-button, .delete { width: 38px; height: 38px; border: 0; border-radius: 50%; background-color: transparent; cursor: pointer; }
  .icon-button::before, .delete::before { display: block; width: 20px; height: 20px; margin: auto; content: ''; background: var(--color-font-secondary); mask-position: center; mask-repeat: no-repeat; mask-size: contain; }
  .attach::before { mask-image: var(--icon-url-files); }
  .mic::before { mask-image: var(--icon-url-recordaudio); }
  .delete::before { mask-image: var(--icon-url-delete); }
  .icon-button:hover, .delete:hover { background: var(--color-grey-20); }
  .send { min-height: 38px; padding: 0 18px; border: 0; border-radius: var(--radius-full); background: var(--color-button-primary); color: var(--color-font-button); font: inherit; font-weight: 800; cursor: pointer; }
  .send:disabled { opacity: 0.45; cursor: not-allowed; }
  .processing-state, .embed-error { margin: 0; padding: 0 18px 14px; font-size: var(--font-size-xs); font-weight: 700; }
  .processing-state { color: var(--color-font-secondary); }
  .embed-error, .error { color: var(--color-error); }
  .error { margin: 0 0 18px; padding: 12px 14px; border-radius: 12px; background: color-mix(in srgb, var(--color-error) 10%, transparent); }
  .stream { display: grid; gap: 0; }
  article { padding: 14px 4px; }
  article:last-child { border-bottom: 0; }
  .message-wrapper { display: flex; width: 100%; flex-direction: column; }
  .message-wrapper.user { align-items: flex-end; }
  .message-wrapper.assistant { align-items: flex-start; }
  .message-wrapper.system { align-items: center; gap: 5px; }
  .message-wrapper :global(.chat-message) { width: 100%; }
  .user-attribution { display: flex; align-items: center; gap: 7px; margin: 0 12px 5px; color: var(--color-font-secondary); font-size: var(--font-size-xs); }
  .user-attribution strong { color: var(--color-font-primary); }
  .avatar { display: grid; width: 24px; height: 24px; place-items: center; overflow: hidden; border-radius: 50%; background: linear-gradient(135deg, var(--color-app-tasks-start, var(--color-primary-start)), var(--color-app-tasks-end, var(--color-primary-end))); color: var(--color-grey-0); font-size: 9px; font-weight: 900; }
  .avatar img { width: 100%; height: 100%; object-fit: cover; }
  .source { color: var(--color-primary); font-weight: 700; }
  .message-footer { display: flex; align-items: center; min-height: 30px; gap: 6px; margin: 2px 10px 0; }
  .message-wrapper.user .message-footer { justify-content: flex-end; }
  time { color: var(--color-font-secondary); font-size: var(--font-size-xs); }
  .delete { width: 30px; height: 30px; }
  .tombstone { color: var(--color-font-secondary); }
  .state { margin: 0; line-height: 1.5; }
  .state { padding: 24px 0; color: var(--color-font-secondary); text-align: center; }
  .delete-confirmation { flex-wrap: wrap; gap: 8px; margin-top: 12px; padding: 10px 12px; border-radius: 12px; background: var(--color-grey-10); font-size: var(--font-size-xs); }
  .delete-confirmation span { margin-right: auto; }
  .delete-confirmation button { border: 0; border-radius: var(--radius-full); padding: 7px 12px; font: inherit; font-weight: 700; cursor: pointer; }
  @media (max-width: 700px) {
    .task-activity { margin-top: 36px; padding-top: 26px; }
    .editor { min-height: 104px; padding-inline: 16px; }
    .user-attribution { margin-inline: 8px; }
  }
</style>
