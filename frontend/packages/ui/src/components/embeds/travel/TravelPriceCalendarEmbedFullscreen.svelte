<!--
  frontend/packages/ui/src/components/embeds/travel/TravelPriceCalendarEmbedFullscreen.svelte
  
  Fullscreen view for Travel Price Calendar skill embeds.
  Uses UnifiedEmbedFullscreen as base.
  
  Shows:
  - Header with route summary, month, and provider
  - Calendar heatmap grid: 7 columns (Mon-Sun), rows for weeks
  - Each day cell shows the price, color-coded from green (cheapest) to red (most expensive)
  - Days without data are shown as empty/grey
  - Legend with color scale and min/max prices
  - Summary stats (cheapest price, most expensive, days with data)
  
  This is a non-composite skill: the embed data contains the full entries
  array directly (no child embeds).
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  
  /**
   * Price calendar entry for a single day
   */
  interface PriceCalendarEntry {
    date: string;
    price: number;
    transfers?: number;
    duration_minutes?: number;
    distance_km?: number;
    actual?: boolean;
  }
  
  /**
   * Price calendar result from the backend
   */
  interface PriceCalendarResult {
    type?: string;
    origin?: string;
    origin_name?: string;
    destination?: string;
    destination_name?: string;
    month?: string;
    currency?: string;
    cheapest_price?: number;
    most_expensive_price?: number;
    days_with_data?: number;
    total_days_in_month?: number;
    entries?: PriceCalendarEntry[];
  }
  
  /**
   * Calendar cell representing one day
   */
  interface CalendarCell {
    day: number;
    date: string;
    entry: PriceCalendarEntry | null;
    isCurrentMonth: boolean;
  }
  
  /**
   * Props for travel price calendar embed fullscreen
   */
  interface Props {
    /** Route summary query */
    query?: string;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Optional error message */
    errorMessage?: string;
    /** Results array (non-composite: data embedded directly) */
    results?: PriceCalendarResult[];
    /** Close handler */
    onClose: () => void;
    /** Optional: Embed ID for sharing */
    embedId?: string;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    /** Whether to show the "chat" button */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button */
    onShowChat?: () => void;
  }
  
  let {
    query: queryProp,
    status: statusProp,
    errorMessage: errorMessageProp,
    results: resultsProp,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    showChatButton = false,
    onShowChat
  }: Props = $props();
  
  // Local reactive state
  let localQuery = $state<string>(queryProp || '');
  let localResults = $state<unknown[]>(resultsProp || []);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>(statusProp || 'finished');
  let localErrorMessage = $state<string>(errorMessageProp || '');
  
  // Keep local state in sync with prop changes
  $effect(() => {
    localQuery = queryProp || '';
    localResults = resultsProp || [];
    localStatus = statusProp || 'finished';
    localErrorMessage = errorMessageProp || '';
  });
  
  // Derived state
  let query = $derived(localQuery);
  let status = $derived(localStatus);
  let fullscreenStatus = $derived(status === 'cancelled' ? 'error' : status);
  let errorMessage = $derived(localErrorMessage || ($text('chat.an_error_occured.text') || 'Processing failed.'));
  
  // Skill name from translations
  let skillName = $derived($text('app_skills.travel.price_calendar.text') || 'Price Calendar');
  
  /**
   * Flatten nested results if needed (backend returns [{id, results: [...]}])
   */
  function flattenResults(rawResults: unknown[]): PriceCalendarResult[] {
    if (!rawResults || rawResults.length === 0) return [];
    
    const firstItem = rawResults[0] as Record<string, unknown>;
    if (firstItem && 'results' in firstItem && Array.isArray(firstItem.results)) {
      const flattened: PriceCalendarResult[] = [];
      for (const entry of rawResults as Array<{ id?: string; results?: PriceCalendarResult[] }>) {
        if (entry.results && Array.isArray(entry.results)) {
          flattened.push(...entry.results);
        }
      }
      return flattened;
    }
    
    return rawResults as PriceCalendarResult[];
  }
  
  // First calendar result
  let calendarResult = $derived.by(() => {
    const flat = flattenResults(localResults);
    return flat.length > 0 ? flat[0] : null;
  });
  
  // Entries with reconstructed data from TOON flattening
  let entries = $derived.by(() => {
    if (!calendarResult) return [];
    
    // Check if entries is a direct array
    if (Array.isArray(calendarResult.entries)) {
      return calendarResult.entries;
    }
    
    // Try to reconstruct from TOON-flattened format (entries_0_date, entries_0_price, etc.)
    const raw = calendarResult as Record<string, unknown>;
    const reconstructed: PriceCalendarEntry[] = [];
    for (let i = 0; i < 31; i++) {
      const date = raw[`entries_${i}_date`];
      const price = raw[`entries_${i}_price`];
      if (typeof date !== 'string' || price === undefined) break;
      reconstructed.push({
        date: date,
        price: Number(price),
        transfers: raw[`entries_${i}_transfers`] as number | undefined,
        duration_minutes: raw[`entries_${i}_duration_minutes`] as number | undefined,
        distance_km: raw[`entries_${i}_distance_km`] as number | undefined,
        actual: raw[`entries_${i}_actual`] as boolean | undefined,
      });
    }
    return reconstructed;
  });
  
  // Route display
  let routeDisplay = $derived.by(() => {
    if (!calendarResult) return query || '';
    const origin = calendarResult.origin_name || calendarResult.origin || '';
    const dest = calendarResult.destination_name || calendarResult.destination || '';
    if (origin && dest) return `${origin} \u2192 ${dest}`;
    return query || '';
  });
  
  // IATA codes for subtitle
  let routeCodes = $derived.by(() => {
    if (!calendarResult) return '';
    const origin = calendarResult.origin || '';
    const dest = calendarResult.destination || '';
    if (origin && dest) return `${origin} \u2192 ${dest}`;
    return '';
  });
  
  // Month display (e.g., "March 2026")
  let monthDisplay = $derived.by(() => {
    if (!calendarResult?.month) return '';
    try {
      const [year, month] = calendarResult.month.split('-');
      const date = new Date(parseInt(year), parseInt(month) - 1, 1);
      return date.toLocaleDateString([], { month: 'long', year: 'numeric' });
    } catch {
      return calendarResult.month;
    }
  });
  
  // Currency
  let currency = $derived(calendarResult?.currency || 'EUR');
  
  // Price stats
  let minPrice = $derived(calendarResult?.cheapest_price ?? (entries.length > 0 ? Math.min(...entries.map(e => e.price)) : 0));
  let maxPrice = $derived(calendarResult?.most_expensive_price ?? (entries.length > 0 ? Math.max(...entries.map(e => e.price)) : 0));
  let daysWithData = $derived(calendarResult?.days_with_data ?? entries.length);
  let totalDays = $derived(calendarResult?.total_days_in_month ?? 31);
  
  // Weekday headers (Monday-first)
  const weekdayHeaders = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  
  /**
   * Build the calendar grid for the month.
   * Returns a 2D array of CalendarCells (rows x 7 columns).
   */
  let calendarGrid = $derived.by((): CalendarCell[][] => {
    if (!calendarResult?.month) return [];
    
    try {
      const [yearStr, monthStr] = calendarResult.month.split('-');
      const year = parseInt(yearStr);
      const month = parseInt(monthStr) - 1; // JS months are 0-indexed
      
      // First day of month
      const firstDay = new Date(year, month, 1);
      // Number of days in month
      const daysInMonth = new Date(year, month + 1, 0).getDate();
      
      // Day of week for first day (0=Sun, convert to Mon=0)
      let startDow = firstDay.getDay() - 1;
      if (startDow < 0) startDow = 6; // Sunday becomes 6
      
      // Build a map of date -> entry for quick lookup
      const entryMap = new Map<string, PriceCalendarEntry>();
      for (const entry of entries) {
        entryMap.set(entry.date, entry);
      }
      
      // Build grid rows
      const rows: CalendarCell[][] = [];
      let currentRow: CalendarCell[] = [];
      
      // Leading empty cells (days before the 1st)
      for (let i = 0; i < startDow; i++) {
        currentRow.push({
          day: 0,
          date: '',
          entry: null,
          isCurrentMonth: false,
        });
      }
      
      // Days of the month
      for (let d = 1; d <= daysInMonth; d++) {
        const dateStr = `${yearStr}-${monthStr.padStart(2, '0')}-${String(d).padStart(2, '0')}`;
        currentRow.push({
          day: d,
          date: dateStr,
          entry: entryMap.get(dateStr) || null,
          isCurrentMonth: true,
        });
        
        if (currentRow.length === 7) {
          rows.push(currentRow);
          currentRow = [];
        }
      }
      
      // Trailing empty cells to complete the last row
      if (currentRow.length > 0) {
        while (currentRow.length < 7) {
          currentRow.push({
            day: 0,
            date: '',
            entry: null,
            isCurrentMonth: false,
          });
        }
        rows.push(currentRow);
      }
      
      return rows;
    } catch {
      return [];
    }
  });
  
  /**
   * Get heatmap color for a price value.
   * Green (cheapest) -> Yellow (mid) -> Red (most expensive).
   * Returns an HSL color string.
   */
  function getHeatmapColor(price: number): string {
    if (minPrice === maxPrice) return 'hsl(120, 60%, 40%)'; // All same price = green
    
    // Normalize price to 0-1 range
    const t = (price - minPrice) / (maxPrice - minPrice);
    
    // Hue: 120 (green) -> 60 (yellow) -> 0 (red)
    const hue = 120 - (t * 120);
    // Saturation: 55-65%
    const sat = 55 + t * 10;
    // Lightness: 38-42% (slightly brighter at extremes for readability)
    const light = 38 + Math.abs(t - 0.5) * 8;
    
    return `hsl(${hue}, ${sat}%, ${light}%)`;
  }
  
  /**
   * Get background color with opacity for cell
   */
  function getCellBackground(price: number): string {
    if (minPrice === maxPrice) return 'hsla(120, 60%, 40%, 0.15)';
    
    const t = (price - minPrice) / (maxPrice - minPrice);
    const hue = 120 - (t * 120);
    const sat = 55 + t * 10;
    
    return `hsla(${hue}, ${sat}%, 45%, 0.15)`;
  }
  
  /**
   * Format duration in minutes to human-readable (e.g., "5h 30m")
   */
  function formatDuration(minutes: number): string {
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    if (h === 0) return `${m}m`;
    if (m === 0) return `${h}h`;
    return `${h}h ${m}m`;
  }
  
  /**
   * Format transfers count
   */
  function formatTransfers(transfers: number): string {
    if (transfers === 0) return 'Direct';
    if (transfers === 1) return '1 stop';
    return `${transfers} stops`;
  }
  
  /**
   * Handle embed data updates during streaming
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (!data.decodedContent) return;
    
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    
    const content = data.decodedContent;
    if (typeof content.query === 'string') localQuery = content.query;
    if (Array.isArray(content.results)) localResults = content.results as unknown[];
    if (typeof content.error === 'string') localErrorMessage = content.error;
  }
</script>

<UnifiedEmbedFullscreen
  appId="travel"
  skillId="price_calendar"
  title=""
  onClose={onClose}
  skillIconName="calendar"
  status={fullscreenStatus}
  {skillName}
  showStatus={true}
  legacyResults={localResults}
  currentEmbedId={embedId}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <!-- Header with route and month -->
    <div class="fullscreen-header">
      <div class="route-title">{routeDisplay}</div>
      {#if routeCodes && routeCodes !== routeDisplay}
        <div class="route-codes">{routeCodes}</div>
      {/if}
      {#if monthDisplay}
        <div class="month-title">{monthDisplay}</div>
      {/if}
      <div class="provider-text">{$text('embeds.via.text') || 'via'} Travelpayouts</div>
    </div>
    
    <!-- Error state -->
    {#if status === 'error'}
      <div class="error-state">
        <div class="error-title">{$text('embeds.search_failed.text') || 'Search failed'}</div>
        <div class="error-message">{errorMessage}</div>
      </div>
    {:else if entries.length === 0}
      <div class="no-results">
        <p>{$text('embeds.no_price_data.text') || 'No price data available for this route'}</p>
      </div>
    {:else}
      <!-- Summary stats bar -->
      <div class="stats-bar">
        <div class="stat">
          <span class="stat-label">{$text('embeds.cheapest.text') || 'Cheapest'}</span>
          <span class="stat-value cheapest">{currency} {Math.round(minPrice)}</span>
        </div>
        <div class="stat">
          <span class="stat-label">{$text('embeds.most_expensive.text') || 'Most expensive'}</span>
          <span class="stat-value expensive">{currency} {Math.round(maxPrice)}</span>
        </div>
        <div class="stat">
          <span class="stat-label">{$text('embeds.coverage.text') || 'Coverage'}</span>
          <span class="stat-value">{daysWithData} / {totalDays} {$text('embeds.days.text') || 'days'}</span>
        </div>
      </div>
      
      <!-- Color legend -->
      <div class="legend">
        <span class="legend-label">{currency} {Math.round(minPrice)}</span>
        <div class="legend-gradient"></div>
        <span class="legend-label">{currency} {Math.round(maxPrice)}</span>
      </div>
      
      <!-- Calendar grid -->
      <div class="calendar-container">
        <div class="calendar-grid">
          <!-- Weekday headers -->
          {#each weekdayHeaders as day}
            <div class="weekday-header">{day}</div>
          {/each}
          
          <!-- Calendar cells -->
          {#each calendarGrid as row}
            {#each row as cell}
              {#if !cell.isCurrentMonth}
                <div class="calendar-cell empty"></div>
              {:else if cell.entry}
                <div
                  class="calendar-cell has-data"
                  style="background-color: {getCellBackground(cell.entry.price)}; border-color: {getHeatmapColor(cell.entry.price)};"
                  title="{cell.date}: {currency} {Math.round(cell.entry.price)}{cell.entry.transfers !== undefined ? ` (${formatTransfers(cell.entry.transfers)})` : ''}{cell.entry.duration_minutes ? ` - ${formatDuration(cell.entry.duration_minutes)}` : ''}"
                >
                  <span class="cell-day">{cell.day}</span>
                  <span class="cell-price" style="color: {getHeatmapColor(cell.entry.price)};">
                    {Math.round(cell.entry.price)}
                  </span>
                  {#if cell.entry.transfers !== undefined}
                    <span class="cell-transfers">
                      {cell.entry.transfers === 0 ? 'Direct' : `${cell.entry.transfers}\u00d7`}
                    </span>
                  {/if}
                </div>
              {:else}
                <div class="calendar-cell no-data">
                  <span class="cell-day">{cell.day}</span>
                  <span class="cell-no-price">&mdash;</span>
                </div>
              {/if}
            {/each}
          {/each}
        </div>
      </div>
      
      <!-- Data freshness note -->
      <div class="freshness-note">
        {$text('embeds.price_calendar_note.text') || 'Prices are cached estimates (~48h old). Search specific dates for live pricing.'}
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     Fullscreen Header
     =========================================== */
  
  .fullscreen-header {
    margin-top: 60px;
    margin-bottom: 24px;
    padding: 0 16px;
    text-align: center;
  }
  
  .route-title {
    font-size: 24px;
    font-weight: 600;
    color: var(--color-font-primary);
    line-height: 1.3;
    word-break: break-word;
  }
  
  .route-codes {
    font-size: 14px;
    font-weight: 500;
    color: var(--color-font-secondary);
    margin-top: 4px;
    letter-spacing: 1px;
  }
  
  .month-title {
    font-size: 18px;
    font-weight: 500;
    color: var(--color-font-primary);
    margin-top: 8px;
  }
  
  .provider-text {
    font-size: 14px;
    color: var(--color-font-secondary);
    margin-top: 6px;
  }
  
  @container fullscreen (max-width: 500px) {
    .fullscreen-header {
      margin-top: 70px;
      margin-bottom: 16px;
    }
    
    .route-title {
      font-size: 20px;
    }
    
    .month-title {
      font-size: 16px;
    }
  }
  
  /* ===========================================
     Stats Bar
     =========================================== */
  
  .stats-bar {
    display: flex;
    justify-content: center;
    gap: 24px;
    padding: 12px 16px;
    margin: 0 auto 16px;
    max-width: 600px;
    flex-wrap: wrap;
  }
  
  .stat {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
  }
  
  .stat-label {
    font-size: 12px;
    color: var(--color-font-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  
  .stat-value {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-font-primary);
  }
  
  .stat-value.cheapest {
    color: hsl(120, 55%, 38%);
  }
  
  .stat-value.expensive {
    color: hsl(0, 60%, 42%);
  }
  
  @container fullscreen (max-width: 500px) {
    .stats-bar {
      gap: 16px;
    }
    
    .stat-value {
      font-size: 14px;
    }
  }
  
  /* ===========================================
     Color Legend
     =========================================== */
  
  .legend {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    margin: 0 auto 20px;
    padding: 0 16px;
  }
  
  .legend-label {
    font-size: 12px;
    font-weight: 500;
    color: var(--color-font-secondary);
    white-space: nowrap;
  }
  
  .legend-gradient {
    width: 120px;
    height: 8px;
    border-radius: 4px;
    background: linear-gradient(to right, hsl(120, 55%, 40%), hsl(60, 60%, 42%), hsl(0, 60%, 42%));
  }
  
  /* ===========================================
     Calendar Grid
     =========================================== */
  
  .calendar-container {
    width: 100%;
    max-width: 600px;
    margin: 0 auto;
    padding: 0 12px;
    padding-bottom: 80px;
  }
  
  .calendar-grid {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 4px;
  }
  
  /* Weekday headers */
  .weekday-header {
    text-align: center;
    font-size: 12px;
    font-weight: 600;
    color: var(--color-font-secondary);
    padding: 8px 0;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  
  /* Calendar cells */
  .calendar-cell {
    aspect-ratio: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    border-radius: 8px;
    position: relative;
    min-height: 56px;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }
  
  .calendar-cell.empty {
    background: transparent;
  }
  
  .calendar-cell.has-data {
    border: 1.5px solid;
    cursor: default;
  }
  
  .calendar-cell.has-data:hover {
    transform: scale(1.05);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
    z-index: 1;
  }
  
  .calendar-cell.no-data {
    background-color: var(--color-grey-15, rgba(128, 128, 128, 0.06));
    border: 1px solid var(--color-grey-20, rgba(128, 128, 128, 0.1));
  }
  
  /* Cell content */
  .cell-day {
    font-size: 11px;
    font-weight: 500;
    color: var(--color-font-secondary);
    line-height: 1;
  }
  
  .cell-price {
    font-size: 14px;
    font-weight: 700;
    line-height: 1.2;
  }
  
  .cell-transfers {
    font-size: 9px;
    color: var(--color-font-secondary);
    line-height: 1;
    margin-top: 1px;
  }
  
  .cell-no-price {
    font-size: 14px;
    color: var(--color-grey-40, rgba(128, 128, 128, 0.3));
    line-height: 1;
  }
  
  @container fullscreen (max-width: 500px) {
    .calendar-cell {
      min-height: 48px;
      border-radius: 6px;
    }
    
    .cell-day {
      font-size: 10px;
    }
    
    .cell-price {
      font-size: 12px;
    }
    
    .cell-transfers {
      font-size: 8px;
    }
    
    .calendar-grid {
      gap: 3px;
    }
  }
  
  @container fullscreen (max-width: 360px) {
    .calendar-cell {
      min-height: 40px;
      border-radius: 4px;
    }
    
    .cell-price {
      font-size: 11px;
    }
    
    .cell-transfers {
      display: none;
    }
    
    .calendar-grid {
      gap: 2px;
    }
  }
  
  /* ===========================================
     States
     =========================================== */
  
  .no-results {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
    font-size: 16px;
    text-align: center;
    padding: 0 16px;
  }
  
  .error-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 24px 16px;
    color: var(--color-font-secondary);
    text-align: center;
  }
  
  .error-title {
    font-size: 18px;
    font-weight: 600;
    color: var(--color-error);
  }
  
  .error-message {
    font-size: 14px;
    line-height: 1.4;
    max-width: 520px;
    word-break: break-word;
  }
  
  /* ===========================================
     Freshness Note
     =========================================== */
  
  .freshness-note {
    text-align: center;
    font-size: 12px;
    color: var(--color-font-secondary);
    padding: 16px;
    max-width: 500px;
    margin: 0 auto;
    line-height: 1.4;
    font-style: italic;
  }
</style>
