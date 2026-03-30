<!--
  frontend/packages/ui/src/components/embeds/travel/TravelConnectionEmbedFullscreen.svelte

  Fullscreen detail view for a single travel connection (child embed).
  Uses EntryWithMapTemplate for map-background layout with overlapping detail card.

  Layout (wide):
  - Gradient header: price, route, trip info, CTA
  - Full-background map showing flight arc (great-circle or FR24 track)
  - Detail card overlaid on left: card-based flight details with segment cards

  Layout (narrow/mobile):
  - Gradient header
  - Map strip (150px)
  - Stacked detail card with scrollable segment cards

  Figma: node 4950-44635 (fullscreen), node 4956-45277 (flight details card)
-->

<script lang="ts">
  import EntryWithMapTemplate from '../EntryWithMapTemplate.svelte';
  import { text } from '@repo/ui';
  import { onDestroy } from 'svelte';
  import { notificationStore } from '../../../stores/notificationStore';
  import { getApiEndpoint } from '../../../config/api';
  import { embedStore } from '../../../services/embedStore';
  import 'leaflet/dist/leaflet.css';
  import type { Map as LeafletMap } from 'leaflet';
  import { copyToClipboard } from '../../../utils/clipboardUtils';
  import { proxyImage, MAX_WIDTH_AIRLINE_LOGO_FULLSCREEN } from '../../../utils/imageProxy';
  import { countryCodeToFlag } from '../../../utils/countryFlag';
  
  /** Segment data within a leg */
  interface SegmentData {
    carrier: string;
    carrier_code?: string;
    number?: string;
    departure_station: string;
    departure_time: string;
    departure_latitude?: number;
    departure_longitude?: number;
    arrival_station: string;
    arrival_time: string;
    arrival_latitude?: number;
    arrival_longitude?: number;
    duration: string;
    /** Country codes (ISO 3166-1 alpha-2) for flag emoji display */
    departure_country_code?: string;
    arrival_country_code?: string;
    /** Daytime indicators for time badge color coding (sunrise/sunset-aware) */
    departure_is_daytime?: boolean;
    arrival_is_daytime?: boolean;
    /** Rich metadata from Google Flights */
    airplane?: string;
    airline_logo?: string;
    legroom?: string;
    travel_class?: string;
    extensions?: string[];
    often_delayed?: boolean;
  }
  
  /** Layover data between segments */
  interface LayoverData {
    airport: string;
    airport_code?: string;
    duration?: string;
    duration_minutes?: number;
    overnight?: boolean;
  }
  
  /** Leg data */
  interface LegData {
    leg_index: number;
    origin: string;
    destination: string;
    departure: string;
    arrival: string;
    duration: string;
    stops: number;
    segments: SegmentData[];
    layovers?: LayoverData[];
  }
  
  /** Connection data */
  interface ConnectionData {
    embed_id: string;
    type?: string;
    transport_method?: string;
    trip_type?: string;
    total_price?: string;
    currency?: string;
    bookable_seats?: number;
    last_ticketing_date?: string;
    booking_url?: string;
    booking_provider?: string;
    booking_token?: string;
    booking_context?: Record<string, string>;
    origin?: string;
    destination?: string;
    departure?: string;
    arrival?: string;
    duration?: string;
    stops?: number;
    carriers?: string[];
    carrier_codes?: string[];
    hash?: string;
    legs?: LegData[];
    /** Country codes for route header flag emojis (ISO 3166-1 alpha-2) */
    origin_country_code?: string;
    destination_country_code?: string;
    /** Rich metadata from Google Flights */
    airline_logo?: string;
    co2_kg?: number;
    co2_typical_kg?: number;
    co2_difference_percent?: number;
    /**
     * Persisted flight track data from Flightradar24.
     * Present after a successful get_flight lookup (post-persist).
     * Shape matches FlightDetailsResponse from the REST endpoint.
     */
    flight_track?: {
      fr24_id?: string;
      tracks: Array<{ timestamp: number; lat: number; lon: number; alt?: number; gspeed?: number }>;
      actual_takeoff?: string;
      actual_landing?: string;
      runway_takeoff?: string;
      runway_landing?: string;
      actual_distance_km?: number;
      flight_time_minutes?: number;
      diverted?: boolean;
      actual_destination_iata?: string;
    };
  }
  
  interface Props {
    /** Connection data from parent */
    connection: ConnectionData;
    /** Close handler */
    onClose: () => void;
    /** Embed ID for reference */
    embedId?: string;
    /** Whether there is a previous connection to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next connection to navigate to */
    hasNextEmbed?: boolean;
    /** Navigate to previous connection */
    onNavigatePrevious?: () => void;
    /** Navigate to next connection */
    onNavigateNext?: () => void;
  }
  
  let {
    connection,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
  }: Props = $props();

  // Defensive: connection may be undefined during async component loading in dev preview
  type MaybeConnection = ConnectionData | undefined;
  
  // Format price
  let formattedPrice = $derived.by(() => {
    const conn = connection as MaybeConnection;
    if (!conn?.total_price) return '';
    const num = parseFloat(conn.total_price);
    if (isNaN(num)) return `${conn.currency || 'EUR'} ${conn.total_price}`;
    return `${conn.currency || 'EUR'} ${num.toFixed(num % 1 === 0 ? 0 : 2)}`;
  });
  
  // Route summary
  let routeDisplay = $derived.by(() => {
    const conn = connection as MaybeConnection;
    if (conn?.origin && conn?.destination) {
      return `${conn.origin} → ${conn.destination}`;
    }
    return '';
  });
  
  // Trip type label
  let tripTypeLabel = $derived.by(() => {
    const conn = connection as MaybeConnection;
    switch (conn?.trip_type) {
      case 'round_trip': return 'Round trip';
      case 'multi_city': return 'Multi-city';
      default: return 'One way';
    }
  });
  
  // Leg labels
  function getLegLabel(leg: LegData, totalLegs: number): string {
    if (totalLegs === 1) return '';
    if (totalLegs === 2) {
      return leg.leg_index === 0 ? 'Outbound' : 'Return';
    }
    return `Leg ${leg.leg_index + 1}`;
  }
  
  // Format time from ISO string
  function formatTime(isoString: string): string {
    if (!isoString) return '';
    try {
      const date = new Date(isoString);
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return isoString;
    }
  }
  
  // Format date from ISO string
  function formatDate(isoString: string): string {
    if (!isoString) return '';
    try {
      const date = new Date(isoString);
      return date.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
    } catch {
      return isoString;
    }
  }
  
  // Stops label
  function getStopsLabel(stops: number): string {
    if (stops === 0) return 'Direct';
    if (stops === 1) return '1 stop';
    return `${stops} stops`;
  }
  
  // ── Derived values for the redesigned card-based layout ──

  /** Route header with flags: "🇩🇪 Berlin → 🇹🇭 Bangkok" */
  let routeHeaderWithFlags = $derived.by(() => {
    const conn = connection as MaybeConnection;
    if (!conn) return '';
    const originFlag = conn.origin_country_code ? countryCodeToFlag(conn.origin_country_code) + ' ' : '';
    const destFlag = conn.destination_country_code ? countryCodeToFlag(conn.destination_country_code) + ' ' : '';
    const originCity = conn.origin?.replace(/\s*\([^)]+\)/, '') || conn.origin || '';
    const destCity = conn.destination?.replace(/\s*\([^)]+\)/, '') || conn.destination || '';
    return `${originFlag}${originCity} → ${destFlag}${destCity}`;
  });

  /** Travel class from first segment (e.g., "Economy class") */
  let travelClassLabel = $derived.by(() => {
    const conn = connection as MaybeConnection;
    const firstSeg = conn?.legs?.[0]?.segments?.[0];
    if (firstSeg?.travel_class) return `${firstSeg.travel_class} class`;
    return '';
  });

  /** Starting airport full name */
  let startAirportName = $derived.by(() => {
    const conn = connection as MaybeConnection;
    const firstSeg = conn?.legs?.[0]?.segments?.[0];
    if (!firstSeg) return '';
    const origin = conn?.legs?.[0]?.origin || '';
    return origin || firstSeg.departure_station;
  });

  /** Subtitle for header: "Berlin (BER) → Bangkok (BKK)\nSat, Mar 28 · 31h 20m · 2 stops" */
  let headerSubtitle = $derived.by(() => {
    const conn = connection as MaybeConnection;
    const parts: string[] = [];
    if (routeDisplay) parts.push(routeDisplay);
    const meta: string[] = [];
    if (conn?.departure) {
      const d = formatDate(conn.departure);
      if (d) meta.push(d);
    }
    if (conn?.duration) meta.push(conn.duration);
    if (conn?.stops !== undefined) meta.push(getStopsLabel(conn.stops));
    if (meta.length) parts.push(meta.join(' · '));
    return parts.join('\n');
  });

  /** Price header: "1.111 EUR | One way" */
  let priceHeader = $derived.by(() => {
    if (!formattedPrice) return '';
    return `${formattedPrice} | ${tripTypeLabel}`;
  });

  /** Map center derived from midpoint of route waypoints */
  let mapCenter = $derived.by(() => {
    if (routeWaypoints.length < 2) return undefined;
    const lats = routeWaypoints.map(w => w.lat);
    const lngs = routeWaypoints.map(w => w.lng);
    return {
      lat: (Math.min(...lats) + Math.max(...lats)) / 2,
      lon: (Math.min(...lngs) + Math.max(...lngs)) / 2,
    };
  });

  // ---------------------------------------------------------------------------
  // Three-state booking button
  // State: 'idle' -> 'loading' -> 'loaded' (or 'error')
  // - idle: booking_token exists but URL not yet fetched -> "Get booking link"
  // - loading: REST request in progress -> spinner
  // - loaded: URL resolved -> "Book on {provider}" (clickable)
  // - error: lookup failed -> no booking button shown
  //
  // If booking_url is already present (pre-resolved), skip to 'loaded' state.
  // ---------------------------------------------------------------------------
  
  type BookingState = 'idle' | 'loading' | 'loaded' | 'error';
  
  // Resolved booking URL and provider (from on-demand lookup or pre-existing)
  // Initialised to '' / 'idle' — values from props are applied in onMount below
  let resolvedBookingUrl = $state('');
  let resolvedBookingProvider = $state('');
  let bookingState = $state<BookingState>('idle');

  // Sync initial booking values from the connection prop (once, reactive to connection changes)
  $effect(() => {
    const conn = connection as MaybeConnection;
    if (conn?.booking_url && bookingState === 'idle') {
      resolvedBookingUrl = conn.booking_url;
      resolvedBookingProvider = conn.booking_provider || '';
      bookingState = 'loaded';
    }
  });
  
  // Primary carrier name (for display when provider not yet known)
  let primaryCarrier = $derived((connection as MaybeConnection)?.carriers?.[0] || '');
  
  // Hashed chat ID for linking usage entries to the chat where the embed lives.
  // Loaded from the embed store on mount so it's available for the booking link request.
  let hashedChatId = $state<string | undefined>(undefined);
  
  $effect(() => {
    if (embedId) {
      embedStore.get(`embed:${embedId}`).then(embed => {
        if (embed) hashedChatId = embed.hashed_chat_id || undefined;
      });
    }
  });

  // ---------------------------------------------------------------------------
  // Flight track (Flightradar24) — three-state auto-load
  //
  // State machine:
  //   'idle'    → no air segment found, or flight_track already persisted (skip to loaded)
  //   'loading' → REST request to POST /v1/apps/travel/flight-details in progress
  //   'loaded'  → track data available (either from persist or fresh fetch)
  //   'error'   → fetch failed; UI falls back to existing great-circle arc silently
  //
  // Pattern mirrors the booking-link three-state flow exactly.
  // ---------------------------------------------------------------------------

  type FlightTrackState = 'idle' | 'loading' | 'loaded' | 'error';

  let flightTrackState = $state<FlightTrackState>('idle');

  /** Resolved flight track data (either from persist or fresh fetch) */
  let resolvedFlightTrack = $state<ConnectionData['flight_track'] | null>(null);

  // If flight_track is already persisted in the connection data, skip to loaded state.
  $effect(() => {
    const conn = connection as MaybeConnection;
    if (conn?.flight_track && flightTrackState === 'idle') {
      resolvedFlightTrack = conn.flight_track;
      flightTrackState = 'loaded';
    }
  });

  /**
   * Derive the first air segment's flight number from the connection's legs.
   * Returns null if no air segment with a flight number is found.
   */
  let firstAirFlightNumber = $derived.by(() => {
    const conn = connection as MaybeConnection;
    if (!conn?.legs) return null;
    for (const leg of conn.legs) {
      if (!leg.segments) continue;
      for (const seg of leg.segments) {
        if (seg.number && seg.number.trim()) {
          return seg.number.trim();
        }
      }
    }
    return null;
  });

  /** Departure date extracted from the first leg's departure ISO string */
  let firstDepartureDate = $derived.by(() => {
    const conn = connection as MaybeConnection;
    const depIso = conn?.legs?.[0]?.departure || conn?.departure;
    if (!depIso) return null;
    return depIso.split('T')[0] || null;
  });

  // Auto-trigger: once we have a flight number + date, auto-load the track.
  // Only fires when: we have an air segment, state is idle, track not yet persisted.
  $effect(() => {
    const conn = connection as MaybeConnection;
    if (
      firstAirFlightNumber &&
      firstDepartureDate &&
      flightTrackState === 'idle' &&
      conn?.transport_method === 'airplane'
    ) {
      loadFlightDetails(firstAirFlightNumber, firstDepartureDate);
    }
  });

  /**
   * Fetch real flight track data from Flightradar24 via the REST endpoint.
   * Called automatically when the fullscreen opens for an air connection.
   * Silently falls back to the great-circle arc on any error.
   */
  async function loadFlightDetails(flightNumber: string, departureDate: string) {
    if (flightTrackState !== 'idle') return;

    flightTrackState = 'loading';

    try {
      const response = await fetch(getApiEndpoint('/v1/apps/travel/flight-details'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({
          flight_number: flightNumber,
          departure_date: departureDate,
          origin_iata: connection.booking_context?.departure_id || null,
          destination_iata: connection.booking_context?.arrival_id || null,
          hashed_chat_id: hashedChatId || null,
        }),
        credentials: 'include',
      });

      if (!response.ok) {
        console.debug(
          `[TravelConnectionEmbedFullscreen] Flight details request failed: ${response.status} — falling back to arc`,
        );
        flightTrackState = 'error';
        return;
      }

      const data = await response.json();

      if (data.success && data.tracks && data.tracks.length >= 2) {
        resolvedFlightTrack = {
          fr24_id: data.fr24_id,
          tracks: data.tracks,
          actual_takeoff: data.actual_takeoff,
          actual_landing: data.actual_landing,
          runway_takeoff: data.runway_takeoff,
          runway_landing: data.runway_landing,
          actual_distance_km: data.actual_distance_km,
          flight_time_minutes: data.flight_time_minutes,
          diverted: data.diverted,
          actual_destination_iata: data.actual_destination_iata,
        };
        flightTrackState = 'loaded';

        // Persist into embed so reopening is free (no second API call)
        persistFlightDetailsInEmbed(resolvedFlightTrack);
      } else {
        // Flight not found or no track data — silent fallback to arc
        console.debug(
          '[TravelConnectionEmbedFullscreen] No track data from FR24 — using arc fallback',
          data.error,
        );
        flightTrackState = 'error';
      }
    } catch (err) {
      // Network error etc. — silent fallback to arc
      console.debug('[TravelConnectionEmbedFullscreen] Flight details fetch failed:', err);
      flightTrackState = 'error';
    }
  }

  /**
   * Persist the resolved flight track data into the child embed's content
   * so the real map polyline survives close/reopen of the fullscreen view.
   *
   * Mirrors persistBookingUrlInEmbed() exactly — same IDB + server sync flow.
   * Non-blocking: failures are logged but do not affect the UI.
   */
  async function persistFlightDetailsInEmbed(
    flightTrack: NonNullable<ConnectionData['flight_track']>,
  ) {
    if (!embedId) {
      console.debug('[TravelConnectionEmbedFullscreen] No embedId, skipping flight track persistence');
      return;
    }

    try {
      const contentRef = `embed:${embedId}`;

      const existingEmbed = await embedStore.get(contentRef);
      if (!existingEmbed) {
        console.warn('[TravelConnectionEmbedFullscreen] Embed not found in store, cannot persist flight track:', embedId);
        return;
      }

      const { decodeToonContent } = await import('../../../services/embedResolver');
      let decodedContent: Record<string, unknown> = {};
      if (existingEmbed.content && typeof existingEmbed.content === 'string') {
        decodedContent = (await decodeToonContent(existingEmbed.content)) || {};
      } else if (typeof existingEmbed.content === 'object' && existingEmbed.content !== null) {
        decodedContent = existingEmbed.content as Record<string, unknown>;
      }

      // Inject the flight track data
      decodedContent.flight_track = flightTrack;

      const { encode: toonEncode } = await import('@toon-format/toon');
      const updatedToonContent = toonEncode(decodedContent);

      const embedHashed = existingEmbed.hashed_chat_id || undefined;
      const embedKey = await embedStore.getEmbedKey(embedId, embedHashed);

      if (!embedKey) {
        console.warn('[TravelConnectionEmbedFullscreen] No embed key found, cannot persist flight track:', embedId);
        return;
      }

      const { encryptWithEmbedKey } = await import('../../../services/cryptoService');
      const encryptedContent = await encryptWithEmbedKey(updatedToonContent, embedKey);
      if (!encryptedContent) {
        console.warn('[TravelConnectionEmbedFullscreen] Failed to encrypt updated content');
        return;
      }

      const embedType = existingEmbed.type || existingEmbed.embed_type || 'app-skill-use';
      const encryptedType = (await encryptWithEmbedKey(embedType, embedKey)) || undefined;

      const nowMs = Date.now();

      const encryptedEmbedForStorage = {
        embed_id: existingEmbed.embed_id || embedId,
        encrypted_content: encryptedContent,
        encrypted_type: encryptedType,
        encrypted_text_preview: existingEmbed.encrypted_text_preview,
        status: existingEmbed.status || 'finished',
        hashed_chat_id: existingEmbed.hashed_chat_id,
        hashed_message_id: existingEmbed.hashed_message_id,
        hashed_task_id: existingEmbed.hashed_task_id,
        hashed_user_id: existingEmbed.hashed_user_id,
        embed_ids: existingEmbed.embed_ids,
        parent_embed_id: existingEmbed.parent_embed_id,
        version_number: existingEmbed.version_number,
        file_path: existingEmbed.file_path,
        content_hash: existingEmbed.content_hash,
        text_length_chars: existingEmbed.text_length_chars,
        is_private: existingEmbed.is_private ?? false,
        is_shared: existingEmbed.is_shared ?? false,
        createdAt: existingEmbed.createdAt,
        updatedAt: nowMs,
      };

      await embedStore.putEncrypted(
        contentRef,
        encryptedEmbedForStorage,
        embedType as import('../../../message_parsing/types').EmbedType,
        updatedToonContent,
        { app_id: existingEmbed.app_id, skill_id: existingEmbed.skill_id },
      );

      console.info('[TravelConnectionEmbedFullscreen] Persisted flight track in embed:', embedId);

      try {
        const { chatSyncService } = await import('../../../services/chatSyncService');
        const nowSecs = Math.floor(nowMs / 1000);
        await chatSyncService.sendStoreEmbed({
          embed_id: encryptedEmbedForStorage.embed_id || embedId,
          encrypted_type: encryptedEmbedForStorage.encrypted_type || '',
          encrypted_content: encryptedEmbedForStorage.encrypted_content,
          encrypted_text_preview: encryptedEmbedForStorage.encrypted_text_preview,
          status: encryptedEmbedForStorage.status || 'finished',
          hashed_chat_id: encryptedEmbedForStorage.hashed_chat_id || '',
          hashed_message_id: encryptedEmbedForStorage.hashed_message_id || '',
          hashed_task_id: encryptedEmbedForStorage.hashed_task_id,
          hashed_user_id: encryptedEmbedForStorage.hashed_user_id || '',
          embed_ids: encryptedEmbedForStorage.embed_ids,
          parent_embed_id: encryptedEmbedForStorage.parent_embed_id,
          version_number: encryptedEmbedForStorage.version_number,
          file_path: encryptedEmbedForStorage.file_path,
          content_hash: encryptedEmbedForStorage.content_hash,
          text_length_chars: encryptedEmbedForStorage.text_length_chars,
          is_private: encryptedEmbedForStorage.is_private,
          is_shared: encryptedEmbedForStorage.is_shared,
          created_at: encryptedEmbedForStorage.createdAt
            ? Math.floor(encryptedEmbedForStorage.createdAt / 1000)
            : nowSecs,
          updated_at: nowSecs,
        });
        console.debug('[TravelConnectionEmbedFullscreen] Sent updated embed (flight track) to server:', embedId);
      } catch (sendError) {
        console.warn('[TravelConnectionEmbedFullscreen] Failed to send updated embed (flight track) to server:', sendError);
      }
    } catch (error) {
      console.warn('[TravelConnectionEmbedFullscreen] Failed to persist flight track in embed:', error);
    }
  }

  /**
   * Build a Google Flights search URL from the connection data.
   * Used as a fallback when the direct booking link is unavailable.
   *
   * Format: https://www.google.com/travel/flights?q=Flights+from+BER+to+BKK+on+2026-03-05
   */
  function buildGoogleFlightsUrl(): string {
    const origin = connection.booking_context?.departure_id || connection.origin || '';
    const dest = connection.booking_context?.arrival_id || connection.destination || '';
    const date = connection.booking_context?.outbound_date || connection.departure?.split('T')[0] || '';
    
    const parts = ['Flights'];
    if (origin) parts.push(`from ${origin}`);
    if (dest) parts.push(`to ${dest}`);
    if (date) parts.push(`on ${date}`);
    
    return `https://www.google.com/travel/flights?q=${encodeURIComponent(parts.join(' '))}`;
  }
  
  /**
   * Open Google Flights in a new tab as a fallback.
   */
  function handleOpenGoogleFlights() {
    window.open(buildGoogleFlightsUrl(), '_blank', 'noopener,noreferrer');
  }
  
  /**
   * Fetch booking URL on-demand via the REST endpoint.
   * Called when user clicks the "Get booking link" button.
   */
  async function handleLoadBookingLink() {
    if (!connection.booking_token || bookingState === 'loading') return;
    
    bookingState = 'loading';
    
    try {
      const response = await fetch(getApiEndpoint('/v1/apps/travel/booking-link'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({
          booking_token: connection.booking_token,
          booking_context: connection.booking_context || null,
          hashed_chat_id: hashedChatId || null,
        }),
        credentials: 'include',
      });
      
      if (!response.ok) {
        console.error(`Booking link request failed: ${response.status}`);
        bookingState = 'error';
        notificationStore.error(
          $text('embeds.booking_link_failed')
        );
        return;
      }
      
      const data = await response.json();
      
      if (data.success && data.booking_url) {
        resolvedBookingUrl = data.booking_url;
        resolvedBookingProvider = data.booking_provider || primaryCarrier;
        bookingState = 'loaded';
        
        // Persist the resolved booking URL into the embed so it survives close/reopen
        persistBookingUrlInEmbed(data.booking_url, data.booking_provider || primaryCarrier);
      } else {
        // No booking link found — show Google Flights fallback
        console.log('No booking link available from SerpAPI');
        bookingState = 'error';
        notificationStore.error(
          $text('embeds.booking_link_failed')
        );
      }
    } catch (err) {
      console.error('Booking link lookup failed:', err);
      bookingState = 'error';
      notificationStore.error(
        $text('embeds.booking_link_failed')
      );
    }
  }
  
  /**
   * Open the resolved booking URL in a new tab.
   * Called when user clicks the "Book on {provider}" button (loaded state).
   */
  function handleOpenBookingUrl() {
    if (resolvedBookingUrl) {
      window.open(resolvedBookingUrl, '_blank', 'noopener,noreferrer');
    }
  }
  
  /**
   * Persist the resolved booking URL and provider into the child embed's content
   * so the booking button survives close/reopen of the fullscreen view.
   *
   * Flow:
   * 1. Load the existing embed from embedStore (decrypted)
   * 2. Decode its TOON content and inject booking_url + booking_provider
   * 3. Re-encode as TOON, re-encrypt with the embed key, and store locally
   * 4. Send the updated encrypted embed to the server via store_embed WebSocket event
   *
   * This is non-blocking — failures are logged but don't affect the UI.
   */
  async function persistBookingUrlInEmbed(bookingUrl: string, bookingProvider: string) {
    if (!embedId) {
      console.debug('[TravelConnectionEmbedFullscreen] No embedId, skipping booking URL persistence');
      return;
    }
    
    try {
      const contentRef = `embed:${embedId}`;
      
      // Load the existing embed data (decrypted)
      const existingEmbed = await embedStore.get(contentRef);
      if (!existingEmbed) {
        console.warn('[TravelConnectionEmbedFullscreen] Embed not found in store, cannot persist booking URL:', embedId);
        return;
      }
      
      // Decode the TOON content to a plain object so we can add booking_url
      const { decodeToonContent } = await import('../../../services/embedResolver');
      let decodedContent: Record<string, unknown> = {};
      if (existingEmbed.content && typeof existingEmbed.content === 'string') {
        decodedContent = (await decodeToonContent(existingEmbed.content)) || {};
      } else if (typeof existingEmbed.content === 'object' && existingEmbed.content !== null) {
        decodedContent = existingEmbed.content as Record<string, unknown>;
      }
      
      // Inject the resolved booking URL and provider into the content
      decodedContent.booking_url = bookingUrl;
      decodedContent.booking_provider = bookingProvider;
      
      // Re-encode as TOON
      const { encode: toonEncode } = await import('@toon-format/toon');
      const updatedToonContent = toonEncode(decodedContent);
      
      // Get the embed key for encryption (child embeds inherit parent's key)
      const hashedChatId = existingEmbed.hashed_chat_id || undefined;
      const embedKey = await embedStore.getEmbedKey(embedId, hashedChatId);
      
      if (!embedKey) {
        console.warn('[TravelConnectionEmbedFullscreen] No embed key found, cannot persist booking URL:', embedId);
        return;
      }
      
      // Encrypt the updated content
      const { encryptWithEmbedKey } = await import('../../../services/cryptoService');
      const encryptedContent = await encryptWithEmbedKey(updatedToonContent, embedKey);
      if (!encryptedContent) {
        console.warn('[TravelConnectionEmbedFullscreen] Failed to encrypt updated content');
        return;
      }
      
      // Encrypt the type
      const embedType = existingEmbed.type || existingEmbed.embed_type || 'app-skill-use';
      const encryptedType = (await encryptWithEmbedKey(embedType, embedKey)) || undefined;
      
      const nowMs = Date.now();
      
      // Build the encrypted embed object for local storage
      const encryptedEmbedForStorage = {
        embed_id: existingEmbed.embed_id || embedId,
        encrypted_content: encryptedContent,
        encrypted_type: encryptedType,
        encrypted_text_preview: existingEmbed.encrypted_text_preview,
        status: existingEmbed.status || 'finished',
        hashed_chat_id: existingEmbed.hashed_chat_id,
        hashed_message_id: existingEmbed.hashed_message_id,
        hashed_task_id: existingEmbed.hashed_task_id,
        hashed_user_id: existingEmbed.hashed_user_id,
        embed_ids: existingEmbed.embed_ids,
        parent_embed_id: existingEmbed.parent_embed_id,
        version_number: existingEmbed.version_number,
        file_path: existingEmbed.file_path,
        content_hash: existingEmbed.content_hash,
        text_length_chars: existingEmbed.text_length_chars,
        is_private: existingEmbed.is_private ?? false,
        is_shared: existingEmbed.is_shared ?? false,
        createdAt: existingEmbed.createdAt,
        updatedAt: nowMs,
      };
      
      // Store locally via putEncrypted (updates IndexedDB + memory cache)
      await embedStore.putEncrypted(
        contentRef,
        encryptedEmbedForStorage,
        embedType as import('../../../message_parsing/types').EmbedType,
        updatedToonContent,
        { app_id: existingEmbed.app_id, skill_id: existingEmbed.skill_id },
      );
      
      console.info('[TravelConnectionEmbedFullscreen] Persisted booking URL in embed:', embedId);
      
      // Send updated embed to server via store_embed WebSocket event
      try {
        const { chatSyncService } = await import('../../../services/chatSyncService');
        const nowSecs = Math.floor(nowMs / 1000);
        await chatSyncService.sendStoreEmbed({
          embed_id: encryptedEmbedForStorage.embed_id || embedId,
          encrypted_type: encryptedEmbedForStorage.encrypted_type || '',
          encrypted_content: encryptedEmbedForStorage.encrypted_content,
          encrypted_text_preview: encryptedEmbedForStorage.encrypted_text_preview,
          status: encryptedEmbedForStorage.status || 'finished',
          hashed_chat_id: encryptedEmbedForStorage.hashed_chat_id || '',
          hashed_message_id: encryptedEmbedForStorage.hashed_message_id || '',
          hashed_task_id: encryptedEmbedForStorage.hashed_task_id,
          hashed_user_id: encryptedEmbedForStorage.hashed_user_id || '',
          embed_ids: encryptedEmbedForStorage.embed_ids,
          parent_embed_id: encryptedEmbedForStorage.parent_embed_id,
          version_number: encryptedEmbedForStorage.version_number,
          file_path: encryptedEmbedForStorage.file_path,
          content_hash: encryptedEmbedForStorage.content_hash,
          text_length_chars: encryptedEmbedForStorage.text_length_chars,
          is_private: encryptedEmbedForStorage.is_private,
          is_shared: encryptedEmbedForStorage.is_shared,
          created_at: encryptedEmbedForStorage.createdAt ? Math.floor(encryptedEmbedForStorage.createdAt / 1000) : nowSecs,
          updated_at: nowSecs,
        });
        
        console.debug('[TravelConnectionEmbedFullscreen] Sent updated embed to server:', embedId);
      } catch (sendError) {
        // Non-fatal — embed is stored locally, will sync on next connection
        console.warn('[TravelConnectionEmbedFullscreen] Failed to send updated embed to server:', sendError);
      }
    } catch (error) {
      // Non-blocking — the booking button still works, just won't survive close/reopen
      console.warn('[TravelConnectionEmbedFullscreen] Failed to persist booking URL in embed:', error);
    }
  }
  
  // ---------------------------------------------------------------------------
  // Share connection embed
  // ---------------------------------------------------------------------------
  
  /**
   * Share is handled by UnifiedEmbedFullscreen's built-in share handler
   * which uses currentEmbedId, appId, and skillId to construct the embed
   * share context and properly opens the settings panel (including on mobile).
   */
  
  // ---------------------------------------------------------------------------
  // Copy flight details to clipboard
  // ---------------------------------------------------------------------------
  
  /**
   * Build a plain-text summary of the connection and copy it to the clipboard.
   * Format:
   *   Route · Trip type · Price
   *   Carriers
   *   
   *   [Leg label:] Origin → Destination
   *   Date · Duration · Stops
   *     HH:MM  Departure Station
   *     Carrier · Flight# · Duration
   *     HH:MM  Arrival Station
   *   
   *   Booking info (seats, deadline)
   */
  async function handleCopy() {
    try {
      const lines: string[] = [];
      
      // Header: route, trip type, price
      const headerParts = [routeDisplay, tripTypeLabel, formattedPrice].filter(Boolean);
      if (headerParts.length) lines.push(headerParts.join(' · '));
      
      // Carriers
      if (connection.carriers && connection.carriers.length > 0) {
        lines.push(connection.carriers.join(', '));
      }
      
      lines.push('');
      
      // Legs
      if (connection.legs && connection.legs.length > 0) {
        for (const leg of connection.legs) {
          const legLabel = getLegLabel(leg, connection.legs.length);
          const legHeader = legLabel
            ? `${legLabel}: ${leg.origin} → ${leg.destination}`
            : `${leg.origin} → ${leg.destination}`;
          lines.push(legHeader);
          
          const legMeta = [
            formatDate(leg.departure),
            leg.duration,
            getStopsLabel(leg.stops),
          ].filter(Boolean).join(' · ');
          if (legMeta) lines.push(legMeta);
          
          lines.push('');
          
          for (const seg of leg.segments) {
            lines.push(`  ${formatTime(seg.departure_time)}  ${seg.departure_station}`);
            const segInfo = [seg.carrier, seg.number, seg.duration].filter(Boolean).join(' · ');
            if (segInfo) lines.push(`  ${segInfo}`);
            lines.push(`  ${formatTime(seg.arrival_time)}  ${seg.arrival_station}`);
            lines.push('');
          }
        }
      } else {
        // Summary-only fallback
        if (connection.departure && connection.arrival) {
          lines.push(`${formatTime(connection.departure)} → ${formatTime(connection.arrival)}`);
        }
        if (connection.duration) lines.push(connection.duration);
        if (connection.stops !== undefined) lines.push(getStopsLabel(connection.stops));
        lines.push('');
      }
      
      // Booking info
      if (connection.bookable_seats !== undefined && connection.bookable_seats > 0) {
        lines.push(`${connection.bookable_seats} seat(s) remaining`);
      }
      if (connection.last_ticketing_date) {
        lines.push(`Book by ${connection.last_ticketing_date}`);
      }
      
      const textContent = lines.join('\n').trim();
      const clipResult = await copyToClipboard(textContent);
      if (!clipResult.success) throw new Error(clipResult.error || 'Copy failed');
      console.debug('[TravelConnectionEmbedFullscreen] Copied flight details to clipboard');
      notificationStore.success($text('embeds.copied_to_clipboard'));
    } catch (error) {
      console.error('[TravelConnectionEmbedFullscreen] Failed to copy flight details:', error);
      notificationStore.error($text('embeds.copy_failed'));
    }
  }
  
  // ---------------------------------------------------------------------------
  // PDF Download (jspdf)
  // ---------------------------------------------------------------------------
  
  /**
   * Generate and download a PDF itinerary for this connection.
   * Uses jspdf (dynamically imported) to create a clean A4 document
   * with route, price, date, leg details, and carrier info.
   */
  async function _handleDownload() {
    try {
      const { jsPDF } = await import('jspdf');
      const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });
      const pageWidth = doc.internal.pageSize.getWidth();
      let y = 20;
      
      // --- Title ---
      doc.setFontSize(20);
      doc.setFont('helvetica', 'bold');
      const titleText = routeDisplay || 'Flight Itinerary';
      doc.text(titleText, pageWidth / 2, y, { align: 'center' });
      y += 10;
      
      // --- Trip type and price ---
      doc.setFontSize(12);
      doc.setFont('helvetica', 'normal');
      const subTitle = [tripTypeLabel, formattedPrice].filter(Boolean).join(' · ');
      if (subTitle) {
        doc.text(subTitle, pageWidth / 2, y, { align: 'center' });
        y += 8;
      }
      
      // --- Carriers ---
      if (connection.carriers && connection.carriers.length > 0) {
        doc.setFontSize(10);
        doc.setTextColor(100, 100, 100);
        doc.text(connection.carriers.join(', '), pageWidth / 2, y, { align: 'center' });
        doc.setTextColor(0, 0, 0);
        y += 12;
      } else {
        y += 4;
      }
      
      // --- Separator line ---
      doc.setDrawColor(200, 200, 200);
      doc.setLineWidth(0.3);
      doc.line(20, y, pageWidth - 20, y);
      y += 10;
      
      // --- Legs ---
      if (connection.legs && connection.legs.length > 0) {
        for (const leg of connection.legs) {
          // Check if we need a new page
          if (y > 250) {
            doc.addPage();
            y = 20;
          }
          
          // Leg header
          const legLabel = getLegLabel(leg, connection.legs?.length ?? 0);
          doc.setFontSize(13);
          doc.setFont('helvetica', 'bold');
          const legHeaderParts = [
            legLabel ? `${legLabel}:` : '',
            `${leg.origin} → ${leg.destination}`,
          ].filter(Boolean);
          doc.text(legHeaderParts.join(' '), 20, y);
          y += 6;
          
          // Leg meta
          doc.setFontSize(9);
          doc.setFont('helvetica', 'normal');
          doc.setTextColor(100, 100, 100);
          const legMeta = [
            formatDate(leg.departure),
            leg.duration,
            getStopsLabel(leg.stops),
          ].filter(Boolean).join(' · ');
          doc.text(legMeta, 20, y);
          doc.setTextColor(0, 0, 0);
          y += 8;
          
          // Segments
          for (const seg of leg.segments) {
            if (y > 265) {
              doc.addPage();
              y = 20;
            }
            
            // Departure
            doc.setFontSize(11);
            doc.setFont('helvetica', 'bold');
            doc.text(formatTime(seg.departure_time), 25, y);
            doc.setFont('helvetica', 'normal');
            doc.text(seg.departure_station, 50, y);
            y += 5;
            
            // Flight info
            doc.setFontSize(9);
            doc.setTextColor(80, 80, 80);
            const flightInfo = [seg.carrier, seg.number, seg.duration].filter(Boolean).join(' · ');
            doc.text(flightInfo, 30, y);
            doc.setTextColor(0, 0, 0);
            y += 5;
            
            // Arrival
            doc.setFontSize(11);
            doc.setFont('helvetica', 'bold');
            doc.text(formatTime(seg.arrival_time), 25, y);
            doc.setFont('helvetica', 'normal');
            doc.text(seg.arrival_station, 50, y);
            y += 8;
          }
          
          y += 6;
        }
      }
      
      // --- Booking info footer ---
      if (y > 260) {
        doc.addPage();
        y = 20;
      }
      
      doc.setDrawColor(200, 200, 200);
      doc.setLineWidth(0.3);
      doc.line(20, y, pageWidth - 20, y);
      y += 8;
      
      doc.setFontSize(9);
      doc.setTextColor(100, 100, 100);
      
      if (connection.bookable_seats != null && connection.bookable_seats > 0) {
        doc.text(`${connection.bookable_seats} seat(s) remaining`, 20, y);
        y += 5;
      }
      if (connection.last_ticketing_date) {
        doc.text(`Book by ${connection.last_ticketing_date}`, 20, y);
        y += 5;
      }
      
      // Footer
      y += 5;
      doc.setFontSize(8);
      doc.text('Generated by OpenMates', pageWidth / 2, y, { align: 'center' });
      
      // Download
      const originCode = connection.legs?.[0]?.segments?.[0]?.departure_station || 'flight';
      const destCode = connection.legs?.[0]?.segments?.at(-1)?.arrival_station || 'itinerary';
      const dateStr = connection.departure?.slice(0, 10) || 'unknown';
      doc.save(`${originCode}-${destCode}_${dateStr}.pdf`);
    } catch (err) {
      console.error('[TravelConnectionEmbedFullscreen] PDF download failed:', err);
    }
  }
  
  // ---------------------------------------------------------------------------
  // Route map (via EntryWithMapTemplate's onMapReady callback)
  // ---------------------------------------------------------------------------

  /** Leaflet module reference (set by onMapReady) */
  let L: typeof import('leaflet') | null = null;

  /** Leaflet map instance (set by onMapReady) */
  let map: LeafletMap | null = null;
  
  /**
   * Collect all unique airport coordinates from the connection legs/segments.
   * Returns an ordered array of waypoints: [(lat, lng, iataCode), ...]
   * following the flight path from first departure to final arrival.
   */
  let routeWaypoints = $derived.by(() => {
    const conn = connection as MaybeConnection;
    if (!conn?.legs || conn.legs.length === 0) return [];
    
    const waypoints: Array<{ lat: number; lng: number; code: string }> = [];
    const seen = new Set<string>();
    
    for (const leg of conn.legs) {
      if (!leg.segments) continue;
      for (const seg of leg.segments) {
        // Add departure airport
        if (
          seg.departure_latitude != null &&
          seg.departure_longitude != null &&
          seg.departure_station &&
          !seen.has(seg.departure_station)
        ) {
          waypoints.push({
            lat: seg.departure_latitude,
            lng: seg.departure_longitude,
            code: seg.departure_station,
          });
          seen.add(seg.departure_station);
        }
        // Add arrival airport
        if (
          seg.arrival_latitude != null &&
          seg.arrival_longitude != null &&
          seg.arrival_station &&
          !seen.has(seg.arrival_station)
        ) {
          waypoints.push({
            lat: seg.arrival_latitude,
            lng: seg.arrival_longitude,
            code: seg.arrival_station,
          });
          seen.add(seg.arrival_station);
        }
      }
    }
    return waypoints;
  });
  
  /**
   * Compute intermediate points along a great-circle arc between two coordinates.
   * Uses the spherical interpolation (slerp) formula to produce a smooth curved
   * line that follows the Earth's surface — essential for long-distance flights
   * where a straight line on a Mercator projection looks incorrect.
   *
   * @param lat1 Start latitude (degrees)
   * @param lng1 Start longitude (degrees)
   * @param lat2 End latitude (degrees)
   * @param lng2 End longitude (degrees)
   * @param numPoints Number of intermediate points (more = smoother curve)
   * @returns Array of [lat, lng] tuples along the arc
   */
  function greatCircleArc(
    lat1: number, lng1: number,
    lat2: number, lng2: number,
    numPoints: number = 50,
  ): [number, number][] {
    const toRad = (d: number) => (d * Math.PI) / 180;
    const toDeg = (r: number) => (r * 180) / Math.PI;

    const φ1 = toRad(lat1), λ1 = toRad(lng1);
    const φ2 = toRad(lat2), λ2 = toRad(lng2);

    // Central angle via Haversine
    const dφ = φ2 - φ1;
    const dλ = λ2 - λ1;
    const a = Math.sin(dφ / 2) ** 2 + Math.cos(φ1) * Math.cos(φ2) * Math.sin(dλ / 2) ** 2;
    const d = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));

    // If the two points are very close, a straight line is fine
    if (d < 0.0001) {
      return [[lat1, lng1], [lat2, lng2]];
    }

    const points: [number, number][] = [];
    for (let i = 0; i <= numPoints; i++) {
      const f = i / numPoints;
      const A = Math.sin((1 - f) * d) / Math.sin(d);
      const B = Math.sin(f * d) / Math.sin(d);
      const x = A * Math.cos(φ1) * Math.cos(λ1) + B * Math.cos(φ2) * Math.cos(λ2);
      const y = A * Math.cos(φ1) * Math.sin(λ1) + B * Math.cos(φ2) * Math.sin(λ2);
      const z = A * Math.sin(φ1) + B * Math.sin(φ2);
      const lat = toDeg(Math.atan2(z, Math.sqrt(x * x + y * y)));
      const lng = toDeg(Math.atan2(y, x));
      points.push([lat, lng]);
    }
    return points;
  }

  /**
   * onMapReady callback for EntryWithMapTemplate.
   * Called with the raw Leaflet map instance and L module when the map is mounted.
   * Draws flight arcs, FR24 tracks, and airport markers.
   */
  function handleMapReady(mapInstance: unknown, leafletModule: unknown) {
    map = mapInstance as LeafletMap;
    L = leafletModule as typeof import('leaflet');

    if (!L || !map || routeWaypoints.length < 2) return;

    try {
      const airportIcon = L.divIcon({
        className: 'travel-route-marker',
        html: '<div class="marker-dot"></div>',
        iconSize: [16, 16],
        iconAnchor: [8, 8],
      });

      for (const wp of routeWaypoints) {
        L.marker([wp.lat, wp.lng], { icon: airportIcon })
          .addTo(map)
          .bindPopup(wp.code);
      }

      drawFlightPath();
    } catch (err) {
      console.error('[TravelConnectionEmbedFullscreen] Failed to render map overlays:', err);
    }
  }

  function drawFlightPath() {
    if (!L || !map) return;

    let boundsLatLngs: import('leaflet').LatLng[];

    if (resolvedFlightTrack && resolvedFlightTrack.tracks.length >= 2) {
      const trackLatLngs = resolvedFlightTrack.tracks.map(p => L.latLng(p.lat, p.lon));
      L.polyline(trackLatLngs, {
        color: 'var(--color-primary, #6366f1)',
        weight: 2.5,
        opacity: 0.85,
      }).addTo(map);
      boundsLatLngs = trackLatLngs;
    } else {
      for (let i = 0; i < routeWaypoints.length - 1; i++) {
        const wp1 = routeWaypoints[i];
        const wp2 = routeWaypoints[i + 1];
        const arcPoints = greatCircleArc(wp1.lat, wp1.lng, wp2.lat, wp2.lng, 60);
        const arcLatLngs = arcPoints.map(([lat, lng]) => L.latLng(lat, lng));
        L.polyline(arcLatLngs, {
          color: 'var(--color-primary, #6366f1)',
          weight: 2.5,
          opacity: 0.7,
        }).addTo(map);
      }
      boundsLatLngs = routeWaypoints.map(wp => L.latLng(wp.lat, wp.lng));
    }

    const bounds = L.latLngBounds(boundsLatLngs);
    map.fitBounds(bounds, { padding: [40, 40] });
  }

  // Redraw flight path when FR24 track data loads after map is already mounted
  $effect(() => {
    if (resolvedFlightTrack && map && L) {
      drawFlightPath();
    }
  });

  // Cleanup on destroy
  onDestroy(() => {
    map = null;
    L = null;
  });
</script>

{#if connection}
<EntryWithMapTemplate
  appId="travel"
  skillId="connection"
  {onClose}
  onCopy={handleCopy}
  skillIconName="travel"
  embedHeaderTitle={priceHeader}
  embedHeaderSubtitle={headerSubtitle}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {mapCenter}
  mapZoom={4}
  onMapReady={handleMapReady}
>
  {#snippet embedHeaderCta()}
    {#if bookingState === 'loaded' && resolvedBookingUrl}
      <button class="cta-button" onclick={handleOpenBookingUrl} data-testid="booking-cta">
        {$text('embeds.book_on').replace('{provider}', resolvedBookingProvider || primaryCarrier)}
      </button>
    {:else if bookingState === 'loading'}
      <div class="cta-button cta-loading">
        <span class="cta-spinner"></span>
      </div>
    {:else if bookingState === 'error'}
      <button class="cta-button cta-fallback" onclick={handleOpenGoogleFlights}>
        {$text('embeds.open_google_flights')}
      </button>
    {:else if connection.booking_token && bookingState === 'idle'}
      <button class="cta-button" onclick={handleLoadBookingLink} data-testid="booking-cta">
        {$text('embeds.get_booking_link')}
      </button>
    {/if}
  {/snippet}

  {#snippet detailContent(_childContext)}
    <div class="flight-card" data-testid="flight-details-card">
      {#if routeHeaderWithFlags}
        <div class="route-header-pill" data-testid="route-header">{routeHeaderWithFlags}</div>
      {/if}

      {#if travelClassLabel}
        <div class="travel-class-label">{travelClassLabel}</div>
      {/if}

      {#if startAirportName}
        <div class="start-airport">
          <span class="start-label">Start:</span>
          <span>{startAirportName}</span>
        </div>
      {/if}

      {#if connection.legs && connection.legs.length > 0}
        {#each connection.legs as leg}
          {#each leg.segments as segment, segIdx}
            <div class="segment-card" data-testid="segment-card">
              <div class="segment-left">
                <div class="time-badge" class:daytime={segment.departure_is_daytime === true} class:nighttime={segment.departure_is_daytime !== true}>
                  <span class="time-icon">{segment.departure_is_daytime ? '☀' : '🌙'}</span>
                  <span class="time-text">{formatTime(segment.departure_time)}</span>
                </div>
                <div class="segment-duration-text">{segment.duration}</div>
                <div class="time-badge" class:daytime={segment.arrival_is_daytime === true} class:nighttime={segment.arrival_is_daytime !== true}>
                  <span class="time-icon">{segment.arrival_is_daytime ? '☀' : '🌙'}</span>
                  <span class="time-text">{formatTime(segment.arrival_time)}</span>
                </div>
              </div>

              <div class="segment-center">
                <div class="segment-airport-code" data-testid="departure-code">
                  {#if segment.departure_country_code}{countryCodeToFlag(segment.departure_country_code)} {/if}{segment.departure_station}
                </div>
                <div class="segment-carrier-row">
                  {#if segment.airline_logo}
                    <img class="segment-airline-logo" src={proxyImage(segment.airline_logo, MAX_WIDTH_AIRLINE_LOGO_FULLSCREEN)} alt={segment.carrier} />
                  {/if}
                  <div class="segment-carrier-info">
                    <span class="carrier-flight">{segment.carrier}{segment.number ? ` | ${segment.number}` : ''}</span>
                    {#if segment.airplane}
                      <span class="carrier-aircraft">via {segment.airplane}</span>
                    {/if}
                  </div>
                </div>
                <div class="segment-airport-code" data-testid="arrival-code">
                  {#if segment.arrival_country_code}{countryCodeToFlag(segment.arrival_country_code)} {/if}{segment.arrival_station}
                </div>
              </div>
            </div>

            {#if segIdx < leg.segments.length - 1}
              {@const layover = leg.layovers?.[segIdx]}
              <div class="layover-section" data-testid="layover-section">
                {#if layover?.overnight}
                  <div class="layover-overnight-badge">
                    <span class="time-icon">🌙</span>
                    <span>Overnight</span>
                  </div>
                {/if}
                <div class="layover-duration-text">
                  {layover?.duration || 'Connection'}
                </div>
                <div class="layover-airport-text">
                  Layover in{#if layover?.airport}<br/>{layover.airport}{/if}
                </div>
              </div>
            {/if}
          {/each}
        {/each}
      {:else}
        <div class="summary-fallback">
          {#if connection.departure && connection.arrival}
            <span>{formatTime(connection.departure)} → {formatTime(connection.arrival)}</span>
          {/if}
          {#if connection.duration}
            <span>{connection.duration}</span>
          {/if}
        </div>
      {/if}

      {#if flightTrackState === 'loaded' && resolvedFlightTrack}
        <div class="fr24-attribution">
          Track: <a href="https://www.flightradar24.com" target="_blank" rel="noopener noreferrer">Flightradar24</a>
        </div>
      {/if}
    </div>
  {/snippet}

  {#snippet ctaContent()}
    <div class="booking-info">
      {#if connection.bookable_seats !== undefined && connection.bookable_seats > 0}
        <div class="booking-item" class:warning={connection.bookable_seats <= 4}>
          {connection.bookable_seats} {connection.bookable_seats === 1 ? 'seat' : 'seats'} remaining
        </div>
      {/if}
      {#if connection.last_ticketing_date}
        <div class="booking-item">
          Book by {connection.last_ticketing_date}
        </div>
      {/if}
      {#if connection.co2_kg != null}
        <div class="co2-badge" class:co2-good={connection.co2_difference_percent != null && connection.co2_difference_percent < 0}>
          {connection.co2_kg} kg CO2
          {#if connection.co2_difference_percent != null}
            ({connection.co2_difference_percent > 0 ? '+' : ''}{connection.co2_difference_percent}% vs typical)
          {/if}
        </div>
      {/if}
    </div>
  {/snippet}
</EntryWithMapTemplate>
{/if}

<style>
  .cta-button {
    background-color: var(--color-button-primary);
    color: white;
    border: none;
    border-radius: 20px;
    padding: 12px 30px;
    font-family: 'Lexend Deca', sans-serif;
    font-size: 0.938rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease-in-out;
    filter: drop-shadow(0px 4px 4px rgba(0, 0, 0, 0.25));
    margin-top: 16px;
    min-width: 200px;
    height: 46px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .cta-button:hover { background-color: var(--color-button-primary-hover); scale: 1.02; }
  .cta-button:active { background-color: var(--color-button-primary-pressed); scale: 0.98; filter: none; }
  .cta-fallback { background-color: var(--color-grey-70, #555); }
  .cta-fallback:hover { background-color: var(--color-grey-80, #444); }
  .cta-loading { background-color: var(--color-grey-30, #e0e0e0); cursor: default; filter: none; }
  .cta-loading:hover { background-color: var(--color-grey-30, #e0e0e0); scale: 1; }
  .cta-spinner { width: 20px; height: 20px; border: 2.5px solid var(--color-grey-50, #999); border-top-color: var(--color-grey-80, #444); border-radius: 50%; animation: cta-spin 0.8s linear infinite; }
  @keyframes cta-spin { to { transform: rotate(360deg); } }

  .flight-card { display: flex; flex-direction: column; gap: 12px; }
  .route-header-pill { background: var(--color-grey-10); border-radius: 11px; padding: 8px 14px; font-size: 1rem; font-weight: 700; color: var(--color-font-primary); text-align: center; }
  .travel-class-label { font-size: 1rem; font-weight: 700; color: var(--color-font-primary); text-align: center; }
  .start-airport { font-size: 0.875rem; font-weight: 700; color: var(--color-grey-50); text-align: center; }

  .segment-card { display: flex; gap: 12px; background: var(--color-grey-10); border-radius: 15px; padding: 14px; }
  .segment-left { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; flex-shrink: 0; min-width: 96px; }
  .time-badge { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 58px; font-size: 0.875rem; font-weight: 700; color: white; white-space: nowrap; }
  .time-badge.nighttime { background: linear-gradient(to right, #365dad, #1745a1); }
  .time-badge.daytime { background: linear-gradient(to right, #f5bb12, #e79600); }
  .time-icon { font-size: 0.75rem; line-height: 1; }
  .time-text { line-height: 1; }
  .segment-duration-text { font-size: 1.25rem; font-weight: 700; background: linear-gradient(164deg, rgb(72, 103, 205) 9%, rgb(90, 133, 235) 90%); background-clip: text; -webkit-background-clip: text; -webkit-text-fill-color: transparent; padding: 2px 0; }

  .segment-center { display: flex; flex-direction: column; gap: 8px; flex: 1; min-width: 0; justify-content: space-between; }
  .segment-airport-code { font-size: 1rem; font-weight: 700; color: var(--color-font-primary); }
  .segment-carrier-row { display: flex; align-items: center; gap: 8px; }
  .segment-airline-logo { width: 28px; height: 28px; border-radius: 50%; object-fit: cover; background: var(--color-grey-10); border: 1.5px solid var(--color-grey-20); flex-shrink: 0; }
  .segment-carrier-info { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
  .carrier-flight { font-size: 0.875rem; font-weight: 700; color: var(--color-font-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .carrier-aircraft { font-size: 0.875rem; font-weight: 700; color: var(--color-font-primary); }

  .layover-section { display: flex; flex-direction: column; gap: 4px; padding: 8px 14px; }
  .layover-overnight-badge { display: inline-flex; align-items: center; gap: 4px; padding: 4px 12px; border-radius: 58px; background: linear-gradient(to right, #365dad, #1745a1); color: white; font-size: 1rem; font-weight: 700; width: fit-content; }
  .layover-duration-text { font-size: 1.25rem; font-weight: 700; background: linear-gradient(164deg, rgb(72, 103, 205) 9%, rgb(90, 133, 235) 90%); background-clip: text; -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  .layover-airport-text { font-size: 0.875rem; font-weight: 700; color: var(--color-font-primary); }

  .summary-fallback { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 16px 0; font-size: 1rem; color: var(--color-font-primary); font-weight: 600; }
  .fr24-attribution { font-size: 0.7rem; color: var(--color-grey-50); text-align: right; margin-top: 4px; }
  .fr24-attribution a { color: inherit; text-decoration: underline; text-underline-offset: 2px; }
  .booking-info { display: flex; flex-direction: column; gap: 6px; }
  .booking-info:empty { display: none; }
  .booking-item { font-size: 0.813rem; color: var(--color-grey-60); }
  .booking-item.warning { color: var(--color-warning, #f59e0b); font-weight: 600; }
  .co2-badge { font-size: 0.75rem; color: var(--color-grey-50); margin-top: 4px; }
  .co2-badge.co2-good { color: var(--color-success, #22c55e); }
  :global(.travel-route-marker) { background: transparent !important; border: none !important; }
  :global(.travel-route-marker .marker-dot) { width: 12px; height: 12px; border-radius: 50%; background-color: var(--color-primary, #6366f1); border: 2px solid white; box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3); margin: 2px; }
</style>
