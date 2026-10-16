<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { draftEditorUIState } from '../drafts/draftState';
  import { getPreparedChatForSend, prepareChatForSend } from '../preparedChatForSend';
  import { canBindUnclaimedFreshShell, reserveInitialFreshShellId } from '../../utils/chatDraftState';

  let { initialize }: { initialize: () => Promise<void> } = $props();
  let temporaryChatId = $state<string | null>(null);
  let preparedChatId = $state<string | null>(null);
  let allocations = $state(0);
  const createId = () => { allocations += 1; return `new-${allocations}`; };

  onMount(() => {
    const draftId = get(draftEditorUIState).currentChatId;
    temporaryChatId = reserveInitialFreshShellId({
      chat: null, temporaryChatId, selectedChatId: null,
      preparedDraftChatId: draftId && getPreparedChatForSend(draftId) ? draftId : null,
      showWelcome: true, hasMessages: false,
    }, createId);
    void initialize().then(() => {
      temporaryChatId = reserveInitialFreshShellId({
        chat: null, temporaryChatId, selectedChatId: null, preparedDraftChatId: null,
        showWelcome: true, hasMessages: false,
      }, createId);
    });
  });

  function focus() {
    if (!temporaryChatId) return;
    const draftId = get(draftEditorUIState).currentChatId;
    if (canBindUnclaimedFreshShell({
      chat: null, temporaryChatId, composerChatId: temporaryChatId, draftChatId: draftId,
      activeChatId: null, pendingDraftSelection: false, hasMessages: false,
      hasLiveDraftContent: false, showWelcome: true, authenticated: true,
      accountId: 'account-a', teamId: null, incognito: false,
    })) {
      draftEditorUIState.update(state => state.currentChatId ? state
        : { ...state, currentChatId: temporaryChatId });
    }
    prepareChatForSend({ currentChatId: temporaryChatId,
      draftChatId: get(draftEditorUIState).currentChatId, freshNewChatShell: true });
    preparedChatId = getPreparedChatForSend(temporaryChatId)?.shell.chat_id ?? null;
  }
</script>
<input aria-label="Fresh chat composer" onfocus={focus} />
<output data-testid="shell-id">{temporaryChatId ?? ''}</output>
<output data-testid="prepared-id">{preparedChatId ?? ''}</output>
<output data-testid="allocation-count">{allocations}</output>
