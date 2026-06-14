<!--
  frontend/packages/ui/src/components/embeds/weather/WeatherRainRadarEmbedFullscreen.svelte

  Fullscreen view for Weather / Rain radar embeds.
  Renders compact timeline metadata now and is structured for lazy radar blob loading.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { text } from '@repo/ui';
  import { loadRainRadarBlob, type RadarBlobFrame, type RadarBlobPayload } from './weatherRainRadarCrypto';

  interface RadarTimelineFrame {
    frame_id?: string;
    timestamp?: string;
    kind?: 'past' | 'current' | 'forecast';
    label?: string;
    rain_at_location_mm_5min?: number;
    max_intensity?: string;
    rain_area_pct?: number;
  }

  interface RadarSummary {
    rain_expected?: boolean | null;
    in_10_min?: string;
    next_2_hours?: string;
    peak_intensity?: string;
    preview_frame_id?: string | null;
  }

  interface RadarFileVariant {
    s3_key?: string;
  }

  interface RadarFiles {
    radar_blob?: RadarFileVariant;
  }

  interface Props {
    data?: EmbedFullscreenRawData;
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
    onShowChat
  }: Props = $props();

  let isPlaying = $state(false);
  let selectedIndex = $state(0);
  let radarBlob = $state<RadarBlobPayload | null>(null);
  let radarLoadError = $state('');
  let loadedBlobKey = $state('');
  let radarCanvas = $state<HTMLCanvasElement | null>(null);
  let playTimer: ReturnType<typeof setInterval> | undefined;

  let content = $derived.by(() => {
    const decodedContent = data?.decodedContent;
    return decodedContent && typeof decodedContent === 'object' ? decodedContent as Record<string, unknown> : {};
  });
  let location = $derived(content.location && typeof content.location === 'object' ? content.location as Record<string, unknown> : {});
  let locationName = $derived(typeof location.name === 'string' ? location.name : '');
  let provider = $derived(typeof content.provider === 'string' ? content.provider : 'Weather');
  let summary = $derived(content.summary && typeof content.summary === 'object' ? content.summary as RadarSummary : {});
  let timeline = $derived(Array.isArray(content.timeline) ? content.timeline as RadarTimelineFrame[] : []);
  let files = $derived(content.files && typeof content.files === 'object' ? content.files as RadarFiles : {});
  let aesKey = $derived(typeof content.aes_key === 'string' ? content.aes_key : '');
  let aesNonce = $derived(typeof content.aes_nonce === 'string' ? content.aes_nonce : '');
  let inlineRadarBlob = $derived(typeof content.radar_blob_b64 === 'string' ? content.radar_blob_b64 : '');
  let blobLoadKey = $derived(inlineRadarBlob
    ? `inline:${inlineRadarBlob.length}`
    : `${files.radar_blob?.s3_key || ''}:${aesKey}:${aesNonce}`);
  let selectedFrame = $derived(timeline[selectedIndex] || timeline[0]);
  let status = $derived(content.coverage && typeof content.coverage === 'object'
    ? String((content.coverage as Record<string, unknown>).status || 'available')
    : 'available');
  let intensity = $derived((selectedFrame?.max_intensity || summary.peak_intensity || 'none').toLowerCase());
  let rainAreaPct = $derived(selectedFrame?.rain_area_pct ?? 0);
  let rainAtLocation = $derived(selectedFrame?.rain_at_location_mm_5min ?? 0);

  $effect(() => {
    const previewId = summary.preview_frame_id;
    const previewIndex = timeline.findIndex((frame) => frame.frame_id === previewId);
    selectedIndex = previewIndex >= 0 ? previewIndex : 0;
  });

  $effect(() => {
    if (status !== 'available' || !blobLoadKey || blobLoadKey === loadedBlobKey) return;
    if (!inlineRadarBlob && (!files.radar_blob?.s3_key || !aesKey)) return;

    loadedBlobKey = blobLoadKey;
    radarLoadError = '';
    void loadRainRadarBlob({
      radarBlobBase64: inlineRadarBlob || undefined,
      s3Key: files.radar_blob?.s3_key,
      aesKeyBase64: aesKey || undefined,
      nonceBase64: aesNonce,
    }).then((payload) => {
      if (loadedBlobKey === blobLoadKey) radarBlob = payload;
    }).catch((error) => {
      console.error('[WeatherRainRadarEmbedFullscreen] Failed to load radar blob:', error);
      if (loadedBlobKey === blobLoadKey) radarLoadError = error instanceof Error ? error.message : String(error);
    });
  });

  $effect(() => {
    if (!isPlaying || timeline.length <= 1) {
      if (playTimer) clearInterval(playTimer);
      playTimer = undefined;
      return;
    }
    playTimer = setInterval(() => {
      selectedIndex = (selectedIndex + 1) % timeline.length;
    }, 850);
    return () => {
      if (playTimer) clearInterval(playTimer);
      playTimer = undefined;
    };
  });

  $effect(() => {
    const frameId = selectedFrame?.frame_id;
    if (!radarCanvas || !radarBlob || !frameId) return;
    const frame = radarBlob.frames.find((candidate) => candidate.frame_id === frameId) || radarBlob.frames[0];
    if (frame) drawRadarFrame(radarCanvas, radarBlob, frame);
  });

  function formatTimestamp(value?: string): string {
    if (!value) return '';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(parsed);
  }

  function drawRadarFrame(canvas: HTMLCanvasElement, blob: RadarBlobPayload, frame: RadarBlobFrame) {
    const context = canvas.getContext('2d');
    if (!context) return;

    const ratio = window.devicePixelRatio || 1;
    const cssWidth = Math.max(1, canvas.clientWidth || 800);
    const cssHeight = Math.max(1, canvas.clientHeight || 450);
    canvas.width = Math.round(cssWidth * ratio);
    canvas.height = Math.round(cssHeight * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.fillStyle = '#eef6fa';
    context.fillRect(0, 0, cssWidth, cssHeight);

    const width = Math.max(1, blob.grid.width);
    const height = Math.max(1, blob.grid.height);
    const cellWidth = cssWidth / width;
    const cellHeight = cssHeight / height;
    frame.values.slice(0, width * height).forEach((rawValue, index) => {
      context.fillStyle = colorForRadarValue(rawValue);
      context.fillRect((index % width) * cellWidth, Math.floor(index / width) * cellHeight, cellWidth + 0.5, cellHeight + 0.5);
    });
  }

  function colorForRadarValue(value: number): string {
    if (value <= 0) return 'rgba(230, 240, 245, 0.72)';
    if (value < 50) return `rgba(0, 167, 201, ${Math.min(0.82, 0.28 + value / 90)})`;
    if (value < 200) return `rgba(54, 99, 255, ${Math.min(0.9, 0.36 + value / 360)})`;
    return 'rgba(98, 51, 176, 0.92)';
  }
</script>

<UnifiedEmbedFullscreen
  appId="weather"
  skillId="rain_radar"
  skillIconName="weather"
  showSkillIcon={true}
  embedHeaderTitle={$text('apps.weather.rain_radar')}
  embedHeaderSubtitle={[locationName, provider].filter(Boolean).join(' · ')}
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
    <div class="rain-radar-fullscreen" data-testid="weather-rain-radar-fullscreen">
      {#if status === 'unavailable'}
        <section class="summary-card unavailable" data-testid="weather-rain-radar-unavailable">
          <h3>{summary.in_10_min || $text('embeds.weather.rain_radar.unavailable')}</h3>
          <p>{summary.next_2_hours}</p>
        </section>
      {:else}
        <section class="radar-stage" data-testid="weather-rain-radar-stage">
          <div class="radar-map intensity-{intensity}">
            {#if radarBlob}
              <canvas bind:this={radarCanvas} class="radar-canvas" data-testid="weather-rain-radar-canvas"></canvas>
            {:else}
              <div class="radar-grid"></div>
              <div class="rain-cell cell-a" style={`--cell-opacity: ${Math.min(0.9, 0.2 + rainAreaPct / 100)}`}></div>
              <div class="rain-cell cell-b" style={`--cell-opacity: ${Math.min(0.8, 0.15 + rainAtLocation)}`}></div>
            {/if}
            <div class="location-dot"></div>
            <div class="frame-badge">
              <span>{selectedFrame?.label || 'now'}</span>
              <strong>{formatTimestamp(selectedFrame?.timestamp)}</strong>
            </div>
          </div>
          {#if radarLoadError}
            <p class="radar-load-error" title={radarLoadError}>{$text('embeds.weather.rain_radar.load_failed')}</p>
          {/if}
        </section>

        <section class="summary-card" data-testid="weather-rain-radar-summary">
          <div>
            <p class="kicker">{locationName}</p>
            <h3>{summary.in_10_min || $text('embeds.weather.rain_radar.no_rain')}</h3>
            <p>{summary.next_2_hours}</p>
          </div>
          <div class="metric-stack">
            <span>{$text('embeds.weather.rain_radar.peak')}: {summary.peak_intensity || 'unknown'}</span>
            <span>{$text('embeds.weather.rain_radar.at_location')}: {rainAtLocation} mm / 5 min</span>
          </div>
        </section>

        <section class="timeline-card" data-testid="weather-rain-radar-timeline">
          <div class="timeline-header">
            <button type="button" class="play-button" onclick={() => (isPlaying = !isPlaying)} data-testid="weather-rain-radar-play-toggle">
              {isPlaying ? $text('embeds.weather.rain_radar.pause') : $text('embeds.weather.rain_radar.play')}
            </button>
            <span>{timeline.length} {$text('embeds.weather.rain_radar.frames')}</span>
          </div>
          <input
            type="range"
            min="0"
            max={Math.max(0, timeline.length - 1)}
            bind:value={selectedIndex}
            data-testid="weather-rain-radar-scrubber"
          />
          <div class="frame-strip">
            {#each timeline as frame, index}
              <button
                type="button"
                class:active={index === selectedIndex}
                onclick={() => (selectedIndex = index)}
                data-testid="weather-rain-radar-frame-button"
              >
                <span>{frame.label}</span>
                <strong>{frame.max_intensity}</strong>
              </button>
            {/each}
          </div>
        </section>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .rain-radar-fullscreen {
    display: flex;
    flex-direction: column;
    gap: 18px;
    padding: 24px 16px 120px;
    max-width: 1040px;
    margin: 0 auto;
  }

  .radar-stage,
  .summary-card,
  .timeline-card {
    border-radius: 28px;
    border: 1px solid color-mix(in srgb, var(--color-app-weather) 22%, var(--color-grey-20));
    background: color-mix(in srgb, var(--color-grey-0) 92%, transparent);
    box-shadow: 0 18px 44px color-mix(in srgb, var(--color-grey-100) 10%, transparent);
  }

  .radar-stage {
    padding: 14px;
  }

  .radar-map {
    position: relative;
    min-height: min(58vh, 520px);
    border-radius: 22px;
    overflow: hidden;
    background:
      radial-gradient(circle at 50% 50%, color-mix(in srgb, var(--color-grey-90) 16%, transparent), transparent 5px),
      linear-gradient(135deg, color-mix(in srgb, var(--color-app-weather) 18%, var(--color-grey-0)), var(--color-grey-0));
  }

  .radar-grid {
    position: absolute;
    inset: 0;
    background-image:
      linear-gradient(color-mix(in srgb, var(--color-app-weather) 13%, transparent) 1px, transparent 1px),
      linear-gradient(90deg, color-mix(in srgb, var(--color-app-weather) 13%, transparent) 1px, transparent 1px);
    background-size: 28px 28px;
  }

  .radar-canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
  }

  .radar-load-error {
    margin: 10px 4px 0;
    color: var(--color-grey-70);
    font-size: 13px;
  }

  .rain-cell {
    position: absolute;
    border-radius: 999px;
    opacity: var(--cell-opacity, 0.45);
    filter: blur(2px);
    background: color-mix(in srgb, var(--color-app-weather) 82%, #ffffff);
  }

  .cell-a {
    width: 54%;
    height: 48%;
    left: 10%;
    top: 16%;
  }

  .cell-b {
    width: 34%;
    height: 34%;
    right: 12%;
    bottom: 16%;
  }

  .intensity-none .rain-cell {
    opacity: 0.05;
  }

  .intensity-moderate .rain-cell,
  .intensity-heavy .rain-cell {
    background: color-mix(in srgb, var(--color-app-weather) 55%, #3f63ff);
  }

  .location-dot {
    position: absolute;
    left: 50%;
    top: 50%;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    transform: translate(-50%, -50%);
    background: var(--color-grey-100);
    border: 3px solid var(--color-grey-0);
    box-shadow: 0 0 0 6px color-mix(in srgb, var(--color-grey-100) 12%, transparent);
  }

  .frame-badge {
    position: absolute;
    right: 16px;
    bottom: 16px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 10px 12px;
    border-radius: 16px;
    background: color-mix(in srgb, var(--color-grey-0) 86%, transparent);
    color: var(--color-grey-100);
  }

  .summary-card {
    display: flex;
    justify-content: space-between;
    gap: 18px;
    padding: 20px;
  }

  .summary-card.unavailable {
    display: block;
  }

  .kicker,
  .summary-card p,
  .metric-stack,
  .timeline-header span {
    color: var(--color-grey-70);
    font-size: 13px;
  }

  .summary-card h3 {
    margin: 6px 0;
    color: var(--color-grey-100);
    font-size: clamp(24px, 4vw, 42px);
    line-height: 1.05;
  }

  .metric-stack {
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 190px;
  }

  .timeline-card {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 18px;
  }

  .timeline-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .play-button,
  .frame-strip button {
    border: 0;
    border-radius: 999px;
    background: color-mix(in srgb, var(--color-app-weather) 16%, var(--color-grey-0));
    color: var(--color-grey-100);
    cursor: pointer;
  }

  .play-button {
    padding: 9px 14px;
    font-weight: 700;
  }

  input[type='range'] {
    width: 100%;
    accent-color: var(--color-app-weather);
  }

  .frame-strip {
    display: flex;
    gap: 8px;
    overflow-x: auto;
    padding-bottom: 4px;
  }

  .frame-strip button {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 76px;
    padding: 9px 11px;
    text-align: left;
  }

  .frame-strip button.active {
    background: var(--color-app-weather);
    color: var(--color-grey-0);
  }
</style>
