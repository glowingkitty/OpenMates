<!--
  frontend/packages/ui/src/components/embeds/code/ApplicationEmbedPreview.svelte

  Preview component for generated application embeds.
  Shows project metadata, latest screenshot/placeholder, and an explicit play
  affordance. Finished generated apps auto-start once to capture their thumbnail.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { fetchAndDecryptImage, getCachedImageUrl, retainCachedImage, releaseCachedImage } from '../images/imageEmbedCrypto';
  import { activeChatStore } from '../../../stores/activeChatStore';
  import { authStore } from '../../../stores/authStore';
  import {
    buildApplicationPreviewSharedContext,
    getApplicationPreviewStatus,
    startApplicationPreview,
    type ApplicationPreviewStatus,
    type ApplicationPreviewStatusValue,
  } from '../../../services/applicationPreviewService';

  const AUTO_START_STATUS_ATTEMPTS = 40;
  const AUTO_START_STATUS_DELAY_MS = 2_000;
  const ACTIVE_PREVIEW_STATUSES = new Set<ApplicationPreviewStatusValue>(['queued', 'starting', 'running']);

  interface FileRef {
    path?: string;
    embed_id?: string;
    role?: string;
  }

  interface ScreenshotRef {
    files?: { preview?: { s3_key?: string; encryption?: string } };
    s3_base_url?: string;
    aes_key?: string;
    aes_nonce?: string;
  }

  interface Props {
    id: string;
    name?: string;
    framework?: string;
    runtime?: string;
    file_refs?: FileRef[];
    entrypoints?: Array<Record<string, unknown>>;
    latest_screenshot_url?: string;
    latest_screenshot?: ScreenshotRef;
    status: 'processing' | 'finished' | 'error';
    taskId?: string;
    chatId?: string;
    sourceMessageId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    name = '',
    framework = '',
    runtime = '',
    file_refs = [],
    entrypoints = [],
    latest_screenshot_url,
    latest_screenshot,
    status,
    taskId,
    chatId,
    sourceMessageId,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  const skillIconName = 'coding';
  let fileCount = $derived(Array.isArray(file_refs) ? file_refs.length : 0);
  let entrypointCount = $derived(Array.isArray(entrypoints) ? entrypoints.length : 0);
  let skillName = $derived(name || $text('embeds.application_title'));
  let decryptedScreenshotUrl = $state('');
  let retainedScreenshotKey = $state('');
  let latestScreenshotUrl = $state('');
  let latestScreenshotRef = $state<ScreenshotRef | undefined>(undefined);
  let autoStartRequested = $state(false);
  let destroyed = false;
  let screenshotUrl = $derived(latestScreenshotUrl || latest_screenshot_url || decryptedScreenshotUrl);
  let screenshotRef = $derived(latestScreenshotRef || latest_screenshot);
  let statusText = $derived.by(() => {
    if (status === 'processing') return $text('embeds.processing');
    if (status === 'error') return $text('embeds.application_preview_failed');
    const facts = [framework, runtime, fileCount ? $text('embeds.application_file_count', { values: { count: String(fileCount) } }) : ''].filter(Boolean);
    return facts.join(' · ') || $text('embeds.application_ready');
  });

  function handleStop() {
    // Live preview sessions are started/stopped from fullscreen in this slice.
  }

  async function loadEncryptedScreenshot() {
    const previewVariant = screenshotRef?.files?.preview;
    const s3Key = previewVariant?.s3_key;
    const aesKey = screenshotRef?.aes_key;
    const aesNonce = screenshotRef?.aes_nonce;
    if (retainedScreenshotKey && s3Key !== retainedScreenshotKey) {
      releaseCachedImage(retainedScreenshotKey);
      retainedScreenshotKey = '';
      decryptedScreenshotUrl = '';
    }
    if (latest_screenshot_url || !s3Key || !aesKey || aesNonce === undefined || decryptedScreenshotUrl) return;

    const cached = getCachedImageUrl(s3Key);
    if (cached) {
      decryptedScreenshotUrl = cached;
      retainedScreenshotKey = s3Key;
      retainCachedImage(s3Key);
      return;
    }

    try {
      await fetchAndDecryptImage(screenshotRef?.s3_base_url || '', s3Key, aesKey, aesNonce, previewVariant);
      const decryptedUrl = getCachedImageUrl(s3Key);
      if (!decryptedUrl) return;
      decryptedScreenshotUrl = decryptedUrl;
      retainedScreenshotKey = s3Key;
      retainCachedImage(s3Key);
    } catch (error) {
      console.warn('[ApplicationEmbedPreview] Failed to load encrypted screenshot:', error);
    }
  }

  function applicationContent(): Record<string, unknown> {
    return {
      type: 'application',
      name,
      framework,
      runtime,
      file_refs,
      entrypoints,
    };
  }

  function applyStatusResponse(response: ApplicationPreviewStatus) {
    latestScreenshotUrl = response.latest_screenshot_url ?? latestScreenshotUrl;
    latestScreenshotRef = (response.latest_screenshot as ScreenshotRef | undefined) ?? latestScreenshotRef;
    void loadEncryptedScreenshot();
  }

  async function pollForAutoStartedScreenshot(sessionId: string) {
    for (let attempt = 0; attempt < AUTO_START_STATUS_ATTEMPTS && !destroyed; attempt += 1) {
      const response = await getApplicationPreviewStatus(sessionId);
      applyStatusResponse(response);
      if (response.latest_screenshot_url || response.latest_screenshot) return;
      if (!ACTIVE_PREVIEW_STATUSES.has(response.status)) return;
      await new Promise((resolve) => setTimeout(resolve, AUTO_START_STATUS_DELAY_MS));
    }
  }

  async function maybeAutoStartThumbnailCapture() {
    const resolvedChatId = chatId || $activeChatStore || undefined;
    if (
      autoStartRequested ||
      status !== 'finished' ||
      screenshotUrl ||
      !resolvedChatId ||
      !id ||
      !$authStore.isAuthenticated
    ) return;

    autoStartRequested = true;
    try {
      const sharedContext = await buildApplicationPreviewSharedContext(id, applicationContent());
      const session = await startApplicationPreview(resolvedChatId, id, {
        sharedContext,
        autoStarted: true,
        sourceMessageId,
      });
      await pollForAutoStartedScreenshot(session.session_id);
    } catch (error) {
      console.warn('[ApplicationEmbedPreview] Failed to auto-start thumbnail capture:', error);
    }
  }

  $effect(() => {
    void loadEncryptedScreenshot();
  });

  $effect(() => {
    void maybeAutoStartThumbnailCapture();
  });

  onDestroy(() => {
    destroyed = true;
    if (retainedScreenshotKey) releaseCachedImage(retainedScreenshotKey);
  });
</script>

<UnifiedEmbedPreview
  {id}
  appId="code"
  skillId="application"
  {skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  showStatus={true}
  customStatusText={statusText}
  showSkillIcon={false}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="application-preview" class:mobile={isMobileLayout} data-testid="application-preview-details">
      <div class="screenshot-frame" data-testid="application-preview-screenshot">
        {#if screenshotUrl}
          <img src={screenshotUrl} alt="" class="screenshot" data-testid="application-preview-screenshot-image" />
        {:else}
          <div class="placeholder" aria-hidden="true">
            <span class="app-window-dot"></span>
            <span class="app-window-line wide"></span>
            <span class="app-window-line"></span>
            <span class="app-window-card"></span>
          </div>
        {/if}
        <div class="play-overlay" data-testid="application-preview-play-overlay" aria-hidden="true">▶</div>
      </div>
      <div class="meta-row">
        <span>{fileCount} {$text(fileCount === 1 ? 'embeds.application_file_singular' : 'embeds.application_file_plural')}</span>
        {#if entrypointCount}
          <span>{entrypointCount} {$text(entrypointCount === 1 ? 'embeds.application_entrypoint_singular' : 'embeds.application_entrypoint_plural')}</span>
        {/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .application-preview {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
    height: 100%;
    min-height: 0;
  }

  .screenshot-frame {
    position: relative;
    flex: 1;
    min-height: 0;
    border-radius: var(--radius-3);
    overflow: hidden;
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-20);
  }

  .screenshot {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .placeholder {
    display: grid;
    grid-template-columns: 1fr;
    gap: var(--spacing-2);
    padding: var(--spacing-3);
    height: 100%;
    align-content: start;
  }

  .app-window-dot,
  .app-window-line,
  .app-window-card {
    display: block;
    border-radius: var(--radius-full);
    background: var(--color-grey-30);
  }

  .app-window-dot {
    width: 34px;
    height: 8px;
  }

  .app-window-line {
    width: 55%;
    height: 10px;
  }

  .app-window-line.wide {
    width: 80%;
  }

  .app-window-card {
    width: 100%;
    height: 54px;
    border-radius: var(--radius-3);
    opacity: 0.7;
  }

  .play-overlay {
    position: absolute;
    inset: 50% auto auto 50%;
    transform: translate(-50%, -50%);
    width: 42px;
    height: 42px;
    display: grid;
    place-items: center;
    border-radius: var(--radius-full);
    color: var(--color-font-button);
    background: var(--color-app-code);
    box-shadow: 0 4px 14px rgb(0 0 0 / 20%);
    font-size: var(--font-size-small);
  }

  .meta-row {
    display: flex;
    gap: var(--spacing-2);
    flex-wrap: wrap;
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
  }
</style>
