<!--
  frontend/packages/ui/src/components/embeds/audio/AudioGenerateEmbedPreview.svelte

  Preview card for audio.generate and audio.speak app-skill embeds.
  Generated audio uses the same encrypted/static audio loading path as music,
  but renders like recording previews: a prompt details area plus a play button
  in the basic info bar instead of a second subtitle/status line.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { fetchAndDecryptAudio, releaseCachedAudio } from './audioEmbedCrypto';
  import { getModelDisplayName } from '../../../utils/modelDisplayName';
  import {
    getGeneratedAudioDataUrl,
    getGeneratedAudioFiles,
    getNumberField,
    getStringField,
    normalizeAudioSkillId,
    resolveGeneratedAudioContent,
    type GeneratedAudioFiles,
  } from './audioGeneratedEmbedContent';

  const WAVEFORM_SAMPLES = [22, 38, 28, 52, 45, 74, 58, 86, 64, 49, 72, 56, 41, 68, 84, 62, 46, 33, 54, 39, 25, 34, 21, 16];

  interface Props {
    id: string;
    skillId?: 'generate' | 'speak';
    content?: Record<string, unknown> | null;
    prompt?: string;
    textPreview?: string;
    generationType?: string;
    voice?: string;
    mode?: string;
    model?: string;
    durationSeconds?: number;
    s3BaseUrl?: string;
    files?: GeneratedAudioFiles;
    aesKey?: string;
    aesNonce?: string;
    previewAudioUrl?: string;
    status: 'processing' | 'finished' | 'error';
    error?: string;
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    skillId = 'generate',
    content,
    prompt,
    textPreview,
    generationType,
    voice,
    mode,
    model,
    durationSeconds,
    s3BaseUrl,
    files,
    aesKey,
    aesNonce,
    previewAudioUrl,
    status: statusProp,
    error,
    taskId,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let updatedContent = $state<Record<string, unknown> | null>(null);
  let updatedStatus = $state<'processing' | 'finished' | 'error' | undefined>();
  let audioUrl = $state<string | undefined>();
  let audioError = $state<string | undefined>();
  let audioEl: HTMLAudioElement | undefined = $state(undefined);
  let isPlaying = $state(false);
  let currentTime = $state(0);
  let playbackAnimationFrame: number | null = null;
  let retainedS3Key: string | undefined;

  const sourceContent = $derived(resolveGeneratedAudioContent(updatedContent ?? content));
  const normalizedSkillId = $derived(normalizeAudioSkillId(skillId || sourceContent.skill_id));
  const skillName = $derived(
    normalizedSkillId === 'speak'
      ? $text('app_skills.audio.speak')
      : $text('app_skills.audio.generate')
  );
  const status = $derived(updatedStatus ?? statusProp ?? 'processing');
  const displayPrompt = $derived(
    prompt || textPreview || getStringField(sourceContent, ['prompt', 'text_preview', 'text'])
  );
  const displayMode = $derived(
    mode ||
      (normalizedSkillId === 'speak'
        ? voice || getStringField(sourceContent, ['voice'])
        : generationType || getStringField(sourceContent, ['generation_type'])) ||
      getStringField(sourceContent, ['mode']) ||
      (normalizedSkillId === 'speak' ? 'speech' : 'sound_effect')
  );
  const resolvedModel = $derived(model || getStringField(sourceContent, ['model']));
  const resolvedDurationSeconds = $derived(
    durationSeconds ?? getNumberField(sourceContent, ['duration_seconds'])
  );
  const resolvedS3BaseUrl = $derived(s3BaseUrl || getStringField(sourceContent, ['s3_base_url']));
  const resolvedFiles = $derived(files || getGeneratedAudioFiles(sourceContent));
  const resolvedAesKey = $derived(aesKey || getStringField(sourceContent, ['aes_key']));
  const resolvedAesNonce = $derived(aesNonce || getStringField(sourceContent, ['aes_nonce']));
  const resolvedPreviewAudioUrl = $derived(
    previewAudioUrl ||
      getStringField(sourceContent, ['previewAudioUrl', 'preview_audio_url', 'audio_url']) ||
      getGeneratedAudioDataUrl(sourceContent)
  );
  const resolvedTestIdPrefix = $derived(`audio-${normalizedSkillId}`);
  const promptLabel = $derived($text('embeds.music_generate.prompt_label'));
  const modeLabel = $derived(displayMode.replace(/_/g, ' ').replace(/^./, (char) => char.toUpperCase()));
  const durationLabel = $derived(formatDuration(resolvedDurationSeconds || resolvedFiles?.original?.duration_seconds));
  const modelLabel = $derived(resolvedModel ? getModelDisplayName(resolvedModel) : 'ElevenLabs');
  const metaLabel = $derived(
    [modelLabel, durationLabel].filter(Boolean).join(' - ')
  );
  const hasAudioSrc = $derived(!!audioUrl);
  const waveformProgressPercent = $derived.by(() => {
    const total = resolvedDurationSeconds || resolvedFiles?.original?.duration_seconds || 0;
    if (!total || !Number.isFinite(total)) return 0;
    return Math.max(0, Math.min(100, (currentTime / total) * 100));
  });

  onDestroy(() => {
    stopPlaybackProgressLoop();
    if (audioEl) audioEl.pause();
    if (retainedS3Key) releaseCachedAudio(retainedS3Key);
  });

  $effect(() => {
    if (status !== 'finished') return;
    if (resolvedPreviewAudioUrl) {
      if (retainedS3Key) {
        releaseCachedAudio(retainedS3Key);
        retainedS3Key = undefined;
      }
      audioError = undefined;
      audioUrl = resolvedPreviewAudioUrl;
      return;
    }

    const file = resolvedFiles?.original;
    if (!file?.s3_key || !resolvedAesKey) return;
    if (retainedS3Key === file.s3_key && audioUrl) return;
    loadAudio(file.s3_key, file.mime_type || 'audio/mpeg');
  });

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    const decoded = resolveGeneratedAudioContent(data.decodedContent);
    updatedContent = decoded;
    if (decoded.status === 'processing' || decoded.status === 'finished' || decoded.status === 'error') {
      updatedStatus = decoded.status;
    } else if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      updatedStatus = data.status;
    }
  }

  async function loadAudio(s3Key: string, mimeType: string) {
    try {
      audioError = undefined;
      audioUrl = await fetchAndDecryptAudio(
        resolvedS3BaseUrl,
        s3Key,
        resolvedAesKey,
        resolvedAesNonce,
        mimeType,
      );
      retainedS3Key = s3Key;
    } catch (err) {
      console.error('[AudioGenerateEmbedPreview] Failed to load generated audio:', err);
      audioError = err instanceof Error ? err.message : 'Audio unavailable';
    }
  }

  function togglePlayback(event: MouseEvent) {
    event.stopPropagation();
    if (!audioEl) return;
    if (isPlaying) {
      audioEl.pause();
    } else {
      audioEl.play().catch((err) => {
        console.error('[AudioGenerateEmbedPreview] Audio play failed:', err);
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

  function formatDuration(seconds?: number): string {
    if (!seconds || Number.isNaN(seconds)) return '';
    const minutes = Math.floor(seconds / 60);
    const rest = Math.floor(seconds % 60).toString().padStart(2, '0');
    return `${minutes}:${rest}`;
  }
</script>

{#if hasAudioSrc && status !== 'error'}
  <audio
    bind:this={audioEl}
    data-testid={`${resolvedTestIdPrefix}-audio`}
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
{/if}

<UnifiedEmbedPreview
  {id}
  appId="audio"
  skillId={normalizedSkillId}
  skillIconName="audio"
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  showStatus={false}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet actionButton()}
    {#if hasAudioSrc && status === 'finished'}
      <button
        class="play-btn"
        onclick={togglePlayback}
        type="button"
        data-testid={`${resolvedTestIdPrefix}-preview-play-button`}
        aria-label={isPlaying ? 'Pause' : 'Play'}
        style="pointer-events: auto !important;"
      >
        {#if isPlaying}
          <span class="pause-icon"><span class="bar"></span><span class="bar"></span></span>
        {:else}
          <span class="play-icon"></span>
        {/if}
      </button>
    {/if}
  {/snippet}

  {#snippet details({ isMobile: isMobileSnippet })}
    <div class="generated-audio-preview" data-testid={`${resolvedTestIdPrefix}-preview`} class:mobile={isMobileSnippet}>
      {#if status === 'error'}
        <div class="error-state">{error || $text('embeds.music_generate.error')}</div>
      {:else}
        <div
          class="waveform-strip"
          data-progress={Math.round(waveformProgressPercent)}
          style={`--waveform-progress: ${waveformProgressPercent}%; --waveform-sample-count: ${WAVEFORM_SAMPLES.length};`}
          aria-hidden="true"
        >
          <div class="waveform-bars">
            {#each WAVEFORM_SAMPLES as sample, index (index)}
              <span class="waveform-bar" style:height={`${sample}%`}></span>
            {/each}
          </div>
          <span class="waveform-playhead"></span>
        </div>

        <div class="prompt-card">
          <div class="prompt-label" data-testid={`${resolvedTestIdPrefix}-prompt-label`}>{promptLabel}</div>
          <p class="prompt-text" data-testid={`${resolvedTestIdPrefix}-prompt`}>{displayPrompt || modeLabel}</p>
          {#if metaLabel}
            <div class="meta-line">{metaLabel}</div>
          {/if}
        </div>

        {#if audioError}
          <p class="audio-error">{audioError}</p>
        {:else if status !== 'finished' || !hasAudioSrc}
          <div class="loading-line"></div>
        {/if}
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .generated-audio-preview {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: var(--spacing-4);
    padding: 14px 16px;
    box-sizing: border-box;
    overflow: hidden;
  }

  .generated-audio-preview.mobile {
    padding: var(--spacing-5) var(--spacing-6);
    gap: var(--spacing-3);
  }

  .waveform-strip {
    width: 100%;
    height: 30px;
    min-height: 30px;
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
    gap: 1px;
    opacity: 0.78;
  }

  .waveform-bar {
    width: 100%;
    min-width: 0;
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

  .prompt-card {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
  }

  .prompt-label,
  .meta-line {
    font-size: var(--font-size-tiny);
    line-height: 1.35;
    color: var(--color-grey-50, #888);
    font-weight: 600;
    letter-spacing: 0.01em;
  }

  .prompt-text {
    margin: 0;
    font-size: var(--font-size-xxs);
    line-height: 1.5;
    color: var(--color-grey-70, #444);
    display: -webkit-box;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
    word-break: break-word;
  }

  .loading-line {
    width: 100%;
    height: 8px;
    border-radius: var(--radius-full);
    background: linear-gradient(90deg, var(--color-grey-20), var(--color-grey-10), var(--color-grey-20));
    animation: pulse 1.4s infinite ease-in-out;
  }

  .audio-error,
  .error-state {
    margin: 0;
    color: var(--color-error, #d33);
    font-size: var(--font-size-xs);
  }

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
    pointer-events: auto !important;
  }

  .play-btn:hover {
    background: color-mix(in srgb, var(--color-app-audio, #e05555) 85%, #000 15%) !important;
    background-color: color-mix(in srgb, var(--color-app-audio, #e05555) 85%, #000 15%) !important;
    transform: scale(1.05);
    scale: 1 !important;
  }

  .play-btn:active {
    transform: scale(0.97);
    scale: 1 !important;
    filter: none !important;
  }

  .play-icon {
    width: 0;
    height: 0;
    border-top: 7px solid transparent;
    border-bottom: 7px solid transparent;
    border-left: 12px solid white;
    margin-left: var(--spacing-1);
  }

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

  @keyframes pulse {
    0%, 100% { opacity: 0.55; }
    50% { opacity: 1; }
  }

  :global(.dark) .prompt-text {
    color: var(--color-grey-30, #ccc);
  }

  :global(.dark) .waveform-strip {
    opacity: 0.9;
  }
</style>
