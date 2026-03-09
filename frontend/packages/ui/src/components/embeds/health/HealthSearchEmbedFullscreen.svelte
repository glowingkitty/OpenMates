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
    query: queryProp,
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
  let localQuery = $state('');
  let localEmbedIds = $state<string | string[] | undefined>(undefined);
  let localResults = $state<unknown[]>([]);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('finished');
  let localErrorMessage = $state('');

  $effect(() => {
    localQuery = queryProp || '';
    localEmbedIds = embedIds;
    localResults = resultsProp || [];
    localStatus = statusProp || 'finished';
    localErrorMessage = errorMessageProp || '';
  });

  let embedIdsValue = $derived(localEmbedIds);
  let legacyResults = $derived(localResults);

  /**
   * Transform raw embed content to AppointmentResult format.
   * Handles TOON-flattened slots and native arrays.
   */
  function transformToAppointmentResult(embedId: string, content: Record<string, unknown>): AppointmentResult {
    let slots: SlotData[] = [];

    if (Array.isArray(content.slots)) {
      slots = (content.slots as Record<string, unknown>[]).map(s => ({
        datetime: (s.datetime as string) || '',
        booking_url: (s.booking_url as string) || undefined,
      }));
    } else {
      for (let i = 0; i < 20; i++) {
        const dt = content[`slots_${i}_datetime`];
        if (typeof dt !== 'string') break;
        slots.push({
          datetime: dt,
          booking_url: (content[`slots_${i}_booking_url`] as string) || undefined,
        });
      }
      // Legacy: pipe-joined ISO string
      if (slots.length === 0 && typeof content.slots === 'string' && content.slots) {
        const datetimes = (content.slots as string).split('|');
        slots = datetimes.filter(dt => dt).map(dt => ({ datetime: dt }));
      }
    }

    return {
      embed_id: embedId,
      type: (content.type as string) || 'appointment',
      name: content.name as string | undefined,
      speciality: content.speciality as string | undefined,
      address: content.address as string | undefined,
      slots_count: (content.slots_count as number) || 0,
      next_slot: content.next_slot as string | undefined,
      next_slot_url: (content.next_slot_url as string | undefined) || undefined,
      slots,
      insurance: content.insurance as string | undefined,
      telehealth: (content.telehealth as boolean) || false,
      practice_url: content.practice_url as string | undefined,
      provider: content.provider as string | undefined,
    };
  }

  /**
   * Transform legacy inline results to AppointmentResult format.
   */
  function transformLegacyResults(results: unknown[]): AppointmentResult[] {
    return (results as Array<Record<string, unknown>>).map((r, i) =>
      transformToAppointmentResult(`legacy-${i}`, r)
    );
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
    if (typeof content.query === 'string') localQuery = content.query;
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
  minCardWidth="280px"
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
