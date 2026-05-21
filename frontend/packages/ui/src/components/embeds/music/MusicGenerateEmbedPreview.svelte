<!--
  frontend/packages/ui/src/components/embeds/music/MusicGenerateEmbedPreview.svelte

  Preview for music.generate embeds. Generated audio files are encrypted in S3
  and decrypted client-side with the same AES-GCM flow used by generated images.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { fetchAndDecryptAudio, releaseCachedAudio } from '../audio/audioEmbedCrypto';
  import { getModelDisplayName } from '../../../utils/modelDisplayName';

  interface MusicFileVariant {
    s3_key: string;
    size_bytes?: number;
    format?: string;
    mime_type?: string;
    duration_seconds?: number;
  }

  interface MusicFiles {
    original?: MusicFileVariant;
  }

  interface Props {
    id: string;
    prompt?: string;
    mode?: string;
    model?: string;
    durationSeconds?: number;
    s3BaseUrl?: string;
    files?: MusicFiles;
    aesKey?: string;
    aesNonce?: string;
    status: 'processing' | 'finished' | 'error';
    error?: string;
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    prompt: promptProp,
    mode: modeProp,
    model: modelProp,
    durationSeconds: durationProp,
    s3BaseUrl: s3BaseUrlProp,
    files: filesProp,
    aesKey: aesKeyProp,
    aesNonce: aesNonceProp,
    status: statusProp,
    error: errorProp,
    taskId,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let updatedPrompt = $state<string | undefined>();
  let updatedMode = $state<string | undefined>();
  let updatedModel = $state<string | undefined>();
  let updatedDurationSeconds = $state<number | undefined>();
  let updatedS3BaseUrl = $state<string | undefined>();
  let updatedFiles = $state<MusicFiles | undefined>();
  let updatedAesKey = $state<string | undefined>();
  let updatedAesNonce = $state<string | undefined>();
  let updatedStatus = $state<'processing' | 'finished' | 'error' | undefined>();
  let updatedError = $state<string | undefined>();

  const prompt = $derived(updatedPrompt ?? promptProp ?? '');
  const mode = $derived(updatedMode ?? modeProp ?? 'background');
  const model = $derived(updatedModel ?? modelProp ?? '');
  const durationSeconds = $derived(updatedDurationSeconds ?? durationProp);
  const s3BaseUrl = $derived(updatedS3BaseUrl ?? s3BaseUrlProp ?? '');
  const files = $derived(updatedFiles ?? filesProp);
  const aesKey = $derived(updatedAesKey ?? aesKeyProp ?? '');
  const aesNonce = $derived(updatedAesNonce ?? aesNonceProp ?? '');
  const status = $derived(updatedStatus ?? statusProp ?? 'processing');
  const error = $derived(updatedError ?? errorProp ?? '');
  let audioUrl = $state<string | undefined>();
  let audioError = $state<string | undefined>();
  let retainedS3Key: string | undefined;

  const skillName = $text('app_skills.music.generate');
  const modelName = $derived(model ? getModelDisplayName(model) : 'Lyria');
  const durationLabel = $derived(formatDuration(durationSeconds || files?.original?.duration_seconds));
  const statusText = $derived(
    status === 'processing'
      ? $text('embeds.music_generate.generating')
      : status === 'error'
        ? $text('embeds.music_generate.error')
        : `${modelName}${durationLabel ? ` · ${durationLabel}` : ''}`
  );

  onDestroy(() => {
    if (retainedS3Key) releaseCachedAudio(retainedS3Key);
  });

  $effect(() => {
    if (status === 'finished' && !audioUrl && files?.original?.s3_key && s3BaseUrl && aesKey && aesNonce) {
      loadAudio();
    }
  });

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    const decoded = data.decodedContent;
    updatedStatus = (decoded.status as 'processing' | 'finished' | 'error') || (data.status as 'processing' | 'finished' | 'error') || status;
    updatedPrompt = typeof decoded.prompt === 'string' ? decoded.prompt : updatedPrompt;
    updatedMode = typeof decoded.mode === 'string' ? decoded.mode : updatedMode;
    updatedModel = typeof decoded.model === 'string' ? decoded.model : updatedModel;
    updatedDurationSeconds = typeof decoded.duration_seconds === 'number' ? decoded.duration_seconds : updatedDurationSeconds;
    updatedS3BaseUrl = typeof decoded.s3_base_url === 'string' ? decoded.s3_base_url : updatedS3BaseUrl;
    updatedFiles = typeof decoded.files === 'object' && decoded.files !== null ? decoded.files as MusicFiles : updatedFiles;
    updatedAesKey = typeof decoded.aes_key === 'string' ? decoded.aes_key : updatedAesKey;
    updatedAesNonce = typeof decoded.aes_nonce === 'string' ? decoded.aes_nonce : updatedAesNonce;
    updatedError = typeof decoded.error === 'string' ? decoded.error : updatedError;
  }

  async function loadAudio() {
    const file = files?.original;
    if (!file?.s3_key) return;
    try {
      audioError = undefined;
      audioUrl = await fetchAndDecryptAudio(s3BaseUrl, file.s3_key, aesKey, aesNonce, file.mime_type || 'audio/wav');
      retainedS3Key = file.s3_key;
    } catch (err) {
      audioError = err instanceof Error ? err.message : 'Failed to load audio';
    }
  }

  function formatDuration(seconds?: number): string {
    if (!seconds || Number.isNaN(seconds)) return '';
    const minutes = Math.floor(seconds / 60);
    const rest = Math.floor(seconds % 60).toString().padStart(2, '0');
    return `${minutes}:${rest}`;
  }

  function modeLabel(value?: string): string {
    if (!value) return 'Generated music';
    return value.replace(/_/g, ' ').replace(/^./, (char) => char.toUpperCase());
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="music"
  skillId="generate"
  skillIconName="music"
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  customStatusText={statusText}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details()}
    <div class="music-preview" data-testid="music-generate-preview">
      {#if status === 'error'}
        <div class="error-box">{error || $text('embeds.music_generate.error')}</div>
      {:else}
        <div class="track-art" aria-hidden="true">
          <span class="note">♪</span>
        </div>
        <div class="track-details">
          <div class="track-title">{modeLabel(mode)}</div>
          <div class="prompt">{prompt || $text('embeds.music_generate.generating')}</div>
          {#if status === 'finished' && audioUrl}
            <audio
              class="audio-player"
              data-testid="music-generate-audio"
              src={audioUrl}
              controls
              preload="metadata"
              onpointerdown={(event) => event.stopPropagation()}
              onclick={(event) => event.stopPropagation()}
            ></audio>
          {:else if audioError}
            <div class="error-inline">{audioError}</div>
          {:else}
            <div class="loading-line"></div>
          {/if}
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .music-preview {
    display: flex;
    gap: 12px;
    height: 100%;
    padding: 12px;
    box-sizing: border-box;
    align-items: center;
  }

  .track-art {
    width: 70px;
    height: 70px;
    border-radius: 14px;
    background: var(--color-app-music);
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 8px 22px rgba(0, 0, 0, 0.18);
    flex: 0 0 auto;
  }

  .note {
    color: var(--color-grey-0);
    font-size: 34px;
    font-weight: 700;
  }

  .track-details {
    min-width: 0;
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .track-title {
    color: var(--color-font-primary);
    font-size: 16px;
    font-weight: 600;
  }

  .prompt {
    color: var(--color-font-secondary);
    font-size: 13px;
    line-height: 1.35;
    display: -webkit-box;
    line-clamp: 2;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .audio-player {
    width: 100%;
    height: 32px;
  }

  .loading-line {
    width: 100%;
    height: 8px;
    border-radius: 999px;
    background: linear-gradient(90deg, var(--color-grey-20), var(--color-grey-10), var(--color-grey-20));
    animation: pulse 1.4s infinite ease-in-out;
  }

  .error-box,
  .error-inline {
    color: var(--color-error, #d33);
    font-size: 13px;
  }

  @keyframes pulse {
    0%, 100% { opacity: 0.55; }
    50% { opacity: 1; }
  }
</style>
