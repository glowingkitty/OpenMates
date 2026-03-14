<!--
  frontend/packages/ui/src/components/embeds/health/HealthSearchEmbedFullscreen.svelte

  Fullscreen view for the Health Search Appointments skill embed.
  Uses SearchResultsTemplate for unified grid + overlay + loading pattern.

  Shows:
  - Header with skill label
  - Grid of HealthAppointmentEmbedPreview cards (one per doctor)
  - Drill-down: clicking a card opens HealthAppointmentEmbedFullscreen overlay with sibling nav

  Child embeds are automatically loaded by SearchResultsTemplate/UnifiedEmbedFullscreen.

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import HealthAppointmentEmbedPreview from './HealthAppointmentEmbedPreview.svelte';
  import HealthAppointmentEmbedFullscreen from './HealthAppointmentEmbedFullscreen.svelte';
  import { text } from '@repo/ui';

  /**
   * A single appointment slot.
   */
  interface SlotData {
    datetime: string;
    booking_url?: string;
  }

  /**
   * Appointment result — one doctor with their available slots.
   */
  interface AppointmentResult {
    embed_id: string;
    type?: string;
    name?: string;
    speciality?: string;
    address?: string;
    gps_coordinates?: { latitude: number; longitude: number };
    slots_count?: number;
    next_slot?: string;
    next_slot_url?: string;
    slots?: SlotData[];
    insurance?: string;
    telehealth?: boolean;
    practice_url?: string;
    provider?: string;
  }

  interface Props {
    query?: string;
    provider?: string;
    embedIds?: string | string[];
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    errorMessage?: string;
    results?: unknown[];
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
    embedIds,
    status: statusProp,
    errorMessage: errorMessageProp,
    results: resultsProp,
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

  // Local reactive state for streaming updates
  let localEmbedIds = $state<string | string[] | undefined>(undefined);
  let localResults = $state<unknown[]>([]);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('finished');
  let localErrorMessage = $state('');

  $effect(() => {
    localEmbedIds = embedIds;
    localResults = resultsProp || [];
    localStatus = statusProp || 'finished';
    localErrorMessage = errorMessageProp || '';
  });

  let embedIdsValue = $derived(localEmbedIds);
  let legacyResults = $derived(localResults);

  function asString(value: unknown): string | undefined {
    if (typeof value === 'string') {
      const trimmed = value.trim();
      return trimmed.length > 0 ? trimmed : undefined;
    }
    if (Array.isArray(value)) {
      const joined = value.filter((v) => typeof v === 'string').join(', ').trim();
      return joined.length > 0 ? joined : undefined;
    }
    return undefined;
  }

  function asNumber(value: unknown): number | undefined {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string') {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
    return undefined;
  }

  function asBoolean(value: unknown): boolean {
    return value === true || value === 'true' || value === 1 || value === '1';
  }

  function parseGpsCoordinates(content: Record<string, unknown>):
    | { latitude: number; longitude: number }
    | undefined {
    const gps = content.gps_coordinates;
    if (!gps || typeof gps !== 'object') return undefined;

    const latitude = asNumber((gps as Record<string, unknown>).latitude ?? (gps as Record<string, unknown>).lat);
    const longitude = asNumber((gps as Record<string, unknown>).longitude ?? (gps as Record<string, unknown>).lon);
    if (latitude === undefined || longitude === undefined) return undefined;

    return { latitude, longitude };
  }

  function parseSlots(content: Record<string, unknown>): SlotData[] {
    if (Array.isArray(content.slots)) {
      return (content.slots as Array<Record<string, unknown>>)
        .map((slot) => ({
          datetime: asString(slot.datetime) || '',
          booking_url: asString(slot.booking_url),
        }))
        .filter((slot) => slot.datetime.length > 0);
    }

    const flattenedSlots: SlotData[] = [];
    for (let i = 0; i < 20; i++) {
      const datetime = asString(content[`slots_${i}_datetime`]);
      if (!datetime) break;
      flattenedSlots.push({
        datetime,
        booking_url: asString(content[`slots_${i}_booking_url`]),
      });
    }

    if (flattenedSlots.length > 0) return flattenedSlots;

    const pipeJoinedSlots = asString(content.slots);
    if (!pipeJoinedSlots) return [];

    return pipeJoinedSlots
      .split('|')
      .map((datetime) => datetime.trim())
      .filter((datetime) => datetime.length > 0)
      .map((datetime) => ({ datetime }));
  }

  function transformToAppointmentResult(embedId: string, content: Record<string, unknown>): AppointmentResult {
    const slots = parseSlots(content);
    const slotsCount = asNumber(content.slots_count) ?? slots.length;

    return {
      embed_id: asString(content.embed_id) || embedId,
      type: asString(content.type) || 'appointment',
      name: asString(content.name),
      speciality: asString(content.speciality),
      address: asString(content.address),
      gps_coordinates: parseGpsCoordinates(content),
      slots_count: slotsCount,
      next_slot: asString(content.next_slot),
      next_slot_url: asString(content.next_slot_url),
      slots,
      insurance: asString(content.insurance),
      telehealth: asBoolean(content.telehealth),
      practice_url: asString(content.practice_url),
      provider: asString(content.provider),
    };
  }

  /**
   * Transform legacy inline results to AppointmentResult format.
   */
  function transformLegacyResults(results: unknown[]): AppointmentResult[] {
    const transformed: AppointmentResult[] = [];

    for (let i = 0; i < results.length; i++) {
      const item = results[i] as Record<string, unknown>;
      if (!item || typeof item !== 'object') continue;

      const groupedResults = item.results;
      if (Array.isArray(groupedResults)) {
        for (let j = 0; j < groupedResults.length; j++) {
          const groupedItem = groupedResults[j] as Record<string, unknown>;
          if (!groupedItem || typeof groupedItem !== 'object') continue;
          transformed.push(transformToAppointmentResult(`legacy-${i}-${j}`, groupedItem));
        }
        continue;
      }

      transformed.push(transformToAppointmentResult(`legacy-${i}`, item));
    }

    return transformed;
  }

  /**
   * Handle embed data updates during streaming.
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (!data.decodedContent) return;
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    const content = data.decodedContent;
    if (content.embed_ids) localEmbedIds = content.embed_ids as string | string[];
    if (Array.isArray(content.results)) localResults = content.results as unknown[];
    if (typeof content.error === 'string') localErrorMessage = content.error;
  }
</script>

<SearchResultsTemplate
  appId="health"
  skillId="search_appointments"
  embedHeaderTitle={$text('app_skills.health.search_appointments')}
  skillIconName="health"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToAppointmentResult}
  {legacyResults}
  legacyResultTransformer={transformLegacyResults}
  status={localStatus}
  errorMessage={localErrorMessage}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  minCardWidth="260px"
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet resultCard({ result, onSelect })}
    <HealthAppointmentEmbedPreview
      id={result.embed_id}
      name={result.name}
      speciality={result.speciality}
      address={result.address}
      slotsCount={result.slots_count}
      nextSlot={result.next_slot}
      nextSlotUrl={result.next_slot_url}
      insurance={result.insurance}
      telehealth={result.telehealth}
      status="finished"
      isMobile={false}
      onFullscreen={onSelect}
    />
  {/snippet}

  {#snippet childFullscreen(nav)}
    <HealthAppointmentEmbedFullscreen
      appointment={nav.result}
      onClose={nav.onClose}
      embedId={nav.result.embed_id}
      hasPreviousEmbed={nav.hasPrevious}
      hasNextEmbed={nav.hasNext}
      onNavigatePrevious={nav.onPrevious}
      onNavigateNext={nav.onNext}
    />
  {/snippet}
</SearchResultsTemplate>
