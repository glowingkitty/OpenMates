<!--
  frontend/packages/ui/src/components/embeds/music/MusicGenerateEmbedFullscreen.svelte

  Fullscreen player for generated music embeds.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { fetchAndDecryptAudio, releaseCachedAudio } from '../audio/audioEmbedCrypto';
  import { getModelDisplayName } from '../../../utils/modelDisplayName';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  interface MusicFileVariant {
    s3_key: string;
    size_bytes?: number;
    format?: string;
    mime_type?: string;
    duration_seconds?: number;
  }
  interface MusicFiles { original?: MusicFileVariant; }

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

  let dc = $derived(data.decodedContent);
  let prompt = $derived(typeof dc.prompt === 'string' ? dc.prompt : '');
  let mode = $derived(typeof dc.mode === 'string' ? dc.mode : 'background');
  let model = $derived(typeof dc.model === 'string' ? dc.model : '');
  let modelName = $derived(model ? getModelDisplayName(model) : 'Lyria');
  let durationSeconds = $derived(typeof dc.duration_seconds === 'number' ? dc.duration_seconds : undefined);
  let s3BaseUrl = $derived(typeof dc.s3_base_url === 'string' ? dc.s3_base_url : '');
  let files = $derived((typeof dc.files === 'object' && dc.files !== null) ? dc.files as MusicFiles : undefined);
  let aesKey = $derived(typeof dc.aes_key === 'string' ? dc.aes_key : '');
  let aesNonce = $derived(typeof dc.aes_nonce === 'string' ? dc.aes_nonce : '');
  let error = $derived(typeof dc.error === 'string' ? dc.error : undefined);
  let generatedAt = $derived(typeof dc.generated_at === 'string' ? dc.generated_at : undefined);
  let watermarking = $derived(typeof dc.watermarking === 'string' ? dc.watermarking : undefined);

  let audioUrl = $state<string | undefined>();
  let audioError = $state<string | undefined>();
  let retainedS3Key: string | undefined;

  let headerTitle = $derived(prompt ? truncate(prompt, 80) : $text('app_skills.music.generate'));
  let headerSubtitle = $derived(`${modelName}${durationSeconds ? ` · ${formatDuration(durationSeconds)}` : ''}`);

  onDestroy(() => {
    if (retainedS3Key) releaseCachedAudio(retainedS3Key);
  });

  $effect(() => {
    if (!audioUrl && files?.original?.s3_key && s3BaseUrl && aesKey && aesNonce) {
      loadAudio();
    }
  });

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
    if (!seconds) return '';
    const minutes = Math.floor(seconds / 60);
    const rest = Math.floor(seconds % 60).toString().padStart(2, '0');
    return `${minutes}:${rest}`;
  }

  function truncate(value: string, max: number): string {
    return value.length > max ? `${value.slice(0, max - 1)}…` : value;
  }
</script>

<UnifiedEmbedFullscreen
  appId="music"
  skillId="generate"
  skillIconName="music"
  embedHeaderTitle={headerTitle}
  embedHeaderSubtitle={headerSubtitle}
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="music-fullscreen" data-testid="music-generate-fullscreen">
      <section class="player-card">
        <div class="cover" aria-hidden="true">♪</div>
        <div class="player-main">
          <h2>{mode.replace(/_/g, ' ')}</h2>
          {#if error}
            <p class="error">{error}</p>
          {:else if audioUrl}
            <audio
              class="player"
              data-testid="music-generate-fullscreen-audio"
              src={audioUrl}
              controls
              autoplay
              preload="auto"
            ></audio>
          {:else if audioError}
            <p class="error">{audioError}</p>
          {:else}
            <p class="muted">{$text('embeds.music_generate.loading')}</p>
          {/if}
        </div>
      </section>

      <section class="details-card">
        <dl>
          <div><dt>{$text('embeds.music_generate.prompt_label')}</dt><dd>{prompt}</dd></div>
          <div><dt>{$text('embeds.music_generate.model_label')}</dt><dd>{modelName}</dd></div>
          {#if durationSeconds}<div><dt>{$text('embeds.music_generate.duration')}</dt><dd>{formatDuration(durationSeconds)}</dd></div>{/if}
          {#if generatedAt}<div><dt>{$text('embeds.music_generate.generated_at')}</dt><dd>{new Date(generatedAt).toLocaleString()}</dd></div>{/if}
          {#if watermarking}<div><dt>{$text('embeds.music_generate.watermarking')}</dt><dd>{watermarking}</dd></div>{/if}
        </dl>
      </section>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .music-fullscreen {
    container-type: inline-size;
    display: grid;
    gap: 18px;
    padding: 22px;
    max-width: 980px;
    margin: 0 auto;
  }

  .player-card,
  .details-card {
    border-radius: 24px;
    background: var(--color-grey-0);
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.12);
    padding: 20px;
  }

  .player-card {
    display: grid;
    grid-template-columns: 180px minmax(0, 1fr);
    gap: 22px;
    align-items: center;
  }

  .cover {
    aspect-ratio: 1;
    border-radius: 28px;
    background: var(--color-app-music);
    color: var(--color-grey-0);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 72px;
    font-weight: 700;
  }

  h2 {
    margin: 0 0 14px;
    text-transform: capitalize;
    color: var(--color-font-primary);
  }

  .player {
    width: 100%;
  }

  dl {
    display: grid;
    gap: 14px;
    margin: 0;
  }

  dt {
    color: var(--color-font-secondary);
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 4px;
  }

  dd {
    margin: 0;
    color: var(--color-font-primary);
    line-height: 1.45;
  }

  .muted { color: var(--color-font-secondary); }
  .error { color: var(--color-error, #d33); }

  @container (max-width: 640px) {
    .player-card {
      grid-template-columns: 1fr;
    }
    .cover {
      max-width: 220px;
      width: 100%;
      margin: 0 auto;
    }
  }
</style>
