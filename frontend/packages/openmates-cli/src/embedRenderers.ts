/*
 * CLI text-only embed renderers.
 *
 * Purpose: render embed preview cards and fullscreen details as structured
 * terminal text, matching the visual information shown by each Svelte
 * preview/fullscreen component in the web app.
 *
 * Architecture: each embed type (31 total, from embedRegistry.generated.ts)
 * has a preview renderer (compact card) and a fullscreen renderer (expanded
 * detail). Both receive the same DecryptedEmbed and produce terminal output.
 *
 * When adding a new embed type:
 * 1. Add a preview case in renderEmbedPreview()
 * 2. Add a fullscreen case in renderEmbedFullscreen()
 * 3. Update docs/claude/embed-types.md checklist
 *
 * Architecture doc: docs/architecture/openmates-cli.md
 * Tests: frontend/packages/openmates-cli/tests/
 */

import type { DecryptedEmbed } from "./client.js";
import type { OpenMatesClient } from "./client.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const str = (v: unknown): string | null =>
  typeof v === "string" && v.length > 0 ? v : null;

/** Direct types for child embeds — these have their own type field and should
 * NOT be dispatched via the parent's app_id/skill_id switch. */
const DIRECT_TYPES = new Set([
  "code",
  "code-code",
  "docs-doc",
  "doc",
  "sheets-sheet",
  "sheet",
  "pdf",
  "image",
  "web-website",
  "videos-video",
  "travel-connection",
  "travel-stay",
  "maps",
  "maps-place",
  "recording",
  "mail-email",
  "math-plot",
  "events-event",
  "health-appointment",
  "shopping-product",
  "images-image-result",
  "news-article",
]);

/** Human-readable labels for direct types */
const DIRECT_TYPE_LABELS: Record<string, string> = {
  "code": "code",
  "code-code": "code",
  "docs-doc": "document",
  "doc": "document",
  "sheets-sheet": "sheet",
  "sheet": "sheet",
  "pdf": "pdf",
  "image": "image",
  "web-website": "website",
  "videos-video": "video",
  "travel-connection": "connection",
  "travel-stay": "stay",
  "maps": "place",
  "maps-place": "place",
  "recording": "recording",
  "mail-email": "email",
  "math-plot": "plot",
  "events-event": "event",
  "health-appointment": "appointment",
  "shopping-product": "product",
  "images-image-result": "image",
  "news-article": "article",
};

const STATUS_ICONS: Record<string, string> = {
  processing: "\x1b[33m⟳\x1b[0m",
  finished: "\x1b[32m✓\x1b[0m",
  error: "\x1b[31m✗\x1b[0m",
  cancelled: "\x1b[2m⊘\x1b[0m",
};

const STATUS_LABELS: Record<string, string> = {
  processing: "\x1b[33mProcessing...\x1b[0m",
  finished: "\x1b[32mCompleted\x1b[0m",
  error: "\x1b[31mError\x1b[0m",
  cancelled: "\x1b[2mCancelled\x1b[0m",
};

function statusIcon(status: string | null | undefined): string {
  return STATUS_ICONS[status ?? ""] ?? "";
}

function statusLabel(status: string | null | undefined): string {
  return STATUS_LABELS[status ?? ""] ?? "";
}

/** Parse pipe-separated embed_ids to array */
function parseEmbedIds(raw: unknown): string[] {
  if (typeof raw === "string") return raw.split("|").filter(Boolean);
  if (Array.isArray(raw)) return raw.map(String).filter(Boolean);
  return [];
}

/** Format a price with currency */
function formatPrice(amount: unknown, currency: unknown): string {
  if (amount === null || amount === undefined) return "";
  const cur = str(currency)?.toUpperCase() ?? "";
  return cur ? `${cur} ${amount}` : String(amount);
}

/** Truncate string */
function trunc(s: string, max: number): string {
  return s.length > max ? s.slice(0, max) + "…" : s;
}

// ---------------------------------------------------------------------------
// Preview renderer — compact card shown inline in chat messages
// ---------------------------------------------------------------------------

/**
 * Render an embed as a compact preview card (matching the web app's
 * preview card layout). Called for inline embeds in chat messages
 * and for skill embeds shown between user/assistant messages.
 *
 * Format:
 *   ┌─ [✓] events/search  · "AI"  via Meetup
 *   │  + 10 events
 *   └─ openmates embeds show e37b83eb
 */
export async function renderEmbedPreview(
  embed: DecryptedEmbed,
  client: OpenMatesClient,
): Promise<void> {
  const shortId = embed.embedId.slice(0, 8);
  const c = (embed.content ?? {}) as Record<string, unknown>;
  const resolvedType = embed.type ?? str(c.type) ?? "";

  // Child embeds (e.g. individual video, website, connection) have their own
  // type field but may inherit parent's app_id/skill_id. Check type first to
  // dispatch to the correct direct-type renderer.
  if (DIRECT_TYPES.has(resolvedType)) {
    const typeLabel = DIRECT_TYPE_LABELS[resolvedType] ?? resolvedType;
    const ln = (s: string) => process.stdout.write(`\x1b[2m│\x1b[0m  ${s}\n`);
    process.stdout.write(`\x1b[2m┌─\x1b[0m \x1b[1m${typeLabel}\x1b[0m\n`);
    renderByDirectType(embed, c, ln);
    process.stdout.write(
      `\x1b[2m└─ openmates embeds show ${shortId}\x1b[0m\n`,
    );
    return;
  }

  const app = embed.appId ?? str(embed.content?.app_id) ?? "";
  const skill = embed.skillId ?? str(embed.content?.skill_id) ?? "";
  const label = skill ? `${app}/${skill}` : app || "embed";
  const status = str(c.status) ?? (embed.type ? null : null);

  // Build header components
  const query = str(c.query) ?? str(c.search_query) ?? str(c.question);
  const querySuffix = query ? `  · "${trunc(query, 60)}"` : "";
  const providerSuffix = str(c.provider) ? `  via ${c.provider}` : "";
  const statusSuffix = status ? `  ${statusLabel(status)}` : "";

  const ln = (s: string) => process.stdout.write(`\x1b[2m│\x1b[0m  ${s}\n`);

  // Header line
  process.stdout.write(
    `\x1b[2m┌─\x1b[0m ${statusIcon(status)} \x1b[1m${label}\x1b[0m${querySuffix}\x1b[2m${providerSuffix}\x1b[0m${statusSuffix}\n`,
  );

  // Type-specific body
  const key = `${app}/${skill}`;
  switch (key) {
    // ── Search types (query + provider + result count) ──────────────────
    case "web/search":
    case "news/search":
    case "shopping/search_products":
    case "images/search":
    case "mail/search":
      await renderSearchPreview(c, ln, client);
      break;

    case "events/search":
      await renderEventsSearchPreview(c, ln, client);
      break;

    case "videos/search":
      await renderVideosSearchPreview(c, ln, client);
      break;

    case "maps/search":
      renderMapsSearchPreview(c, ln);
      break;

    // ── Travel types ───────────────────────────────────────────────────
    case "travel/search_connections":
      await renderTravelConnectionsPreview(c, ln, client);
      break;

    case "travel/search_stays":
      await renderTravelStaysPreview(c, ln, client);
      break;

    case "travel/price_calendar":
      renderTravelPriceCalendarPreview(c, ln);
      break;

    case "travel/get_flight":
      renderTravelFlightPreview(c, ln);
      break;

    // ── Content types ──────────────────────────────────────────────────
    case "code/get_docs":
      renderCodeDocsPreview(c, ln);
      break;

    case "web/read":
      renderWebReadPreview(c, ln);
      break;

    case "math/calculate":
      renderMathCalculatePreview(c, ln);
      break;

    // ── Reminder ────────────────────────────────────────────────────────
    case "reminder/set-reminder":
    case "reminder/list-reminders":
    case "reminder/cancel-reminder":
      renderReminderPreview(c, ln);
      break;

    // ── Media types ────────────────────────────────────────────────────
    case "images/generate":
    case "images/generate_draft":
      renderImageGeneratePreview(c, ln);
      break;

    case "videos/get_transcript":
      renderVideoTranscriptPreview(c, ln);
      break;

    case "health/search_appointments":
      await renderHealthSearchPreview(c, ln, client);
      break;

    case "audio/transcribe":
      renderAudioTranscribePreview(c, ln);
      break;

    default:
      // Handle by embed type for direct-type embeds
      renderByDirectType(embed, c, ln);
      break;
  }

  // Footer
  process.stdout.write(`\x1b[2m└─ openmates embeds show ${shortId}\x1b[0m\n`);
}

// ---------------------------------------------------------------------------
// Fullscreen renderer — expanded detail shown by `embeds show`
// ---------------------------------------------------------------------------

/**
 * Render an embed as a fullscreen detail view (matching the web app's
 * fullscreen panel). Called by `openmates embeds show <id>`.
 */
export async function renderEmbedFullscreen(
  embed: DecryptedEmbed,
  client: OpenMatesClient,
): Promise<void> {
  const c = (embed.content ?? {}) as Record<string, unknown>;
  const resolvedType = embed.type ?? str(c.type) ?? "";

  // Child embeds with a direct type — use type-specific fullscreen renderer.
  if (DIRECT_TYPES.has(resolvedType)) {
    const typeLabel = DIRECT_TYPE_LABELS[resolvedType] ?? resolvedType;
    process.stdout.write(
      `\x1b[1m${typeLabel}\x1b[0m  \x1b[2m${embed.embedId.slice(0, 8)}\x1b[0m\n`,
    );
    if (embed.createdAt)
      process.stdout.write(
        `\x1b[2mCreated:\x1b[0m ${formatTs(embed.createdAt)}\n`,
      );
    process.stdout.write("\n");
    renderDirectTypeFullscreen(embed, c);
    return;
  }

  const app = embed.appId ?? str(embed.content?.app_id) ?? "";
  const skill = embed.skillId ?? str(embed.content?.skill_id) ?? "";
  const label = skill ? `${app}/${skill}` : app || "embed";
  const status = str(c.status);

  // Header
  process.stdout.write(`\x1b[1m${label}\x1b[0m`);
  if (status) process.stdout.write(`  ${statusLabel(status)}`);
  process.stdout.write(`  \x1b[2m${embed.embedId.slice(0, 8)}\x1b[0m\n`);

  const query = str(c.query) ?? str(c.search_query) ?? str(c.question);
  const provider = str(c.provider);
  if (query) process.stdout.write(`\x1b[2mQuery:\x1b[0m ${query}\n`);
  if (provider) process.stdout.write(`\x1b[2mProvider:\x1b[0m ${provider}\n`);
  if (embed.createdAt)
    process.stdout.write(
      `\x1b[2mCreated:\x1b[0m ${formatTs(embed.createdAt)}\n`,
    );

  const error = str(c.error) ?? str(c.error_message);
  if (error) {
    process.stdout.write(`\n\x1b[31mError:\x1b[0m ${error}\n`);
  }

  process.stdout.write("\n");

  // Type-specific detail
  const key = `${app}/${skill}`;
  switch (key) {
    case "web/search":
    case "news/search":
    case "shopping/search_products":
    case "images/search":
    case "mail/search":
      await renderSearchFullscreen(c, client);
      break;

    case "events/search":
      await renderEventsSearchFullscreen(c, client);
      break;

    case "videos/search":
      await renderVideosSearchFullscreen(c, client);
      break;

    case "maps/search":
      renderMapsSearchFullscreen(c);
      break;

    case "travel/search_connections":
      await renderTravelConnectionsFullscreen(c, client);
      break;

    case "travel/search_stays":
      await renderTravelStaysFullscreen(c, client);
      break;

    case "travel/price_calendar":
      renderTravelPriceCalendarFullscreen(c);
      break;

    case "travel/get_flight":
      renderTravelFlightFullscreen(c);
      break;

    case "code/get_docs":
      renderCodeDocsFullscreen(c);
      break;

    case "web/read":
      renderWebReadFullscreen(c);
      break;

    case "math/calculate":
      renderMathCalculateFullscreen(c);
      break;

    case "reminder/set-reminder":
    case "reminder/list-reminders":
    case "reminder/cancel-reminder":
      renderReminderFullscreen(c);
      break;

    case "images/generate":
    case "images/generate_draft":
      renderImageGenerateFullscreen(c);
      break;

    case "videos/get_transcript":
      renderVideoTranscriptFullscreen(c);
      break;

    case "health/search_appointments":
      await renderHealthSearchFullscreen(c, client);
      break;

    case "audio/transcribe":
      renderAudioTranscribeFullscreen(c);
      break;

    default:
      renderDirectTypeFullscreen(embed, c);
      break;
  }
}

// ---------------------------------------------------------------------------
// Search types (web, news, shopping, images, mail)
// ---------------------------------------------------------------------------

async function renderSearchPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
  client: OpenMatesClient,
): Promise<void> {
  const count = resolveResultCount(c);
  if (count !== null) ln(`\x1b[2m+ ${count} results\x1b[0m`);
  else if (str(c.status) === "finished") ln("\x1b[2mNo results\x1b[0m");
}

async function renderSearchFullscreen(
  c: Record<string, unknown>,
  client: OpenMatesClient,
): Promise<void> {
  const results = await resolveChildResults(c, client);
  if (results.length === 0) {
    console.log("No results found.");
    return;
  }
  console.log(`${results.length} results:\n`);
  for (const r of results) {
    const title = str(r.title) ?? str(r.name) ?? "";
    const url = str(r.url) ?? str(r.link) ?? "";
    const desc = str(r.description) ?? str(r.snippet) ?? str(r.summary) ?? "";
    const age = str(r.page_age);
    if (title) process.stdout.write(`  \x1b[1m${title}\x1b[0m\n`);
    if (url) process.stdout.write(`  \x1b[2m${url}\x1b[0m\n`);
    if (age) process.stdout.write(`  \x1b[2m${age}\x1b[0m\n`);
    if (desc) process.stdout.write(`  ${trunc(desc, 300)}\n`);
    process.stdout.write(`  \x1b[2m${"─".repeat(40)}\x1b[0m\n`);
  }
}

// ── Events search ────────────────────────────────────────────────────────

async function renderEventsSearchPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
  client: OpenMatesClient,
): Promise<void> {
  const count = resolveResultCount(c);
  if (count !== null) ln(`\x1b[2m+ ${count} events\x1b[0m`);
  else if (str(c.status) === "finished") ln("\x1b[2mNo events found\x1b[0m");
}

async function renderEventsSearchFullscreen(
  c: Record<string, unknown>,
  client: OpenMatesClient,
): Promise<void> {
  const results = await resolveChildResults(c, client);
  if (results.length === 0) {
    console.log("No events found.");
    return;
  }
  console.log(`${results.length} events:\n`);
  for (const r of results) {
    const name = str(r.name) ?? str(r.title) ?? "";
    const date = str(r.date) ?? str(r.start_date) ?? str(r.dateTime) ?? "";
    const venue = str(r.venue) ?? str(r.location) ?? "";
    const url = str(r.url) ?? str(r.link) ?? "";
    const desc = str(r.description) ?? str(r.summary) ?? "";
    const going = typeof r.going_count === "number" ? r.going_count : null;
    if (name) process.stdout.write(`  \x1b[1m${name}\x1b[0m\n`);
    if (date) process.stdout.write(`  \x1b[2m${date}\x1b[0m`);
    if (venue) process.stdout.write(`  \x1b[2m@ ${venue}\x1b[0m`);
    if (date || venue) process.stdout.write("\n");
    if (going !== null)
      process.stdout.write(`  \x1b[2m${going} going\x1b[0m\n`);
    if (desc) process.stdout.write(`  ${trunc(desc, 200)}\n`);
    if (url) process.stdout.write(`  \x1b[2m${url}\x1b[0m\n`);
    process.stdout.write(`  \x1b[2m${"─".repeat(40)}\x1b[0m\n`);
  }
}

// ── Videos search ────────────────────────────────────────────────────────

async function renderVideosSearchPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
  client: OpenMatesClient,
): Promise<void> {
  const count = resolveResultCount(c);
  if (count !== null) ln(`\x1b[2m+ ${count} videos\x1b[0m`);
  else if (str(c.status) === "finished") ln("\x1b[2mNo videos found\x1b[0m");
}

async function renderVideosSearchFullscreen(
  c: Record<string, unknown>,
  client: OpenMatesClient,
): Promise<void> {
  const results = await resolveChildResults(c, client);
  if (results.length === 0) {
    console.log("No videos found.");
    return;
  }
  console.log(`${results.length} videos:\n`);
  for (const r of results) {
    const title = str(r.title) ?? "";
    const channel = str(r.channel) ?? str(r.author) ?? "";
    const duration = str(r.duration) ?? "";
    const url = str(r.url) ?? str(r.link) ?? "";
    if (title) process.stdout.write(`  \x1b[1m${title}\x1b[0m\n`);
    if (channel || duration) {
      process.stdout.write(
        `  \x1b[2m${channel}${duration ? `  ${duration}` : ""}\x1b[0m\n`,
      );
    }
    if (url) process.stdout.write(`  \x1b[2m${url}\x1b[0m\n`);
    console.log();
  }
}

// ── Maps search ──────────────────────────────────────────────────────────

function renderMapsSearchPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
): void {
  const results = c.results as Array<Record<string, unknown>> | undefined;
  if (Array.isArray(results) && results.length > 0) {
    ln(`\x1b[2m+ ${results.length} places\x1b[0m`);
  } else if (str(c.status) === "finished") {
    ln("\x1b[2mNo places found\x1b[0m");
  }
}

function renderMapsSearchFullscreen(c: Record<string, unknown>): void {
  const results = c.results as Array<Record<string, unknown>> | undefined;
  if (!Array.isArray(results) || results.length === 0) {
    console.log("No places found.");
    return;
  }
  console.log(`${results.length} places:\n`);
  for (const r of results) {
    const name = str(r.displayName) ?? str(r.name) ?? "";
    const address = str(r.formattedAddress) ?? str(r.address) ?? "";
    const rating = typeof r.rating === "number" ? `★ ${r.rating}` : "";
    if (name)
      process.stdout.write(
        `  \x1b[1m${name}\x1b[0m${rating ? `  ${rating}` : ""}\n`,
      );
    if (address) process.stdout.write(`  \x1b[2m${address}\x1b[0m\n`);
    console.log();
  }
}

// ---------------------------------------------------------------------------
// Travel types
// ---------------------------------------------------------------------------

async function renderTravelConnectionsPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
  client: OpenMatesClient,
): Promise<void> {
  const count = resolveResultCount(c);
  const results = c.results as Array<Record<string, unknown>> | undefined;

  // Route summary from first result
  if (Array.isArray(results) && results.length > 0) {
    const r = results[0];
    const origin = str(r.origin) ?? "";
    const dest = str(r.destination) ?? "";
    if (origin && dest) ln(`${origin} → ${dest}`);
  }

  if (count !== null) ln(`\x1b[2m${count} connections\x1b[0m`);

  // Price range
  if (Array.isArray(results) && results.length > 0) {
    const prices = results
      .map((r) => (typeof r.total_price === "number" ? r.total_price : null))
      .filter((p): p is number => p !== null);
    if (prices.length > 0) {
      const min = Math.min(...prices);
      const currency = str(results[0].currency) ?? "EUR";
      ln(`\x1b[2mfrom ${currency} ${min}\x1b[0m`);
    }
  }
}

async function renderTravelConnectionsFullscreen(
  c: Record<string, unknown>,
  client: OpenMatesClient,
): Promise<void> {
  const results = await resolveChildResults(c, client);
  if (results.length === 0) {
    console.log("No connections found.");
    return;
  }
  console.log(`${results.length} connections:\n`);
  for (const r of results) {
    const origin = str(r.origin) ?? "";
    const dest = str(r.destination) ?? "";
    const dep = str(r.departure)?.slice(11, 16) ?? "";
    const arr = str(r.arrival)?.slice(11, 16) ?? "";
    const duration = str(r.duration) ?? "";
    const price = formatPrice(r.total_price ?? r.price, r.currency);
    const stops =
      typeof r.stops === "number"
        ? r.stops === 0
          ? "Direct"
          : `${r.stops} stops`
        : "";
    const carriers = Array.isArray(r.carriers)
      ? r.carriers.join(", ")
      : (str(r.carrier) ?? "");

    if (origin && dest)
      process.stdout.write(`  \x1b[1m${origin} → ${dest}\x1b[0m\n`);
    if (dep && arr)
      process.stdout.write(
        `  ${dep} – ${arr}${duration ? `  (${duration})` : ""}\n`,
      );
    if (price || stops || carriers) {
      process.stdout.write(
        `  \x1b[2m${[price, stops, carriers].filter(Boolean).join("  · ")}\x1b[0m\n`,
      );
    }
    console.log();
  }
}

async function renderTravelStaysPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
  client: OpenMatesClient,
): Promise<void> {
  const count = resolveResultCount(c);
  if (count !== null) ln(`\x1b[2m${count} stays\x1b[0m`);
}

async function renderTravelStaysFullscreen(
  c: Record<string, unknown>,
  client: OpenMatesClient,
): Promise<void> {
  const results = await resolveChildResults(c, client);
  if (results.length === 0) {
    console.log("No stays found.");
    return;
  }
  console.log(`${results.length} stays:\n`);
  for (const r of results) {
    const name = str(r.name) ?? str(r.hotel_name) ?? "";
    const price = formatPrice(r.total_price ?? r.price, r.currency);
    const rating = typeof r.rating === "number" ? `★ ${r.rating}` : "";
    const address = str(r.address) ?? "";

    if (name)
      process.stdout.write(
        `  \x1b[1m${name}\x1b[0m${rating ? `  ${rating}` : ""}\n`,
      );
    if (price) process.stdout.write(`  ${price}\n`);
    if (address) process.stdout.write(`  \x1b[2m${address}\x1b[0m\n`);
    console.log();
  }
}

function renderTravelPriceCalendarPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
): void {
  const origin = str(c.origin) ?? "";
  const dest = str(c.destination) ?? "";
  if (origin && dest) ln(`${origin} → ${dest}`);
  const cheapest = c.cheapest_price;
  const currency = str(c.currency) ?? "EUR";
  if (cheapest !== undefined && cheapest !== null) {
    ln(`\x1b[2mFrom ${currency} ${cheapest}\x1b[0m`);
  }
}

function renderTravelPriceCalendarFullscreen(c: Record<string, unknown>): void {
  const prices = c.prices as Array<Record<string, unknown>> | undefined;
  if (!Array.isArray(prices) || prices.length === 0) {
    console.log("No price data available.");
    return;
  }
  const currency = str(c.currency) ?? "EUR";
  console.log(`Price calendar (${prices.length} dates):\n`);
  for (const p of prices.slice(0, 14)) {
    const date = str(p.date) ?? "";
    const price = p.price ?? p.amount;
    if (date && price !== undefined) {
      process.stdout.write(`  ${date}  ${currency} ${price}\n`);
    }
  }
  if (prices.length > 14) console.log(`  ... and ${prices.length - 14} more`);
}

function renderTravelFlightPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
): void {
  const flightNumber = str(c.flight_number) ?? str(c.callsign) ?? "";
  const airline = str(c.airline) ?? "";
  const origin = str(c.origin) ?? "";
  const dest = str(c.destination) ?? "";
  if (flightNumber)
    ln(`\x1b[1m${flightNumber}\x1b[0m${airline ? `  ${airline}` : ""}`);
  if (origin && dest) ln(`${origin} → ${dest}`);
  const status = str(c.flight_status);
  if (status) ln(`\x1b[2mStatus: ${status}\x1b[0m`);
}

function renderTravelFlightFullscreen(c: Record<string, unknown>): void {
  const fields: [string, unknown][] = [
    ["Flight", c.flight_number ?? c.callsign],
    ["Airline", c.airline],
    [
      "Route",
      c.origin && c.destination ? `${c.origin} → ${c.destination}` : null,
    ],
    ["Departure", c.departure],
    ["Arrival", c.arrival],
    ["Status", c.flight_status],
    ["Aircraft", c.aircraft],
    ["Altitude", c.altitude],
    ["Speed", c.speed],
  ];
  for (const [label, value] of fields) {
    if (value !== null && value !== undefined) {
      process.stdout.write(`  \x1b[2m${label.padEnd(14)}\x1b[0m ${value}\n`);
    }
  }
}

// ---------------------------------------------------------------------------
// Content types
// ---------------------------------------------------------------------------

function renderCodeDocsPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
): void {
  const results = c.results as Array<Record<string, unknown>> | undefined;
  const first = Array.isArray(results) ? results[0] : null;
  const libId =
    (first?.library as Record<string, unknown>)?.id ??
    first?.library_id ??
    str(c.library);
  const wordCount = first?.word_count ?? c.word_count;
  if (libId) ln(`\x1b[2mLibrary: ${String(libId)}\x1b[0m`);
  if (wordCount) ln(`\x1b[2m${String(wordCount)} words\x1b[0m`);
}

function renderCodeDocsFullscreen(c: Record<string, unknown>): void {
  const results = c.results as Array<Record<string, unknown>> | undefined;
  const first = Array.isArray(results) ? results[0] : null;
  const docs =
    str(first?.documentation as string) ?? str(c.documentation as string) ?? "";
  if (docs) {
    // Show first 2000 chars of documentation
    console.log(trunc(docs, 2000));
  } else {
    console.log("No documentation content.");
  }
}

function renderWebReadPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
): void {
  const url = str(c.url) ?? "";
  const resultCount = c.result_count;
  if (url) ln(`\x1b[2m${trunc(url, 60)}\x1b[0m`);
  if (resultCount) ln(`\x1b[2m${resultCount} results\x1b[0m`);
}

function renderWebReadFullscreen(c: Record<string, unknown>): void {
  const url = str(c.url);
  if (url) process.stdout.write(`\x1b[2mURL:\x1b[0m ${url}\n\n`);
  const results = c.results as Array<Record<string, unknown>> | undefined;
  if (Array.isArray(results)) {
    for (const r of results) {
      const content = str(r.content) ?? str(r.text) ?? "";
      if (content) console.log(trunc(content, 2000));
      console.log();
    }
  }
}

function renderMathCalculatePreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
): void {
  const results = c.results as Array<Record<string, unknown>> | undefined;
  if (Array.isArray(results) && results.length > 0) {
    const first = results[0];
    const expr = str(first.expression) ?? str(first.input) ?? "";
    const result = str(first.result) ?? str(first.output) ?? "";
    if (expr && result) ln(`${trunc(expr, 40)} = ${trunc(result, 40)}`);
    else if (result) ln(trunc(result, 80));
  }
}

function renderMathCalculateFullscreen(c: Record<string, unknown>): void {
  const results = c.results as Array<Record<string, unknown>> | undefined;
  if (!Array.isArray(results) || results.length === 0) {
    console.log("No calculation results.");
    return;
  }
  for (const r of results) {
    const expr = str(r.expression) ?? str(r.input) ?? "";
    const result = str(r.result) ?? str(r.output) ?? "";
    if (expr) process.stdout.write(`  \x1b[2mExpression:\x1b[0m ${expr}\n`);
    if (result) process.stdout.write(`  \x1b[1mResult:\x1b[0m ${result}\n`);
    console.log();
  }
}

// ---------------------------------------------------------------------------
// Reminder
// ---------------------------------------------------------------------------

function renderReminderPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
): void {
  const prompt = str(c.prompt) ?? str(c.message) ?? str(c.reminder_text) ?? "";
  const time = str(c.trigger_at_formatted) ?? str(c.trigger_at) ?? "";
  if (prompt) ln(trunc(prompt, 60));
  if (time) ln(`\x1b[2m🕑 ${time}\x1b[0m`);
  if (c.is_repeating === true) ln("\x1b[2mRepeating\x1b[0m");
}

function renderReminderFullscreen(c: Record<string, unknown>): void {
  const fields: [string, unknown][] = [
    ["Message", c.prompt ?? c.message ?? c.reminder_text],
    ["Time", c.trigger_at_formatted ?? c.trigger_at],
    [
      "Target",
      c.target_type === "new_chat"
        ? "Opens new chat"
        : c.target_type === "same_chat"
          ? "Continues this chat"
          : c.target_type,
    ],
    [
      "Repeating",
      c.is_repeating === true ? "Yes" : c.is_repeating === false ? "No" : null,
    ],
    ["Interval", c.repeat_interval],
  ];
  for (const [label, value] of fields) {
    if (value !== null && value !== undefined) {
      process.stdout.write(`  \x1b[2m${label.padEnd(14)}\x1b[0m ${value}\n`);
    }
  }
}

// ---------------------------------------------------------------------------
// Media types
// ---------------------------------------------------------------------------

function renderImageGeneratePreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
): void {
  const model = str(c.model) ?? "";
  const prompt = str(c.prompt) ?? "";
  if (model) ln(`\x1b[2mModel: ${model}\x1b[0m`);
  if (prompt) ln(trunc(prompt, 60));
  ln("\x1b[2m[image]\x1b[0m");
}

function renderImageGenerateFullscreen(c: Record<string, unknown>): void {
  const fields: [string, unknown][] = [
    ["Model", c.model],
    ["Prompt", c.prompt],
    ["Aspect ratio", c.aspect_ratio],
    ["Files", Array.isArray(c.files) ? `${c.files.length} images` : null],
  ];
  for (const [label, value] of fields) {
    if (value !== null && value !== undefined) {
      process.stdout.write(`  \x1b[2m${label.padEnd(14)}\x1b[0m ${value}\n`);
    }
  }
  console.log("\n  [Images are encrypted — view in web app]");
}

function renderVideoTranscriptPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
): void {
  const title = str(c.title) ?? str(c.video_title) ?? "";
  const channel = str(c.channel) ?? str(c.author) ?? "";
  if (title) ln(trunc(title, 60));
  if (channel) ln(`\x1b[2m${channel}\x1b[0m`);
}

function renderVideoTranscriptFullscreen(c: Record<string, unknown>): void {
  const title = str(c.title) ?? str(c.video_title);
  const url = str(c.url) ?? str(c.video_url);
  if (title) process.stdout.write(`\x1b[1m${title}\x1b[0m\n`);
  if (url) process.stdout.write(`\x1b[2m${url}\x1b[0m\n`);
  console.log();
  const transcript = str(c.transcript) ?? str(c.text) ?? "";
  if (transcript) console.log(trunc(transcript, 3000));
  else console.log("No transcript available.");
}

async function renderHealthSearchPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
  client: OpenMatesClient,
): Promise<void> {
  const count = resolveResultCount(c);
  if (count !== null) ln(`\x1b[2m+ ${count} appointments\x1b[0m`);
  else if (str(c.status) === "finished")
    ln("\x1b[2mNo appointments found\x1b[0m");
}

async function renderHealthSearchFullscreen(
  c: Record<string, unknown>,
  client: OpenMatesClient,
): Promise<void> {
  const results = await resolveChildResults(c, client);
  if (results.length === 0) {
    console.log("No appointments found.");
    return;
  }
  console.log(`${results.length} appointments:\n`);
  for (const r of results) {
    const slotDt = str(r.slot_datetime) ?? str(r.next_slot) ?? str(r.date) ?? "";
    const name = str(r.name) ?? str(r.doctor_name) ?? str(r.title) ?? "";
    const speciality = str(r.speciality) ?? "";
    const address = str(r.address) ?? "";
    if (slotDt) process.stdout.write(`  \x1b[1m${slotDt}\x1b[0m\n`);
    if (name) process.stdout.write(`  ${name}${speciality ? ` · ${speciality}` : ""}\n`);
    if (address) process.stdout.write(`  \x1b[2m${address}\x1b[0m\n`);
    console.log();
  }
}

function renderAudioTranscribePreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
): void {
  const duration = str(c.duration) ?? str(c.length) ?? "";
  const language = str(c.language) ?? "";
  if (duration) ln(`\x1b[2mDuration: ${duration}\x1b[0m`);
  if (language) ln(`\x1b[2mLanguage: ${language}\x1b[0m`);
  const text = str(c.text) ?? str(c.transcript) ?? "";
  if (text) ln(trunc(text, 60));
}

function renderAudioTranscribeFullscreen(c: Record<string, unknown>): void {
  const text = str(c.text) ?? str(c.transcript) ?? "";
  if (text) console.log(text);
  else console.log("No transcript available.");
}

// ---------------------------------------------------------------------------
// Direct-type embeds (not app-skill-use)
// ---------------------------------------------------------------------------

function renderByDirectType(
  embed: DecryptedEmbed,
  c: Record<string, unknown>,
  ln: (s: string) => void,
): void {
  const type = embed.type ?? str(c.type) ?? "";

  switch (type) {
    case "code":
    case "code-code": {
      const lang = str(c.language) ?? "";
      const filename = str(c.filename) ?? "";
      const lineCount = c.line_count;
      if (filename) ln(`\x1b[2m${filename}\x1b[0m`);
      if (lang)
        ln(`\x1b[2m${lang}${lineCount ? `  ${lineCount} lines` : ""}\x1b[0m`);
      const code = str(c.code) ?? str(c.content) ?? "";
      if (code) {
        const lines = code.split("\n").slice(0, 4);
        for (const l of lines) ln(`  ${trunc(l, 80)}`);
        if (code.split("\n").length > 4) ln("  ...");
      }
      break;
    }

    case "docs-doc":
    case "doc": {
      const title = str(c.title) ?? str(c.filename) ?? "";
      const wordCount = c.word_count;
      if (title) ln(title);
      if (wordCount) ln(`\x1b[2m${wordCount} words\x1b[0m`);
      break;
    }

    case "sheets-sheet":
    case "sheet": {
      const title = str(c.title) ?? "";
      const rows = c.row_count ?? c.rows;
      const cols = c.col_count ?? c.cols;
      if (title) ln(title);
      if (rows && cols) ln(`\x1b[2m${rows} rows × ${cols} columns\x1b[0m`);
      const table = str(c.table) ?? str(c.content) ?? "";
      if (table) {
        const tableRows = table
          .split("\n")
          .filter((l) => l.trim().startsWith("|"))
          .slice(0, 4);
        for (const row of tableRows) ln(`  ${trunc(row, 80)}`);
      }
      break;
    }

    case "pdf": {
      const filename = str(c.filename) ?? "";
      const pageCount = c.page_count;
      if (filename) ln(`\x1b[2m${filename}\x1b[0m`);
      if (pageCount) ln(`\x1b[2m${pageCount} pages\x1b[0m`);
      break;
    }

    case "image": {
      const alt = str(c.alt) ?? str(c.caption) ?? "";
      if (alt) ln(trunc(alt, 60));
      ln("\x1b[2m[image]\x1b[0m");
      break;
    }

    case "web-website": {
      const title = str(c.title) ?? "";
      const url = str(c.url) ?? "";
      const desc = str(c.description) ?? str(c.snippet) ?? "";
      if (title) ln(`\x1b[1m${trunc(title, 60)}\x1b[0m`);
      if (url) ln(`\x1b[2m${trunc(url, 60)}\x1b[0m`);
      if (desc) ln(trunc(desc, 100));
      break;
    }

    case "videos-video": {
      const title = str(c.title) ?? "";
      const channel = str(c.channel) ?? str(c.author) ?? "";
      const duration = str(c.duration) ?? "";
      if (title) ln(trunc(title, 60));
      if (channel || duration)
        ln(`\x1b[2m${channel}${duration ? `  ${duration}` : ""}\x1b[0m`);
      break;
    }

    case "travel-connection": {
      const origin = str(c.origin) ?? "";
      const dest = str(c.destination) ?? "";
      const price = formatPrice(c.total_price ?? c.price, c.currency);
      const dep = str(c.departure)?.slice(11, 16) ?? "";
      const arr = str(c.arrival)?.slice(11, 16) ?? "";
      if (origin && dest) ln(`${origin} → ${dest}`);
      if (dep && arr) ln(`${dep} – ${arr}`);
      if (price) ln(`\x1b[2m${price}\x1b[0m`);
      break;
    }

    case "travel-stay": {
      const name = str(c.name) ?? str(c.hotel_name) ?? "";
      const price = formatPrice(c.total_price ?? c.price, c.currency);
      const rating = typeof c.rating === "number" ? `★ ${c.rating}` : "";
      if (name) ln(`${name}${rating ? `  ${rating}` : ""}`);
      if (price) ln(`\x1b[2m${price}\x1b[0m`);
      break;
    }

    case "maps":
    case "maps-place": {
      const name = str(c.displayName) ?? str(c.name) ?? "";
      const address = str(c.formattedAddress) ?? str(c.address) ?? "";
      if (name) ln(name);
      if (address) ln(`\x1b[2m${address}\x1b[0m`);
      break;
    }

    case "recording": {
      const duration = str(c.duration) ?? "";
      if (duration) ln(`\x1b[2mDuration: ${duration}\x1b[0m`);
      ln("\x1b[2m[audio recording]\x1b[0m");
      break;
    }

    case "mail-email": {
      const subject = str(c.subject) ?? "";
      const receiver = str(c.receiver) ?? "";
      if (subject) ln(trunc(subject, 60));
      if (receiver) ln(`\x1b[2mTo: ${receiver}\x1b[0m`);
      break;
    }

    case "math-plot": {
      ln("\x1b[2m[mathematical plot]\x1b[0m");
      break;
    }

    case "images-image-result": {
      const title = str(c.title) ?? "";
      const source = str(c.source) ?? str(c.url) ?? "";
      if (title) ln(trunc(title, 60));
      if (source) ln(`\x1b[2m${trunc(source, 60)}\x1b[0m`);
      break;
    }

    case "events-event": {
      const name = str(c.name) ?? str(c.title) ?? "";
      const date = str(c.date) ?? str(c.start_date) ?? "";
      const venue = str(c.venue) ?? str(c.location) ?? "";
      if (name) ln(name);
      if (date || venue)
        ln(`\x1b[2m${[date, venue].filter(Boolean).join("  @ ")}\x1b[0m`);
      break;
    }

    case "focus-mode-activation": {
      const modeName = str(c.focus_mode_name) ?? "";
      if (modeName) ln(`Focus mode: ${modeName}`);
      break;
    }

    default: {
      // Generic fallback: show first few non-internal fields
      let count = 0;
      for (const [k, v] of Object.entries(c)) {
        if (count >= 4) break;
        if (
          v !== null &&
          v !== undefined &&
          typeof v !== "object" &&
          !k.startsWith("_")
        ) {
          ln(`\x1b[2m${k}: ${trunc(String(v), 80)}\x1b[0m`);
          count++;
        }
      }
    }
  }
}

function renderDirectTypeFullscreen(
  embed: DecryptedEmbed,
  c: Record<string, unknown>,
): void {
  const type = embed.type ?? str(c.type) ?? "";

  switch (type) {
    case "code":
    case "code-code": {
      const lang = str(c.language);
      const filename = str(c.filename);
      const code = str(c.code) ?? str(c.content) ?? "";
      if (filename) process.stdout.write(`\x1b[2mFile:\x1b[0m ${filename}\n`);
      if (lang) process.stdout.write(`\x1b[2mLanguage:\x1b[0m ${lang}\n`);
      console.log();
      if (code) console.log(trunc(code, 5000));
      break;
    }

    case "docs-doc":
    case "doc": {
      const title = str(c.title);
      const html = str(c.html) ?? "";
      if (title) process.stdout.write(`\x1b[1m${title}\x1b[0m\n\n`);
      if (html) {
        // Strip HTML for text output
        const text = html
          .replace(/<[^>]+>/g, " ")
          .replace(/\s+/g, " ")
          .trim();
        console.log(trunc(text, 3000));
      }
      break;
    }

    case "sheets-sheet":
    case "sheet": {
      const title = str(c.title);
      const table = str(c.table) ?? str(c.content) ?? "";
      if (title) process.stdout.write(`\x1b[1m${title}\x1b[0m\n\n`);
      if (table) console.log(trunc(table, 3000));
      break;
    }

    case "pdf": {
      const filename = str(c.filename);
      if (filename) process.stdout.write(`\x1b[2mFile:\x1b[0m ${filename}\n`);
      const results = c.results as Array<Record<string, unknown>> | undefined;
      if (Array.isArray(results)) {
        for (const r of results) {
          const content = str(r.content) ?? str(r.text) ?? "";
          if (content) {
            console.log();
            console.log(trunc(content, 3000));
          }
        }
      }
      break;
    }

    case "web-website": {
      const title = str(c.title);
      const url = str(c.url);
      const desc = str(c.description) ?? str(c.snippet) ?? "";
      const age = str(c.page_age);
      if (title) process.stdout.write(`\x1b[1m${title}\x1b[0m\n`);
      if (url) process.stdout.write(`\x1b[2m${url}\x1b[0m\n`);
      if (age) process.stdout.write(`\x1b[2mAge: ${age}\x1b[0m\n`);
      if (desc) {
        console.log();
        console.log(desc);
      }
      break;
    }

    case "videos-video": {
      const title = str(c.title);
      const url = str(c.url);
      const channel = str(c.channel) ?? str(c.author) ?? "";
      const duration = str(c.duration) ?? "";
      const desc = str(c.description) ?? str(c.snippet) ?? "";
      if (title) process.stdout.write(`\x1b[1m${title}\x1b[0m\n`);
      if (url) process.stdout.write(`\x1b[2m${url}\x1b[0m\n`);
      if (channel)
        process.stdout.write(
          `\x1b[2mChannel:\x1b[0m ${channel}${duration ? `  \x1b[2m(${duration})\x1b[0m` : ""}\n`,
        );
      if (desc) {
        console.log();
        console.log(desc);
      }
      break;
    }

    case "mail-email": {
      const subject = str(c.subject);
      const receiver = str(c.receiver);
      const content = str(c.content) ?? "";
      if (subject) process.stdout.write(`\x1b[1m${subject}\x1b[0m\n`);
      if (receiver) process.stdout.write(`\x1b[2mTo: ${receiver}\x1b[0m\n`);
      if (content) {
        console.log();
        console.log(trunc(content, 2000));
      }
      break;
    }

    default: {
      // Generic: show all non-null fields
      for (const [k, v] of Object.entries(c)) {
        if (v === null || v === undefined || k.startsWith("_")) continue;
        if (typeof v === "object") {
          process.stdout.write(
            `  \x1b[2m${k.padEnd(20)}\x1b[0m ${JSON.stringify(v).slice(0, 120)}\n`,
          );
        } else {
          process.stdout.write(
            `  \x1b[2m${k.padEnd(20)}\x1b[0m ${trunc(String(v), 100)}\n`,
          );
        }
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

/** Resolve result count from inline results, embed_ids, or result_count field */
function resolveResultCount(c: Record<string, unknown>): number | null {
  if (typeof c.result_count === "number") return c.result_count;
  const results = c.results;
  if (Array.isArray(results)) return results.length;
  const ids = parseEmbedIds(c.embed_ids);
  if (ids.length > 0) return ids.length;
  return null;
}

/** Load child embeds from embed_ids or inline results */
async function resolveChildResults(
  c: Record<string, unknown>,
  client: OpenMatesClient,
): Promise<Array<Record<string, unknown>>> {
  // Try inline results first
  const inline = c.results;
  if (Array.isArray(inline) && inline.length > 0) {
    return inline as Array<Record<string, unknown>>;
  }

  // Load from embed_ids
  const ids = parseEmbedIds(c.embed_ids);
  const results: Array<Record<string, unknown>> = [];
  for (const id of ids) {
    try {
      const child = await client.getEmbed(id);
      const content = (child.content ?? {}) as Record<string, unknown>;
      // Only include children that actually have content (not empty from
      // failed decryption). Check for at least one non-internal field.
      const hasContent = Object.keys(content).some(
        (k) =>
          !k.startsWith("_") && content[k] !== null && content[k] !== undefined,
      );
      if (hasContent) results.push(content);
    } catch {
      // skip unresolvable
    }
  }
  return results;
}

/** Format timestamp */
function formatTs(ts: number | null | undefined): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toISOString().slice(0, 16).replace("T", " ");
}
