<!--
  frontend/packages/ui/src/components/embeds/audio/RecordingEmbedFullscreen.svelte

  Fullscreen transcript and audio player for user-recorded voice note embeds.

  Triggered when the user clicks a finished recording embed card (in either the
  message editor or a read-only chat message).

  Shows:
  - A working audio player (using local blob URL or decrypted S3 audio)
  - The full transcript text (scrollable)
  - Filename and duration in the bottom info bar (via UnifiedEmbedFullscreen)

  Event chain (from embed card click):
    RecordingEmbedPreview.svelte (onFullscreen prop)
    → RecordingRenderer.ts (dispatches 'recordingfullscreen' CustomEvent, bubbles)
    → [Editor path]    MessageInput.svelte re-dispatches → ActiveChat.svelte on:recordingfullscreen
    → [Read-only path] document listener in ActiveChat.svelte onMount
    → ActiveChat.svelte handleRecordingFullscreen → showRecordingFullscreen = true
    → this component is mounted

  Audio decryption:
  - Editor context: blobUrl is already a local blob (no fetch needed)
  - Read-only context: fetches and decrypts audio from S3 using AES-256-GCM
    via audioEmbedCrypto.ts (same pattern as imageEmbedCrypto.ts for images)
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { fetchAndDecryptAudio, releaseCachedAudio } from './audioEmbedCrypto';

  /** Max chars for filename display in the info bar */
  const MAX_FILENAME_LENGTH = 40;

  interface Props {
    /** Full transcript text from Mistral Voxtral */
    transcript?: string;
    /** Local blob URL (editor context — no S3 fetch needed) */
    blobUrl?: string;
    /** Original filename (e.g. "voice_note_2026-02-20.webm") */
    filename?: string;
    /** Formatted duration string (e.g. "1:23") */
    duration?: string;
    /** S3 file variants: { original: { s3_key, size_bytes } } */
    s3Files?: Record<string, { s3_key: string; size_bytes: number }>;
    /** S3 bucket base URL */
    s3BaseUrl?: string;
    /** Plaintext AES-256 key (base64) for client-side decryption */
    aesKey?: string;
    /** AES-GCM nonce (base64) */
    aesNonce?: string;
    /** Embed ID (reserved for future use) */
    embedId?: string;
    /** Close handler */
    onClose: () => void;
  }

  let {
    transcript,
    blobUrl,
    filename = 'voice_note.webm',
    duration,
    s3Files,
    s3BaseUrl,
    aesKey,
    aesNonce,
    embedId,
    onClose,
  }: Props = $props();

  // Reserved — not used directly in the template but passed through from event detail
  void embedId;

  // -------------------------------------------------------------------------
  // Audio loading state
  // -------------------------------------------------------------------------

  /** Resolved audio source: local blob (editor) or decrypted S3 URL (read-only) */
  let resolvedAudioSrc = $state<string | undefined>(blobUrl);
  let isLoadingAudio = $state(false);
  let audioLoadError = $state<string | undefined>(undefined);

  /** Audio element for playback controls */
  let audioEl: HTMLAudioElement | undefined = $state(undefined);
  let isPlaying = $state(false);
  let currentTime = $state(0);
  let totalDuration = $state(0);

  /** Retained S3 key for cache release on unmount */
  let retainedS3Key: string | undefined = undefined;

  onDestroy(() => {
    if (audioEl) audioEl.pause();
    if (retainedS3Key) {
      releaseCachedAudio(retainedS3Key);
      retainedS3Key = undefined;
    }
  });

  // -------------------------------------------------------------------------
  // Derived values
  // -------------------------------------------------------------------------

  /** S3 key for the original audio file */
  let audioS3Key = $derived(
    s3Files?.original?.s3_key ?? Object.values(s3Files ?? {})[0]?.s3_key,
  );

  /** Truncated filename for the info bar */
  let infoBarTitle = $derived.by(() => {
    if (!filename) return 'Voice Note';
    if (filename.length <= MAX_FILENAME_LENGTH) return filename;
    const lastDot = filename.lastIndexOf('.');
    if (lastDot > 0) {
      const ext = filename.slice(lastDot);
      const stem = filename.slice(0, lastDot);
      const allowedStem = MAX_FILENAME_LENGTH - ext.length - 1;
      return allowedStem > 0
        ? stem.slice(0, allowedStem) + '\u2026' + ext
        : filename.slice(0, MAX_FILENAME_LENGTH - 1) + '\u2026';
    }
    return filename.slice(0, MAX_FILENAME_LENGTH - 1) + '\u2026';
  });

  /** Info bar subtitle: duration when known */
  let infoBarSubtitle = $derived(duration || $text('app_skills.audio.transcribe'));

  /** Progress bar fill percentage (0–100) */
  let progressPercent = $derived(
    totalDuration > 0 ? Math.round((currentTime / totalDuration) * 100) : 0,
  );

  // -------------------------------------------------------------------------
  // Lazy audio fetch from S3 (read-only context)
  // -------------------------------------------------------------------------

  $effect(() => {
    // Already have a local blob URL — nothing to fetch
    if (blobUrl) {
      resolvedAudioSrc = blobUrl;
      return;
    }

    // Missing S3 data — skip
    if (!audioS3Key || !s3BaseUrl || !aesKey || !aesNonce) return;

    // Avoid re-fetching if already resolved
    if (retainedS3Key === audioS3Key && resolvedAudioSrc) return;

    isLoadingAudio = true;
    audioLoadError = undefined;

    const ext = audioS3Key.split('.').pop()?.toLowerCase() ?? 'webm';
    const mimeType = ext === 'mp4' ? 'audio/mp4' : ext === 'ogg' ? 'audio/ogg' : 'audio/webm';

    fetchAndDecryptAudio(s3BaseUrl, audioS3Key, aesKey, aesNonce, mimeType)
      .then((url) => {
        resolvedAudioSrc = url;
        retainedS3Key = audioS3Key;
        isLoadingAudio = false;
      })
      .catch((err: unknown) => {
        console.error('[RecordingEmbedFullscreen] Failed to fetch/decrypt audio:', err);
        audioLoadError = 'Audio unavailable';
        isLoadingAudio = false;
      });
  });

  // -------------------------------------------------------------------------
  // Audio controls
  // -------------------------------------------------------------------------

  function togglePlayback() {
    if (!audioEl) return;
    if (isPlaying) {
      audioEl.pause();
    } else {
      audioEl.play().catch((err) => {
        console.error('[RecordingEmbedFullscreen] Audio play failed:', err);
      });
    }
  }

  function handleAudioPlay() { isPlaying = true; }
  function handleAudioPause() { isPlaying = false; }
  function handleAudioEnded() { isPlaying = false; currentTime = 0; }
  function handleAudioTimeUpdate() { if (audioEl) currentTime = audioEl.currentTime; }
  function handleAudioLoadedMetadata() { if (audioEl) totalDuration = audioEl.duration; }

  function handleProgressClick(e: MouseEvent) {
    if (!audioEl || !totalDuration) return;
    const bar = e.currentTarget as HTMLElement;
    const rect = bar.getBoundingClientRect();
    audioEl.currentTime = ((e.clientX - rect.left) / rect.width) * totalDuration;
  }

  function formatSeconds(s: number): string {
    if (!isFinite(s) || isNaN(s)) return '0:00';
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, '0')}`;
  }
</script>

<UnifiedEmbedFullscreen
  appId="audio"
  skillId="transcribe"
  skillIconName="microphone"
  skillName={infoBarTitle}
  customStatusText={infoBarSubtitle}
  showStatus={true}
  showSkillIcon={false}
  showShare={false}
  title=""
  {onClose}
>
  {#snippet content()}
    <div class="recording-fullscreen">

      <!-- Audio player section -->
      <div class="player-section">
        {#if resolvedAudioSrc}
          <!-- Hidden audio element -->
          <audio
            bind:this={audioEl}
            src={resolvedAudioSrc}
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
            <!-- Play/Pause button -->
            <button
              class="play-btn"
              onclick={togglePlayback}
              type="button"
              aria-label={isPlaying ? 'Pause' : 'Play'}
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

            <!-- Seek bar + time -->
            <div class="progress-area">
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
                <div class="progress-fill" style="width: {progressPercent}%"></div>
              </button>
              <span class="time-label">
                {formatSeconds(currentTime)} / {formatSeconds(totalDuration || 0)}
              </span>
            </div>
          </div>

        {:else if isLoadingAudio}
          <!-- Loading skeleton while decrypting S3 audio -->
          <div class="player-skeleton">
            <div class="skeleton-circle"></div>
            <div class="skeleton-bar-area">
              <div class="skeleton-line long"></div>
              <div class="skeleton-line short"></div>
            </div>
          </div>
        {:else if audioLoadError}
          <p class="audio-error">{audioLoadError}</p>
        {/if}
      </div>

      <!-- Transcript section -->
      <div class="transcript-section">
        {#if transcript}
          <p class="transcript-text">{transcript}</p>
        {:else}
          <p class="no-transcript">No transcript available.</p>
        {/if}
      </div>

    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ==========================================================================
     Main layout: player at top, transcript scrollable below
     ========================================================================== */

  .recording-fullscreen {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    overflow: hidden;
  }

  /* ==========================================================================
     Audio player section
     ========================================================================== */

  .player-section {
    padding: 24px 32px 20px;
    flex-shrink: 0;
    border-bottom: 1px solid var(--color-grey-15, #f0f0f0);
  }

  .player-row {
    display: flex;
    align-items: center;
    gap: 16px;
  }

  .play-btn {
    width: 48px;
    height: 48px;
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

  .play-icon {
    width: 0;
    height: 0;
    border-top: 9px solid transparent;
    border-bottom: 9px solid transparent;
    border-left: 15px solid white;
    margin-left: 3px;
  }

  .pause-icon {
    display: flex;
    gap: 4px;
    align-items: center;
    height: 18px;
  }

  .pause-icon .bar {
    width: 4px;
    height: 18px;
    background: white;
    border-radius: 2px;
  }

  .progress-area {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
  }

  .progress-bar {
    height: 6px;
    background: var(--color-grey-20, #e0e0e0);
    border-radius: 3px;
    cursor: pointer;
    overflow: hidden;
    position: relative;
    border: none;
    padding: 0;
    width: 100%;
    display: block;
    transition: height 0.1s;
  }

  .progress-bar:hover {
    height: 8px;
  }

  .progress-fill {
    height: 100%;
    background: var(--color-app-audio, #e05555);
    border-radius: 3px;
    transition: width 0.1s linear;
    min-width: 0;
  }

  .time-label {
    font-size: 12px;
    color: var(--color-grey-50, #888);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  /* ==========================================================================
     Loading skeleton
     ========================================================================== */

  .player-skeleton {
    display: flex;
    align-items: center;
    gap: 16px;
  }

  .skeleton-circle {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    background: var(--color-grey-15, #f0f0f0);
    flex-shrink: 0;
    animation: pulse 1.5s ease-in-out infinite;
  }

  .skeleton-bar-area {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .skeleton-line {
    height: 10px;
    background: var(--color-grey-15, #f0f0f0);
    border-radius: 4px;
    animation: pulse 1.5s ease-in-out infinite;
  }

  .skeleton-line.long { width: 80%; }
  .skeleton-line.short { width: 45%; }

  @keyframes pulse {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
  }

  .audio-error {
    font-size: 13px;
    color: var(--color-grey-50, #888);
    margin: 0;
    padding: 8px 0;
  }

  /* ==========================================================================
     Transcript section
     ========================================================================== */

  .transcript-section {
    flex: 1;
    overflow-y: auto;
    padding: 24px 32px 32px;
    min-height: 0;
  }

  .transcript-text {
    margin: 0;
    font-size: 16px;
    line-height: 1.7;
    color: var(--color-font-primary);
    white-space: pre-wrap;
    word-break: break-word;
  }

  .no-transcript {
    margin: 0;
    font-size: 14px;
    color: var(--color-grey-50, #888);
    font-style: italic;
  }

  /* ==========================================================================
     Dark mode
     ========================================================================== */

  :global(.dark) .player-section {
    border-bottom-color: var(--color-grey-80, #333);
  }

  :global(.dark) .progress-bar {
    background: var(--color-grey-70, #444);
  }

  :global(.dark) .skeleton-circle,
  :global(.dark) .skeleton-line {
    background: var(--color-grey-80, #333);
  }

  :global(.dark) .transcript-text {
    color: var(--color-font-primary-dark, #e0e0e0);
  }

  :global(.dark) .time-label {
    color: var(--color-grey-40, #aaa);
  }
</style>
