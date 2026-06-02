<!--
  frontend/packages/ui/src/components/embeds/weather/WeatherForecastEmbedPreview.svelte

  Preview card for Weather / Forecast skill embeds.
  Uses UnifiedEmbedPreview as the base and shows compact daily summaries.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';

  interface WeatherDaySummary {
    date?: string;
    condition?: string;
    icon?: string;
    temperature_min_c?: number;
    temperature_max_c?: number;
    precipitation_total_mm?: number;
    precipitation_probability_max_pct?: number;
    rain_hours?: number;
  }

  interface Props {
    id: string;
    query?: string;
    locationName?: string;
    provider?: string;
    status: 'processing' | 'finished' | 'error' | 'cancelled';
    results?: WeatherDaySummary[];
    taskId?: string;
    skillTaskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    query: queryProp = '',
    locationName: locationNameProp = '',
    provider: providerProp = 'Weather',
    status: statusProp,
    results: resultsProp = [],
    taskId: taskIdProp,
    skillTaskId: skillTaskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  let localQuery = $state('');
  let localLocationName = $state('');
  let localProvider = $state('Weather');
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let localResults = $state<WeatherDaySummary[]>([]);
  let localTaskId = $state<string | undefined>();
  let localSkillTaskId = $state<string | undefined>();

  $effect(() => {
    localQuery = queryProp;
    localLocationName = locationNameProp;
    localProvider = providerProp;
    localStatus = statusProp || 'processing';
    localResults = resultsProp || [];
    localTaskId = taskIdProp;
    localSkillTaskId = skillTaskIdProp;
  });

  let query = $derived(localQuery || `${localLocationName} weather forecast`.trim());
  let locationName = $derived(localLocationName || query.replace(/ weather forecast$/i, ''));
  let provider = $derived(localProvider);
  let status = $derived(localStatus);
  let results = $derived(localResults);
  let taskId = $derived(localTaskId);
  let skillTaskId = $derived(localSkillTaskId);
  let visibleDays = $derived(results.slice(0, isMobile ? 3 : 4));
  let skillName = $derived($text('apps.weather.forecast'));

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    const content = data.decodedContent;
    if (!content) return;
    if (typeof content.query === 'string') localQuery = content.query;
    if (typeof content.provider === 'string') localProvider = content.provider;
    const location = content.location as Record<string, unknown> | undefined;
    if (location && typeof location.name === 'string') localLocationName = location.name;
    if (Array.isArray(content.results)) localResults = content.results as WeatherDaySummary[];
    if (typeof content.skill_task_id === 'string') localSkillTaskId = content.skill_task_id;
  }

  async function handleStop() {
    if (status !== 'processing') return;
    if (skillTaskId) {
      await chatSyncService.sendCancelSkill(skillTaskId, id).catch((err) => {
        console.error('[WeatherForecastEmbedPreview] Failed to cancel skill:', err);
      });
    } else if (taskId) {
      await chatSyncService.sendCancelAiTask(taskId).catch((err) => {
        console.error('[WeatherForecastEmbedPreview] Failed to cancel task:', err);
      });
    }
  }

  function formatTemp(min?: number, max?: number): string {
    if (min === undefined && max === undefined) return '—';
    if (min === undefined) return `${Math.round(max as number)}°`;
    if (max === undefined) return `${Math.round(min)}°`;
    return `${Math.round(min)}° / ${Math.round(max)}°`;
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="weather"
  skillId="forecast"
  skillIconName="weather"
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="weather-forecast-details" class:mobile={isMobileLayout} data-testid="weather-forecast-preview">
      <div class="forecast-title" data-testid="weather-forecast-title">{locationName || query || $text('apps.weather.forecast')}</div>
      <div class="forecast-subtitle" data-testid="weather-forecast-provider">{provider}</div>

      {#if status === 'finished' && visibleDays.length > 0}
        <div class="day-strip" data-testid="weather-forecast-day-strip">
          {#each visibleDays as day}
            <div class="day-pill" data-testid="weather-forecast-day-pill">
              <span class="day-date">{day.date?.slice(5) || '—'}</span>
              <span class="day-temp">{formatTemp(day.temperature_min_c, day.temperature_max_c)}</span>
              <span class="day-rain">{day.precipitation_probability_max_pct ?? 0}% rain</span>
            </div>
          {/each}
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
  .weather-forecast-details {
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 6px;
    height: 100%;
  }

  .weather-forecast-details.mobile {
    justify-content: flex-start;
  }

  .forecast-title {
    color: var(--color-grey-100);
    font-size: 16px;
    font-weight: 600;
    line-height: 1.25;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .forecast-subtitle,
  .loading-copy {
    color: var(--color-grey-70);
    font-size: 13px;
  }

  .day-strip {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px;
    margin-top: 4px;
  }

  .weather-forecast-details.mobile .day-strip {
    grid-template-columns: 1fr;
  }

  .day-pill {
    display: flex;
    flex-direction: column;
    gap: 1px;
    padding: 6px;
    border-radius: 10px;
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-20);
  }

  .day-date,
  .day-rain {
    color: var(--color-grey-70);
    font-size: 11px;
  }

  .day-temp {
    color: var(--color-grey-100);
    font-size: 13px;
    font-weight: 600;
  }

  .error-indicator {
    color: var(--color-error);
    font-size: 13px;
  }
</style>
