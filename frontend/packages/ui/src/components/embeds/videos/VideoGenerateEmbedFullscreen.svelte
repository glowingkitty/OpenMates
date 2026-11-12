<!--
  frontend/packages/ui/src/components/embeds/videos/VideoGenerateEmbedFullscreen.svelte

  Opened video of videos.generate (spec videos-generate.timeline.below-the-video,
  .change.extend-generated-clip, .change.edit-mode). The player is followed by the
  stored timeline (older videos get a one-clip timeline from the loaded length).
  Generative videos offer "+" buttons to extend the clip at the start or end; edit
  mode collects texts, trims and removals as pending edits. Extend and Apply send
  one ordinary follow-up about this video through the result follow-up path; nothing
  is rendered or fetched here while editing and no transport lives in this file.
  Decryption uses the same client-side S3 path as the generated media previews.
-->

<script lang="ts">
  import { getContext, onDestroy, untrack } from 'svelte';
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
  import GeneratedMediaThumbnails from '../GeneratedMediaThumbnails.svelte';
  import EmbedVersionTimeline from '../shared/EmbedVersionTimeline.svelte';
  import VideoTimeline from './VideoTimeline.svelte';
  import VideoExtendField from './VideoExtendField.svelte';
  import VideoEditInspector from './VideoEditInspector.svelte';
  import { createAudioUrlOwner } from '../audio/audioEmbedCrypto';
  import { text } from '../../../i18n/translations';
  import { decodeToonContent, requestEmbedFromServerOnce, resolveEmbed } from '../../../services/embedResolver';
  import { chatSyncService } from '../../../services/chatSyncService';
  import { EMBED_VERSIONS_ENABLED, embedContentAtVersion, embedHead, noteEmbedHeadChanged } from '../../../services/rustCore/embeds/messageEmbedVersion';
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedFullscreenRawData, type EmbedSourceChatContext } from '../../../types/embedFullscreen';
  import { hasMediaEncryptionMetadata } from '../../../services/encryption/mediaEncryption';
  import {
    EMPTY_EDITS, buildEditRequestText, buildExtendRequestText, countEdits, formatSeconds, madeByOf,
    normalizeTimeline, resultingDurationFrames, synthesizeTimeline, type PendingEdits, type Translate,
  } from './videoTimelineModel';

  const audioUrlOwner = createAudioUrlOwner();
  const fetchAndDecryptAudio = audioUrlOwner.fetch;
  const releaseCachedAudio = audioUrlOwner.release;
  onDestroy(audioUrlOwner.destroy);
  const sourceChatContext = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT);
  const sourceChatId = sourceChatContext?.exampleChatId ?? sourceChatContext?.lookupChatId ?? sourceChatContext?.chatId ?? null;

  interface VideoFileVariant { s3_key: string; mime_type?: string; duration_seconds?: number; aes_nonce?: string; encryption?: string; }
  interface Props {
    data: EmbedFullscreenRawData;
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next' | null;
    showChatButton?: boolean;
    onShowChat?: () => void;
    /** Preview only: the number of versions, without the core. */
    versionCount?: number;
  }

  let {
    data, embedId, onClose, hasPreviousEmbed = false,
    hasNextEmbed = false, onNavigatePrevious, onNavigateNext, navigateDirection = null,
    showChatButton = false, onShowChat, versionCount,
  }: Props = $props();

  // Versions: the timeline below switches the shown version (same wiring as generated images).
  let headVersion = $state<number | undefined>(untrack(() => versionCount));
  let shownVersion = $state<number | undefined>(untrack(() => versionCount));
  let versionContent = $state<Record<string, unknown> | null>(null);
  let versionError = $state<string | undefined>(undefined);

  let dc = $derived(versionContent ?? data.decodedContent);
  let prompt = $derived(typeof dc.prompt === 'string' ? dc.prompt : '');
  let model = $derived(typeof dc.model === 'string' ? dc.model : '');
  let resolution = $derived(typeof dc.resolution === 'string' ? dc.resolution : '');
  let s3BaseUrl = $derived(typeof dc.s3_base_url === 'string' ? dc.s3_base_url : '');
  let files = $derived((typeof dc.files === 'object' && dc.files !== null) ? dc.files as { original?: VideoFileVariant } : undefined);
  let aesKey = $derived(typeof dc.aes_key === 'string' ? dc.aes_key : '');
  let aesNonce = $derived(typeof dc.aes_nonce === 'string' ? dc.aes_nonce : '');
  let previewVideoUrl = $derived(typeof dc.previewVideoUrl === 'string' ? dc.previewVideoUrl : (typeof dc.preview_video_url === 'string' ? dc.preview_video_url : ''));
  let previewImageUrl = $derived(typeof dc.previewImageUrl === 'string' ? dc.previewImageUrl : (typeof dc.preview_image_url === 'string' ? dc.preview_image_url : ''));
  let inputEmbedIds = $derived(Array.isArray(dc.input_embed_ids) ? dc.input_embed_ids.filter((id): id is string => typeof id === 'string') : []);
  let sourceTitles = $derived(Array.isArray(dc.source_titles) ? dc.source_titles.filter((s): s is string => typeof s === 'string' && s.length > 0) : []);
  let madeBy = $derived(madeByOf(dc));

  let videoUrl = $state<string | undefined>();
  let error = $state<string | undefined>();
  let loadingVideo = false;
  let retainedS3Key: string | undefined;
  let videoEl: HTMLVideoElement | undefined = $state();
  let currentTime = $state(0);
  let loadedSeconds = $state(0);
  let frame = 0;

  const storedSeconds = $derived(
    typeof dc.duration_seconds === 'number' ? dc.duration_seconds : (files?.original?.duration_seconds ?? 0),
  );
  const timeline = $derived.by(() => {
    const stored = normalizeTimeline(dc);
    if (stored) return stored;
    const seconds = storedSeconds || loadedSeconds;
    if (seconds <= 0) return undefined;
    return synthesizeTimeline(seconds, $text('embeds.video_generate.clip'), {
      width: typeof dc.width === 'number' ? dc.width : undefined, height: typeof dc.height === 'number' ? dc.height : undefined,
    });
  });
  const totalSeconds = $derived(timeline ? timeline.durationInFrames / timeline.fps : 0);
  const sizeLabel = $derived(timeline && timeline.width > 0 && timeline.height > 0 ? `${timeline.width} x ${timeline.height}` : resolution);
  const subtitle = $derived([
    $text(madeBy === 'composed' ? 'embeds.video_generate.kind_composed' : 'embeds.video_generate.kind_generative'),
    totalSeconds > 0 ? formatSeconds(totalSeconds) : '', sizeLabel,
  ].filter(Boolean).join(' · '));
  const canExtendStart = $derived(madeBy === 'generative' && dc.can_extend_start === true);
  const canExtendEnd = $derived(madeBy === 'generative' && dc.can_extend_end === true);

  // Edit mode and extend field: pending state only, nothing is rendered or sent until Apply / Send.
  let editing = $state(false);
  let edits = $state<PendingEdits>(EMPTY_EDITS);
  let selectedPartId = $state<string | undefined>();
  let extendSide = $state<'start' | 'end' | null>(null);
  let confirmingLeave = $state(false);
  const pendingCount = $derived(countEdits(edits));
  const selectedPart = $derived(timeline?.tracks.flatMap((t) => t.parts).find((p) => p.id === selectedPartId));
  const translate: Translate = (key, values) => $text(key, values ? { values } : undefined);

  $effect(() => {
    if (previewVideoUrl && videoUrl !== previewVideoUrl) {
      videoUrl = previewVideoUrl;
      return;
    }
    if (!videoUrl && !loadingVideo && files?.original?.s3_key && s3BaseUrl && aesKey && hasMediaEncryptionMetadata(files.original, aesNonce)) void loadVideo();
  });

  $effect(() => {
    if (!EMBED_VERSIONS_ENABLED || !embedId || versionCount !== undefined) return;
    const id = embedId;
    void embedHead(id).then((head) => {
      headVersion = head?.version ?? 1;
      shownVersion = headVersion;
    }).catch((err) => {
      console.error('[VideoGenerateEmbedFullscreen] Failed to read the video version:', err);
      versionError = err instanceof Error ? err.message : String(err);
    });
  });

  // A change (edit, extend) stores the next version of this same video while it is open: show it.
  const HEAD_RELOAD_ATTEMPTS = 5;
  const HEAD_RELOAD_DELAY_MS = 2000;
  let reloadTimer: ReturnType<typeof setTimeout> | undefined;
  async function reloadHead(attempt = 1) {
    const id = embedId;
    if (!EMBED_VERSIONS_ENABLED || !id) return;
    try {
      await requestEmbedFromServerOnce(id, 'video embed updated', { chatId: sourceChatId });
      noteEmbedHeadChanged(id);
      const head = await embedHead(id);
      const version = head?.version ?? 1;
      if (version <= (headVersion ?? 1)) {
        // The finished event can arrive before the new head is readable here.
        if (attempt < HEAD_RELOAD_ATTEMPTS) reloadTimer = setTimeout(() => void reloadHead(attempt + 1), HEAD_RELOAD_DELAY_MS);
        return;
      }
      const stored = await resolveEmbed(id, { chatId: sourceChatId ?? undefined });
      if (typeof stored?.content !== 'string') return;
      headVersion = version;
      await showVersion(version, stored.content);
    } catch (err) {
      console.error('[VideoGenerateEmbedFullscreen] Failed to load the new video version:', err);
      versionError = err instanceof Error ? err.message : String(err);
    }
  }
  function onEmbedUpdated(event: Event) {
    const detail = (event as CustomEvent<{ embed_id?: string; status?: string }>).detail;
    const updated = detail?.embed_id?.replace(/^embed:/, '');
    if (updated && updated === embedId?.replace(/^embed:/, '') && detail.status === 'finished') {
      clearTimeout(reloadTimer);
      void reloadHead();
    }
  }
  chatSyncService.addEventListener('embedUpdated', onEmbedUpdated);

  onDestroy(() => {
    chatSyncService.removeEventListener('embedUpdated', onEmbedUpdated);
    clearTimeout(reloadTimer);
    cancelAnimationFrame(frame);
    if (retainedS3Key) releaseCachedAudio(retainedS3Key);
  });

  async function loadVideo() {
    const file = files?.original;
    if (!file?.s3_key) return;
    loadingVideo = true;
    try {
      videoUrl = await fetchAndDecryptAudio(s3BaseUrl, file.s3_key, aesKey, aesNonce, file.mime_type || 'video/mp4', file);
      retainedS3Key = file.s3_key;
    } catch (err) {
      error = err instanceof Error ? err.message : $text('embeds.video_generate.load_error');
    } finally {
      loadingVideo = false;
    }
  }

  async function showVersion(version: number, toon: string | null) {
    versionError = undefined;
    const content = toon === null ? null : await decodeToonContent(toon);
    if (toon !== null && !content) {
      versionError = 'embed_version_content_undecodable';
      return;
    }
    if (retainedS3Key) releaseCachedAudio(retainedS3Key);
    retainedS3Key = undefined;
    videoUrl = undefined;
    error = undefined;
    shownVersion = version;
    versionContent = (content as Record<string, unknown> | null) ?? null;
    discardEdits();
  }

  function trackPlayhead() {
    if (videoEl) currentTime = videoEl.currentTime;
    frame = requestAnimationFrame(trackPlayhead);
  }
  function handleSeek(seconds: number) {
    if (videoEl) videoEl.currentTime = seconds;
    currentTime = seconds;
  }

  function discardEdits() {
    edits = EMPTY_EDITS;
    selectedPartId = timeline && madeBy === 'generative' && timeline.tracks[0]?.parts.length === 1 ? timeline.tracks[0].parts[0].id : undefined;
    confirmingLeave = false;
  }
  function toggleEdit() {
    if (editing) {
      if (pendingCount > 0 && !confirmingLeave) { confirmingLeave = true; return; }
      editing = false;
      discardEdits();
      return;
    }
    extendSide = null;
    editing = true;
    discardEdits();
  }
  function openExtend(side: 'start' | 'end') {
    extendSide = extendSide === side ? null : side;
  }
  function closeExtend() {
    const side = extendSide;
    extendSide = null;
    queueMicrotask(() => document.querySelector<HTMLElement>(`[data-testid="video-timeline-extend-${side}"]`)?.focus());
  }
  async function sendExtend(requestFollowup: (value: string) => Promise<boolean>, description: string) {
    if (!extendSide) return;
    if (await requestFollowup(buildExtendRequestText(extendSide, description))) extendSide = null;
  }
  async function applyEdits(requestFollowup: (value: string) => Promise<boolean>) {
    if (!timeline || pendingCount === 0) return;
    if (await requestFollowup(buildEditRequestText(edits, timeline, translate))) {
      editing = false;
      discardEdits();
    }
  }
</script>

<ResultEmbedFullscreen
  result={{ prompt, model, resolution, made_by: madeBy }}
  mediaLayout="immersive"
  appId="videos"
  skillId="generate"
  skillIconName="videos"
  embedHeaderTitle={prompt || $text(madeBy === 'composed' ? 'embeds.video_generate.kind_composed' : 'embeds.video_generate.kind_generative')}
  embedHeaderSubtitle={subtitle}
  showSkillIcon={true}
  {onClose}
  onEdit={timeline ? toggleEdit : undefined}
  editActive={editing}
  editTestId="video-edit-button"
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  navigateDirection={navigateDirection ?? undefined}
  {showChatButton}
  {onShowChat}
>
  {#snippet summary()}
    {#if sizeLabel}<ResultEmbedInfo icon="maximize" label={sizeLabel} value={sizeLabel} />{/if}
  {/snippet}
  {#snippet media({ requestFollowup, submitting })}
    <div class="video-fullscreen" data-testid="video-generate-fullscreen" data-made-by={madeBy} data-embed-version={shownVersion ?? 1}>
      {#if videoUrl}
        <video class="result-primary-media" bind:this={videoEl} src={videoUrl} poster={previewImageUrl || undefined} controls playsinline autoplay
          data-testid="video-generate-fullscreen-video"
          onloadedmetadata={() => { loadedSeconds = videoEl?.duration ?? 0; }}
          ontimeupdate={() => { if (videoEl) currentTime = videoEl.currentTime; }}
          onplay={() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(trackPlayhead); }}
          onpause={() => cancelAnimationFrame(frame)} onended={() => cancelAnimationFrame(frame)}>
          <track kind="captions" src="data:text/vtt,WEBVTT" />
        </video>
      {:else if error}
        <p>{error}</p>
      {:else}
        <p>{$text('embeds.video_generate.loading')}</p>
      {/if}

      {#if timeline}
        <VideoTimeline {timeline} {currentTime} onSeek={handleSeek} selectable={editing} {selectedPartId}
          onSelectPart={(id) => { selectedPartId = id; }} {edits} canExtendStart={!editing && canExtendStart}
          canExtendEnd={!editing && canExtendEnd} extendOpenSide={extendSide} onExtend={openExtend} />
      {/if}

      {#if extendSide && !editing}
        <VideoExtendField side={extendSide} {submitting} onClose={closeExtend}
          onSend={(description) => void sendExtend(requestFollowup, description)} />
      {/if}

      {#if editing && timeline}
        {#if selectedPart}
          <VideoEditInspector {timeline} part={selectedPart} {edits} onChange={(next) => { edits = next; confirmingLeave = false; }} />
        {:else}
          <p class="hint" data-testid="video-edit-hint">{$text('embeds.video_generate.edit_hint')}</p>
        {/if}
        <div class="pending" data-testid="video-edit-pending" role="status">
          {#if confirmingLeave}
            <span class="pending-text" data-testid="video-edit-confirm">{$text('embeds.video_generate.discard_confirm')}</span>
            <div class="pending-actions">
              <button type="button" class="secondary" data-testid="video-edit-keep" onclick={() => { confirmingLeave = false; }}>{$text('embeds.video_generate.keep_editing')}</button>
              <button type="button" class="danger" data-testid="video-edit-confirm-discard" onclick={toggleEdit}>{$text('embeds.video_generate.discard')}</button>
            </div>
          {:else}
            <span class="pending-text">
              <strong data-testid="video-edit-pending-count">{$text('embeds.video_generate.pending_changes', { values: { count: pendingCount } })}</strong>
              <span data-testid="video-edit-new-length">{$text('embeds.video_generate.new_length', { values: { length: formatSeconds(resultingDurationFrames(timeline, edits) / timeline.fps) } })}</span>
            </span>
            <div class="pending-actions">
              <button type="button" class="secondary" data-testid="video-edit-discard" disabled={pendingCount === 0} onclick={discardEdits}>{$text('embeds.video_generate.discard')}</button>
              <button type="button" class="primary" data-testid="video-edit-apply" disabled={pendingCount === 0 || submitting}
                onclick={() => void applyEdits(requestFollowup)}>{$text('embeds.video_generate.apply')}</button>
            </div>
          {/if}
        </div>
      {/if}

      {#if embedId && headVersion && headVersion > 1}
        <EmbedVersionTimeline
          {embedId}
          chatId={sourceChatId ?? undefined}
          currentVersion={headVersion}
          currentContent=""
          initialVersion={shownVersion}
          showChangesToggle={false}
          loadVersionContent={(version) => embedContentAtVersion(sourceChatId ?? '', embedId, version)}
          onVersionSelect={(version, content) => { void showVersion(version, content); }}
          onVersionError={(version) => { versionError = `embed_version_unavailable:v${version}`; }}
        />
      {/if}
      {#if versionError}<p class="hint" data-testid="video-generate-version-error">{versionError}</p>{/if}
    </div>
  {/snippet}
  {#snippet detailContent()}
    <dl>
      {#if prompt}<dt>{$text('embeds.video_generate.prompt')}</dt><dd>{prompt}</dd>{/if}
      {#if model}<dt>{$text('embeds.video_generate.model')}</dt><dd>{model}</dd>{/if}
      {#if resolution}<dt>{$text('embeds.video_generate.resolution')}</dt><dd>{resolution}</dd>{/if}
    </dl>
    {#if inputEmbedIds.length > 0 || sourceTitles.length > 0}
      <section class="sources" data-testid="video-generate-sources">
        <h3>{$text('embeds.video_generate.sources')}</h3>
        {#if inputEmbedIds.length > 0}<GeneratedMediaThumbnails childEmbedIds={inputEmbedIds} />{/if}
        {#if sourceTitles.length > 0}<ul>{#each sourceTitles as title (title)}<li>{title}</li>{/each}</ul>{/if}
      </section>
    {/if}
  {/snippet}
</ResultEmbedFullscreen>

<style>
  /* The shared media budget minus the timeline, so the timeline is visible at first open. */
  .video-fullscreen {
    display: grid; gap: var(--spacing-8); padding: 0; min-width: 0;
    --result-media-max-height: max(11rem, calc(var(--result-fullscreen-height, 100dvh) - 36rem - max(0px, var(--result-followup-height, 4rem) - 4rem)));
  }
  video { display: block; width: auto; max-width: 100%; justify-self: center; max-height: var(--result-media-max-height); border-radius: var(--radius-5); background: var(--color-grey-100); }
  .hint { margin: 0; text-align: center; font-size: var(--font-size-small); color: var(--color-font-secondary); }
  dl { display: grid; grid-template-columns: max-content 1fr; gap: var(--spacing-4) var(--spacing-6); color: var(--color-font-primary); margin: 0; }
  dt { font-weight: 700; }
  dd { margin: 0; overflow-wrap: anywhere; }
  .sources { width: 100%; display: grid; gap: var(--spacing-4); }
  .sources h3 { margin: 0; font-size: var(--font-size-p); }
  .sources ul { margin: 0; padding-left: var(--spacing-8); font-size: var(--font-size-small); color: var(--color-font-secondary); }
  .pending {
    display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--spacing-4);
    padding: var(--spacing-4) var(--spacing-6); border-radius: var(--radius-4);
    background: var(--color-grey-10); border: 1px solid var(--color-grey-25);
  }
  .pending-text { display: grid; gap: var(--spacing-1); font-size: var(--font-size-small); color: var(--color-font-secondary); min-width: 0; }
  .pending-text strong { color: var(--color-font-primary); }
  .pending-actions { display: flex; gap: var(--spacing-3); margin-left: auto; }
  .pending button {
    font: inherit; font-size: var(--font-size-small); font-weight: 600; padding: var(--spacing-3) var(--spacing-6);
    border-radius: var(--radius-8); border: 1px solid transparent; cursor: pointer;
    min-width: 0; height: auto; margin: 0; filter: none;
  }
  .pending .primary { background: var(--color-button-primary); color: var(--color-font-button); }
  .pending .secondary { background: var(--color-grey-0); color: var(--color-font-primary); border-color: var(--color-grey-30); }
  .pending .danger { background: var(--color-error); color: var(--color-font-button); }
  .pending button:disabled { opacity: 0.45; cursor: default; }
  .pending button:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
</style>
