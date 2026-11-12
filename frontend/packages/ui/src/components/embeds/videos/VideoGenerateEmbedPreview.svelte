<!--
  frontend/packages/ui/src/components/embeds/videos/VideoGenerateEmbedPreview.svelte

  Result card of a videos.generate video. The card never loads the MP4: it shows
  the video's still image (`files.thumbnail`, decrypted client-side with the
  video's AES key, or a public poster) under a round play button that opens the
  fullscreen player, which starts playing. The maker is named once as
  "Created by <model>"; the meta line holds only duration and resolution.

  While a request runs the card names the current step. A change of an earlier
  video (edit / extend) shows that video's dimmed thumbnail, the kind of change
  and the change instruction.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import VideoSourceThumbnail from './VideoSourceThumbnail.svelte';
  import { text } from '@repo/ui';
  import { createImageUrlOwner } from '../images/imageEmbedCrypto';
  import { formatSeconds } from './videoTimelineModel';
  import {
    EMPTY_VIDEO_PROGRESS, loadVideoThumbnail, readVideoProgress, videoChangeText, videoMakerName, videoStageText,
    type VideoChange, type VideoFiles, type VideoProgress, type VideoProgressStage,
  } from './videoGenerateCard';

  type Status = 'processing' | 'finished' | 'error';

  interface Props {
    id: string;
    prompt?: string;
    model?: string;
    /** Author model of a composed video (e.g. "gpt-6.1-sol"). */
    authorModel?: string;
    /** "generative" | "composed". */
    madeBy?: string;
    durationSeconds?: number;
    resolution?: string;
    s3BaseUrl?: string;
    files?: VideoFiles;
    aesKey?: string;
    aesNonce?: string;
    /** Public poster (fixtures, store examples); preferred over the encrypted thumbnail. */
    previewImageUrl?: string;
    status: Status;
    error?: string;
    progressStage?: VideoProgressStage;
    progressAttempt?: number;
    change?: VideoChange;
    sourceEmbedId?: string;
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id, prompt = '', model = '', authorModel = '', madeBy = '', durationSeconds, resolution = '', s3BaseUrl = '', files,
    aesKey = '', aesNonce = '', previewImageUrl = '', status, error = '', progressStage, progressAttempt, change,
    sourceEmbedId, taskId, isMobile = false, onFullscreen,
  }: Props = $props();

  const skillName = $text('app_skills.videos.generate');
  const imageOwner = createImageUrlOwner();
  onDestroy(imageOwner.destroy);

  let updatedStatus = $state<Status | undefined>();
  let updated = $state<Record<string, unknown>>({});
  let updatedProgress = $state<VideoProgress | undefined>();

  function pick<T>(key: string, kind: 'string' | 'number' | 'object', fallback: T): T {
    const value = updated[key];
    if (kind === 'object') return (typeof value === 'object' && value !== null ? value : fallback) as T;
    return (typeof value === kind ? value : fallback) as T;
  }

  const currentStatus = $derived(updatedStatus ?? status);
  const currentPrompt = $derived(pick('prompt', 'string', prompt));
  const currentModel = $derived(pick('model', 'string', model));
  const currentAuthorModel = $derived(pick('author_model', 'string', authorModel));
  const currentMadeBy = $derived(pick('made_by', 'string', madeBy));
  const currentDurationSeconds = $derived(pick<number | undefined>('duration_seconds', 'number', durationSeconds));
  const currentResolution = $derived(pick('resolution', 'string', resolution));
  const currentS3BaseUrl = $derived(pick('s3_base_url', 'string', s3BaseUrl));
  const currentFiles = $derived(pick<VideoFiles | undefined>('files', 'object', files));
  const currentAesKey = $derived(pick('aes_key', 'string', aesKey));
  const currentAesNonce = $derived(pick('aes_nonce', 'string', aesNonce));
  const currentPreviewImageUrl = $derived(pick('previewImageUrl', 'string', pick('preview_image_url', 'string', previewImageUrl)));
  const currentError = $derived(pick('error', 'string', error));
  const progress = $derived(updatedProgress ?? readVideoProgress({
    progress_stage: progressStage, progress_attempt: progressAttempt, change, source_embed_id: sourceEmbedId,
  }, EMPTY_VIDEO_PROGRESS));

  const translate = (key: string, options?: { values: Record<string, string> }) => $text(key, options);
  const processing = $derived(currentStatus === 'processing');
  const changeLabel = $derived(processing ? videoChangeText(progress.change, translate) : undefined);
  const stageText = $derived(processing ? (videoStageText(progress, translate) ?? $text('embeds.processing')) : undefined);
  const maker = $derived(videoMakerName({ model: currentModel, authorModel: currentAuthorModel, madeBy: currentMadeBy }));
  const sourceLabel = $derived(processing
    ? changeLabel
    : (currentStatus === 'finished' && maker ? $text('embeds.video_generate.created_by', { values: { model: maker } }) : undefined));
  const metaLine = $derived(
    processing ? stageText
      : currentStatus === 'error' ? (currentError || $text('embeds.video_generate.failed'))
      : [currentDurationSeconds ? formatSeconds(currentDurationSeconds) : '', currentResolution].filter(Boolean).join(' · ') || undefined,
  );
  const showSource = $derived(processing && !!progress.sourceEmbedId);

  let thumbnailUrl = $state<string | undefined>();
  $effect(() => {
    const source = {
      previewImageUrl: currentPreviewImageUrl, s3BaseUrl: currentS3BaseUrl, files: currentFiles,
      aesKey: currentAesKey, aesNonce: currentAesNonce,
    };
    if (currentStatus !== 'finished') { thumbnailUrl = undefined; return; }
    let cancelled = false;
    loadVideoThumbnail(source, imageOwner)
      .then((url) => { if (!cancelled) thumbnailUrl = url; })
      .catch((err) => {
        // The play button stays on the neutral surface; fullscreen still loads the video.
        console.error('[VideoGenerateEmbedPreview] Failed to load the video thumbnail:', err);
        if (!cancelled) thumbnailUrl = undefined;
      });
    return () => { cancelled = true; };
  });

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    const decoded = data.decodedContent ?? {};
    const next = (decoded.status ?? data.status) as Status | undefined;
    if (next === 'processing' || next === 'finished' || next === 'error') updatedStatus = next;
    updated = { ...updated, ...decoded };
    updatedProgress = readVideoProgress(decoded, progress);
  }

  function open(event: MouseEvent) {
    event.stopPropagation();
    event.preventDefault();
    onFullscreen();
  }
</script>

<UnifiedEmbedPreview
  resultPreview={true}
  {id}
  appId="videos"
  skillId="generate"
  skillIconName="videos"
  status={currentStatus}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  customStatusText={metaLine}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details()}
    <ResultEmbedCard title={currentPrompt || skillName} {sourceLabel} description={metaLine} mediaFit="contain">
      {#snippet media()}
        <div class="video-generate-preview" data-testid="video-generate-preview" data-status={currentStatus}>
          {#if currentStatus === 'finished'}
            <button type="button" class="open-video" aria-label={$text('embeds.video_play')} data-testid="video-generate-open" onclick={open}>
              {#if thumbnailUrl}
                <img class="thumbnail" src={thumbnailUrl} alt="" data-testid="video-generate-thumbnail" />
              {:else}
                <span class="placeholder" data-testid="video-generate-placeholder"></span>
              {/if}
              <span class="play-button" data-testid="video-generate-play" aria-hidden="true"><span class="play-icon"></span></span>
            </button>
          {:else if showSource && progress.sourceEmbedId}
            <VideoSourceThumbnail embedId={progress.sourceEmbedId} />
          {:else if processing}
            <span class="placeholder" data-testid="video-generate-placeholder"></span>
            <span class="spinner" data-testid="video-generate-processing" aria-hidden="true"></span>
          {:else}
            <span class="placeholder" data-testid="video-generate-placeholder"></span>
            <span class="error-text" data-testid="video-generate-error">{metaLine}</span>
          {/if}
          {#if stageText}
            <span class="stage" data-testid="video-generate-stage" data-stage={progress.stage}>{stageText}</span>
          {/if}
        </div>
      {/snippet}
    </ResultEmbedCard>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .video-generate-preview { position: absolute; inset: 0; overflow: hidden; }
  .open-video { position: absolute; inset: 0; width: 100%; height: 100%; min-width: 0; margin: 0; padding: 0; border: 0; border-radius: inherit; background: none; filter: none; scale: 1; cursor: pointer; display: block; }
  .open-video:hover, .open-video:active { background: none; scale: 1; filter: none; }
  .open-video:focus-visible { outline: 2px solid var(--color-primary); outline-offset: -2px; }
  /* The still image fills the media area, pinned to its box (Safari cannot size it in a flex item). */
  .thumbnail { position: absolute; inset: 0; width: 100%; height: 100%; display: block; object-fit: cover; }
  .placeholder { position: absolute; inset: 0; display: block; background: var(--color-grey-20); }
  /* Same round dark play button as the video fullscreen thumbnail, sized for the card. */
  .play-button {
    position: absolute; top: 50%; left: 50%; width: 56px; height: 56px; transform: translate(-50%, -50%);
    display: flex; align-items: center; justify-content: center; border-radius: var(--radius-full);
    background: color-mix(in srgb, black 70%, transparent); pointer-events: none;
    transition: transform var(--duration-normal) var(--easing-in-out), background var(--duration-normal) var(--easing-in-out);
  }
  .open-video:hover .play-button { background: color-mix(in srgb, black 85%, transparent); transform: translate(-50%, -50%) scale(1.1); }
  .open-video:active .play-button { transform: translate(-50%, -50%) scale(0.95); }
  .play-icon {
    width: 32px; height: 32px; display: block; background-image: url('@openmates/ui/static/icons/play.svg');
    background-size: contain; background-repeat: no-repeat; background-position: center; filter: brightness(0) invert(1);
  }
  .spinner {
    position: absolute; top: 50%; left: 50%; width: 36px; height: 36px; margin: -18px 0 0 -18px; box-sizing: border-box;
    border-radius: var(--radius-full); border: 3px solid var(--color-grey-40); border-top-color: var(--color-grey-70);
    animation: spin 1s linear infinite;
  }
  .stage {
    position: absolute; left: var(--spacing-4); bottom: var(--spacing-4); max-width: calc(100% - 2 * var(--spacing-4));
    padding: var(--spacing-1) var(--spacing-4); box-sizing: border-box; border-radius: var(--radius-2);
    background: color-mix(in srgb, black 55%, transparent); color: white; font-size: var(--font-size-tiny); line-height: 1.3;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; pointer-events: none;
  }
  .error-text {
    position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; box-sizing: border-box;
    padding: var(--spacing-4); text-align: center; color: var(--color-error); font-size: var(--font-size-xs); overflow-wrap: anywhere;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }
</style>
