<!--
  frontend/packages/ui/src/components/embeds/travel/TravelConnectionEmbedFullscreen.svelte
  
  Fullscreen detail view for a single travel connection (child embed).
  Uses UnifiedEmbedFullscreen as base and shows leg-by-leg, segment-by-segment detail.
  
  Layout:
  - Header: Price + route + trip type
  - For each leg:
    - Leg header (e.g., "Outbound: Munich → London")
    - Timeline of segments with departure/arrival times, stations, carrier, flight number
  - Footer: Booking info (seats remaining, last ticketing date)
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { onDestroy } from 'svelte';
  import { notificationStore } from '../../../stores/notificationStore';
  import { getApiEndpoint } from '../../../config/api';
  import { embedStore } from '../../../services/embedStore';
  import 'leaflet/dist/leaflet.css';
  import type { Map as LeafletMap, TileLayer } from 'leaflet';
  
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
    /** Rich metadata from Google Flights */
    airline_logo?: string;
    co2_kg?: number;
    co2_typical_kg?: number;
    co2_difference_percent?: number;
  }
  
  interface Props {
    /** Connection data from parent */
    connection: ConnectionData;
    /** Close handler */
    onClose: () => void;
    /** Embed ID for reference */
    embedId?: string;
  }
  
  let {
    connection,
    onClose,
    embedId,
  }: Props = $props();
  
  // Format price
  let formattedPrice = $derived.by(() => {
    if (!connection.total_price) return '';
    const num = parseFloat(connection.total_price);
    if (isNaN(num)) return `${connection.currency || 'EUR'} ${connection.total_price}`;
    return `${connection.currency || 'EUR'} ${num.toFixed(num % 1 === 0 ? 0 : 2)}`;
  });
  
  // Route summary
  let routeDisplay = $derived.by(() => {
    if (connection.origin && connection.destination) {
      return `${connection.origin} → ${connection.destination}`;
    }
    return '';
  });
  
  // Trip type label
  let tripTypeLabel = $derived.by(() => {
    switch (connection.trip_type) {
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
  let resolvedBookingUrl = $state(connection.booking_url || '');
  let resolvedBookingProvider = $state(connection.booking_provider || '');
  let bookingState = $state<BookingState>(connection.booking_url ? 'loaded' : 'idle');
  
  // Primary carrier name (for display when provider not yet known)
  let primaryCarrier = $derived(connection.carriers?.[0] || '');
  
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
          $text('embeds.booking_link_failed') || 'Could not load booking link. Try searching on Google Flights instead.'
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
          $text('embeds.booking_link_failed') || 'Could not load booking link. Try searching on Google Flights instead.'
        );
      }
    } catch (err) {
      console.error('Booking link lookup failed:', err);
      bookingState = 'error';
      notificationStore.error(
        $text('embeds.booking_link_failed') || 'Could not load booking link. Try searching on Google Flights instead.'
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
      await navigator.clipboard.writeText(textContent);
      console.debug('[TravelConnectionEmbedFullscreen] Copied flight details to clipboard');
      notificationStore.success($text('embeds.copied_to_clipboard') || 'Copied to clipboard');
    } catch (error) {
      console.error('[TravelConnectionEmbedFullscreen] Failed to copy flight details:', error);
      notificationStore.error($text('embeds.copy_failed') || 'Failed to copy to clipboard');
    }
  }
  
  // Skill name for bottom bar
  let skillName = $derived($text('app_skills.travel.search_connections') || 'Search');
  
  // ---------------------------------------------------------------------------
  // PDF Download (jspdf)
  // ---------------------------------------------------------------------------
  
  /**
   * Generate and download a PDF itinerary for this connection.
   * Uses jspdf (dynamically imported) to create a clean A4 document
   * with route, price, date, leg details, and carrier info.
   */
  async function handleDownload() {
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
  // Route map (Leaflet / OpenStreetMap)
  // ---------------------------------------------------------------------------
  
  /** Reference to the map container DOM element */
  let mapContainer: HTMLDivElement | undefined = $state(undefined);
  
  /** Leaflet module reference (dynamically imported) */
  let L: typeof import('leaflet') | null = null;
  
  /** Leaflet map instance */
  let map: LeafletMap | null = null;
  
  /** Whether the map has been initialized */
  let mapInitialized = $state(false);
  
  /** Detect dark mode from CSS custom property or media query */
  let isDarkMode = $derived.by(() => {
    if (typeof window === 'undefined') return false;
    const cssVar = getComputedStyle(document.documentElement).getPropertyValue('--is-dark-mode').trim();
    if (cssVar === '1' || cssVar === 'true') return true;
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
  });
  
  /**
   * Collect all unique airport coordinates from the connection legs/segments.
   * Returns an ordered array of waypoints: [(lat, lng, iataCode), ...]
   * following the flight path from first departure to final arrival.
   */
  let routeWaypoints = $derived.by(() => {
    if (!connection.legs || connection.legs.length === 0) return [];
    
    const waypoints: Array<{ lat: number; lng: number; code: string }> = [];
    const seen = new Set<string>();
    
    for (const leg of connection.legs) {
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
   * Initialize the Leaflet map when the container is mounted and waypoints are available.
   */
  async function initializeMap() {
    if (!mapContainer || routeWaypoints.length < 2 || mapInitialized) return;
    
    try {
      L = await import('leaflet');
      
      // Create map with default view
      const firstWp = routeWaypoints[0];
      map = L.map(mapContainer, {
        center: [firstWp.lat, firstWp.lng],
        zoom: 5,
        zoomControl: true,
        scrollWheelZoom: false,
        attributionControl: true,
      });
      
      // Add OSM tile layer
      const tileLayer: TileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        className: isDarkMode ? 'dark-tiles' : '',
      }).addTo(map);
      
      // Custom airport marker icon
      const airportIcon = L.divIcon({
        className: 'travel-route-marker',
        html: '<div class="marker-dot"></div>',
        iconSize: [16, 16],
        iconAnchor: [8, 8],
      });
      
      // Add markers for each waypoint
      for (const wp of routeWaypoints) {
        L.marker([wp.lat, wp.lng], { icon: airportIcon })
          .addTo(map)
          .bindPopup(wp.code);
      }
      
      // Draw geodesic (great-circle) arcs between consecutive waypoints.
      // This produces the curved flight route lines that follow the
      // Earth's surface, looking correct even for long-haul flights.
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
      
      // Fit bounds to show all waypoints with padding
      const waypointLatLngs = routeWaypoints.map(wp => L.latLng(wp.lat, wp.lng));
      const bounds = L.latLngBounds(waypointLatLngs);
      map.fitBounds(bounds, { padding: [40, 40] });
      
      // Listen for dark mode changes
      const darkModeQuery = window.matchMedia('(prefers-color-scheme: dark)');
      const updateDarkMode = () => {
        if (tileLayer && map) {
          const container = tileLayer.getContainer();
          if (container) {
            if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
              container.classList.add('dark-tiles');
            } else {
              container.classList.remove('dark-tiles');
            }
          }
        }
      };
      darkModeQuery.addEventListener('change', updateDarkMode);
      
      mapInitialized = true;
    } catch (err) {
      console.error('[TravelConnectionEmbedFullscreen] Failed to initialize map:', err);
    }
  }
  
  // Initialize map when container is ready and waypoints are available
  $effect(() => {
    if (mapContainer && routeWaypoints.length >= 2 && !mapInitialized) {
      initializeMap();
    }
  });
  
  // Cleanup on destroy
  onDestroy(() => {
    if (map) {
      map.remove();
      map = null;
    }
  });
</script>

<UnifiedEmbedFullscreen
  appId="travel"
  skillId="connection"
  title=""
  {onClose}
  onCopy={handleCopy}
  onDownload={handleDownload}
  skillIconName="search"
  status="finished"
  {skillName}
  showStatus={false}
  currentEmbedId={embedId}
>
  {#snippet content()}
    <div class="connection-fullscreen">
      <!-- Header: Price + Route + Trip Type -->
      <div class="connection-header">
        {#if formattedPrice}
          <div class="price">{formattedPrice}</div>
        {/if}
        {#if routeDisplay}
          <div class="route">{routeDisplay}</div>
        {/if}
        <div class="trip-type-badge">{tripTypeLabel}</div>
        {#if connection.carriers && connection.carriers.length > 0}
          <div class="carriers">{connection.carriers.join(', ')}</div>
        {/if}
        
        <!-- CO2 emissions -->
        {#if connection.co2_kg != null}
          <div class="co2-info" class:co2-good={connection.co2_difference_percent != null && connection.co2_difference_percent < 0} class:co2-bad={connection.co2_difference_percent != null && connection.co2_difference_percent > 20}>
            <span class="co2-value">{connection.co2_kg} kg CO2</span>
            {#if connection.co2_difference_percent != null}
              <span class="co2-diff">
                {connection.co2_difference_percent > 0 ? '+' : ''}{connection.co2_difference_percent}% vs typical
              </span>
            {/if}
          </div>
        {/if}
        
        <!-- Booking CTA: three-state button (idle -> loading -> loaded) -->
        <!-- All three states render in the same spot with identical dimensions -->
        {#if bookingState === 'loaded' && resolvedBookingUrl}
          <!-- State: loaded — direct booking link available -->
          <button class="cta-button" onclick={handleOpenBookingUrl}>
            {($text('embeds.book_on') || 'Book on {provider}').replace('{provider}', resolvedBookingProvider || primaryCarrier)}
          </button>
        {:else if bookingState === 'loading'}
          <!-- State: loading — spinner replaces the button in the same spot -->
          <div class="cta-button cta-loading">
            <span class="cta-spinner"></span>
          </div>
        {:else if bookingState === 'error'}
          <!-- State: error — fallback to Google Flights search -->
          <button class="cta-button cta-fallback" onclick={handleOpenGoogleFlights}>
            {$text('embeds.open_google_flights') || 'Open Google Flights'}
          </button>
        {:else if connection.booking_token && bookingState === 'idle'}
          <!-- State: idle — regular primary button to fetch the booking link -->
          <button class="cta-button" onclick={handleLoadBookingLink}>
            {$text('embeds.get_booking_link') || 'Get booking link'}
          </button>
        {/if}
      </div>
      
      <!-- Route Map (OpenStreetMap via Leaflet) -->
      {#if routeWaypoints.length >= 2}
        <div class="route-map-container" bind:this={mapContainer}></div>
      {/if}
      
      <!-- Legs Timeline -->
      {#if connection.legs && connection.legs.length > 0}
        <div class="legs-container">
          {#each connection.legs as leg}
            {@const legLabel = getLegLabel(leg, connection.legs?.length ?? 0)}
            <div class="leg">
              <!-- Leg Header -->
              <div class="leg-header">
                {#if legLabel}
                  <span class="leg-label">{legLabel}:</span>
                {/if}
                <span class="leg-route">{leg.origin} → {leg.destination}</span>
                <span class="leg-meta">
                  {formatDate(leg.departure)} · {leg.duration} · {getStopsLabel(leg.stops)}
                </span>
              </div>
              
              <!-- Segments Timeline -->
              <div class="segments">
                {#each leg.segments as segment, segIdx}
                  <div class="segment">
                    <!-- Departure -->
                    <div class="segment-endpoint">
                      <div class="segment-time">{formatTime(segment.departure_time)}</div>
                      <div class="timeline-dot"></div>
                      <div class="segment-station">{segment.departure_station}</div>
                    </div>
                    
                    <!-- Flight/train info bar -->
                    <div class="segment-info">
                      <div class="timeline-line"></div>
                      <div class="segment-details-block">
                        <div class="segment-details">
                          {#if segment.airline_logo}
                            <img class="segment-airline-logo" src={`https://preview.openmates.org/api/v1/image?url=${encodeURIComponent(segment.airline_logo)}&max_width=36`} alt={segment.carrier} />
                          {/if}
                          <span class="carrier-name">{segment.carrier}</span>
                          {#if segment.number}
                            <span class="flight-number">{segment.number}</span>
                          {/if}
                          <span class="segment-duration">{segment.duration}</span>
                        </div>
                        {#if segment.airplane || segment.legroom || segment.travel_class}
                          <div class="segment-meta">
                            {#if segment.airplane}
                              <span>{segment.airplane}</span>
                            {/if}
                            {#if segment.travel_class}
                              <span>{segment.travel_class}</span>
                            {/if}
                            {#if segment.legroom}
                              <span>{segment.legroom}</span>
                            {/if}
                          </div>
                        {/if}
                        {#if segment.often_delayed}
                          <div class="segment-warning">Often delayed by 30+ min</div>
                        {/if}
                      </div>
                    </div>
                    
                    <!-- Arrival -->
                    <div class="segment-endpoint">
                      <div class="segment-time">{formatTime(segment.arrival_time)}</div>
                      <div class="timeline-dot"></div>
                      <div class="segment-station">{segment.arrival_station}</div>
                    </div>
                    
                    <!-- Layover indicator between segments -->
                    {#if segIdx < leg.segments.length - 1}
                      {@const layover = leg.layovers?.[segIdx]}
                      <div class="layover">
                        <div class="layover-line"></div>
                        <div class="layover-info">
                          <span class="layover-label">
                            {#if layover?.duration}
                              {layover.duration} layover
                            {:else}
                              Connection
                            {/if}
                          </span>
                          {#if layover?.airport}
                            <span class="layover-airport">{layover.airport}{layover.airport_code ? ` (${layover.airport_code})` : ''}</span>
                          {/if}
                          {#if layover?.overnight}
                            <span class="layover-overnight">Overnight</span>
                          {/if}
                        </div>
                      </div>
                    {/if}
                  </div>
                {/each}
              </div>
            </div>
          {/each}
        </div>
      {:else}
        <!-- No leg details available - show summary -->
        <div class="summary-only">
          {#if connection.departure && connection.arrival}
            <div class="summary-times">
              <span>{formatTime(connection.departure)}</span>
              <span class="summary-arrow">→</span>
              <span>{formatTime(connection.arrival)}</span>
            </div>
          {/if}
          {#if connection.duration}
            <div class="summary-duration">{connection.duration}</div>
          {/if}
          {#if connection.stops !== undefined}
            <div class="summary-stops">{getStopsLabel(connection.stops)}</div>
          {/if}
        </div>
      {/if}
      
      <!-- Booking Info Footer -->
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
      </div>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     Connection Fullscreen Layout
     =========================================== */
  
  .connection-fullscreen {
    max-width: 600px;
    margin: 60px auto 120px;
    padding: 0 20px;
  }
  
  @container fullscreen (max-width: 500px) {
    .connection-fullscreen {
      margin-top: 70px;
      padding: 0 16px;
    }
  }
  
  /* ===========================================
     Header
     =========================================== */
  
  .connection-header {
    text-align: center;
    margin-bottom: 40px;
  }
  
  .price {
    font-size: 32px;
    font-weight: 700;
    color: var(--color-font-primary);
    line-height: 1.2;
  }
  
  @container fullscreen (max-width: 500px) {
    .price {
      font-size: 28px;
    }
  }
  
  .route {
    font-size: 18px;
    color: var(--color-font-secondary);
    margin-top: 8px;
    line-height: 1.3;
  }
  
  .trip-type-badge {
    display: inline-block;
    margin-top: 12px;
    padding: 4px 12px;
    border-radius: 100px;
    background-color: var(--color-grey-20);
    font-size: 13px;
    font-weight: 500;
    color: var(--color-grey-80);
  }
  
  .carriers {
    font-size: 14px;
    color: var(--color-grey-60);
    margin-top: 8px;
  }
  
  /* CO2 emissions display */
  .co2-info {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-top: 8px;
    padding: 4px 12px;
    border-radius: 100px;
    background-color: var(--color-grey-15, rgba(0, 0, 0, 0.05));
    font-size: 12px;
    color: var(--color-grey-60);
  }
  
  .co2-info.co2-good {
    background-color: rgba(34, 197, 94, 0.1);
    color: var(--color-success, #16a34a);
  }
  
  .co2-info.co2-bad {
    background-color: rgba(239, 68, 68, 0.1);
    color: var(--color-error, #dc2626);
  }
  
  .co2-value {
    font-weight: 500;
  }
  
  .co2-diff {
    opacity: 0.8;
  }
  
  /* CTA Booking Button — uses the standard primary button design.
     All three states (idle, loading, loaded) share this base so they
     occupy the exact same space and swapping between them is seamless. */
  .cta-button {
    background-color: var(--color-button-primary);
    color: white;
    border: none;
    border-radius: 20px;
    padding: 12px 30px;
    font-family: 'Lexend Deca', sans-serif;
    font-size: 15px;
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
  
  .cta-button:hover {
    background-color: var(--color-button-primary-hover);
    scale: 1.02;
  }
  
  .cta-button:active {
    background-color: var(--color-button-primary-pressed);
    scale: 0.98;
    filter: none;
  }
  
  /* Error/fallback state — secondary style to indicate it's a fallback action */
  .cta-fallback {
    background-color: var(--color-grey-70, #555);
  }
  
  .cta-fallback:hover {
    background-color: var(--color-grey-80, #444);
  }
  
  .cta-fallback:active {
    background-color: var(--color-grey-90, #333);
  }
  
  /* Loading state — same dimensions, just shows a spinner */
  .cta-loading {
    background-color: var(--color-grey-30, #e0e0e0);
    cursor: default;
    filter: none;
  }
  
  .cta-loading:hover {
    background-color: var(--color-grey-30, #e0e0e0);
    scale: 1;
  }
  
  /* Spinner animation */
  .cta-spinner {
    width: 20px;
    height: 20px;
    border: 2.5px solid var(--color-grey-50, #999);
    border-top-color: var(--color-grey-80, #444);
    border-radius: 50%;
    animation: cta-spin 0.8s linear infinite;
  }
  
  @keyframes cta-spin {
    to { transform: rotate(360deg); }
  }
  
  /* ===========================================
     Route Map
     =========================================== */
  
  .route-map-container {
    width: 100%;
    height: 200px;
    border-radius: 16px;
    overflow: hidden;
    margin-bottom: 24px;
    background-color: var(--color-grey-10, #f5f5f5);
  }
  
  @container fullscreen (max-width: 500px) {
    .route-map-container {
      height: 160px;
      border-radius: 12px;
    }
  }
  
  /* Leaflet overrides scoped to this component */
  .route-map-container :global(.leaflet-container) {
    width: 100%;
    height: 100%;
    z-index: 0;
    background-color: var(--color-grey-10, #f5f5f5);
  }
  
  .route-map-container :global(.leaflet-control-attribution) {
    font-size: 9px;
    background: rgba(255, 255, 255, 0.6);
  }
  
  .route-map-container :global(.leaflet-control-zoom) {
    border: none;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.15);
  }
  
  .route-map-container :global(.leaflet-control-zoom a) {
    background-color: var(--color-bg-primary, #fff);
    color: var(--color-font-primary, #333);
    border-color: var(--color-grey-20, #e5e5e5);
  }
  
  /* Custom airport marker */
  .route-map-container :global(.travel-route-marker) {
    background: transparent;
    border: none;
  }
  
  .route-map-container :global(.travel-route-marker .marker-dot) {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background-color: var(--color-primary, #6366f1);
    border: 2px solid white;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
    margin: 2px;
  }
  
  /* Dark mode tile inversion */
  .route-map-container :global(.dark-tiles) {
    filter: invert(1) hue-rotate(180deg) brightness(0.95) contrast(0.9);
  }
  
  /* ===========================================
     Legs Container
     =========================================== */
  
  .legs-container {
    display: flex;
    flex-direction: column;
    gap: 32px;
  }
  
  .leg {
    background: var(--color-grey-10, rgba(0, 0, 0, 0.03));
    border-radius: 16px;
    padding: 20px;
  }
  
  .leg-header {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--color-grey-20);
  }
  
  .leg-label {
    font-size: 13px;
    font-weight: 600;
    color: var(--color-primary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  
  .leg-route {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-font-primary);
  }
  
  .leg-meta {
    font-size: 13px;
    color: var(--color-grey-60);
  }
  
  /* ===========================================
     Segments Timeline
     =========================================== */
  
  .segments {
    display: flex;
    flex-direction: column;
  }
  
  .segment {
    display: flex;
    flex-direction: column;
  }
  
  .segment-endpoint {
    display: grid;
    grid-template-columns: 60px 20px 1fr;
    align-items: center;
    gap: 8px;
    min-height: 28px;
  }
  
  .segment-time {
    font-size: 15px;
    font-weight: 600;
    color: var(--color-font-primary);
    text-align: right;
  }
  
  .timeline-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background-color: var(--color-primary);
    justify-self: center;
  }
  
  .segment-station {
    font-size: 14px;
    color: var(--color-font-primary);
    font-weight: 500;
  }
  
  .segment-info {
    display: grid;
    grid-template-columns: 60px 20px 1fr;
    gap: 8px;
    min-height: 40px;
    align-items: center;
  }
  
  /* First column in segment-info grid is the empty time slot area */
  
  .timeline-line {
    width: 2px;
    height: 100%;
    min-height: 32px;
    background-color: var(--color-primary);
    opacity: 0.3;
    justify-self: center;
  }
  
  .segment-details-block {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 4px 0;
  }
  
  .segment-details {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--color-grey-60);
  }
  
  .segment-airline-logo {
    width: 18px;
    height: 18px;
    border-radius: 3px;
    object-fit: contain;
    flex-shrink: 0;
  }
  
  .carrier-name {
    font-weight: 500;
    color: var(--color-grey-80);
  }
  
  .flight-number {
    color: var(--color-grey-50);
  }
  
  .segment-duration {
    color: var(--color-grey-50);
  }
  
  .segment-meta {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    color: var(--color-grey-50);
  }
  
  .segment-meta span:not(:last-child)::after {
    content: '·';
    margin-left: 6px;
    color: var(--color-grey-40);
  }
  
  .segment-warning {
    font-size: 11px;
    color: var(--color-warning, #f59e0b);
    font-weight: 500;
  }
  
  /* Layover between segments */
  .layover {
    display: grid;
    grid-template-columns: 60px 20px 1fr;
    gap: 8px;
    min-height: 36px;
    align-items: center;
  }
  
  .layover-line {
    width: 2px;
    height: 100%;
    min-height: 28px;
    background: repeating-linear-gradient(
      to bottom,
      var(--color-grey-40) 0px,
      var(--color-grey-40) 4px,
      transparent 4px,
      transparent 8px
    );
    justify-self: center;
    grid-column: 2;
  }
  
  .layover-info {
    grid-column: 3;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  
  .layover-label {
    font-size: 12px;
    color: var(--color-warning, #f59e0b);
    font-weight: 500;
    font-style: italic;
  }
  
  .layover-airport {
    font-size: 11px;
    color: var(--color-grey-50);
    font-style: normal;
  }
  
  .layover-overnight {
    font-size: 11px;
    color: var(--color-error, #dc2626);
    font-weight: 500;
    font-style: normal;
  }
  
  /* ===========================================
     Summary Only (when no leg details)
     =========================================== */
  
  .summary-only {
    text-align: center;
    padding: 24px 0;
  }
  
  .summary-times {
    font-size: 20px;
    font-weight: 600;
    color: var(--color-font-primary);
  }
  
  .summary-arrow {
    margin: 0 8px;
    color: var(--color-grey-50);
  }
  
  .summary-duration,
  .summary-stops {
    font-size: 14px;
    color: var(--color-grey-60);
    margin-top: 4px;
  }
  
  /* ===========================================
     Booking Info Footer
     =========================================== */
  
  .booking-info {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-top: 24px;
    padding: 16px;
    background: var(--color-grey-10, rgba(0, 0, 0, 0.03));
    border-radius: 12px;
  }
  
  .booking-info:empty {
    display: none;
  }
  
  .booking-item {
    font-size: 13px;
    color: var(--color-grey-60);
  }
  
  .booking-item.warning {
    color: var(--color-warning, #f59e0b);
    font-weight: 600;
  }
  
  /* ===========================================
     Skill Icon Styling
     =========================================== */
  
  /* Skill icon uses the existing 'search' icon mapping from BasicInfosBar */
</style>
