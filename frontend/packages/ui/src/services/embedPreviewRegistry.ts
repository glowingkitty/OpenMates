/**
 * embedPreviewRegistry.ts
 *
 * Unified registry for resolving embed preview components and their props.
 *
 * This is the single source of truth for the mapping:
 *   (embedId, embedData, decodedContent) → { component: SvelteComponent, props: Record<string, unknown> }
 *
 * Modelled after embedFullscreenResolver.ts (which does the same for fullscreen components).
 * Previously, AppEmbedsPanel.svelte and SettingsShare.svelte each maintained independent
 * copy-paste if/else chains with subtle divergences (wrong field names, missing embed types).
 * This registry fixes all of that and ensures a single addition registers a new embed type
 * everywhere it is shown (My Embeds panel, Share settings panel, etc.).
 *
 * ── Adding a new embed type ────────────────────────────────────────────────────────────────
 * 1. Add a new entry to the `resolvers` Map below (key = canonical embed type string or a
 *    synthetic key like "app:web:search" for app-skill-use embeds).
 * 2. Inside the resolver, dynamic-import the Preview component and return { component, props }.
 * 3. That's it. Both AppEmbedsPanel and SettingsShare will automatically pick it up.
 * ──────────────────────────────────────────────────────────────────────────────────────────
 */

// ── Types ────────────────────────────────────────────────────────────────────

/**
 * All the data available when resolving a preview component.
 * Every field is optional so callers don't have to pad missing data.
 */
export interface EmbedPreviewContext {
  /** Embed UUID (without "embed:" prefix) */
  embedId: string;
  /**
   * Raw embed entry from the store (e.g. from embedStore.get() or resolveEmbed()).
   * Has `.status`, `.type`, `.app_id`, `.skill_id`, `.content`.
   */
  embedData: Record<string, unknown>;
  /**
   * TOON-decoded content object — the canonical field source.
   * Callers must decode before calling the registry.
   */
  decodedContent: Record<string, unknown>;
  /**
   * Callback invoked when the user clicks the preview card to open the fullscreen.
   * Pass a no-op `() => {}` when fullscreen is not supported (e.g. share preview).
   */
  onFullscreen: () => void;
}

type PreviewResolver = (
  ctx: EmbedPreviewContext,
) => Promise<{ component: unknown; props: Record<string, unknown> } | null>;

// ── Helper ────────────────────────────────────────────────────────────────────

/**
 * Narrow the raw status string from the embed store to the union accepted by
 * most preview components.  Defaults to 'finished' because preview panels only
 * show already-stored (completed) embeds — 'processing' is the right default
 * only for the live in-chat renderer (AppSkillUseRenderer).
 */
function normalizeStatus(
  raw: unknown,
): "processing" | "finished" | "error" | "cancelled" {
  if (
    raw === "processing" ||
    raw === "finished" ||
    raw === "error" ||
    raw === "cancelled"
  ) {
    return raw;
  }
  return "finished";
}

function normalizeEmbedIds(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.filter((id): id is string => typeof id === "string" && id.trim().length > 0);
  }
  if (typeof value !== "string") return [];
  return value.split("|").map((id) => id.trim()).filter(Boolean);
}

function firstText(...values: unknown[]): string | undefined {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
  }
  return undefined;
}

function firstNumber(...values: unknown[]): number | undefined {
  for (const value of values) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return undefined;
}

function firstBoolean(...values: unknown[]): boolean | undefined {
  for (const value of values) {
    if (typeof value === "boolean") return value;
    if (typeof value === "string") {
      const normalized = value.trim().toLowerCase();
      if (normalized === "true") return true;
      if (normalized === "false") return false;
    }
  }
  return undefined;
}

function nestedRecord(record: Record<string, unknown>, key: string): Record<string, unknown> | null {
  const value = record[key];
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function stringList(value: unknown): string[] {
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
  if (typeof value === "string") return value.split(/[|,]/).map((item) => item.trim()).filter(Boolean);
  return [];
}

export function parentPreviewProps(
  decodedContent: Record<string, unknown>,
  embedData: Record<string, unknown>,
): {
  results: unknown[];
  resultCount: number | undefined;
  childEmbedIds: string[];
  previewResultsJson: string;
} {
  const results = decodedContent.results || decodedContent.preview_results || decodedContent.preview_thumbnails;
  const childEmbedIds = normalizeEmbedIds(decodedContent.embed_ids || embedData.embed_ids);
  const resultCount = typeof decodedContent.result_count === "number"
    ? decodedContent.result_count
    : Array.isArray(results)
      ? results.length || childEmbedIds.length
      : childEmbedIds.length || undefined;
  const previewResultsJson = typeof decodedContent.preview_results_json === "string"
    ? decodedContent.preview_results_json
    : "";
  return {
    results: Array.isArray(results) ? results : [],
    resultCount,
    childEmbedIds,
    previewResultsJson,
  };
}

// ── Registry ──────────────────────────────────────────────────────────────────

/**
 * Keys in this Map follow two conventions:
 *
 *  • App-skill-use embeds:  "app:<appId>:<skillId>"
 *    e.g. "app:web:search", "app:images:generate"
 *
 *  • Direct / auto-converted embeds:  the canonical `embedData.type` string
 *    e.g. "code-code", "docs-doc", "sheets-sheet", "math-plot"
 *    Aliases (legacy type strings) are registered as separate Map entries
 *    pointing to the same resolver so old stored embeds still resolve.
 */
const resolvers = new Map<string, PreviewResolver>();

// ── App-skill-use: web ────────────────────────────────────────────────────────

resolvers.set(
  "app:web:search",
  async ({ embedId, decodedContent, embedData, onFullscreen }) => {
    const { default: component } =
      await import("../components/embeds/web/WebSearchEmbedPreview.svelte");
    const metadata = parentPreviewProps(decodedContent, embedData);
    return {
      component,
      props: {
        id: embedId,
        query: decodedContent.query || "",
        provider: decodedContent.provider || "Brave Search",
        status: normalizeStatus(embedData.status),
        results: metadata.results,
        resultCount: metadata.resultCount,
        childEmbedIds: metadata.childEmbedIds,
        isMobile: false,
        onFullscreen,
      },
    };
  },
);

// ── App-skill-use: images / search ────────────────────────────────────────────

resolvers.set(
  "app:images:search",
  async ({ embedId, decodedContent, embedData, onFullscreen }) => {
    const { default: component } =
      await import("../components/embeds/images/ImagesSearchEmbedPreview.svelte");
    const metadata = parentPreviewProps(decodedContent, embedData);
    return {
      component,
      props: {
        id: embedId,
        query: decodedContent.query || "",
        provider: decodedContent.provider || "Brave Search",
        status: normalizeStatus(embedData.status),
        results: metadata.results,
        resultCount: metadata.resultCount,
        childEmbedIds: metadata.childEmbedIds,
        previewResultsJson: metadata.previewResultsJson,
        isMobile: false,
        onFullscreen,
      },
    };
  },
);

// ── App-skill-use: design / search_icons ─────────────────────────────────────

resolvers.set(
  "app:design:search_icons",
  async ({ embedId, decodedContent, embedData, onFullscreen }) => {
    const { default: component } =
      await import("../components/embeds/design/DesignIconSearchEmbedPreview.svelte");
    const metadata = parentPreviewProps(decodedContent, embedData);
    return {
      component,
      props: {
        id: embedId,
        query: decodedContent.query || "Icons",
        provider: decodedContent.provider || "Iconify",
        result_count: metadata.resultCount,
        status: normalizeStatus(embedData.status),
        isMobile: false,
        onFullscreen,
      },
    };
  },
);

// ── App-skill-use: news ───────────────────────────────────────────────────────

resolvers.set(
  "app:news:search",
  async ({ embedId, decodedContent, embedData, onFullscreen }) => {
    const { default: component } =
      await import("../components/embeds/news/NewsSearchEmbedPreview.svelte");
    const metadata = parentPreviewProps(decodedContent, embedData);
    return {
      component,
      props: {
        id: embedId,
        query: decodedContent.query || "",
        provider: decodedContent.provider || "Brave Search",
        status: normalizeStatus(embedData.status),
        results: metadata.results,
        resultCount: metadata.resultCount,
        childEmbedIds: metadata.childEmbedIds,
        isMobile: false,
        onFullscreen,
      },
    };
  },
);

// ── App-skill-use: videos / search ────────────────────────────────────────────

resolvers.set(
  "app:videos:search",
  async ({ embedId, decodedContent, embedData, onFullscreen }) => {
    const { default: component } =
      await import("../components/embeds/videos/VideosSearchEmbedPreview.svelte");
    const metadata = parentPreviewProps(decodedContent, embedData);
    return {
      component,
      props: {
        id: embedId,
        query: decodedContent.query || "",
        provider: decodedContent.provider || "Brave Search",
        status: normalizeStatus(embedData.status),
        results: metadata.results,
        resultCount: metadata.resultCount,
        childEmbedIds: metadata.childEmbedIds,
        isMobile: false,
        onFullscreen,
      },
    };
  },
);

// ── App-skill-use: videos / get_transcript ────────────────────────────────────

const videoTranscriptResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/videos/VideoTranscriptEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      results: decodedContent.results || [],
      status: normalizeStatus(embedData.status),
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("app:videos:get_transcript", videoTranscriptResolver);
resolvers.set("app:videos:get-transcript", videoTranscriptResolver); // hyphen alias

// ── App-skill-use: events / event ─────────────────────────────────────────────

const eventResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/events/EventEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      event: decodedContent,
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("app:events:event", eventResolver);
resolvers.set("events-event", eventResolver);

// ── App-skill-use: maps / search ──────────────────────────────────────────────

resolvers.set(
  "app:maps:search",
  async ({ embedId, decodedContent, embedData, onFullscreen }) => {
    const { default: component } =
      await import("../components/embeds/maps/MapsSearchEmbedPreview.svelte");
    return {
      component,
      props: {
        id: embedId,
        query: decodedContent.query || "",
        provider: decodedContent.provider || "Brave Search",
        status: normalizeStatus(embedData.status),
        results: decodedContent.results || [],
        isMobile: false,
        onFullscreen,
      },
    };
  },
);

// ── App-skill-use: code / get_docs ────────────────────────────────────────────

const codeGetDocsResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/code/CodeGetDocsEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      status: normalizeStatus(embedData.status),
      results: decodedContent.results || [],
      library: decodedContent.library || "",
      question: decodedContent.question || "",
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("app:code:get_docs", codeGetDocsResolver);
resolvers.set("app:code:get-docs", codeGetDocsResolver); // hyphen alias

// ── App-skill-use: travel / search_connections ────────────────────────────────

const travelSearchResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/travel/TravelSearchEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      query: decodedContent.query || "",
      provider: decodedContent.provider || "",
      providers: (decodedContent.providers as Array<{ id: string; name: string; icon_url: string }>) || [],
      legs: decodedContent.legs || [],
      origin: decodedContent.origin || "",
      destination: decodedContent.destination || "",
      date: decodedContent.date || "",
      resultCount: typeof decodedContent.result_count === "number" ? decodedContent.result_count : undefined,
      childEmbedIds: decodedContent.embed_ids || embedData.embed_ids,
      status: normalizeStatus(embedData.status),
      results: decodedContent.results || [],
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("app:travel:search_connections", travelSearchResolver);
resolvers.set("app:travel:search-connections", travelSearchResolver); // hyphen alias

// ── App-skill-use: travel / price_calendar ────────────────────────────────────

const travelPriceCalResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/travel/TravelPriceCalendarEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      query: decodedContent.query || "",
      status: normalizeStatus(embedData.status),
      results: decodedContent.results || [],
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("app:travel:price_calendar", travelPriceCalResolver);
resolvers.set("app:travel:price-calendar", travelPriceCalResolver); // hyphen alias

// ── App-skill-use: reminder / set_reminder ────────────────────────────────────

const reminderResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/reminder/ReminderEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      reminderId: decodedContent.reminder_id,
      triggerAtFormatted: decodedContent.trigger_at_formatted,
      triggerAt: decodedContent.trigger_at,
      targetType: decodedContent.target_type,
      isRepeating: decodedContent.is_repeating || false,
      message: decodedContent.message,
      emailNotificationWarning: decodedContent.email_notification_warning,
      status: normalizeStatus(embedData.status),
      error: decodedContent.error,
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("app:reminder:set_reminder", reminderResolver);
resolvers.set("app:reminder:set-reminder", reminderResolver); // hyphen alias

// ── App-skill-use: finance / check_accounts ──────────────────────────────────

const financeCheckAccountsResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/finance/FinanceCheckAccountsEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      status: normalizeStatus(embedData.status || decodedContent.status),
      period: decodedContent.period || "monthly",
      account_count: decodedContent.account_count,
      transaction_count: decodedContent.transaction_count,
      overview: decodedContent.overview,
      results: decodedContent.results || [],
      summary: decodedContent.summary || "",
      provider: decodedContent.provider || "Revolut Business",
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("app:finance:check_accounts", financeCheckAccountsResolver);
resolvers.set("app:finance:check-accounts", financeCheckAccountsResolver);

// ── App-skill-use: images / generate ─────────────────────────────────────────

const imageGenerateResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/images/ImageGenerateEmbedPreview.svelte");
  const skillId =
    (decodedContent.skill_id as string) ||
    (embedData.skill_id as string) ||
    "generate";
  return {
    component,
    props: {
      id: embedId,
      skillId: skillId as "generate" | "generate_draft",
      prompt: decodedContent.prompt || "",
      model: decodedContent.model || embedData.model || "",
      s3BaseUrl: decodedContent.s3_base_url || embedData.s3_base_url || "",
      files: decodedContent.files || embedData.files || undefined,
      aesKey: decodedContent.aes_key || embedData.aes_key || "",
      aesNonce: decodedContent.aes_nonce || embedData.aes_nonce || "",
      status: normalizeStatus(embedData.status),
      error: decodedContent.error || embedData.error || "",
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("app:images:generate", imageGenerateResolver);
resolvers.set("app:images:generate_draft", imageGenerateResolver);

// ── Direct / child: design icon result ───────────────────────────────────────

const designIconResultResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/design/DesignIconResultEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      icon_id: decodedContent.icon_id || "",
      prefix: decodedContent.prefix || "",
      name: decodedContent.name || "",
      display_name: decodedContent.display_name || "",
      collection_name: decodedContent.collection_name || "",
      license_title: decodedContent.license_title || decodedContent.license_spdx || "",
      svg_path: decodedContent.svg_path || "",
      status: normalizeStatus(embedData.status) as "processing" | "finished" | "error",
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("design-icon-result", designIconResultResolver);
resolvers.set("icon_result", designIconResultResolver);
resolvers.set("app:design:icon_result", designIconResultResolver);

// ── Direct / child: maps place ───────────────────────────────────────────────

const mapsPlaceResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/maps/MapLocationEmbedPreview.svelte");
  const location = nestedRecord(decodedContent, "location");
  const venue = nestedRecord(decodedContent, "venue");
  return {
    component,
    props: {
      id: embedId,
      displayName: firstText(decodedContent.displayName, decodedContent.display_name, decodedContent.name, decodedContent.title),
      formattedAddress: firstText(decodedContent.formattedAddress, decodedContent.formatted_address, decodedContent.address, location?.address, venue?.address),
      rating: firstNumber(decodedContent.rating, decodedContent.stars, decodedContent.review_score),
      userRatingCount: firstNumber(decodedContent.userRatingCount, decodedContent.user_rating_count, decodedContent.review_count, decodedContent.rating_count),
      placeType: firstText(decodedContent.placeType, decodedContent.place_type, decodedContent.category, decodedContent.type),
      imageUrl: firstText(decodedContent.imageUrl, decodedContent.image_url, decodedContent.photo_url, decodedContent.thumbnail),
      status: normalizeStatus(embedData.status) as "processing" | "finished" | "error",
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("maps-place", mapsPlaceResolver);
resolvers.set("map-location", mapsPlaceResolver);
resolvers.set("place", mapsPlaceResolver);
resolvers.set("app:maps:place", mapsPlaceResolver);
resolvers.set("app:maps:location", mapsPlaceResolver);

// ── Direct / child: travel connection ────────────────────────────────────────

const travelConnectionResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/travel/TravelConnectionEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      price: decodedContent.price ?? decodedContent.total_price,
      currency: decodedContent.currency || "EUR",
      fare: decodedContent.fare,
      fareIsPartial: firstBoolean(decodedContent.fare_is_partial, decodedContent.fareIsPartial),
      transportMethod: firstText(decodedContent.transport_method, decodedContent.transportMethod, decodedContent.mode) || "airplane",
      tripType: firstText(decodedContent.trip_type, decodedContent.tripType) || "one_way",
      origin: firstText(decodedContent.origin, decodedContent.origin_name, decodedContent.from),
      destination: firstText(decodedContent.destination, decodedContent.destination_name, decodedContent.to),
      departure: firstText(decodedContent.departure, decodedContent.scheduled_departure),
      arrival: firstText(decodedContent.arrival, decodedContent.scheduled_arrival),
      duration: firstText(decodedContent.duration, decodedContent.duration_minutes),
      stops: firstNumber(decodedContent.stops, decodedContent.transfers, decodedContent.transfer_count),
      arrivalDelayMinutes: firstNumber(decodedContent.arrival_delay_minutes, decodedContent.arrivalDelayMinutes),
      hasCancellation: firstBoolean(decodedContent.has_cancellation, decodedContent.hasCancellation),
      carriers: stringList(decodedContent.carriers ?? decodedContent.carrier),
      bookingProvider: firstText(decodedContent.booking_provider, decodedContent.provider, decodedContent.source_provider),
      airlineLogo: firstText(decodedContent.airline_logo, decodedContent.logo_url, decodedContent.provider_logo),
      carrierCodes: stringList(decodedContent.carrier_codes ?? decodedContent.carrier_code),
      bookableSeats: firstNumber(decodedContent.bookable_seats, decodedContent.bookableSeats),
      optimization: decodedContent.optimization,
      isCheapest: firstBoolean(decodedContent.is_cheapest, decodedContent.isCheapest),
      status: normalizeStatus(embedData.status) as "processing" | "finished" | "error",
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("travel-connection", travelConnectionResolver);
resolvers.set("travel-route", travelConnectionResolver);
resolvers.set("connection", travelConnectionResolver);

// ── Direct / child: health appointment ───────────────────────────────────────

const healthAppointmentResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/health/HealthAppointmentEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      slotDatetime: firstText(decodedContent.slotDatetime, decodedContent.slot_datetime, decodedContent.start_time, decodedContent.date_start),
      name: firstText(decodedContent.name, decodedContent.doctor_name, decodedContent.title),
      speciality: firstText(decodedContent.speciality, decodedContent.specialty, decodedContent.category),
      address: firstText(decodedContent.address, decodedContent.formatted_address),
      insurance: firstText(decodedContent.insurance, decodedContent.insurance_sector),
      telehealth: firstBoolean(decodedContent.telehealth, decodedContent.is_telehealth) ?? false,
      rating: firstNumber(decodedContent.rating, decodedContent.review_score),
      ratingCount: firstNumber(decodedContent.ratingCount, decodedContent.rating_count, decodedContent.review_count),
      price: firstNumber(decodedContent.price, decodedContent.service_price),
      providerPlatform: firstText(decodedContent.providerPlatform, decodedContent.provider_platform, decodedContent.provider),
      additionalSlotCount: firstNumber(decodedContent.additionalSlotCount, decodedContent.additional_slot_count) ?? 0,
      status: normalizeStatus(embedData.status) as "processing" | "finished" | "error",
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("health-appointment", healthAppointmentResolver);
resolvers.set("app:health:appointment", healthAppointmentResolver);

// ── Direct / child: travel stay ──────────────────────────────────────────────

const travelStayResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/travel/TravelStayEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      name: firstText(decodedContent.name, decodedContent.title, decodedContent.property_name),
      thumbnail: firstText(decodedContent.thumbnail, decodedContent.image_url, decodedContent.photo_url),
      hotelClass: firstNumber(decodedContent.hotelClass, decodedContent.hotel_class, decodedContent.stars),
      overallRating: firstNumber(decodedContent.overallRating, decodedContent.overall_rating, decodedContent.rating),
      reviews: firstNumber(decodedContent.reviews, decodedContent.review_count),
      currency: decodedContent.currency || "EUR",
      ratePerNight: firstNumber(decodedContent.ratePerNight, decodedContent.rate_per_night, decodedContent.price, decodedContent.min_price),
      totalRate: firstNumber(decodedContent.totalRate, decodedContent.total_rate, decodedContent.total_price),
      amenities: stringList(decodedContent.amenities),
      isCheapest: firstBoolean(decodedContent.isCheapest, decodedContent.is_cheapest) ?? false,
      ecoCertified: firstBoolean(decodedContent.ecoCertified, decodedContent.eco_certified) ?? false,
      freeCancellation: firstBoolean(decodedContent.freeCancellation, decodedContent.free_cancellation) ?? false,
      status: normalizeStatus(embedData.status) as "processing" | "finished" | "error",
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("travel-stay", travelStayResolver);
resolvers.set("travel-hotel", travelStayResolver);
resolvers.set("app:travel:stay", travelStayResolver);

// ── Direct / child: fitness result ───────────────────────────────────────────

const fitnessResultResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/fitness/FitnessResultEmbedPreview.svelte");
  const skillId = firstText(decodedContent.skill_id, decodedContent.skillId) || "search_locations";
  return {
    component,
    props: {
      id: embedId,
      result: {
        ...decodedContent,
        embed_id: embedId,
      },
      skillId,
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("fitness-location", fitnessResultResolver);
resolvers.set("fitness-class", fitnessResultResolver);
resolvers.set("app:fitness:location", fitnessResultResolver);
resolvers.set("app:fitness:class", fitnessResultResolver);

// ── Direct / auto-converted: code ─────────────────────────────────────────────

const codeResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/code/CodeEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      status: normalizeStatus(embedData.status),
      language: decodedContent.language || "",
      filename: decodedContent.filename,
      lineCount: decodedContent.line_count || decodedContent.lineCount || 0,
      codeContent: decodedContent.code || decodedContent.content || "",
      isMobile: false,
      onFullscreen,
    },
  };
};
// All known type strings that mean "code embed"
resolvers.set("code-code", codeResolver);
resolvers.set("code", codeResolver); // legacy server type
resolvers.set("code-block", codeResolver); // legacy client alias
resolvers.set("code_embed", codeResolver); // legacy alias used in AppEmbedsPanel
// Also reachable via app-skill routing when app_id === 'code' and no specific skill matched:
resolvers.set("app:code:*", codeResolver);

// ── Direct / auto-converted: sheets ──────────────────────────────────────────

const sheetResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/sheets/SheetEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      status: normalizeStatus(embedData.status) as
        | "processing"
        | "finished"
        | "error",
      title: decodedContent.title || "",
      rowCount: decodedContent.row_count || 0,
      colCount: decodedContent.col_count || 0,
      // Canonical field is `table`; keep `table_content` and `content` as fallbacks
      // for any embeds stored before field was standardised.
      tableContent: (decodedContent.table ||
        decodedContent.table_content ||
        decodedContent.content ||
        "") as string,
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("sheets-sheet", sheetResolver);
resolvers.set("sheet", sheetResolver); // legacy server type
// App-skill route for sheets app (skill = "sheet")
resolvers.set("app:sheets:sheet", sheetResolver);

// ── Direct / auto-converted: math-plot ───────────────────────────────────────

const mathPlotResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/math/MathPlotEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      status: normalizeStatus(embedData.status),
      // plot_spec is the canonical field; expression is the legacy name (pre-rename)
      plotSpec: decodedContent.plot_spec || decodedContent.expression || "",
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("math-plot", mathPlotResolver);
// App-skill route for math app
resolvers.set("app:math:plot", mathPlotResolver);

// ── Direct / auto-converted: docs (document_html) ────────────────────────────

const docsResolver: PreviewResolver = async ({
  embedId,
  decodedContent,
  embedData,
  onFullscreen,
}) => {
  const { default: component } =
    await import("../components/embeds/docs/DocsEmbedPreview.svelte");
  return {
    component,
    props: {
      id: embedId,
      status: normalizeStatus(embedData.status) as
        | "processing"
        | "finished"
        | "error",
      title: decodedContent.title || "",
      wordCount: decodedContent.word_count || 0,
      htmlContent: decodedContent.html || "",
      isMobile: false,
      onFullscreen,
    },
  };
};
resolvers.set("docs-doc", docsResolver);
resolvers.set("document", docsResolver); // legacy server type
// App-skill route for docs app
resolvers.set("app:docs:doc", docsResolver);

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Derive the registry key from the embed context.
 *
 * Resolution order (first match wins):
 *  1. Specific app-skill key:  "app:<appId>:<skillId>"
 *  2. Wildcard app key:        "app:<appId>:*"   (catches code embeds via app_id only)
 *  3. Direct type key:         embedData.type    (e.g. "docs-doc", "math-plot")
 *
 * Returns null if no key matches — the caller should fall back to a text summary.
 */
function deriveKey(ctx: EmbedPreviewContext): string | null {
  const d = ctx.decodedContent;
  const e = ctx.embedData;

  const appId = (d.app_id as string) || (e.app_id as string) || "";
  const skillId = (d.skill_id as string) || (e.skill_id as string) || "";
  const type = (e.type as string) || (d.type as string) || "";

  if ((type === "icon_result" || type === "design-icon-result") && resolvers.has(type)) {
    return type;
  }

  // Child/direct embeds often carry the parent skill_id that created them. Prefer
  // the concrete embed type so child route/place cards don't render as parent searches.
  if (type && type !== "app_skill_use" && resolvers.has(type)) return type;

  // 1. Specific app:skill key
  if (appId && skillId) {
    const appSkillKey = `app:${appId}:${skillId}`;
    if (resolvers.has(appSkillKey)) return appSkillKey;
  }

  // 2. Wildcard app key (e.g. "app:code:*" catches plain code embeds)
  if (appId) {
    const wildcardKey = `app:${appId}:*`;
    if (resolvers.has(wildcardKey)) return wildcardKey;
  }

  // 3. Direct type key
  if (type && resolvers.has(type)) return type;

  return null;
}

/**
 * Resolve the preview component and props for an embed.
 *
 * @param ctx - The embed context (id, raw data, decoded content, fullscreen callback).
 * @returns `{ component, props }` ready to mount, or `null` if no resolver is registered.
 *
 * @example
 * ```ts
 * const result = await embedPreviewRegistry.resolve({
 *   embedId,
 *   embedData,
 *   decodedContent,
 *   onFullscreen: () => openEmbedFullscreen(embedId, embedData, embedEntry),
 * });
 * if (result) {
 *   mount(result.component, { target, props: result.props });
 * }
 * ```
 */
async function resolve(
  ctx: EmbedPreviewContext,
): Promise<{ component: unknown; props: Record<string, unknown> } | null> {
  const key = deriveKey(ctx);

  if (!key) {
    console.warn("[embedPreviewRegistry] No resolver found for embed:", {
      embedId: ctx.embedId,
      app_id: ctx.decodedContent.app_id || ctx.embedData.app_id,
      skill_id: ctx.decodedContent.skill_id || ctx.embedData.skill_id,
      type: ctx.embedData.type,
    });
    return null;
  }

  try {
    const resolver = resolvers.get(key)!;
    return await resolver(ctx);
  } catch (error) {
    console.error(
      "[embedPreviewRegistry] Error resolving preview for key:",
      key,
      error,
    );
    return null;
  }
}

/**
 * Check whether a resolver exists for the given embed context without loading any component.
 * Useful to pre-filter embeds before attempting a full resolve.
 */
function canResolve(ctx: Omit<EmbedPreviewContext, "onFullscreen">): boolean {
  return deriveKey({ ...ctx, onFullscreen: () => {} }) !== null;
}

export const embedPreviewRegistry = { resolve, canResolve };
