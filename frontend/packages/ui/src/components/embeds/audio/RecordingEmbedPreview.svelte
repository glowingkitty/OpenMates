<!--
  frontend/packages/ui/src/components/embeds/audio/RecordingEmbedPreview.svelte

  Preview card for user-recorded audio embeds with live transcription.

  Architecture mirrors ImageEmbedPreview:
  - No skill icon (showSkillIcon=false)
  - skillName = "Audio recording" (i18n key: app_skills.audio.transcribe.audio_recording)
  - customStatusText = dynamic subtitle reflecting upload/transcription state
  - Play/pause button lives in BasicInfosBar via the actionButton snippet slot
  - Details area shows transcript preview, shimmer placeholder, or signup prompt

  Status lifecycle:
    'uploading'      → "Processing…"       (audio blob uploading to server)
    'transcribing'   → "Processing…"       (upload done, Mistral Voxtral running)
    'finished'       → duration string     (or "Signup to upload…" for unauth)
    'error'          → error message       (upload failed or transcription failed)

  Details area content:
    Unauth user      → "Signup to see transcript here."
    Processing       → Shimmer placeholder (gradient sweep, 4 lines)
    Finished         → Transcript preview (truncated)
    Error            → Error icon + message + optional retry button

  Rendering contexts:

  A) Editor context (blobUrl set — local blob from recording session):
     - Shows audio player using the local blob URL.
     - Play button in BasicInfosBar.
     - Transcript shown as preview text once available.

  B) Read-only context (blobUrl absent, S3 data present — received/sent message):
     - Audio is lazily fetched and decrypted from S3 (original variant key) using AES-256-GCM.
     - Shows shimmer placeholder while loading, then play button once decrypted.
     - Transcript shown from embed content.
     - Fullscreen available when status is 'finished'.

  Fullscreen: calls onFullscreen() → RecordingRenderer.ts fires 'recordingfullscreen'
  CustomEvent → ActiveChat.svelte (via document listener or MessageInput relay) opens
  RecordingEmbedFullscreen.svelte.

  Stop button: calls onStop() → RecordingRenderer.ts fires 'cancelrecordingupload'
  CustomEvent → Embed.ts node view listener calls cancelUpload(id) + deletes the node.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { fetchAndDecryptAudio, releaseCachedAudio, AudioFetchError, AudioNetworkError, AudioDecryptError } from './audioEmbedCrypto';
  import { getModelDisplayName, getModelByNameOrId } from '../../../utils/modelDisplayName';
  import { getProviderIconUrl } from '../../../data/providerIcons';

  /** Max chars of transcript to show in the preview card before truncating */
  const MAX_TRANSCRIPT_PREVIEW = 120;

  interface Props {
    /** Unique embed ID */
    id: string;
    /** Original filename of the recorded audio */
    filename?: string;
    /** Upload + transcription status */
    status: 'uploading' | 'transcribing' | 'finished' | 'error';
    /**
     * Local blob URL for audio playback while in editor context.
     * Not present in read-only message display (blob URLs are ephemeral).
     */
    blobUrl?: string;
    /** Error message to display when status is 'error' */
    uploadError?: string;
    /** Transcribed text returned by Mistral Voxtral */
    transcript?: string;
    /** Formatted duration string (e.g. "0:42") */
    duration?: string;
    /** S3 file metadata — set after successful upload */
    s3Files?: Record<string, { s3_key: string; size_bytes: number }>;
    /** S3 base URL */
    s3BaseUrl?: string;
    /** Plaintext AES-256 key (base64) for client-side decryption */
    aesKey?: string;
    /** AES-GCM nonce (base64) */
    aesNonce?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Whether the user is authenticated */
    isAuthenticated?: boolean;
    /** Called when user clicks to open fullscreen / edit transcript */
    onFullscreen: () => void;
    /** Called when user clicks the stop button during upload */
    onStop?: () => void;
    /**
     * Called when user clicks the retry button in error state.
     * Only available when upload succeeded (s3Files present) so transcription
     * can be retried without re-uploading. Passed from RecordingRenderer.ts.
     */
    onRetry?: () => void;
    /**
     * Transcription model name (e.g. 'voxtral-mini-2602').
     * Shown during 'transcribing' and in the finished subtitle as "Transcribed via <model>".
     */
    model?: string;
  }

  let {
    id,
    filename,
    status: statusProp,
    blobUrl,
    uploadError,
    transcript,
    duration,
    s3Files,
    s3BaseUrl,
    aesKey,
    aesNonce,
    isMobile = false,
    isAuthenticated = true,
    onFullscreen,
    onStop,
    onRetry,
    model,
  }: Props = $props();

  // --- Audio playback state ---

  /**
   * Resolved audio source: local blobUrl (editor) or decrypted S3 blob URL (read-only).
   * Initialised via $effect (not inline $state(blobUrl)) so that Svelte 5 correctly
   * tracks prop changes and avoids the "state_referenced_locally" lint warning.
   */
  let resolvedAudioSrc = $state<string | undefined>(undefined);
  /** True while fetching + decrypting audio from S3 */
  let isLoadingAudio = $state(false);
  /** Error message if S3 fetch/decrypt fails */
  let audioLoadError = $state<string | undefined>(undefined);

  // Audio element reference for the playback controls
  let audioEl: HTMLAudioElement | undefined = $state(undefined);
  let isPlaying = $state(false);

  // Track retained S3 cache key for cleanup on unmount
  let retainedS3Key: string | undefined = undefined;

  // Cleanup on unmount
  onDestroy(() => {
    if (audioEl) audioEl.pause();
    if (retainedS3Key) {
      releaseCachedAudio(retainedS3Key);
      retainedS3Key = undefined;
    }
  });

  // --- Derived state ---

  let status = $derived(statusProp);

  /** Map upload-specific status to UnifiedEmbedPreview's status union */
  let unifiedStatus = $derived(
    (status === 'uploading' || status === 'transcribing')
      ? 'processing'
      : (status as 'processing' | 'finished' | 'error'),
  );

  /**
   * S3 key for the original audio file.
   * Used to fetch audio in read-only context (no blobUrl).
   */
  let audioS3Key = $derived(
    s3Files?.original?.s3_key ?? Object.values(s3Files ?? {})[0]?.s3_key,
  );

  /**
   * Whether we have a playable audio source (local blob or decrypted S3 URL).
   */
  let hasAudioSrc = $derived(!!resolvedAudioSrc);

  /**
   * Whether fullscreen is available:
   * - status must be 'finished'
   * - need either a transcript, a local blob, or S3 data to show something useful
   */
  let isFullscreenEnabled = $derived(
    status === 'finished' && (!!transcript || !!blobUrl || !!audioS3Key),
  );

  /**
   * Resolved metadata and logo URL for the transcription model.
   * Used to show a circular provider icon alongside the "Transcribing via" and
   * "Transcribed by" labels. Falls back gracefully when model is unknown.
   */
  let modelMetadata = $derived(model ? getModelByNameOrId(model) : undefined);
  let modelIconUrl = $derived(
    modelMetadata?.logo_svg ? getProviderIconUrl(modelMetadata.logo_svg) : undefined,
  );

  /**
   * Lazily fetch and decrypt audio from S3 when:
   * - No local blobUrl (read-only / received message context)
   * - S3 data is present: s3Files, s3BaseUrl, aesKey, aesNonce
   * - Status is 'finished' (upload and transcription completed)
   *
   * Uses $effect so it re-runs if the S3 key or auth data changes.
   */
  $effect(() => {
    // Already have a local blob URL — nothing to fetch
    if (blobUrl) {
      resolvedAudioSrc = blobUrl;
      return;
    }

    // Not yet finished or missing required S3 data — skip
    if (status !== 'finished') return;
    if (!audioS3Key || !s3BaseUrl || !aesKey || !aesNonce) return;

    // Avoid re-fetching if we already resolved this key
    if (retainedS3Key === audioS3Key && resolvedAudioSrc) return;

    isLoadingAudio = true;
    audioLoadError = undefined;

    // Derive MIME type from the original filename (e.g. "voice_note_2026-02-20.mp4")
    // rather than from the S3 key, which always ends in ".bin" and gives the wrong type.
    // Falls back to "audio/webm" (the default browser recording format on non-Safari).
    const filenameExt = (filename ?? '').split('.').pop()?.toLowerCase() ?? '';
    const mimeType = filenameExt === 'mp4' ? 'audio/mp4' : filenameExt === 'ogg' ? 'audio/ogg' : 'audio/webm';

    fetchAndDecryptAudio(s3BaseUrl, audioS3Key, aesKey, aesNonce, mimeType)
      .then((url) => {
        resolvedAudioSrc = url;
        retainedS3Key = audioS3Key;
        isLoadingAudio = false;
      })
      .catch((err: unknown) => {
        // Log with typed detail so the root cause is visible in the browser console.
        // AudioDecryptError wraps DOMException which would otherwise serialize as '{}' in console.error.
        if (err instanceof AudioDecryptError || err instanceof AudioFetchError || err instanceof AudioNetworkError) {
          console.error(`[RecordingEmbedPreview] ${err.name}: ${err.message}`);
        } else if (err instanceof Error) {
          console.error('[RecordingEmbedPreview] Failed to fetch/decrypt audio from S3:', err.message, err);
        } else {
          console.error('[RecordingEmbedPreview] Failed to fetch/decrypt audio from S3:', String(err));
        }
        audioLoadError = 'Audio unavailable';
        isLoadingAudio = false;
      });
  });

  /**
   * Whether to show the stop button.
   * Shown during 'uploading' AND 'transcribing' — both phases can be cancelled.
   * The AbortController in embedHandlers stays registered until transcription
   * completes/fails, so cancelUpload() aborts either the upload fetch or the
   * transcription fetch, whichever is currently in flight.
   */
  let showStop = $derived(hasAudioSrc && (status === 'uploading' || status === 'transcribing') && !!onStop);

  /**
   * Card subtitle text (shown below "Audio recording" in BasicInfosBar):
   * - uploading              → "Processing…"
   * - transcribing           → "Transcribing via <model>…" if model known, else "Processing…"
   * - error                  → error message
   * - finished (unauth)      → "Signup to upload…"
   * - finished (auth)        → duration string or "Audio recording" fallback
   */
  let statusText = $derived.by(() => {
    if (status === 'uploading') {
      return $text('app_skills.audio.transcribe.processing');
    }
    if (status === 'transcribing') {
      if (model) {
        return $text('app_skills.audio.transcribe.transcribing_via').replace(
          '{model}',
          getModelDisplayName(model),
        );
      }
      return $text('app_skills.audio.transcribe.processing');
    }
    if (status === 'error') {
      return uploadError || $text('app_skills.audio.transcribe.upload_failed');
    }
    if (status === 'finished') {
      if (!isAuthenticated) return $text('app_skills.audio.transcribe.signup_to_upload');
      // Show duration (e.g. "0:42") — the "Transcribed by <model>" label is now
      // rendered above the transcript preview text in the details snippet instead.
      if (duration) return duration;
      return $text('app_skills.audio.transcribe.description');
    }
    return '';
  });

  /**
   * Truncated transcript for the preview area.
   * Shows the first MAX_TRANSCRIPT_PREVIEW chars with ellipsis if needed.
   */
  let transcriptPreview = $derived.by(() => {
    if (!transcript) return '';
    if (transcript.length <= MAX_TRANSCRIPT_PREVIEW) return transcript;
    return transcript.slice(0, MAX_TRANSCRIPT_PREVIEW - 1) + '\u2026';
  });

  // --- Audio controls ---

  function togglePlayback(e: MouseEvent) {
    // Prevent the click from bubbling to UnifiedEmbedPreview (which opens fullscreen)
    e.stopPropagation();
    if (!audioEl) return;
    if (isPlaying) {
      audioEl.pause();
    } else {
      audioEl.play().catch((err) => {
        console.error('[RecordingEmbedPreview] Audio play failed:', err);
      });
    }
  }

  function handleAudioPlay() {
    isPlaying = true;
  }

  function handleAudioPause() {
    isPlaying = false;
  }

  function handleAudioEnded() {
    isPlaying = false;
  }
</script>

<!--
  Hidden audio element at component top level (outside snippets).
  Snippets are rendered inside UnifiedEmbedPreview where pointer-events: none
  is applied to children of clickable embeds. The audio element doesn't need
  pointer events but must be in the DOM for JS playback control.
-->
{#if hasAudioSrc && status !== 'error'}
  <audio
    bind:this={audioEl}
    src={resolvedAudioSrc}
    onplay={handleAudioPlay}
    onpause={handleAudioPause}
    onended={handleAudioEnded}
    preload="metadata"
    style="display:none"
    aria-hidden="true"
  ></audio>
{/if}

<UnifiedEmbedPreview
  {id}
  appId="audio"
  skillId="transcribe"
  skillIconName="microphone"
  status={unifiedStatus}
  skillName={$text('app_skills.audio.transcribe.audio_recording')}
  {isMobile}
  onFullscreen={isFullscreenEnabled ? onFullscreen : undefined}
  onStop={showStop ? onStop : undefined}
  showStatus={true}
  customStatusText={statusText}
  showSkillIcon={false}
>
  {#snippet actionButton()}
    <!--
      Play/pause button rendered inside BasicInfosBar between the app icon
      and the status text. Needs pointer-events: auto to override the
      pointer-events: none on clickable embed children, and stopPropagation
      to prevent fullscreen opening on click.
    -->
    {#if hasAudioSrc && status === 'finished'}
      <button
        class="play-btn"
        onclick={togglePlayback}
        type="button"
        aria-label={isPlaying ? 'Pause' : 'Play'}
        style="pointer-events: auto !important;"
      >
        {#if isPlaying}
          <span class="pause-icon">
            <span class="bar"></span>
            <span class="bar"></span>
          </span>
        {:else}
          <span class="play-icon"></span>
        {/if}
      </button>
    {/if}
  {/snippet}

  {#snippet details({ isMobile: isMobileSnippet })}
    <div class="recording-preview" class:mobile={isMobileSnippet}>

      {#if !isAuthenticated && status === 'finished'}
        <!--
          Unauthenticated user: show signup prompt in the details area.
          They can still play the local recording but cannot see transcripts.
        -->
        <p class="signup-prompt">{$text('app_skills.audio.transcribe.signup_to_see_transcript')}</p>

      {:else if status === 'error'}
        <!-- Error state: error icon + message + optional retry button -->
        <div class="error-state">
          <span class="error-icon">!</span>
          <span class="error-text">{uploadError || $text('app_skills.audio.transcribe.upload_failed')}</span>
          {#if onRetry}
            <!--
              Retry button: shown only when upload succeeded and s3Files is present,
              so transcription can be retried without re-uploading the audio.
              Fires 'retryrecordingtranscription' CustomEvent via RecordingRenderer.ts.
            -->
            <button class="retry-btn" type="button" onclick={onRetry}>
              {$text('app_skills.audio.transcribe.retry')}
            </button>
          {/if}
        </div>

      {:else if status === 'uploading' || status === 'transcribing' || isLoadingAudio}
        <!--
          Processing / loading state: provider info row (when model is known) above
          the shimmer placeholder lines. The gradient sweep animation gives a polished look.
        -->
        {#if (status === 'transcribing') && model}
          <div class="model-info-line">
            {#if modelIconUrl}
              <div class="model-icon-circle">
                <img src={modelIconUrl} alt="" class="model-icon" />
              </div>
            {/if}
            <span class="model-info-text">
              {$text('app_skills.audio.transcribe.transcribing_via').replace('{model}', getModelDisplayName(model))}
            </span>
          </div>
        {/if}
        <div class="shimmer-container">
          <div class="shimmer-line" style="width: 90%;"></div>
          <div class="shimmer-line" style="width: 75%;"></div>
          <div class="shimmer-line" style="width: 85%;"></div>
          <div class="shimmer-line" style="width: 55%;"></div>
        </div>

      {:else if transcriptPreview}
        <!--
          Finished with transcript: show provider label ("Transcribed by Mistral:")
          with a circular logo above the truncated preview text.
          The label is only shown when we know which model was used so it's
          future-proof if the transcription provider is swapped out.
        -->
        {#if model}
          <div class="model-info-line">
            {#if modelIconUrl}
              <div class="model-icon-circle">
                <img src={modelIconUrl} alt="" class="model-icon" />
              </div>
            {/if}
            <span class="model-info-text">
              {$text('app_skills.audio.transcribe.transcribed_by').replace('{model}', getModelDisplayName(model))}
            </span>
          </div>
        {/if}
        <p class="transcript-preview">{transcriptPreview}</p>

      {:else if audioLoadError}
        <!-- Audio loading failed but we might still have no transcript -->
        <p class="audio-load-error">{audioLoadError}</p>

      {:else}
        <!--
          Finished but no transcript available yet.
          Could be a recording that hasn't been transcribed or data still loading.
        -->
        <p class="no-transcript">{$text('app_skills.audio.transcribe.no_transcript')}</p>
      {/if}

    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ---- Details area container ---- */
  .recording-preview {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 8px;
    padding: 14px 16px;
    box-sizing: border-box;
    overflow: hidden;
  }

  .recording-preview.mobile {
    padding: 10px 12px;
    gap: 6px;
  }

  /* ---- Signup prompt for unauthenticated users ---- */
  .signup-prompt {
    margin: 0;
    font-size: 13px;
    line-height: 1.5;
    color: var(--color-grey-50, #888);
    font-style: italic;
  }

  /* ---- Provider model info row (used in both transcribing and finished states) ---- */
  /* Displays a circular provider logo followed by the "Transcribing via / Transcribed by" label */
  .model-info-line {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  /* Circular container for the provider logo SVG */
  .model-icon-circle {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--color-grey-10, #f5f5f5);
    border: 1px solid var(--color-grey-20, #e8e8e8);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    overflow: hidden;
  }

  .model-icon {
    width: 10px;
    height: 10px;
    object-fit: contain;
    flex-shrink: 0;
  }

  .model-info-text {
    font-size: 10px;
    line-height: 1.4;
    color: var(--color-grey-50, #888);
    font-weight: 500;
    letter-spacing: 0.01em;
  }

  /* ---- Transcript preview text ---- */
  .transcript-preview {
    margin: 0;
    font-size: 12px;
    line-height: 1.5;
    color: var(--color-grey-70, #444);
    display: -webkit-box;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
    word-break: break-word;
  }

  /* ---- No transcript message ---- */
  .no-transcript {
    margin: 0;
    font-size: 12px;
    line-height: 1.5;
    color: var(--color-grey-50, #888);
  }

  /* ---- Audio load error ---- */
  .audio-load-error {
    margin: 0;
    font-size: 11px;
    color: var(--color-grey-50, #888);
  }

  /* ---- Shimmer placeholder (gradient sweep) ---- */
  .shimmer-container {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 4px 0;
  }

  .shimmer-line {
    height: 10px;
    background: linear-gradient(
      90deg,
      var(--color-grey-15, #f0f0f0) 25%,
      var(--color-grey-10, #f8f8f8) 50%,
      var(--color-grey-15, #f0f0f0) 75%
    );
    background-size: 200% 100%;
    border-radius: 4px;
    animation: shimmerSweep 1.5s ease-in-out infinite;
  }

  @keyframes shimmerSweep {
    0% {
      background-position: 200% 0;
    }
    100% {
      background-position: -200% 0;
    }
  }

  /* ---- Error state ---- */
  .error-state {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    color: var(--color-grey-50, #888);
  }

  .error-icon {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--color-error-20, #f5c0c0);
    color: var(--color-error-70, #b04a4a);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: 700;
    flex-shrink: 0;
  }

  .error-text {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Retry button in error state */
  .retry-btn {
    flex-shrink: 0;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 500;
    border-radius: 4px;
    border: 1px solid var(--color-app-audio, #e05555);
    color: var(--color-app-audio, #e05555);
    background: transparent;
    cursor: pointer;
    transition: background 0.15s ease, color 0.15s ease;
    white-space: nowrap;
  }

  .retry-btn:hover {
    background: var(--color-app-audio, #e05555);
    color: #fff;
  }

  /* ---- Play/Pause button (rendered inside BasicInfosBar via actionButton snippet) ----
     Must override ALL global button styles from buttons.css which applies:
     background-color, padding: 25px 30px, border-radius: 20px, filter: drop-shadow,
     min-width: 112px, height: 41px, margin-right: 10px, scale on hover/active.
     Follows the same pattern as .stop-button in BasicInfosBar.svelte. */
  .play-btn {
    width: 36px !important;
    height: 36px !important;
    border-radius: 50% !important;
    background: var(--color-app-audio, #e05555) !important;
    background-color: var(--color-app-audio, #e05555) !important;
    border: none !important;
    padding: 0 !important;
    min-width: auto !important;
    filter: none !important;
    margin-left: auto !important;
    margin-right: 10px !important;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    transition: background 0.15s ease, transform 0.1s ease;
    /* Override pointer-events: none from UnifiedEmbedPreview clickable children */
    pointer-events: auto !important;
  }

  .play-btn:hover {
    background: color-mix(in srgb, var(--color-app-audio, #e05555) 85%, #000 15%) !important;
    background-color: color-mix(in srgb, var(--color-app-audio, #e05555) 85%, #000 15%) !important;
    transform: scale(1.05);
    scale: 1 !important; /* Override scale: 1.02 from buttons.css */
  }

  .play-btn:active {
    transform: scale(0.97);
    scale: 1 !important; /* Override scale: 0.98 from buttons.css */
    filter: none !important;
  }

  /* Play icon: CSS-only right-pointing triangle */
  .play-icon {
    width: 0;
    height: 0;
    border-top: 7px solid transparent;
    border-bottom: 7px solid transparent;
    border-left: 12px solid white;
    margin-left: 2px; /* optical centering */
  }

  /* Pause icon: two vertical bars */
  .pause-icon {
    display: flex;
    gap: 3px;
    align-items: center;
    height: 14px;
  }

  .pause-icon .bar {
    width: 3px;
    height: 14px;
    background: white;
    border-radius: 2px;
  }

  /* ---- Dark mode ---- */
  :global(.dark) .transcript-preview {
    color: var(--color-grey-30, #ccc);
  }

  :global(.dark) .shimmer-line {
    background: linear-gradient(
      90deg,
      var(--color-grey-80, #333) 25%,
      var(--color-grey-75, #3a3a3a) 50%,
      var(--color-grey-80, #333) 75%
    );
    background-size: 200% 100%;
    animation: shimmerSweep 1.5s ease-in-out infinite;
  }

  :global(.dark) .signup-prompt {
    color: var(--color-grey-40, #aaa);
  }

  :global(.dark) .no-transcript {
    color: var(--color-grey-40, #aaa);
  }
</style>
