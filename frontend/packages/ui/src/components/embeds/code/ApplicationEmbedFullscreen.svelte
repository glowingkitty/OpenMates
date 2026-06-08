<!--
  frontend/packages/ui/src/components/embeds/code/ApplicationEmbedFullscreen.svelte

  Fullscreen workspace for generated application embeds.
  Uses the application manifest as source of truth and starts a live E2B preview
  only after the user explicitly clicks Start preview.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { authStore } from '../../../stores/authStore';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import {
    buildApplicationPreviewSharedContext,
    getApplicationPreviewStatus,
    startApplicationPreview,
    stopApplicationPreview,
    type ApplicationPreviewStatusValue,
  } from '../../../services/applicationPreviewService';
  import { fetchAndDecryptImage, getCachedImageUrl, retainCachedImage, releaseCachedImage } from '../images/imageEmbedCrypto';

  interface FileRef {
    path?: string;
    embed_id?: string;
    role?: string;
  }

  interface PreviewEvent {
    kind: string;
    text: string;
    timestamp: number;
  }

  interface ScreenshotRef {
    files?: { preview?: { s3_key?: string } };
    s3_base_url?: string;
    aes_key?: string;
    aes_nonce?: string;
  }

  interface Props {
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    chatId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    data,
    onClose,
    embedId,
    chatId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
  }: Props = $props();

  let dc = $derived(data.decodedContent ?? {});
  let appName = $derived(typeof dc.name === 'string' ? dc.name : $text('embeds.application_title'));
  let framework = $derived(typeof dc.framework === 'string' ? dc.framework : '');
  let runtime = $derived(typeof dc.runtime === 'string' ? dc.runtime : '');
  let fileRefs = $derived(Array.isArray(dc.file_refs) ? dc.file_refs as FileRef[] : []);
  let initialScreenshotUrl = $derived(typeof dc.latest_screenshot_url === 'string' ? dc.latest_screenshot_url : '');
  let initialScreenshotRef = $derived((dc.latest_screenshot && typeof dc.latest_screenshot === 'object') ? dc.latest_screenshot as ScreenshotRef : undefined);
  let sessionId = $state<string | null>(null);
  let previewUrl = $state<string | null>(null);
  let latestScreenshotUrl = $state<string>('');
  let latestScreenshotRef = $state<ScreenshotRef | undefined>(undefined);
  let decryptedScreenshotUrl = $state('');
  let retainedScreenshotKey = $state('');
  let previewStatus = $state<ApplicationPreviewStatusValue | 'idle'>('idle');
  let previewEvents = $state<PreviewEvent[]>([]);
  let errorMessage = $state<string | null>(null);
  let isBusy = $state(false);
  let pollTimeout: ReturnType<typeof setTimeout> | null = null;

  let subtitle = $derived([framework, runtime].filter(Boolean).join(' · '));
  let screenshotUrl = $derived(latestScreenshotUrl || initialScreenshotUrl || decryptedScreenshotUrl);
  let canStart = $derived(Boolean(chatId && embedId && !isBusy && previewStatus !== 'running' && previewStatus !== 'starting' && previewStatus !== 'queued'));
  let canStop = $derived(Boolean(sessionId && !isBusy && ['queued', 'starting', 'running'].includes(previewStatus)));
  let canOpenWindow = $derived(Boolean(previewUrl && previewStatus === 'running'));
  let previewStatusLabel = $derived.by(() => {
    if (previewStatus === 'idle') return $text('embeds.application_preview_not_started');
    if (previewStatus === 'queued' || previewStatus === 'starting') return $text('common.loading');
    if (previewStatus === 'running') return $text('embeds.application_live_preview');
    if (previewStatus === 'stopped') return $text('embeds.application_preview_stopped');
    if (previewStatus === 'timeout') return $text('embeds.application_preview_timeout');
    return $text('embeds.application_preview_failed');
  });

  onDestroy(() => {
    clearStatusPoll();
    if (retainedScreenshotKey) releaseCachedImage(retainedScreenshotKey);
  });

  function clearStatusPoll() {
    if (pollTimeout) {
      clearTimeout(pollTimeout);
      pollTimeout = null;
    }
  }

  function scheduleStatusPoll() {
    clearStatusPoll();
    pollTimeout = setTimeout(() => {
      void pollStatus();
    }, 1500);
  }

  async function pollStatus() {
    if (!sessionId || !['queued', 'starting'].includes(previewStatus)) return;
    try {
      const response = await getApplicationPreviewStatus(sessionId);
      previewStatus = response.status;
      previewEvents = response.events ?? previewEvents;
      latestScreenshotUrl = response.latest_screenshot_url ?? latestScreenshotUrl;
      latestScreenshotRef = (response.latest_screenshot as ScreenshotRef | undefined) ?? latestScreenshotRef;
      void loadEncryptedScreenshot();
      if (response.status === 'failed' || response.status === 'timeout') {
        errorMessage = response.error || $text('embeds.application_preview_failed');
        return;
      }
      if (response.status === 'queued' || response.status === 'starting') {
        scheduleStatusPoll();
      }
    } catch (error) {
      previewStatus = 'failed';
      errorMessage = error instanceof Error ? error.message : $text('embeds.application_preview_failed');
    }
  }

  async function handleStartPreview() {
    if (!chatId || !embedId || isBusy) return;
    if (!$authStore.isAuthenticated) {
      window.dispatchEvent(new CustomEvent('openSignupInterface'));
      return;
    }
    isBusy = true;
    errorMessage = null;
    previewEvents = [];
    previewStatus = 'starting';
    try {
      const sharedContext = await buildApplicationPreviewSharedContext(embedId, dc);
      const response = await startApplicationPreview(chatId, embedId, sharedContext);
      sessionId = response.session_id;
      previewUrl = response.preview_url;
      previewStatus = response.status;
      if (response.status === 'queued' || response.status === 'starting') {
        scheduleStatusPoll();
      }
    } catch (error) {
      previewStatus = 'failed';
      errorMessage = error instanceof Error ? error.message : $text('embeds.application_preview_failed');
    } finally {
      isBusy = false;
    }
  }

  async function handleStopPreview() {
    if (!sessionId || isBusy) return;
    clearStatusPoll();
    isBusy = true;
    try {
      const response = await stopApplicationPreview(sessionId);
      previewStatus = response.status as ApplicationPreviewStatusValue;
      const status = await getApplicationPreviewStatus(sessionId);
      previewEvents = status.events ?? previewEvents;
      latestScreenshotUrl = status.latest_screenshot_url ?? latestScreenshotUrl;
      latestScreenshotRef = (status.latest_screenshot as ScreenshotRef | undefined) ?? latestScreenshotRef;
      void loadEncryptedScreenshot();
    } catch (error) {
      errorMessage = error instanceof Error ? error.message : $text('embeds.application_preview_stop_failed');
    } finally {
      isBusy = false;
    }
  }

  function handleOpenPreviewWindow() {
    if (!previewUrl) return;
    window.open(previewUrl, '_blank', 'noopener,noreferrer');
  }

  async function loadEncryptedScreenshot() {
    const source = latestScreenshotRef || initialScreenshotRef;
    const s3Key = source?.files?.preview?.s3_key;
    const aesKey = source?.aes_key;
    const aesNonce = source?.aes_nonce;
    if (retainedScreenshotKey && s3Key !== retainedScreenshotKey) {
      releaseCachedImage(retainedScreenshotKey);
      retainedScreenshotKey = '';
      decryptedScreenshotUrl = '';
    }
    if (latestScreenshotUrl || initialScreenshotUrl || !s3Key || !aesKey || aesNonce === undefined || decryptedScreenshotUrl) return;

    const cached = getCachedImageUrl(s3Key);
    if (cached) {
      decryptedScreenshotUrl = cached;
      retainedScreenshotKey = s3Key;
      retainCachedImage(s3Key);
      return;
    }

    try {
      await fetchAndDecryptImage(source?.s3_base_url || '', s3Key, aesKey, aesNonce);
      const decryptedUrl = getCachedImageUrl(s3Key);
      if (!decryptedUrl) return;
      decryptedScreenshotUrl = decryptedUrl;
      retainedScreenshotKey = s3Key;
      retainCachedImage(s3Key);
    } catch (error) {
      console.warn('[ApplicationEmbedFullscreen] Failed to load encrypted screenshot:', error);
    }
  }

  $effect(() => {
    void loadEncryptedScreenshot();
  });
</script>

<UnifiedEmbedFullscreen
  appId="code"
  skillId="application"
  {onClose}
  skillIconName="coding"
  embedHeaderTitle={appName}
  embedHeaderSubtitle={subtitle}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet embedHeaderCta()}
    <div class="preview-actions">
      {#if canStop}
        <button class="secondary-action" data-testid="application-stop-preview" type="button" onclick={handleStopPreview}>{$text('embeds.application_stop_preview')}</button>
      {/if}
      {#if canOpenWindow}
        <button class="secondary-action" data-testid="application-open-preview-window" type="button" onclick={handleOpenPreviewWindow}>{$text('embeds.application_open_preview_window')}</button>
      {/if}
      <button class="primary-action" data-testid="application-start-preview" type="button" onclick={handleStartPreview} disabled={!canStart}>
        {$text('embeds.application_start_preview')}
      </button>
    </div>
  {/snippet}

  {#snippet content()}
    <div class="application-fullscreen">
      <section class="preview-panel" data-testid="application-preview-panel" aria-label={$text('embeds.application_live_preview')}>
        {#if previewUrl && previewStatus === 'running'}
          <iframe data-testid="application-preview-iframe" title={appName} src={previewUrl} sandbox="allow-scripts allow-forms allow-modals allow-popups" referrerpolicy="no-referrer"></iframe>
        {:else if previewStatus === 'queued' || previewStatus === 'starting'}
          <div class="empty-preview">
            <div class="empty-window" aria-hidden="true"></div>
            <h3>{$text('common.loading')}</h3>
            <p>{$text('embeds.application_ready')}</p>
          </div>
        {:else if screenshotUrl}
          <button class="screenshot-preview" data-testid="application-fullscreen-screenshot" type="button" onclick={handleStartPreview} disabled={!canStart} aria-label={$text('embeds.application_start_preview')}>
            <img src={screenshotUrl} alt="" />
            <span class="play-overlay" aria-hidden="true">▶</span>
          </button>
        {:else}
          <div class="empty-preview">
            <div class="empty-window" aria-hidden="true"></div>
            <h3>{$text('embeds.application_preview_not_started')}</h3>
            <p>{$text('embeds.application_preview_not_started_description')}</p>
            {#if errorMessage}<p class="error-text">{errorMessage}</p>{/if}
          </div>
        {/if}
      </section>

      <aside class="details-panel" aria-label={$text('embeds.application_files')}>
        <section class="status-card" data-testid="application-preview-status">
          <span class="status-label">{previewStatusLabel}</span>
          <span class="status-pill" data-status={previewStatus}>{previewStatus}</span>
          {#if errorMessage}<p class="error-text">{errorMessage}</p>{/if}
        </section>

        <section class="logs-section" data-testid="application-preview-logs">
          <h3>{$text('embeds.application_logs')}</h3>
          {#if previewEvents.length}
            <div class="log-list">
              {#each previewEvents.slice(-8) as event}
                <div class="log-row">
                  <span class="log-kind">{event.kind}</span>
                  <span class="log-text">{event.text}</span>
                </div>
              {/each}
            </div>
          {:else}
            <p class="muted-text">{$text('embeds.application_preview_not_started_description')}</p>
          {/if}
        </section>

        <section class="files-section" data-testid="application-preview-files">
          <h3>{$text('embeds.application_files')}</h3>
          <div class="file-list">
            {#each fileRefs as file}
              <div class="file-row">
                <span class="file-path">{file.path}</span>
                {#if file.role}<span class="file-role">{file.role}</span>{/if}
              </div>
            {/each}
          </div>
        </section>
      </aside>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .preview-actions {
    display: flex;
    gap: var(--spacing-2);
    align-items: center;
  }

  .primary-action,
  .secondary-action {
    border: 0;
    border-radius: var(--radius-2);
    padding: var(--spacing-2) var(--spacing-3);
    font-weight: 600;
    cursor: pointer;
  }

  .primary-action {
    color: var(--color-font-button);
    background: var(--color-app-code);
  }

  .primary-action:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }

  .secondary-action {
    color: var(--color-font-primary);
    background: var(--color-grey-10);
  }

  .application-fullscreen {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(240px, 320px);
    gap: var(--spacing-4);
    height: 100%;
    min-height: 0;
  }

  .preview-panel,
  .details-panel {
    min-height: 0;
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-4);
    background: var(--color-grey-0);
    overflow: hidden;
  }

  .preview-panel iframe {
    width: 100%;
    height: 100%;
    border: 0;
    display: block;
    background: var(--color-grey-0);
  }

  .screenshot-preview {
    position: relative;
    width: 100%;
    height: 100%;
    display: block;
    border: 0;
    padding: 0;
    background: var(--color-grey-10);
    cursor: pointer;
  }

  .screenshot-preview:disabled {
    cursor: not-allowed;
  }

  .screenshot-preview img {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: cover;
  }

  .play-overlay {
    position: absolute;
    inset: 50% auto auto 50%;
    transform: translate(-50%, -50%);
    width: 52px;
    height: 52px;
    display: grid;
    place-items: center;
    border-radius: var(--radius-full);
    color: var(--color-font-button);
    background: var(--color-app-code);
    box-shadow: 0 4px 14px rgb(0 0 0 / 20%);
    font-size: 18px;
  }

  .empty-preview {
    height: 100%;
    display: grid;
    place-content: center;
    justify-items: center;
    gap: var(--spacing-3);
    padding: var(--spacing-6);
    text-align: center;
    color: var(--color-font-secondary);
  }

  .empty-window {
    width: 180px;
    height: 110px;
    border-radius: var(--radius-4);
    background: linear-gradient(135deg, var(--color-grey-10), var(--color-grey-20));
  }

  .empty-preview h3,
  .details-panel h3 {
    margin: 0;
    color: var(--color-font-primary);
  }

  .error-text {
    color: var(--color-error);
  }

  .details-panel {
    display: grid;
    align-content: start;
    gap: var(--spacing-4);
    padding: var(--spacing-4);
    overflow: auto;
  }

  .status-card {
    display: grid;
    gap: var(--spacing-2);
    padding: var(--spacing-3);
    border-radius: var(--radius-3);
    background: var(--color-grey-10);
  }

  .status-label {
    color: var(--color-font-primary);
    font-weight: 600;
  }

  .status-pill {
    width: fit-content;
    border-radius: var(--radius-full);
    padding: var(--spacing-1) var(--spacing-2);
    color: var(--color-font-secondary);
    background: var(--color-grey-20);
    font-size: var(--font-size-tiny);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .status-pill[data-status='running'] {
    color: var(--color-font-button);
    background: var(--color-app-code);
  }

  .logs-section,
  .files-section {
    display: grid;
    gap: var(--spacing-3);
  }

  .log-list {
    display: grid;
    gap: var(--spacing-2);
  }

  .log-row {
    display: grid;
    gap: var(--spacing-1);
    padding: var(--spacing-2);
    border-radius: var(--radius-2);
    background: var(--color-grey-10);
  }

  .log-kind,
  .muted-text {
    color: var(--color-font-secondary);
    font-size: var(--font-size-tiny);
  }

  .log-kind {
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .log-text {
    color: var(--color-font-primary);
    font-size: var(--font-size-xs);
  }

  .file-list {
    display: grid;
    gap: var(--spacing-2);
  }

  .file-row {
    display: grid;
    gap: var(--spacing-1);
    padding: var(--spacing-2);
    border-radius: var(--radius-2);
    background: var(--color-grey-10);
  }

  .file-path {
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', 'Consolas', monospace;
    font-size: var(--font-size-xs);
    color: var(--color-font-primary);
  }

  .file-role {
    font-size: var(--font-size-tiny);
    color: var(--color-font-secondary);
  }

  @container (max-width: 760px) {
    .application-fullscreen {
      grid-template-columns: 1fr;
    }
  }
</style>
