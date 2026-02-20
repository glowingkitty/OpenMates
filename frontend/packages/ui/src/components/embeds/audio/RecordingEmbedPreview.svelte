<!--
  frontend/packages/ui/src/components/embeds/audio/RecordingEmbedPreview.svelte

  Preview card for user-recorded audio embeds with live transcription.

  Architecture mirrors ImageEmbedPreview:
  - No skill icon (showSkillIcon=false)
  - skillName = "Voice Note" (i18n key: app_skills.audio.transcribe)
  - customStatusText = dynamic subtitle reflecting upload/transcription state
  - Shows waveform-style bars + transcript preview in the details snippet

  Status lifecycle:
    'uploading'      → "Uploading…"         (audio blob uploading to server)
    'transcribing'   → "Transcribing…"      (upload done, Mistral Voxtral running)
    'finished'       → transcript preview   (or "Transcript not available")
    'error'          → error message        (upload failed or transcription failed)

  Rendering contexts:

  A) Editor context (blobUrl set — local blob from recording session):
     - Shows audio player using the local blob URL.
     - Status shown as subtitle.
     - Transcript shown as preview text once available.

  B) Read-only context (blobUrl absent, S3 data present — received/sent message):
     - Audio is fetched and decrypted from S3 on demand.
     - Transcript shown from embed content.
     - Fullscreen opens editable transcript view (for editor context only).

  Fullscreen: calls onFullscreen() → RecordingRenderer.ts fires 'recordingfullscreen'
  CustomEvent → MessageInput.svelte / ActiveChat handles it.

  Stop button: calls onStop() → RecordingRenderer.ts fires 'cancelrecordingupload'
  CustomEvent → Embed.ts node view listener calls cancelUpload(id) + deletes the node.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';

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
    onFullscreen?: () => void;
    /** Called when user clicks the stop button during upload */
    onStop?: () => void;
  }

  let {
    id,
    // filename, s3Files, s3BaseUrl, aesKey, aesNonce are reserved for the read-only
    // context (received messages, S3 decryption). They are passed through to the
    // RecordingRenderer's fullscreen event and used by future decryption logic.
    // Destructured here so Svelte tracks them as props; not used in the template yet.
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
  }: Props = $props();

  // Reference reserved props in a no-op to prevent ESLint from flagging them
  // as unused. They are exposed for future read-only context use (S3 audio fetch).
  void filename; void s3Files; void s3BaseUrl; void aesKey; void aesNonce;

  // Audio element reference for the playback controls
  let audioEl: HTMLAudioElement | undefined = $state(undefined);
  let isPlaying = $state(false);
  let currentTime = $state(0);
  let totalDuration = $state(0);

  // Cleanup: revoke the local blob URL on destroy to avoid memory leaks.
  // (Only revoke blob: URLs — S3 URLs must not be revoked.)
  onDestroy(() => {
    if (audioEl) {
      audioEl.pause();
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

  /** Whether we have a playable audio source */
  let hasAudioSrc = $derived(!!blobUrl);

  /** Whether fullscreen (transcript editing) is available */
  let isFullscreenEnabled = $derived(
    status === 'finished' && (!!transcript || !!blobUrl),
  );

  /** Whether to show the stop button */
  let showStop = $derived(hasAudioSrc && status === 'uploading' && !!onStop);

  /**
   * Card subtitle text based on current status:
   * - uploading    → "Uploading…"
   * - transcribing → "Transcribing…"
   * - error        → error message
   * - finished     → duration + "Voice recording" or "Sign up to upload"
   */
  let statusText = $derived.by(() => {
    if (status === 'uploading') return $text('app_skills.audio.transcribe.uploading');
    if (status === 'transcribing') return $text('app_skills.audio.transcribe.transcribing');
    if (status === 'error') {
      return uploadError || $text('app_skills.audio.transcribe.upload_failed');
    }
    if (status === 'finished') {
      if (!isAuthenticated) return $text('app_skills.audio.transcribe.signup_to_upload');
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

  /** Progress bar fill percentage (0–100) */
  let progressPercent = $derived(
    totalDuration > 0 ? Math.round((currentTime / totalDuration) * 100) : 0,
  );

  // --- Audio controls ---

  function togglePlayback() {
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
    currentTime = 0;
  }

  function handleAudioTimeUpdate() {
    if (audioEl) currentTime = audioEl.currentTime;
  }

  function handleAudioLoadedMetadata() {
    if (audioEl) totalDuration = audioEl.duration;
  }

  function handleProgressClick(e: MouseEvent) {
    if (!audioEl || !totalDuration) return;
    const bar = e.currentTarget as HTMLElement;
    const rect = bar.getBoundingClientRect();
    const fraction = (e.clientX - rect.left) / rect.width;
    audioEl.currentTime = fraction * totalDuration;
  }

  /** Format seconds into MM:SS display string */
  function formatSeconds(s: number): string {
    if (!isFinite(s) || isNaN(s)) return '0:00';
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, '0')}`;
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="audio"
  skillId="transcribe"
  skillIconName="microphone"
  status={unifiedStatus}
  skillName={$text('app_skills.audio.transcribe')}
  {isMobile}
  onFullscreen={isFullscreenEnabled ? onFullscreen : undefined}
  onStop={showStop ? onStop : undefined}
  showStatus={true}
  customStatusText={statusText}
  showSkillIcon={false}
>
  {#snippet details({ isMobile: isMobileSnippet })}
    <div class="recording-preview" class:mobile={isMobileSnippet}>

      {#if hasAudioSrc && status !== 'error'}
        <!--
          Audio player: compact waveform-style bar + play/pause button.
          Uses the local blob URL in editor context.
          Hidden audio element provides playback control.
        -->
        <audio
          bind:this={audioEl}
          src={blobUrl}
          onplay={handleAudioPlay}
          onpause={handleAudioPause}
          onended={handleAudioEnded}
          ontimeupdate={handleAudioTimeUpdate}
          onloadedmetadata={handleAudioLoadedMetadata}
          preload="metadata"
          style="display:none"
          aria-hidden="true"
        ></audio>

        <div class="player-row">
          <!-- Play/Pause button with aria-label for accessibility -->
          <button
            class="play-btn"
            onclick={togglePlayback}
            type="button"
            aria-label={isPlaying ? 'Pause' : 'Play'}
          >
            {#if isPlaying}
              <!-- Pause icon: two vertical bars -->
              <span class="pause-icon">
                <span class="bar"></span>
                <span class="bar"></span>
              </span>
            {:else}
              <!-- Play icon: right-pointing triangle -->
              <span class="play-icon"></span>
            {/if}
          </button>

          <!-- Progress bar + time -->
          <div class="progress-area">
            <!-- Seek bar — button role makes it natively interactive and accessible -->
            <button
              class="progress-bar"
              type="button"
              role="slider"
              aria-label="Seek audio"
              aria-valuenow={progressPercent}
              aria-valuemin={0}
              aria-valuemax={100}
              onclick={handleProgressClick}
            >
              <div
                class="progress-fill"
                style="width: {progressPercent}%"
              ></div>
            </button>
            <span class="time-label">
              {formatSeconds(currentTime)} / {formatSeconds(totalDuration || 0)}
            </span>
          </div>
        </div>

        {#if status === 'transcribing'}
          <!-- Show transcribing placeholder while waiting for transcript -->
          <div class="transcript-loading">
            <div class="skeleton-line long"></div>
            <div class="skeleton-line short"></div>
          </div>
        {:else if transcriptPreview}
          <p class="transcript-preview">{transcriptPreview}</p>
        {/if}

      {:else if status === 'error'}
        <!-- Error state: no audio playback, just an error indicator -->
        <div class="error-state">
          <span class="error-icon">!</span>
          <span class="error-text">{uploadError || $text('app_skills.audio.transcribe.upload_failed')}</span>
        </div>

      {:else}
        <!-- Skeleton: upload in progress or no blob URL (received message, read-only) -->
        <div class="skeleton-content">
          <div class="skeleton-player-row">
            <div class="skeleton-circle"></div>
            <div class="skeleton-bar-area">
              <div class="skeleton-line long"></div>
              <div class="skeleton-line short"></div>
            </div>
          </div>
          {#if status === 'transcribing'}
            <div class="skeleton-line medium"></div>
          {/if}
        </div>
      {/if}

    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .recording-preview {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 14px 16px;
    box-sizing: border-box;
    overflow: hidden;
  }

  .recording-preview.mobile {
    padding: 10px 12px;
    gap: 8px;
  }

  /* ---- Audio player row ---- */
  .player-row {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-shrink: 0;
  }

  /* Play / Pause button */
  .play-btn {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: var(--color-app-audio, #e05555);
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    transition: background 0.15s ease, transform 0.1s ease;
  }

  .play-btn:hover {
    background: color-mix(in srgb, var(--color-app-audio, #e05555) 85%, #000 15%);
    transform: scale(1.05);
  }

  .play-btn:active {
    transform: scale(0.97);
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

  /* Progress bar */
  .progress-area {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }

  .progress-bar {
    height: 4px;
    background: var(--color-grey-20, #e0e0e0);
    border-radius: 2px;
    cursor: pointer;
    overflow: hidden;
    position: relative;
    /* Reset button defaults */
    border: none;
    padding: 0;
    width: 100%;
    display: block;
  }

  .progress-bar:hover {
    height: 6px;
    margin-top: -1px;
  }

  .progress-fill {
    height: 100%;
    background: var(--color-app-audio, #e05555);
    border-radius: 2px;
    transition: width 0.1s linear;
    min-width: 0;
  }

  .time-label {
    font-size: 11px;
    color: var(--color-grey-50, #888);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  /* ---- Transcript preview text ---- */
  .transcript-preview {
    margin: 0;
    font-size: 12px;
    line-height: 1.5;
    color: var(--color-grey-70, #444);
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    word-break: break-word;
  }

  /* ---- Transcribing loading placeholder ---- */
  .transcript-loading {
    display: flex;
    flex-direction: column;
    gap: 5px;
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

  /* ---- Skeleton loading ---- */
  .skeleton-content {
    display: flex;
    flex-direction: column;
    gap: 10px;
    width: 100%;
  }

  .skeleton-player-row {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .skeleton-circle {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: var(--color-grey-15, #f0f0f0);
    flex-shrink: 0;
    animation: pulse 1.5s ease-in-out infinite;
  }

  .skeleton-bar-area {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .skeleton-line {
    height: 10px;
    background: var(--color-grey-15, #f0f0f0);
    border-radius: 4px;
    animation: pulse 1.5s ease-in-out infinite;
  }

  .skeleton-line.long { width: 80%; }
  .skeleton-line.medium { width: 65%; }
  .skeleton-line.short { width: 45%; }

  @keyframes pulse {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
  }

  /* ---- Dark mode ---- */
  :global(.dark) .progress-bar {
    background: var(--color-grey-70, #444);
  }

  :global(.dark) .transcript-preview {
    color: var(--color-grey-30, #ccc);
  }

  :global(.dark) .skeleton-circle,
  :global(.dark) .skeleton-line {
    background: var(--color-grey-80, #333);
  }

  :global(.dark) .time-label {
    color: var(--color-grey-40, #aaa);
  }
</style>
