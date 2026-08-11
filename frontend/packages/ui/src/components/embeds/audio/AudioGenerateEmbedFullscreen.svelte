<!--
  frontend/packages/ui/src/components/embeds/audio/AudioGenerateEmbedFullscreen.svelte

  Fullscreen player for audio.generate and audio.speak app-skill embeds.
  Uses the shared fullscreen shell and a recording-style custom audio player so
  generated SFX/TTS results do not inherit music artwork or native controls.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import { text } from '@repo/ui';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { fetchAndDecryptAudio, releaseCachedAudio } from './audioEmbedCrypto';
  import { getModelDisplayName } from '../../../utils/modelDisplayName';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import {
    getGeneratedAudioDataUrl,
    getGeneratedAudioFiles,
    getNumberField,
    getStringField,
    normalizeAudioSkillId,
    resolveGeneratedAudioContent,
  } from './audioGeneratedEmbedContent';

  const WAVEFORM_SAMPLES = [22, 38, 28, 52, 45, 74, 58, 86, 64, 49, 72, 56, 41, 68, 84, 62, 46, 33, 54, 39, 25, 34, 21, 16];
  const HEADER_TITLE_MAX_LENGTH = 80;
  type GeneratedAudioStatus = 'processing' | 'finished' | 'error';

  interface Props {
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
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
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
  }: Props = $props();

  let updatedContent = $state<Record<string, unknown> | null>(null);
  let updatedStatus = $state<GeneratedAudioStatus | undefined>();
  let audioUrl = $state<string | undefined>();
  let audioError = $state<string | undefined>();
  let isLoadingAudio = $state(false);
  let audioEl: HTMLAudioElement | undefined = $state(undefined);
  let isPlaying = $state(false);
  let currentTime = $state(0);
  let totalDuration = $state(0);
  let playbackAnimationFrame: number | null = null;
  let retainedS3Key: string | undefined;
  let lastEmbedIdentity = $state<string | undefined>();

  const sourceContent = $derived(resolveGeneratedAudioContent(updatedContent ?? data.decodedContent ?? {}));
  const normalizedSkillId = $derived(normalizeAudioSkillId(sourceContent.skill_id));
  const skillName = $derived(
    normalizedSkillId === 'speak'
      ? $text('app_skills.audio.speak')
      : $text('app_skills.audio.generate')
  );
  const displayPrompt = $derived(
    getStringField(sourceContent, ['prompt', 'text_preview', 'text'])
  );
  const displayMode = $derived(
    getStringField(sourceContent, [
      'mode',
      normalizedSkillId === 'speak' ? 'voice' : 'generation_type',
    ]) || (normalizedSkillId === 'speak' ? 'speech' : 'sound_effect')
  );
  const displayModeLabel = $derived(displayMode.replace(/_/g, ' ').replace(/^./, (char) => char.toUpperCase()));
  const resolvedModel = $derived(getStringField(sourceContent, ['model']));
  const modelLabel = $derived(resolvedModel ? getModelDisplayName(resolvedModel) : 'ElevenLabs');
  const resolvedDurationSeconds = $derived(
    getNumberField(sourceContent, ['duration_seconds']) ?? getGeneratedAudioFiles(sourceContent)?.original?.duration_seconds
  );
  const durationLabel = $derived(formatDuration(resolvedDurationSeconds));
  const headerTitle = $derived(displayPrompt ? truncate(displayPrompt, HEADER_TITLE_MAX_LENGTH) : skillName);
  const headerSubtitle = $derived([modelLabel, durationLabel].filter(Boolean).join(' · '));
  const resolvedS3BaseUrl = $derived(getStringField(sourceContent, ['s3_base_url']));
  const resolvedFiles = $derived(getGeneratedAudioFiles(sourceContent));
  const resolvedAesKey = $derived(getStringField(sourceContent, ['aes_key']));
  const resolvedAesNonce = $derived(getStringField(sourceContent, ['aes_nonce']));
  const embedIdentity = $derived(
    embedId ||
      getStringField(data.embedData ?? {}, ['embed_id', 'id']) ||
      getStringField(data.decodedContent ?? {}, ['embed_id', 'id']) ||
      ''
  );
  const resolvedPreviewAudioUrl = $derived(
    getStringField(sourceContent, ['previewAudioUrl', 'preview_audio_url', 'audio_url']) ||
      getGeneratedAudioDataUrl(sourceContent)
  );
  const embedStatus = $derived.by(() => {
    const rawStatus = sourceContent.status ?? data.embedData?.status ?? data.attrs?.status;
    const normalizedStatus = normalizeStatus(rawStatus);
    if (updatedStatus) return updatedStatus;
    if (normalizedStatus) return normalizedStatus;
    return resolvedPreviewAudioUrl || resolvedFiles?.original?.s3_key ? 'finished' : 'processing';
  });
  const resolvedTestIdPrefix = $derived(`audio-${normalizedSkillId}`);
  const promptLabel = $derived($text('embeds.music_generate.prompt_label'));
  const progressPercent = $derived.by(() => {
    const durationSeconds = totalDuration || resolvedDurationSeconds || 0;
    if (durationSeconds <= 0) return 0;
    return Math.round(Math.max(0, Math.min(100, (currentTime / durationSeconds) * 100)));
  });
  const downloadFilename = $derived(
    normalizedSkillId === 'speak' ? 'openmates-generated-speech.mp3' : 'openmates-generated-sound-effect.mp3'
  );

  onDestroy(() => {
    resetLoadedAudio();
  });

  $effect(() => {
    if (lastEmbedIdentity === undefined) {
      lastEmbedIdentity = embedIdentity;
      return;
    }
    if (embedIdentity !== lastEmbedIdentity) {
      updatedContent = null;
      updatedStatus = undefined;
      resetLoadedAudio();
      lastEmbedIdentity = embedIdentity;
    }
  });

  $effect(() => {
    if (embedStatus !== 'finished') {
      isLoadingAudio = embedStatus === 'processing';
      return;
    }
    if (resolvedPreviewAudioUrl) {
      if (retainedS3Key) {
        releaseCachedAudio(retainedS3Key);
        retainedS3Key = undefined;
      }
      audioError = undefined;
      isLoadingAudio = false;
      audioUrl = resolvedPreviewAudioUrl;
      return;
    }

    const file = resolvedFiles?.original;
    if (!file?.s3_key || !resolvedAesKey) return;
    if (retainedS3Key === file.s3_key && audioUrl) return;
    loadAudio(file.s3_key, file.mime_type || 'audio/mpeg', file);
  });

  $effect(() => {
    currentTime = 0;
    totalDuration = resolvedDurationSeconds || 0;
  });

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    const decoded = resolveGeneratedAudioContent(data.decodedContent);
    updatedContent = decoded;
    updatedStatus = normalizeStatus(decoded.status) ?? normalizeStatus(data.status) ?? updatedStatus;
  }

  function normalizeStatus(value: unknown): GeneratedAudioStatus | undefined {
    return value === 'processing' || value === 'finished' || value === 'error' ? value : undefined;
  }

  async function loadAudio(s3Key: string, mimeType: string, variant: unknown) {
    try {
      if (retainedS3Key && retainedS3Key !== s3Key) {
        releaseCachedAudio(retainedS3Key);
        retainedS3Key = undefined;
      }
      isLoadingAudio = true;
      audioError = undefined;
      audioUrl = await fetchAndDecryptAudio(resolvedS3BaseUrl, s3Key, resolvedAesKey, resolvedAesNonce, mimeType, variant);
      retainedS3Key = s3Key;
    } catch (err) {
      console.error('[AudioGenerateEmbedFullscreen] Failed to load generated audio:', err);
      audioError = err instanceof Error ? err.message : 'Audio unavailable';
    } finally {
      isLoadingAudio = false;
    }
  }

  function togglePlayback() {
    if (!audioEl) return;
    if (isPlaying) {
      audioEl.pause();
    } else {
      audioEl.play().catch((err) => {
        console.error('[AudioGenerateEmbedFullscreen] Audio play failed:', err);
      });
    }
  }

  function handleAudioPlay() {
    isPlaying = true;
    startPlaybackProgressLoop();
  }

  function handleAudioPause() {
    isPlaying = false;
    updatePlaybackProgressFromAudio();
    stopPlaybackProgressLoop();
  }

  function handleAudioEnded() {
    isPlaying = false;
    currentTime = 0;
    stopPlaybackProgressLoop();
  }

  function handleAudioLoadedMetadata() {
    updatePlaybackProgressFromAudio();
  }

  function updatePlaybackProgressFromAudio() {
    if (!audioEl) return;
    currentTime = audioEl.currentTime;
    totalDuration = Number.isFinite(audioEl.duration) && audioEl.duration > 0
      ? audioEl.duration
      : (totalDuration || resolvedDurationSeconds || 0);
  }

  function startPlaybackProgressLoop() {
    stopPlaybackProgressLoop();
    const tick = () => {
      updatePlaybackProgressFromAudio();
      if (audioEl && !audioEl.paused && !audioEl.ended) {
        playbackAnimationFrame = requestAnimationFrame(tick);
      }
    };
    playbackAnimationFrame = requestAnimationFrame(tick);
  }

  function stopPlaybackProgressLoop() {
    if (playbackAnimationFrame !== null) {
      cancelAnimationFrame(playbackAnimationFrame);
      playbackAnimationFrame = null;
    }
  }

  function resetLoadedAudio() {
    stopPlaybackProgressLoop();
    if (audioEl) audioEl.pause();
    if (retainedS3Key) releaseCachedAudio(retainedS3Key);
    retainedS3Key = undefined;
    audioUrl = undefined;
    audioError = undefined;
    isLoadingAudio = false;
    isPlaying = false;
    currentTime = 0;
    totalDuration = 0;
  }

  function handleProgressClick(e: MouseEvent) {
    const durationSeconds = totalDuration || resolvedDurationSeconds || 0;
    if (!audioEl || !durationSeconds) return;
    const bar = e.currentTarget as HTMLElement;
    const rect = bar.getBoundingClientRect();
    audioEl.currentTime = ((e.clientX - rect.left) / rect.width) * durationSeconds;
  }

  function formatDuration(seconds?: number): string {
    if (!seconds || !Number.isFinite(seconds)) return '';
    const minutes = Math.floor(seconds / 60);
    const rest = Math.floor(seconds % 60).toString().padStart(2, '0');
    return `${minutes}:${rest}`;
  }

  function truncate(value: string, max: number): string {
    return value.length > max ? `${value.slice(0, max - 1)}...` : value;
  }

  function noopDownload(): void {
    // UnifiedEmbedFullscreen uses this to reveal the native download anchor.
  }
</script>

<UnifiedEmbedFullscreen
  appId="audio"
  skillId={normalizedSkillId}
  skillIconName="audio"
  embedHeaderTitle={headerTitle}
  embedHeaderSubtitle={headerSubtitle}
  showSkillIcon={true}
  showShare={false}
  onDownload={audioUrl ? noopDownload : undefined}
  downloadHref={audioUrl ?? null}
  downloadFilename={downloadFilename}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet content()}
    <div class="generated-audio-fullscreen" data-testid={`${resolvedTestIdPrefix}-fullscreen`}>
      <section class="player-section">
        {#if audioUrl}
          <audio
            bind:this={audioEl}
            data-testid={`${resolvedTestIdPrefix}-fullscreen-audio`}
            src={audioUrl}
            onplay={handleAudioPlay}
            onpause={handleAudioPause}
            onended={handleAudioEnded}
            ontimeupdate={updatePlaybackProgressFromAudio}
            onloadedmetadata={handleAudioLoadedMetadata}
            preload="metadata"
            style="display:none"
            aria-hidden="true"
          ></audio>

          <div class="player-row">
            <button
              class="play-btn"
              onclick={togglePlayback}
              type="button"
              data-testid={`${resolvedTestIdPrefix}-fullscreen-play-button`}
              aria-label={isPlaying ? 'Pause' : 'Play'}
            >
              {#if isPlaying}
                <span class="pause-icon"><span class="bar"></span><span class="bar"></span></span>
              {:else}
                <span class="play-icon"></span>
              {/if}
            </button>

            <div class="progress-area">
              <button
                class="waveform-seek"
                type="button"
                role="slider"
                aria-label="Seek audio"
                aria-valuenow={progressPercent}
                aria-valuemin={0}
                aria-valuemax={100}
                onclick={handleProgressClick}
                data-testid={`${resolvedTestIdPrefix}-fullscreen-waveform`}
                data-progress={progressPercent}
                style={`--waveform-progress: ${progressPercent}%; --waveform-sample-count: ${WAVEFORM_SAMPLES.length};`}
              >
                <div class="waveform-bars">
                  {#each WAVEFORM_SAMPLES as sample, index (index)}
                    <span class="waveform-bar" style:height={`${sample}%`}></span>
                  {/each}
                </div>
                <span class="waveform-playhead"></span>
              </button>
              <span class="time-label">{formatDuration(currentTime)} / {formatDuration(totalDuration || resolvedDurationSeconds || 0)}</span>
            </div>
          </div>
        {:else if embedStatus === 'processing' || isLoadingAudio}
          <div class="player-skeleton">
            <div class="skeleton-circle"></div>
            <div class="skeleton-bar-area">
              <div class="skeleton-line long"></div>
              <div class="skeleton-line short"></div>
            </div>
          </div>
        {:else if audioError || getStringField(sourceContent, ['error'])}
          <p class="audio-error">{audioError || getStringField(sourceContent, ['error'])}</p>
        {:else}
          <p class="audio-error">Audio unavailable</p>
        {/if}
      </section>

      <section class="details-section">
        <dl>
          <div>
            <dt data-testid={`${resolvedTestIdPrefix}-prompt-label`}>{promptLabel}</dt>
            <dd data-testid={`${resolvedTestIdPrefix}-prompt`}>{displayPrompt || displayModeLabel}</dd>
          </div>
          <div>
            <dt>Mode</dt>
            <dd>{displayModeLabel}</dd>
          </div>
          <div>
            <dt>Model</dt>
            <dd>{modelLabel}</dd>
          </div>
          {#if durationLabel}
            <div>
              <dt>Duration</dt>
              <dd>{durationLabel}</dd>
            </div>
          {/if}
        </dl>
      </section>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .generated-audio-fullscreen {
    display: flex;
    flex-direction: column;
    width: 100%;
    min-height: 100%;
    box-sizing: border-box;
    overflow: hidden;
  }

  .player-section {
    padding: var(--spacing-12) var(--spacing-16) var(--spacing-10);
    flex-shrink: 0;
    border-bottom: 1px solid var(--color-grey-20, #f0f0f0);
  }

  .player-row,
  .player-skeleton {
    display: flex;
    align-items: center;
    gap: var(--spacing-8);
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
    gap: var(--spacing-2);
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
    gap: var(--spacing-3);
    min-width: 0;
  }

  .waveform-seek {
    height: 48px;
    width: 100%;
    padding: 0;
    min-width: 0;
    border: none;
    border-radius: 0;
    filter: none;
    background: transparent;
    cursor: pointer;
    position: relative;
    color: var(--color-app-audio, #e05555);
    overflow: hidden;
  }

  .waveform-bars {
    width: 100%;
    height: 100%;
    display: grid;
    grid-template-columns: repeat(var(--waveform-sample-count, 1), minmax(0, 1fr));
    align-items: center;
    gap: 2px;
    opacity: 0.82;
  }

  .waveform-bar {
    width: 100%;
    min-width: 1px;
    background: currentColor;
    border-radius: var(--radius-full, 9999px);
  }

  .waveform-playhead {
    position: absolute;
    top: 0;
    bottom: 0;
    left: var(--waveform-progress, 0%);
    width: 2px;
    background: currentColor;
    border-radius: var(--radius-full, 9999px);
    opacity: 0.95;
    transform: translateX(-1px);
    transition: left 0.1s linear;
  }

  .time-label {
    font-size: var(--font-size-xxs);
    color: var(--color-grey-50, #888);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  .details-section {
    flex: 1;
    overflow-y: auto;
    padding: var(--spacing-12) var(--spacing-16) var(--spacing-16);
    min-height: 0;
  }

  dl {
    display: grid;
    gap: var(--spacing-8);
    margin: 0;
  }

  dt {
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
    font-weight: 600;
    margin-bottom: var(--spacing-2);
  }

  dd {
    margin: 0;
    color: var(--color-font-primary);
    line-height: 1.55;
    word-break: break-word;
  }

  .skeleton-circle {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    background: var(--color-grey-20, #f0f0f0);
    flex-shrink: 0;
    animation: pulse 1.5s ease-in-out infinite;
  }

  .skeleton-bar-area {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
  }

  .skeleton-line {
    height: 10px;
    background: var(--color-grey-20, #f0f0f0);
    border-radius: var(--radius-1);
    animation: pulse 1.5s ease-in-out infinite;
  }

  .skeleton-line.long { width: 80%; }
  .skeleton-line.short { width: 45%; }

  .audio-error {
    font-size: var(--font-size-xs);
    color: var(--color-error, #d33);
    margin: 0;
    padding: var(--spacing-4) 0;
  }

  @keyframes pulse {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
  }

  :global(.dark) .player-section {
    border-bottom-color: var(--color-grey-80, #333);
  }

  :global(.dark) .skeleton-circle,
  :global(.dark) .skeleton-line {
    background: var(--color-grey-80, #333);
  }

  :global(.dark) dd {
    color: var(--color-font-primary-dark, #e0e0e0);
  }

  :global(.dark) .time-label {
    color: var(--color-grey-40, #aaa);
  }
</style>
