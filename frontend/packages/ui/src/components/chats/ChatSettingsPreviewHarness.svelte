<!-- Account-free Chat Settings preview. Explicit context bypasses account stores
     and service effects; synthetic actions cannot issue API mutations.
     Native Swift counterparts:
     - apple/OpenMates/Sources/Features/Chat/Views/ChatSettingsView.swift
-->
<script lang="ts">
  import ChatSettingsPage from './ChatSettingsPage.svelte';
  import ChatSettingsHeader from '../settings/ChatSettingsHeader.svelte';
  import { type ChatSettingsTab } from '../../stores/chatSettingsStore';
  import type { UserTaskViewModel } from '../../services/userTaskService';
  import type { UserPlanViewModel } from '../../services/userPlanService';
  import type { Chat } from '../../types/chat';
  import { getExampleChatFileReferences, getExampleChatUsageEntries } from '../../demo_chats';
  let { tab = 'plan', shared = false, example = false, exampleChatId = 'example-gigantic-airplanes' }: {
    tab?: ChatSettingsTab; shared?: boolean; example?: boolean; exampleChatId?: string;
  } = $props();
  let chat = $derived({
    chat_id: example ? exampleChatId : 'preview-chat-settings', title: 'Launch preparation',
    chat_summary: 'Coordinate the work and verify the outcome before completion.',
    created_at: 1788883200, updated_at: 1788883200, messages_v: 1, title_v: 1,
    unread_count: 0, is_shared_by_others: shared,
  } as Chat);
  let credits = $derived(example
    ? getExampleChatUsageEntries(chat.chat_id).reduce((total, entry) => total + (entry.credits ?? 0), 0)
    : 24);

  const previewTasks = [{ task_id: 'preview-task', title: 'Review the release checklist', description: 'Verify the outcome before completion.', status: 'todo', encrypted: {} }] as UserTaskViewModel[];
  const previewPlans = [{ plan_id: 'preview-plan', title: 'Prepare the launch', goal: 'Coordinate the work and verify the outcome.', status: 'active', encrypted: {} }] as UserPlanViewModel[];
  let previewFiles = $derived(example ? getExampleChatFileReferences(chat.chat_id) : []);
</script>
<div class="chat-settings-preview">
  <ChatSettingsHeader title="Launch preparation" {credits} breadcrumbLabel="Chats" onBack={() => {}} />
  <ChatSettingsPage {previewTasks} {previewPlans} {previewFiles} previewContext={{ chat, messages: [], activeTab: tab, display: { title: chat.title, summary: chat.chat_summary, credits } }} activeSettingsView={`chats/${chat.chat_id}/${tab}`} />
</div>

<style>
  .chat-settings-preview { height: 100%; overflow: auto; background: var(--color-grey-10); }
  /* Settings.svelte globally hides chat banners until its scoped visible shell
     mounts. This account-free harness supplies that final visible state without
     mounting the authenticated Settings store lifecycle. */
  :global(.chat-settings-preview .chat-settings-header) { opacity: 1; }
</style>
