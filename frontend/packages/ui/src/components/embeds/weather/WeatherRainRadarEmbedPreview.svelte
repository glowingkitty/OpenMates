<!--
  frontend/packages/ui/src/components/embeds/weather/WeatherRainRadarEmbedPreview.svelte

  Preview card for Weather / Rain radar skill embeds.
  Shows a deterministic still based on the +10 minute preview frame metadata.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';
  import { fetchAndDecryptImage } from '../images/imageEmbedCrypto';

  interface RadarSummary {
    rain_expected?: boolean | null;
    in_10_min?: string;
    next_2_hours?: string;
    peak_intensity?: string;
    preview_frame_id?: string | null;
  }

  interface RadarTimelineFrame {
    frame_id?: string;
    timestamp?: string;
    kind?: 'past' | 'current' | 'forecast';
    label?: string;
    rain_at_location_mm_5min?: number;
    max_intensity?: string;
    rain_area_pct?: number;
  }

  interface RadarFileVariant {
    s3_key?: string;
  }

  interface RadarFiles {
    preview?: RadarFileVariant;
  }

  interface Props {
    id: string;
    query?: string;
    locationName?: string;
    provider?: string;
    status: 'processing' | 'finished' | 'error' | 'cancelled';
    summary?: RadarSummary;
    timeline?: RadarTimelineFrame[];
    s3BaseUrl?: string;
    files?: RadarFiles;
    aesKey?: string;
    aesNonce?: string;
    taskId?: string;
    skillTaskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    locationName: locationNameProp = '',
    provider: providerProp = 'Weather',
    status: statusProp,
    summary: summaryProp = {},
    timeline: timelineProp = [],
    s3BaseUrl: s3BaseUrlProp = '',
    files: filesProp,
    aesKey: aesKeyProp = '',
    aesNonce: aesNonceProp = '',
    taskId: taskIdProp,
    skillTaskId: skillTaskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  let localLocationName = $state('');
  let localProvider = $state('Weather');
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let localSummary = $state<RadarSummary>({});
  let localTimeline = $state<RadarTimelineFrame[]>([]);
  let localS3BaseUrl = $state('');
  let localFiles = $state<RadarFiles | undefined>();
  let localAesKey = $state('');
  let localAesNonce = $state('');
  let localTaskId = $state<string | undefined>();
  let localSkillTaskId = $state<string | undefined>();
  let previewImageUrl = $state('');
  let loadedPreviewKey = $state('');

  $effect(() => {
    localLocationName = locationNameProp;
    localProvider = providerProp;
    localStatus = statusProp || 'processing';
    localSummary = summaryProp || {};
    localTimeline = timelineProp || [];
    localS3BaseUrl = s3BaseUrlProp || '';
    localFiles = filesProp;
    localAesKey = aesKeyProp || '';
    localAesNonce = aesNonceProp || '';
    localTaskId = taskIdProp;
    localSkillTaskId = skillTaskIdProp;
  });

  let locationName = $derived(localLocationName);
  let provider = $derived(localProvider);
  let status = $derived(localStatus);
  let summary = $derived(localSummary);
  let timeline = $derived(localTimeline.filter(Boolean));
  let files = $derived(localFiles);
  let previewKey = $derived(`${files?.preview?.s3_key || ''}:${localAesKey}:${localAesNonce}`);
  let taskId = $derived(localTaskId);
  let skillTaskId = $derived(localSkillTaskId);
  let skillName = $derived($text('apps.weather.rain_radar'));
  let previewFrame = $derived.by(() => {
    const targetId = summary.preview_frame_id;
    return timeline.find((frame) => frame.frame_id === targetId) || timeline.find((frame) => frame.kind === 'forecast') || timeline[0];
  });
  let intensity = $derived((previewFrame?.max_intensity || summary.peak_intensity || 'none').toLowerCase());
  let rainAreaPct = $derived(previewFrame?.rain_area_pct ?? 0);
  let rainAtLocation = $derived(previewFrame?.rain_at_location_mm_5min ?? 0);

  $effect(() => {
    if (status !== 'finished' || !files?.preview?.s3_key || !localAesKey || !previewKey || previewKey === loadedPreviewKey) return;
    loadedPreviewKey = previewKey;
    void loadPreviewImage(files.preview.s3_key, previewKey);
  });

  onDestroy(() => {
    if (previewImageUrl) URL.revokeObjectURL(previewImageUrl);
  });

  async function loadPreviewImage(s3Key: string, key: string) {
    try {
      const imageBlob = await fetchAndDecryptImage(localS3BaseUrl, s3Key, localAesKey, localAesNonce);
      const nextUrl = URL.createObjectURL(imageBlob);
      if (loadedPreviewKey !== key) {
        URL.revokeObjectURL(nextUrl);
        return;
      }
      if (previewImageUrl) URL.revokeObjectURL(previewImageUrl);
      previewImageUrl = nextUrl;
    } catch (err) {
      console.error('[WeatherRainRadarEmbedPreview] Failed to load preview image:', err);
    }
  }

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    const content = data.decodedContent;
    if (!content) return;
    if (typeof content.provider === 'string') localProvider = content.provider;
    if (typeof content.summary === 'object' && content.summary) localSummary = content.summary as RadarSummary;
    if (Array.isArray(content.timeline)) localTimeline = content.timeline as RadarTimelineFrame[];
    if (typeof content.s3_base_url === 'string') localS3BaseUrl = content.s3_base_url;
    if (typeof content.files === 'object' && content.files) localFiles = content.files as RadarFiles;
    if (typeof content.aes_key === 'string') localAesKey = content.aes_key;
    if (typeof content.aes_nonce === 'string') localAesNonce = content.aes_nonce;
    if (typeof content.skill_task_id === 'string') localSkillTaskId = content.skill_task_id;
    const location = content.location as Record<string, unknown> | undefined;
    if (typeof location?.name === 'string') localLocationName = location.name;
  }

  async function handleStop() {
    if (status !== 'processing') return;
    if (skillTaskId) {
      await chatSyncService.sendCancelSkill(skillTaskId, id).catch((err) => {
        console.error('[WeatherRainRadarEmbedPreview] Failed to cancel skill:', err);
      });
    } else if (taskId) {
      await chatSyncService.sendCancelAiTask(taskId).catch((err) => {
        console.error('[WeatherRainRadarEmbedPreview] Failed to cancel task:', err);
      });
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="weather"
  skillId="rain_radar"
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  showSkillIcon={false}
  customStatusText={provider ? `${$text('embeds.via')} ${provider}` : undefined}
  onStop={handleStop}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="rain-radar-preview" class:mobile={isMobileLayout} data-testid="weather-rain-radar-preview">
      {#if status === 'finished'}
        <div class="radar-still intensity-{intensity}" data-testid="weather-rain-radar-still">
          {#if previewImageUrl}
            <img src={previewImageUrl} alt="" class="radar-preview-image" data-testid="weather-rain-radar-preview-image" />
          {:else}
            <div class="radar-grid"></div>
            <div class="rain-cell cell-a" style={`--cell-opacity: ${Math.min(0.85, 0.2 + rainAreaPct / 100)}`}></div>
            <div class="rain-cell cell-b" style={`--cell-opacity: ${Math.min(0.75, 0.15 + rainAtLocation)}`}></div>
          {/if}
          <div class="location-dot" title={locationName}></div>
        </div>
        <div class="radar-copy">
          <strong>{locationName || $text('apps.weather.rain_radar')}</strong>
          <span>{summary.in_10_min || $text('embeds.weather.rain_radar.no_rain')}</span>
        </div>
      {:else if status === 'error'}
        <div class="error-indicator">{$text('chat.an_error_occured')}</div>
      {:else}
        <div class="loading-copy">{$text('embeds.loading')}</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .rain-radar-preview {
    display: grid;
    grid-template-columns: minmax(120px, 1.1fr) minmax(0, 1fr);
    gap: 12px;
    align-items: center;
    height: 100%;
  }

  .rain-radar-preview.mobile {
    grid-template-columns: 1fr;
  }

  .radar-still {
    position: relative;
    min-height: 96px;
    border-radius: 20px;
    overflow: hidden;
    border: 1px solid color-mix(in srgb, var(--color-app-weather) 22%, var(--color-grey-20));
    background:
      radial-gradient(circle at 54% 52%, color-mix(in srgb, var(--color-grey-90) 16%, transparent), transparent 4px),
      linear-gradient(135deg, color-mix(in srgb, var(--color-app-weather) 18%, var(--color-grey-0)), var(--color-grey-0));
  }

  .radar-grid {
    position: absolute;
    inset: 0;
    background-image:
      linear-gradient(color-mix(in srgb, var(--color-app-weather) 13%, transparent) 1px, transparent 1px),
      linear-gradient(90deg, color-mix(in srgb, var(--color-app-weather) 13%, transparent) 1px, transparent 1px);
    background-size: 18px 18px;
    opacity: 0.72;
  }

  .radar-preview-image {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .rain-cell {
    position: absolute;
    border-radius: 999px;
    opacity: var(--cell-opacity, 0.45);
    filter: blur(1px);
    background: color-mix(in srgb, var(--color-app-weather) 82%, #ffffff);
  }

  .cell-a {
    width: 58%;
    height: 54%;
    left: 8%;
    top: 15%;
  }

  .cell-b {
    width: 36%;
    height: 38%;
    right: 8%;
    bottom: 12%;
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
    width: 12px;
    height: 12px;
    border-radius: 50%;
    transform: translate(-50%, -50%);
    background: var(--color-grey-100);
    border: 2px solid var(--color-grey-0);
    box-shadow: 0 0 0 4px color-mix(in srgb, var(--color-grey-100) 12%, transparent);
  }

  .radar-copy {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }

  .radar-copy strong {
    color: var(--color-grey-100);
    font-size: 14px;
  }

  .radar-copy span,
  .loading-copy {
    color: var(--color-grey-70);
    font-size: 12px;
    line-height: 1.35;
  }

  .error-indicator {
    color: var(--color-error);
    font-size: 13px;
  }
</style>
