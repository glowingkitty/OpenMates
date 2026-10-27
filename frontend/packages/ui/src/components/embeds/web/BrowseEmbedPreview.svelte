<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '../../../i18n/translations';
  import { browseContent, browseStatusKey } from './browseContent';
  import { webBrowseClient } from '../../../services/webBrowseService';
  interface Props {
    id: string;
    content?: Record<string, unknown>;
    previewData?: Record<string, unknown>;
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    isMobile?: boolean;
    onFullscreen: () => void;
  }
  let { id, content = {}, previewData, status = 'processing', isMobile = false, onFullscreen }: Props = $props();
  let updated = $state<Record<string, unknown> | null>(null);
  let result = $derived(browseContent(updated || previewData || content));
  let envelope = $derived(updated || previewData || content);
  let shellStatus = $derived((envelope.status || status) as 'processing' | 'finished' | 'error' | 'cancelled');
  let stopping = $state(false);
  let stopRequested = $state(false);
  let stopError = $state(false);
  async function stop() {
    if (!result.sessionId || stopping) return;
    stopping = true; stopError = false;
    try {
      const reply = await webBrowseClient.control(result.sessionId, { operation: 'stop' }, new AbortController().signal);
      if (reply.session_id !== result.sessionId || reply.status !== 'paused') throw new Error('browser_stop_unconfirmed');
      updated = { ...envelope, status: 'cancelled' };
    } catch { stopError = true; }
    finally { stopRequested = false; stopping = false; }
  }
  // An early Stop waits for the encrypted admission identity. It never claims
  // cancellation before the owned execution has acknowledged the request.
  $effect(() => { if (stopRequested && result.sessionId && !stopping) void stop(); });
</script>

<UnifiedEmbedPreview {id} appId="web" skillId="browse" skillIconName="website" skillName={$text('embeds.browse.title')}
  status={shellStatus} {isMobile} {onFullscreen} hasProcessingActions optimisticStop={false} onStop={() => { stopRequested = true; }}
  customStatusText={$text(stopRequested ? 'embeds.browse.stopping' : browseStatusKey(result.status))}
  onEmbedDataUpdated={({ decodedContent }) => { updated = decodedContent; }}>
  {#snippet details()}
    <div class="browse-preview" data-testid="browse-preview">
      {#if result.screenshot}<img src={result.screenshot} alt={$text('embeds.browse.saved_frame')} />{/if}
      <div class="title">{result.title || result.url || result.task || $text('embeds.browse.title')}</div>
      {#if stopError}<p role="alert">{$text('embeds.browse.connection_error')}</p>{/if}
      {#if shellStatus === 'processing'}
        <button type="button" onclick={(event) => { event.stopPropagation(); onFullscreen(); }}>{$text('embeds.browse.watch')}</button>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .browse-preview { display: flex; flex-direction: column; gap: var(--spacing-3); height: 100%; min-width: 0; }
  img { width: 100%; min-height: 0; flex: 1; object-fit: contain; border-radius: var(--radius-3); background: var(--color-grey-100); }
  .title { font-size: 1rem; font-weight: 600; color: var(--color-font-primary); overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow-wrap: anywhere; }
  button { align-self: flex-start; font: inherit; border: 0; background: var(--color-grey-20); color: var(--color-font-primary); border-radius: var(--radius-full); min-height: 36px; padding: var(--spacing-3) var(--spacing-6); cursor: pointer; }
  button:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  p { margin: 0; font-size: .875rem; color: var(--color-error); }
</style>
