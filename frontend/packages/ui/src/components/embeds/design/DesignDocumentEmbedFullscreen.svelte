<!-- figma-visual-proof: not-required. Reuses the original Design viewer. -->
<script lang="ts">
  import { getContext } from 'svelte';
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedFullscreenRawData, type EmbedSourceChatContext } from '../../../types/embedFullscreen';
  import { authStore } from '@repo/ui';
  import { chatTeamOf, contentEditScope } from '../../../services/rustCore/embeds/embedContentEdit';
  import type { EmbedEditScope } from '../../../services/rustCore/embeds/embedEditProtocol';
  import { embedContentAtVersion, noteEmbedHeadChanged } from '../../../services/rustCore/embeds/messageEmbedVersion';
  import { getWorkspaceCacheEpoch } from '../../../services/workspaceCacheLifecycle';
  import EmbedFullscreenLoading from '../EmbedFullscreenLoading.svelte';
  import EmbedVersionTimeline from '../shared/EmbedVersionTimeline.svelte';
  import DesignEditorFullscreen from './editor/DesignEditorFullscreen.svelte';
  import type { DesignDocument } from './editor/designDocument';
  import { readDesignView, serializeDesign } from './editor/designView';
  import { readDesignImage } from './editor/designViewAssets';
  import { saveDesignRevision } from './editor/designSave';
  import { writeEmbedToClipboard } from '../../../message_parsing/serializers';

  interface Props {
    data: EmbedFullscreenRawData;
    embedId?: string;
    onClose: () => void;
  }

  let { data, embedId, onClose }: Props = $props();
  const context = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT);
  let loaded = $state.raw<{ id: string | undefined; chat: string | null; epoch: number; requiresAuth: boolean;
    design: DesignDocument; version: number } | null>(null);
  type LoadedVersion = { id: string; chat: string; epoch: number; design: DesignDocument; version: number };
  let saved = $state.raw<LoadedVersion | null>(null);
  let historical = $state.raw<LoadedVersion | null>(null);
  let historyError = $state(false);
  let historyLoading = $state(false);
  let historyRequest = 0;
  let checkedScope = $state.raw<{ chat: string; scope: EmbedEditScope } | null>(null);
  let failed = $state(false);
  let proposalState = $state.raw<{ id: string; status: 'applying' | 'applied' | 'conflict' | 'error' } | null>(null);
  let copyStatus = $state.raw<{ id: string; copied: boolean } | null>(null);
  const proposalStatus = $derived(proposalState?.id === embedId ? proposalState?.status : undefined);
  const chatId = $derived(context?.exampleChatId ? null : context?.lookupChatId ?? context?.chatId ?? null);
  const ownerChat = $derived($authStore.isAuthenticated && context?.isReadOnly === false &&
    context.chatId === chatId ? chatId : null);
  const scope = $derived(checkedScope && checkedScope.chat === ownerChat ? checkedScope.scope : null);
  const serverVersion = $derived(typeof data.embedData?.version_number === 'number' ? data.embedData.version_number : 1);
  const local = $derived(saved && saved.id === embedId && saved.chat === ownerChat &&
    saved.epoch === getWorkspaceCacheEpoch() && saved.version >= serverVersion ? saved : null);
  const remote = $derived(loaded && loaded.id === embedId && loaded.chat === chatId &&
    loaded.epoch === getWorkspaceCacheEpoch() && (!loaded.requiresAuth || $authStore.isAuthenticated) ? loaded : null);
  const headVersion = $derived(local?.version ?? remote?.version ?? serverVersion);
  const head = $derived(local?.design ?? remote?.design ?? null);
  const past = $derived(historical && historical.id === embedId && historical.chat === ownerChat &&
    historical.epoch === getWorkspaceCacheEpoch() ? historical : null);
  const readImage = $derived.by(() => {
    const id = head?.proposal?.embedId ?? embedId;
    const sourceChat = chatId;
    return (asset: string) => id && sourceChat ? readDesignImage(asset, id, sourceChat) : Promise.resolve(null);
  });

  const readExportImage = $derived.by(() => {
    const id = embedId;
    const sourceChat = chatId;
    return (asset: string) => id && sourceChat ? readDesignImage(asset, id, sourceChat, { localOnly: true }) : Promise.resolve(null);
  });

  $effect(() => {
    const owner = ownerChat;
    const epoch = getWorkspaceCacheEpoch();
    let current = true;
    checkedScope = null;
    if (owner) {
      void chatTeamOf(owner).then((team) => {
        const resolved = contentEditScope({ chatId: owner, chatTeamId: team });
        if (current && resolved && getWorkspaceCacheEpoch() === epoch) checkedScope = { chat: owner, scope: resolved };
      }, () => { if (current) checkedScope = null; });
    }
    return () => { current = false; };
  });

  $effect(() => {
    const input = data.embedData?.content;
    const decoded = data.decodedContent;
    const id = embedId;
    const chat = chatId;
    const requiresAuth = !!chat && context?.isReadOnly === false;
    const version = serverVersion;
    const epoch = getWorkspaceCacheEpoch();
    let current = true;
    failed = false;
    void readDesignView(decoded, input).then((result) => {
      if (current && getWorkspaceCacheEpoch() === epoch) {
        loaded = result ? { id, chat, epoch, requiresAuth, design: result, version } : null;
        failed = !result;
      }
    }, () => {
      if (current) {
        loaded = null;
        failed = true;
      }
    });
    return () => { current = false; };
  });

  async function save(baseVersion: number, next: DesignDocument) {
    const id = embedId;
    const chat = ownerChat;
    const writeScope = scope;
    const epoch = getWorkspaceCacheEpoch();
    if (!id || !chat || !writeScope) throw new Error('The design is read-only.');
    const version = await saveDesignRevision(id, writeScope, baseVersion, next);
    if (embedId === id && ownerChat === chat && getWorkspaceCacheEpoch() === epoch) {
      saved = { id, chat, epoch, design: next, version };
      noteEmbedHeadChanged(id);
    }
  }

  async function copyDesign() {
    if (!embedId || !head || head.proposal || !scope) return;
    const reference = { type: 'design-document' as const, id: embedId, status: 'finished' as const,
      contentRef: `embed:${embedId}`, referenceOnly: true };
    const block = JSON.stringify({ type: reference.type, embed_id: embedId });
    try {
      await writeEmbedToClipboard(reference, "```json\n" + block + "\n```");
      copyStatus = { id: reference.id, copied: true };
    } catch {
      copyStatus = { id: reference.id, copied: false };
    }
  }

  async function applyProposal() {
    const id = embedId;
    const writeScope = scope;
    const selected = head;
    const proposal = selected?.proposal;
    if (!id || !writeScope || !selected || !proposal || proposalStatus === 'applying') return;
    const epoch = getWorkspaceCacheEpoch();
    const current = () => embedId === id && epoch === getWorkspaceCacheEpoch();
    proposalState = { id, status: 'applying' };
    try {
      await saveDesignRevision(proposal.embedId, writeScope, proposal.baseVersion, selected);
      if (current()) {
        noteEmbedHeadChanged(proposal.embedId);
        proposalState = { id, status: 'applied' };
      }
    } catch (error) {
      if (current()) {
        const conflict = (error as { code?: string } | null)?.code === 'embed_version_conflict';
        proposalState = { id, status: conflict ? 'conflict' : 'error' };
      }
    }
  }

  function selectVersion(version: number, content: string | null) {
    const request = ++historyRequest;
    const id = embedId;
    const chat = ownerChat;
    const epoch = getWorkspaceCacheEpoch();
    historyError = false;
    if (!content || !id || !chat) {
      historical = null;
      historyLoading = false;
      return;
    }
    void readDesignView({}, content).then((design) => {
      if (request !== historyRequest || embedId !== id || ownerChat !== chat || getWorkspaceCacheEpoch() !== epoch) return;
      historical = design ? { id, chat, epoch, design, version } : null;
      historyError = !design;
      historyLoading = false;
    }, () => {
      if (request === historyRequest && embedId === id && ownerChat === chat && getWorkspaceCacheEpoch() === epoch) {
        historical = null;
        historyError = true;
        historyLoading = false;
      }
    });
  }
</script>

{#snippet assistantTools()}
  {#if head?.proposal}
    <div class="assistant-actions" aria-live="polite" data-testid="design-proposal-controls">
      {#if !scope}
        <span>Proposed revision</span>
      {:else if proposalStatus === 'applied'}
        <span>Changes applied.</span>
      {:else if proposalStatus === 'conflict'}
        <span>The original design has changed. Ask for a new revision.</span>
      {:else}
        <button type="button" data-testid="design-proposal-apply" disabled={proposalStatus === 'applying'} onclick={applyProposal}>
          {proposalStatus === 'applying' ? 'Applying…' : 'Apply changes to original'}
        </button>
        {#if proposalStatus === 'error'}<span>Could not apply changes. Try again.</span>{/if}
      {/if}
    </div>
  {:else}
    <div class="assistant-actions">
      <button type="button" data-testid="design-copy-for-chat" onclick={copyDesign}>
        {copyStatus?.id === embedId && copyStatus?.copied ? 'Copied. Paste into chat' : 'Copy design for chat'}
      </button>
      {#if copyStatus?.id === embedId && copyStatus?.copied === false}<span role="alert">Could not copy the Design.</span>{/if}
    </div>
  {/if}
{/snippet}

{#snippet versionHistory()}
  {#if embedId && ownerChat && head && headVersion > 1}
    {@const id = embedId}
    {@const chat = ownerChat}
    <EmbedVersionTimeline embedId={id} chatId={chat} currentVersion={headVersion}
      currentContent={serializeDesign(head)} showChangesToggle={false}
      loadVersionContent={(version) => embedContentAtVersion(chat, id, version)}
      onVersionPending={() => { historyLoading = true; }}
      onVersionError={() => { historyLoading = false; historyError = true; }}
      onVersionSelect={selectVersion} />
    {#if historyError}<p role="alert" data-testid="design-history-error">This version could not be opened.</p>{/if}
  {/if}
{/snippet}

{#if head}
  {#key embedId}
    <DesignEditorFullscreen {embedId} owningChatId={chatId ?? undefined} document={past?.design ?? head} versionNumber={past?.version ?? headVersion}
      readOnly={!scope || !embedId || !!head.proposal || !!past || historyLoading}
      revision={scope && embedId && !head.proposal ? { version: headVersion, save } : undefined} {readImage} {versionHistory}
      assistantTools={head.proposal || scope && !past ? assistantTools : undefined}
      allowExport={!head.proposal && !historyLoading} {readExportImage} {onClose} />
  {/key}
{:else}
  <EmbedFullscreenLoading data={{ ...data, embedType: 'design-document' }} {failed} {onClose} />
{/if}

<style>
  .assistant-actions {
    display: flex;
    align-items: center;
    gap: var(--spacing-2);
    padding: var(--spacing-2) var(--spacing-4);
    font-size: var(--font-size-small);
  }

  .assistant-actions button {
    padding: var(--spacing-2) var(--spacing-3);
    border: 1px solid var(--color-grey-50);
    background: var(--color-grey-5);
    border-radius: var(--radius-3);
    color: inherit;
    cursor: pointer;
  }
</style>
