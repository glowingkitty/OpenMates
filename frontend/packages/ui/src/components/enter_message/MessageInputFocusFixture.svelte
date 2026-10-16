<script lang="ts">
  import { onMount, tick } from 'svelte';
  import MessageInput from './MessageInput.svelte';
  import { getEditorInstance } from '../../services/drafts/draftCore';
  import { draftEditorUIState } from '../../services/drafts/draftState';

  let composer = $state<{ setDraftContent: (id: string, content: typeof textOnlyDraft, version: number) => Promise<void>; dismissFocus: () => void }>();
  let { emptyDraft = false, mathDraft = false }: { emptyDraft?: boolean; mathDraft?: boolean } = $props();
  let restored = $state(false);
  const ready = $derived(restored && !$draftEditorUIState.isSwitchingContext);
  let focused = $state(false);
  let attachments = $state(0);
  const chatId = 'synthetic-composer-focus';
  let activeChatId = $state(chatId);
  let switched = $state(false);
  // The production write-mode editor keeps math as raw Markdown text.
  const textOnlyDraft = $derived({ type: 'doc', content: [{ type: 'paragraph', content: [{
    type: 'text', text: emptyDraft ? '   ' : mathDraft ? '$$x^2 + y^2$$' : 'Unsent multiline\nsecond line',
  }] }] });

  onMount(() => {
    const restore = () => void composer?.setDraftContent(chatId, textOnlyDraft, 2);
    const switchToEmptyDraft = async () => {
      const empty = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: '   ' }] }] };
      activeChatId = 'synthetic-empty-draft';
      sessionStorage.setItem(`draft_${activeChatId}`, JSON.stringify({ markdown: '   ', preview: '', tiptapJSON: empty, timestamp: Date.now() }));
      await composer?.setDraftContent(activeChatId, empty, 1);
      switched = true;
    };
    const addAttachments = () => {
      const editor = getEditorInstance();
      if (!editor) throw new Error('Composer editor is not mounted');
      editor.commands.insertContent([
        { type: 'embed', attrs: { id: 'synthetic-image', type: 'image', status: 'uploading', filename: 'Fixture image.png', src: '/favicon-32x32.png' } },
        { type: 'embed', attrs: { id: 'synthetic-audio', type: 'recording', status: 'transcribing', filename: 'Fixture audio.webm', duration: 4 } },
      ]);
      attachments += 1;
    };
    window.addEventListener('fixtureRestoreDraft', restore);
    window.addEventListener('fixtureAddAttachments', addAttachments);
    window.addEventListener('fixtureSwitchEmptyDraft', switchToEmptyDraft);
    void tick().then(async () => {
      sessionStorage.setItem(`draft_${chatId}`, JSON.stringify({ markdown: emptyDraft ? '   ' : mathDraft ? '$$x^2 + y^2$$' : 'Unsent multiline\nsecond line', preview: '', tiptapJSON: textOnlyDraft, timestamp: Date.now() }));
      await composer?.setDraftContent(chatId, textOnlyDraft, 1);
      restored = true;
    });
    return () => {
      window.removeEventListener('fixtureRestoreDraft', restore);
      window.removeEventListener('fixtureAddAttachments', addAttachments);
      window.removeEventListener('fixtureSwitchEmptyDraft', switchToEmptyDraft);
    };
  });
</script>

<div class="fixture" data-testid="composer-focus-fixture" data-ready={ready} data-switched={switched} data-attachments-added={attachments}>
  <MessageInput bind:this={composer} currentChatId={activeChatId} showActionButtons={false} bind:isFocused={focused}
    onAssistantSpeechPreferenceChange={() => {}} />
  {#if focused}<button type="button" data-testid="fixture-composer-cancel" data-composer-focus-control onclick={() => composer?.dismissFocus()}>Cancel</button>{/if}
</div>
<style>
  .fixture { width: min(100%, 680px); padding: 1rem; box-sizing: border-box; }
</style>
