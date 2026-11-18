<!--
  Fullscreen for the plans.check skill result: the draft Check rendered by the shared
  Check fullscreen without run actions, plus "Save to Project" which stores the draft
  (encrypted, via the client core) in the Project of the chat it was drafted in. When the
  chat has no Project the action is hidden and the reason is shown.
  Spec: checks.gui.fullscreen.
-->
<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import { get } from 'svelte/store';
  import type { EmbedFullscreenCommonProps, EmbedFullscreenRawData, EmbedSourceChatContext } from '../../../types/embedFullscreen';
  import { EMBED_SOURCE_CHAT_CONTEXT } from '../../../types/embedFullscreen';
  import { activeChatStore } from '../../../stores/activeChatStore';
  import { loadChatProjectIndex } from '../../../services/chatProjectService';
  import { getProject, type ProjectViewModel } from '../../../services/projectService';
  import { createProjectCheck } from '../../../services/projectCheckService';
  import { text } from '../../../i18n/translations';
  import CheckEmbedFullscreen from './CheckEmbedFullscreen.svelte';
  import { checkViewFromSkill, draftFromSkill } from './checkSkillView';

  interface Props extends EmbedFullscreenCommonProps { data: EmbedFullscreenRawData; }
  let { data, onClose, embedId, hasPreviousEmbed = false, hasNextEmbed = false,
    onNavigatePrevious, onNavigateNext, navigateDirection, showChatButton = false, onShowChat }: Props = $props();
  const check = $derived(checkViewFromSkill(data.decodedContent ?? {}, embedId ?? 'draft-check'));
  const sourceChat = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT);

  let project = $state<ProjectViewModel | null>(null);
  let resolved = $state(false);
  let saving = $state(false);
  let saved = $state(false);
  let failed = $state(false);

  onMount(async () => {
    const chatId = sourceChat?.chatId ?? get(activeChatStore);
    try {
      const index = chatId ? await loadChatProjectIndex() : [];
      const home = index.find((entry) => entry.chats.some((chat) => chat.chatId === chatId));
      project = home ? await getProject(home.id) : null;
    } catch (error) {
      console.error('[CheckSkillEmbedFullscreen] project lookup failed:', error);
      project = null;
    }
    resolved = true;
  });

  async function save(): Promise<void> {
    if (!project || saving) return;
    saving = true; failed = false;
    try {
      await createProjectCheck(project, draftFromSkill(data.decodedContent ?? {}));
      saved = true;
    } catch (error) {
      console.error('[CheckSkillEmbedFullscreen] save failed:', error);
      failed = true;
    } finally { saving = false; }
  }
</script>

<CheckEmbedFullscreen {check} {onClose} {embedId} {hasPreviousEmbed} {hasNextEmbed}
  {onNavigatePrevious} {onNavigateNext} navigateDirection={navigateDirection ?? undefined}
  {showChatButton} {onShowChat} showActions={false}
  onRun={() => {}} onCancel={() => {}} onConfirm={() => {}} onSelectRun={() => {}} onOpenTestResult={() => {}}>
  {#snippet draftActions()}
    {#if resolved}
      <div class="save-bar" data-testid="check-save-bar">
        {#if project}
          <button type="button" class="save-btn" data-testid="check-save-to-project" disabled={saving || saved} onclick={() => void save()}>
            {saving ? $text('checks.save.saving') : $text('checks.save.button')}
          </button>
        {:else}
          <p class="save-note" data-testid="check-save-no-project">{$text('checks.save.no_project')}</p>
        {/if}
        {#if saved}<p class="save-note" role="status" data-testid="check-save-success">{$text('checks.save.success')}</p>{/if}
        {#if failed}<p class="save-error" role="alert" data-testid="check-save-error">{$text('checks.save.error')}</p>{/if}
      </div>
    {/if}
  {/snippet}
</CheckEmbedFullscreen>

<style>
  .save-bar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--spacing-6); margin: var(--spacing-4) 0; }
  .save-btn { padding: var(--spacing-4) var(--spacing-8); border: none; border-radius: var(--radius-5); background: var(--color-primary, #4867cd); color: #fff; cursor: pointer; }
  .save-btn:disabled { opacity: 0.6; cursor: default; }
  .save-note { margin: 0; color: var(--color-font-secondary); }
  .save-error { margin: 0; color: var(--color-error, #c0392b); }
</style>
