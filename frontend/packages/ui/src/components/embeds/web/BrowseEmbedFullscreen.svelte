<script lang="ts">
  import { getContext } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import BrowseSessionViewer from './BrowseSessionViewer.svelte';
  import { text } from '../../../i18n/translations';
  import { authStore } from '../../../stores/authState';
  import { userProfile } from '../../../stores/userProfile';
  import { activeTeamContext } from '../../../stores/teamStore';
  import { browseContent, browseStatusKey } from './browseContent';
  import { renderBrowse } from './browseEmbedText';
  import { webBrowseClient, type BrowseSession } from '../../../services/webBrowseService';
  import { queueAppsWorkspaceChatHandoff, captureAppsWorkspaceHandoffGuard } from '../../../services/appsWorkspaceChatHandoffService';
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedSourceChatContext, type EmbedFullscreenRawData, type EmbedFullscreenCommonProps } from '../../../types/embedFullscreen';
  interface Props extends EmbedFullscreenCommonProps { data: EmbedFullscreenRawData; }
  let { data, onClose, embedId, hasPreviousEmbed, hasNextEmbed, onNavigatePrevious, onNavigateNext,
    navigateDirection, showChatButton, onShowChat }: Props = $props();
  const source = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT);
  const ownerCurrent = captureAppsWorkspaceHandoffGuard();
  let updated = $state<Record<string, unknown> | null>(null);
  let result = $derived(browseContent(updated || data.decodedContent));
  // Public examples and shared read-only results never open an authenticated
  // viewer. Account/team changes destroy the live frame and abort all requests.
  let canView = $derived($authStore.isAuthenticated && !!$userProfile.user_id && !source?.exampleChatId && !source?.lookupChatId);
  async function continueInChat(session: BrowseSession) {
    if (!ownerCurrent() || session.session_id !== result.sessionId || !session.chat_id
      || (source?.chatId && source.chatId !== session.chat_id)) throw new Error('browser_chat_changed');
    const request = {
      text: $text('embeds.browse.continue_message', { values: { session: session.session_id, limit: String(session.max_credits) } }),
      attachments: [], context: { chat_id: session.chat_id, ...(embedId ? { embed_id: embedId } : {}) },
      ...(embedId ? { embedReference: { embedId, type: 'app-skill-use', appId: 'web', skillId: 'browse' } } : {}),
    };
    onClose();
    if (ownerCurrent()) await queueAppsWorkspaceChatHandoff(request);
  }
</script>

<UnifiedEmbedFullscreen appId="web" skillId="browse" skillIconName="website" {onClose} {embedId}
  {hasPreviousEmbed} {hasNextEmbed} {onNavigatePrevious} {onNavigateNext} {navigateDirection} {showChatButton} {onShowChat}
  testId="browse-fullscreen" embedHeaderTitle={result.title || $text('embeds.browse.title')}
  embedHeaderSubtitle={$text(browseStatusKey(result.status))}
  owningChatId={source?.chatId || undefined}
  onCopy={() => { void navigator.clipboard.writeText(renderBrowse(updated || data.decodedContent)); }}
  onEmbedDataUpdated={({ decodedContent }) => { updated = decodedContent; }}>
  {#snippet content()}
    <div class="browse-content">
      {#if result.url}<p class="url">{result.url}</p>{/if}
      {#if canView && result.sessionId}
        {#key `${$userProfile.user_id}:${$activeTeamContext.teamId}:${$activeTeamContext.epoch}:${result.sessionId}`}
          <BrowseSessionViewer sessionId={result.sessionId} client={webBrowseClient} savedFrame={result.screenshot} onContinue={continueInChat} />
        {/key}
      {:else if result.screenshot}<img class="saved" src={result.screenshot} alt={$text('embeds.browse.saved_frame')} />
      {:else}<p>{$text('embeds.browse.waiting_frame')}</p>{/if}
      {#if result.reason}<p class="reason">{result.reason}</p>{/if}
      {#if result.data !== null}
        <details><summary>{$text('embeds.browse.structured_data')}</summary><pre data-testid="browse-json">{JSON.stringify(result.data, null, 2)}</pre></details>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .browse-content { width: 100%; max-width: 64rem; margin: 0 auto; padding: var(--spacing-8); display: flex; flex-direction: column; gap: var(--spacing-8); box-sizing: border-box; color: var(--color-font-primary); }
  .url, .reason { margin: 0; overflow-wrap: anywhere; font-size: .875rem; color: var(--color-font-secondary); }
  .saved { width: 100%; height: auto; border-radius: var(--radius-4); }
  summary { cursor: pointer; padding: var(--spacing-4) 0; }
  pre { padding: var(--spacing-8); margin: 0; border-radius: var(--radius-4); background: var(--color-grey-10); overflow: auto; max-height: 24rem; white-space: pre-wrap; overflow-wrap: anywhere; font-size: .875rem; }
  @container fullscreen (max-width: 500px) { .browse-content { padding: var(--spacing-6); } }
</style>
