<!--
  frontend/packages/ui/src/components/embeds/fitness/FitnessResultEmbedFullscreen.svelte

  Detail fullscreen for one Urban Sports Club location or class child embed.
  Uses EntryWithMapTemplate so Fitness drill-down follows the same unified
  fullscreen contract as Events and Maps entries.
-->

<script lang="ts">
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
  import { text } from '@repo/ui';
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
    return classDate && time ? `${classDate}T${time}:00` : classDate;
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
  let failedImage = $state<string>();
  // Do not forward the raw decoded result into the request interpreter.
  let visibleContext = $derived({
    title, provider: asText(result.provider), url: detailUrl, skill_id: skillId,
    address, distance_km: distance, date: asText(result.date), time_range: asText(result.time_range),
    venue_name: asText(result.venue_name), class_type: asText(result.class_type), category: asText(result.category),
    attendance_mode: asText(result.attendance_mode), spots_display: asText(result.spots_display),
    plans_required: plans, disciplines,
  });
</script>

<ResultEmbedFullscreen appId="fitness" {skillId} skillIconName="fitness" embedHeaderTitle={title} embedHeaderSubtitle={subtitle} result={visibleContext} media={imageUrl && failedImage !== imageUrl ? resultMedia : undefined} {onClose} currentEmbedId={embedId} {hasPreviousEmbed} {hasNextEmbed} {onNavigatePrevious} {onNavigateNext} onCalendar={calendarStart ? handleAddToCalendar : undefined} {mapCenter} mapMarkers={markers}>
  {#snippet embedHeaderCta()}{#if detailUrl}<EmbedHeaderCtaButton label={$text('embeds.fitness.open_provider').replace('{provider}', 'Urban Sports')} href={detailUrl} testId="fitness-open-urban-sports" />{/if}{/snippet}
  {#snippet summary()}
    {#if distance !== undefined}<ResultEmbedInfo icon="map-pin" label={$text('result_embed.distance')} value={`${distance.toFixed(2)} km`}><p>{distance.toFixed(2)} km</p></ResultEmbedInfo>{/if}
    {#if result.spots_display}<ResultEmbedInfo icon="users" label={$text('result_embed.spots')} value={asText(result.spots_display)}><p>{asText(result.spots_display)}</p></ResultEmbedInfo>{/if}
    {#if skillId === 'search_classes' && result.time_range}<ResultEmbedInfo icon="clock" label={$text('common.duration')} value={asText(result.time_range)}><p>{asText(result.date)} · {asText(result.time_range)}</p></ResultEmbedInfo>{/if}
  {/snippet}
  {#snippet resultMedia()}{#if imageUrl}<img class="fitness-detail-image" src={imageUrl} alt={title} loading="lazy" onerror={() => { failedImage = imageUrl; }} crossorigin="anonymous" />{/if}{/snippet}
  {#snippet detailContent()}
    <div class="fitness-detail" data-testid="fitness-result-fullscreen">
      {#if address || result.venue_name}<div class="result-location"><div>{#if result.venue_name}<strong>{asText(result.venue_name)}</strong>{/if}{#if address}<p>{address}</p>{/if}</div></div>{/if}
      {#if skillId === 'search_classes'}<p class="result-description">{[result.date, result.time_range, result.class_type, result.category].map(asText).filter(Boolean).join(' · ')}</p>{/if}
      <div class="result-icon-row">
        {#if result.attendance_mode}<ResultEmbedInfo icon="users" label={$text('result_embed.mode')} value={asText(result.attendance_mode)}><p>{asText(result.attendance_mode)}</p></ResultEmbedInfo>{/if}
        {#if disciplines.length}<ResultEmbedInfo icon="activity" label={$text('result_embed.disciplines')}>{#each disciplines as discipline}<p>{discipline}</p>{/each}</ResultEmbedInfo>{/if}
        {#if plans.length}<ResultEmbedInfo icon="ticket" label={$text('navigation.plans')}>{#each plans as plan}<p>{plan}</p>{/each}</ResultEmbedInfo>{/if}
      </div>
    </div>
  {/snippet}
</ResultEmbedFullscreen>
<style>
  .fitness-detail { width:100%; display:flex; flex-direction:column; gap:var(--spacing-8); }
  .fitness-detail-image { display:block; height:auto; max-height:65vh; object-fit:contain; width:100%; }
  p { margin:0; }
</style>
