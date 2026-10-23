<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { draftEditorUIState } from '../drafts/draftState';
  import { prepareChatForSend, reserveInitialComposerChatId } from '../preparedChatForSend';

  let { initialize }: { initialize: () => Promise<void> } = $props();
  let allocations = $state(0);
  const createId = () => { allocations += 1; return `new-${allocations}`; };
  let temporaryChatId = $state(reserveInitialComposerChatId({
    chat: null, temporaryChatId: null, selectedChatId: null,
    showWelcome: true, hasMessages: false, hasLiveDraftContent: false,
  }, createId));

  onMount(() => {
    void initialize().then(() => {
      temporaryChatId = reserveInitialComposerChatId({
        chat: null, temporaryChatId, selectedChatId: null,
        showWelcome: true, hasMessages: false, hasLiveDraftContent: false,
      }, createId);
    });
  });

  function focus() {
    if (!temporaryChatId) return;
    const draftId = get(draftEditorUIState).currentChatId;
    prepareChatForSend({ currentChatId: temporaryChatId,
      draftChatId: draftId });
  }
</script>
<input aria-label="Fresh chat composer" onfocus={focus} />
<output data-testid="shell-id">{temporaryChatId ?? ''}</output>
<output data-testid="allocation-count">{allocations}</output>
