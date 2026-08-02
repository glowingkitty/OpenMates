<!--
  frontend/packages/ui/src/components/embeds/fitness/FitnessResultEmbedFullscreen.svelte

  Detail fullscreen for one Urban Sports Club location or class child embed.
  Uses EntryWithMapTemplate so Fitness drill-down follows the same unified
  fullscreen contract as Events and Maps entries.
-->

<script lang="ts">
  import EntryWithMapTemplate from '../EntryWithMapTemplate.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { proxyImage, MAX_WIDTH_HEADER_IMAGE } from '../../../utils/imageProxy';
  import { downloadCalendarFile, sanitizeCalendarFilename } from '../../../utils/calendarDownload';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import {
    asNumber,
    asText,
    getFitnessResultAddress,
    getFitnessResultTitle,
    getFitnessResultUrl,
    normalizeFitnessSkillId,
    normalizePipedList,
    type FitnessResult,
  } from './fitnessEmbedData';

  interface Props {
    data: EmbedFullscreenRawData;
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }

  let {
    data,
    embedId,
    onClose,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
  }: Props = $props();

  let result: FitnessResult = $derived(data.decodedContent as FitnessResult);
  let skillId = $derived(normalizeFitnessSkillId(result.skill_id, result.app_skill_id === 'search_locations' ? 'search_locations' : 'search_classes'));
  let title = $derived(getFitnessResultTitle(result));
  let address = $derived(getFitnessResultAddress(result));
  let lat = $derived(asNumber(result.lat ?? result.venue_lat));
  let lon = $derived(asNumber(result.lon ?? result.venue_lon));
  let distance = $derived(asNumber(result.distance_km));
  let plans = $derived(normalizePipedList(result.plans_required));
  let disciplines = $derived(normalizePipedList(result.disciplines));
  let detailUrl = $derived(getFitnessResultUrl(result));
  let imageUrl = $derived(result.image_url ? proxyImage(asText(result.image_url), MAX_WIDTH_HEADER_IMAGE) : '');
  let mapCenter = $derived(lat !== undefined && lon !== undefined ? { lat, lon } : undefined);
  let markers = $derived(mapCenter ? [{ lat: mapCenter.lat, lon: mapCenter.lon, title }] : []);
  let subtitle = $derived.by(() => {
    if (skillId === 'search_classes') return [result.date, result.time_range, result.venue_name].map(asText).filter(Boolean).join(' · ');
    return address || 'Urban Sports Club';
  });

  function timeFromRange(value: unknown, index: 0 | 1): string {
    const matches = Array.from(asText(value).matchAll(/\b(\d{1,2}):(\d{2})\b/g));
    const match = matches[index];
    if (!match) return '';
    const hours = Number(match[1]);
    const minutes = Number(match[2]);
    if (!Number.isFinite(hours) || !Number.isFinite(minutes) || hours > 23 || minutes > 59) return '';
    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
  }

  function classDateTime(date: unknown, timeRange: unknown, index: 0 | 1): string {
    const classDate = asText(date);
    const time = timeFromRange(timeRange, index);
    return classDate && time ? `${classDate}T${time}:00` : '';
  }

  let calendarStart = $derived(skillId === 'search_classes' ? classDateTime(result.date, result.time_range, 0) : '');
  let calendarEnd = $derived(skillId === 'search_classes' ? classDateTime(result.date, result.time_range, 1) : '');

  function buildCalendarDescription(): string {
    return [
      result.class_type ? `Class: ${asText(result.class_type)}` : '',
      result.category ? `Category: ${asText(result.category)}` : '',
      result.spots_display ? `Spots: ${asText(result.spots_display)}` : '',
      plans.length > 0 ? `Plans: ${plans.join(', ')}` : '',
      detailUrl,
    ].filter(Boolean).join('\n');
  }

  function handleAddToCalendar() {
    downloadCalendarFile({
      title: title || 'Fitness class',
      start: calendarStart,
      end: calendarEnd || undefined,
      location: [result.venue_name, address].map(asText).filter(Boolean).join(', '),
      description: buildCalendarDescription(),
      url: detailUrl,
      filename: sanitizeCalendarFilename([title || 'fitness-class', asText(result.date)].filter(Boolean).join('-')),
    });
  }
</script>

<EntryWithMapTemplate
  appId="fitness"
  {skillId}
  embedHeaderTitle={title}
  embedHeaderSubtitle={subtitle}
  appIconName="fitness"
  skillIconName="fitness"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  onCalendar={calendarStart ? handleAddToCalendar : undefined}
  {mapCenter}
  mapMarkers={markers}
>
  {#snippet embedHeaderCta()}
    {#if detailUrl}
      <EmbedHeaderCtaButton label="Open Urban Sports" href={detailUrl} testId="fitness-open-urban-sports" />
    {/if}
  {/snippet}

  {#snippet detailContent()}
    <div class="fitness-detail" data-testid="fitness-result-fullscreen">
      {#if imageUrl}
        <img class="fitness-detail-image" src={imageUrl} alt={title} loading="lazy" crossorigin="anonymous" />
      {/if}

      <div class="fitness-detail-section">
        <h3>{title}</h3>
        {#if subtitle}<p>{subtitle}</p>{/if}
      </div>

      <div class="fitness-detail-section">
        {#if address}<div><strong>Address</strong><span>{address}</span></div>{/if}
        {#if distance !== undefined}<div><strong>Distance</strong><span>{distance.toFixed(2)} km</span></div>{/if}
        {#if result.spots_display}<div><strong>Spots</strong><span>{result.spots_display}</span></div>{/if}
        {#if result.attendance_mode}<div><strong>Mode</strong><span>{asText(result.attendance_mode)}</span></div>{/if}
      </div>

      {#if disciplines.length > 0 || plans.length > 0}
        <div class="fitness-detail-tags">
          {#each disciplines as discipline}<span>{discipline}</span>{/each}
          {#each plans as plan}<span>{plan}</span>{/each}
        </div>
      {/if}
    </div>
  {/snippet}
</EntryWithMapTemplate>

<style>
  .fitness-detail {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-5);
  }

  .fitness-detail-image {
    border-radius: var(--radius-4);
    display: block;
    max-height: 180px;
    object-fit: cover;
    width: 100%;
  }

  .fitness-detail-section {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
  }

  .fitness-detail-section h3 {
    color: var(--color-font-primary);
    font-size: var(--font-size-h3);
    margin: 0;
  }

  .fitness-detail-section p,
  .fitness-detail-section span {
    color: var(--color-font-secondary);
  }

  .fitness-detail-section div {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-1);
  }

  .fitness-detail-tags {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-2);
  }

  .fitness-detail-tags span {
    background: var(--color-grey-10);
    border-radius: var(--radius-full);
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
    padding: var(--spacing-2) var(--spacing-4);
  }
</style>
