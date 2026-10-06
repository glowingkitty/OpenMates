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
 * 3. Update docs/contributing/guides/add-embed-type.md checklist
 *
 * Architecture doc: docs/architecture/openmates-cli.md
 * Tests: frontend/packages/openmates-cli/tests/
 */

import type { DecryptedEmbed } from "./client.js";
import type { OpenMatesClient } from "./client.js";
import qrcode from "qrcode-terminal";
import { terminalText } from "./tuiText.js";

type EmbedWriter = (chunk: string) => void;
const stdoutWriter: EmbedWriter = chunk => { process.stdout.write(chunk); };
const writeEmbedLine = (write: EmbedWriter, text = "") => write(`${text}\n`);

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
  "code-application",
  "application",
  "docs-doc",
  "doc",
  "document",
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
  "mindmap",
  "mindmaps-mindmap",
  "events-event",
  "health-appointment",
  "shopping-product",
  "images-image-result",
  "news-article",
  "tasks-task",
  "workflows-workflow",
]);

/** Human-readable labels for direct types */
const DIRECT_TYPE_LABELS: Record<string, string> = {
  "code": "code",
  "code-code": "code",
  "code-application": "application",
  "application": "application",
  "docs-doc": "document",
  "doc": "document",
  "document": "document",
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
  "mindmap": "Mind Map",
  "mindmaps-mindmap": "Mind Map",
  "events-event": "event",
  "health-appointment": "appointment",
  "shopping-product": "product",
  "images-image-result": "image",
  "news-article": "article",
  "tasks-task": "task",
  "workflows-workflow": "workflow",
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

function fareNumberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function fareRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function formatFare(value: Record<string, unknown>): string {
  const fare = fareRecord(value.fare);
  const confidence = str(fare?.confidence);
  if (confidence === "timetable_only") return "Timetable only";
  if (fare?.is_pass_only === true) return str(fare.summary) ?? "Covered by pass";
  const amount = fare?.amount ?? value.total_price ?? value.price;
  const currency = fare?.currency ?? value.currency;
  const price = formatPrice(amount, currency);
  if (!price) return confidence === "unknown" ? "Fare unknown" : "";
  if (fare?.is_partial === true || value.fare_is_partial === true) return `${price} (partial fare)`;
  return price;
}

/** Truncate string */
function trunc(s: string, max: number): string {
  return s.length > max ? s.slice(0, max) + "…" : s;
}

function stripAnsi(value: string): string {
  return value.replace(new RegExp(`${String.fromCharCode(27)}\\[[0-9;]*m`, "g"), "");
}

function extractTextLines(value: unknown): string[] {
  if (typeof value === "string") return value.split("\n");
  if (Array.isArray(value)) return value.flatMap(extractTextLines);
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return [
      ...extractTextLines(record.content),
      ...extractTextLines(record.text),
      ...extractTextLines(record.markdown),
      ...extractTextLines(record.body),
      ...extractTextLines(record.source),
      ...extractTextLines(record.code),
    ];
  }
  return [];
}

function extractFileNames(value: unknown): string[] {
  if (!value || typeof value !== "object") return [];
  const record = value as Record<string, unknown>;
  if (Array.isArray(record.files)) {
    return record.files
      .map((file) => typeof file === "string" ? file : str((file as Record<string, unknown>)?.name) ?? str((file as Record<string, unknown>)?.path))
      .filter((file): file is string => Boolean(file));
  }
  if (record.files && typeof record.files === "object") return Object.keys(record.files as Record<string, unknown>);
  return [];
}

export function formatEmbedPreviewLines(embed: DecryptedEmbed, maxContentLines = 8): string[] {
  const shortId = embed.embedId.slice(0, 8);
  const c = (embed.content ?? {}) as Record<string, unknown>;
  const resolvedType = embed.type ?? str(c.type) ?? "embed";
  if (resolvedType === "tasks-task") return formatTaskEmbedPreviewLines(c, shortId);
  if (resolvedType === "workflows-workflow") return formatWorkflowEmbedPreviewLines(c, shortId);
  const app = embed.appId ?? str(c.app_id) ?? "";
  const skill = embed.skillId ?? str(c.skill_id) ?? "";
  const label = skill ? `${app}/${skill}` : (app || DIRECT_TYPE_LABELS[resolvedType] || resolvedType);
  const title = str(c.title) ?? str(c.name) ?? str(c.query) ?? embed.textPreview ?? "";
  const status = stripAnsi(statusIcon(str(c.status)) || statusIcon("finished"));
  const lines = [`┌─ ${status} ${label}${title ? ` · ${trunc(title, 56)}` : ""}`];

  const fileNames = extractFileNames(c);
  if (fileNames.length > 0) {
    lines.push(`│  Files: ${trunc(fileNames.slice(0, 4).join(", "), 72)}`);
    if (fileNames.length > 4) lines.push(`│  ... ${fileNames.length - 4} more file(s)`);
  }

  const textLines = extractTextLines(c)
    .map((line) => line.trimEnd())
    .filter((line) => line.trim().length > 0 && !line.trim().startsWith("{") && !line.trim().startsWith("["));
  const previewLines = textLines.slice(0, maxContentLines);
  if (previewLines.length > 0) {
    if (lines.length > 1) lines.push("│");
    for (const line of previewLines) lines.push(`│  ${trunc(line, 76)}`);
    if (textLines.length > previewLines.length) lines.push("│  ...");
  }

  lines.push(`└─ openmates embeds show ${shortId}`);
  return lines;
}

function formatTaskEmbedPreviewLines(c: Record<string, unknown>, fallbackShortId: string): string[] {
  const taskId = str(c.short_id) ?? str(c.task_id) ?? fallbackShortId;
  const title = str(c.title) ?? str(c.name) ?? "Untitled task";
  const status = str(c.status) ?? "todo";
  const assignee = str(c.assignee) ?? str(c.assignee_identity) ?? str(c.assignee_type) ?? "user";
  return [
    `┌─ ✓ task · ${taskId} · ${trunc(title, 56)}`,
    `│  Status: ${status}`,
    `│  Assignee: ${assignee}`,
    `└─ openmates tasks show ${taskId}`,
  ];
}

function formatWorkflowEmbedPreviewLines(c: Record<string, unknown>, fallbackShortId: string): string[] {
  const workflowId = str(c.workflow_id) ?? str(c.id) ?? fallbackShortId;
  const title = str(c.title) ?? str(c.name) ?? "Untitled workflow";
  const status = str(c.status) ?? "draft";
  return [
    `┌─ ✓ workflow · ${trunc(title, 56)}`,
    `│  Status: ${status}`,
    `│  ID: ${workflowId}`,
    `└─ openmates workflows show ${workflowId}`,
  ];
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

    case "videos/create":
      await renderRemotionCreatePreview(embed, c, ln, client);
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
  write: EmbedWriter = stdoutWriter,
  createShareLinks = true,
): Promise<void> {
  const c = (embed.content ?? {}) as Record<string, unknown>;
  const resolvedType = embed.type ?? str(c.type) ?? "";

  // Child embeds with a direct type — use type-specific fullscreen renderer.
  if (DIRECT_TYPES.has(resolvedType)) {
    const typeLabel = DIRECT_TYPE_LABELS[resolvedType] ?? resolvedType;
    write(
      `\x1b[1m${typeLabel}\x1b[0m  \x1b[2m${embed.embedId.slice(0, 8)}\x1b[0m\n`,
    );
    if (embed.createdAt)
      write(
        `\x1b[2mCreated:\x1b[0m ${formatTs(embed.createdAt)}\n`,
      );
    write("\n");
    renderDirectTypeFullscreen(embed, c, write);
    return;
  }

  const app = embed.appId ?? str(embed.content?.app_id) ?? "";
  const skill = embed.skillId ?? str(embed.content?.skill_id) ?? "";
  const label = skill ? `${app}/${skill}` : app || "embed";
  const status = str(c.status);

  // Header
  write(`\x1b[1m${label}\x1b[0m`);
  if (status) write(`  ${statusLabel(status)}`);
  write(`  \x1b[2m${embed.embedId.slice(0, 8)}\x1b[0m\n`);

  const query = str(c.query) ?? str(c.search_query) ?? str(c.question);
  const provider = str(c.provider);
  if (query) write(`\x1b[2mQuery:\x1b[0m ${query}\n`);
  if (provider) write(`\x1b[2mProvider:\x1b[0m ${provider}\n`);
  if (embed.createdAt)
    write(
      `\x1b[2mCreated:\x1b[0m ${formatTs(embed.createdAt)}\n`,
    );

  const error = str(c.error) ?? str(c.error_message);
  if (error) {
    write(`\n\x1b[31mError:\x1b[0m ${error}\n`);
  }

  write("\n");

  // Type-specific detail
  const key = `${app}/${skill}`;
  switch (key) {
    case "web/search":
    case "news/search":
    case "shopping/search_products":
    case "images/search":
    case "mail/search":
      await renderSearchFullscreen(c, client, write);
      break;

    case "events/search":
      await renderEventsSearchFullscreen(c, client, write);
      break;

    case "videos/search":
      await renderVideosSearchFullscreen(c, client, write);
      break;

    case "maps/search":
      renderMapsSearchFullscreen(c, write);
      break;

    case "travel/search_connections":
      await renderTravelConnectionsFullscreen(c, client, write);
      break;

    case "travel/search_stays":
      await renderTravelStaysFullscreen(c, client, write);
      break;

    case "travel/price_calendar":
      renderTravelPriceCalendarFullscreen(c, write);
      break;

    case "travel/get_flight":
      renderTravelFlightFullscreen(c, write);
      break;

    case "code/get_docs":
      renderCodeDocsFullscreen(c, write);
      break;

    case "web/read":
      renderWebReadFullscreen(c, write);
      break;

    case "math/calculate":
      renderMathCalculateFullscreen(c, write);
      break;

    case "reminder/set-reminder":
    case "reminder/list-reminders":
    case "reminder/cancel-reminder":
      renderReminderFullscreen(c, write);
      break;

    case "images/generate":
    case "images/generate_draft":
      renderImageGenerateFullscreen(c, write);
      break;

    case "videos/get_transcript":
      renderVideoTranscriptFullscreen(c, write);
      break;

    case "videos/create":
      await renderRemotionCreateFullscreen(embed, c, client, write, createShareLinks);
      break;

    case "health/search_appointments":
      await renderHealthSearchFullscreen(c, client, write);
      break;

    case "audio/transcribe":
      renderAudioTranscribeFullscreen(c, write);
      break;

    default:
      renderDirectTypeFullscreen(embed, c, write);
      break;
  }
}

// ---------------------------------------------------------------------------
// Search types (web, news, shopping, images, mail)
// ---------------------------------------------------------------------------

/** Complete fullscreen content for the TUI, without terminal writes or share mutations. */
export async function formatEmbedFullscreenLines(embed: DecryptedEmbed, client: OpenMatesClient): Promise<string[]> {
  let output = "";
  await renderEmbedFullscreen(embed, client, chunk => {output += chunk;}, false);
  return terminalText(output).trimEnd().split("\n");
}

async function renderSearchPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
  _client: OpenMatesClient,
): Promise<void> {
  const count = resolveResultCount(c);
  if (count !== null) ln(`\x1b[2m+ ${count} results\x1b[0m`);
  else if (str(c.status) === "finished") ln("\x1b[2mNo results\x1b[0m");
}

async function renderSearchFullscreen(
  c: Record<string, unknown>,
  client: OpenMatesClient,
  write: EmbedWriter,
): Promise<void> {
  const results = await resolveChildResults(c, client);
  if (results.length === 0) {
    writeEmbedLine(write, "No results found.");
    return;
  }
  writeEmbedLine(write, `${results.length} results:\n`);
  for (const r of results) {
    const title = str(r.title) ?? str(r.name) ?? "";
    const url = str(r.url) ?? str(r.link) ?? "";
    const desc = str(r.description) ?? str(r.snippet) ?? str(r.summary) ?? "";
    const age = str(r.page_age);
    if (title) write(`  \x1b[1m${title}\x1b[0m\n`);
    if (url) write(`  \x1b[2m${url}\x1b[0m\n`);
    if (age) write(`  \x1b[2m${age}\x1b[0m\n`);
    if (desc) write(`  ${desc}\n`);
    write(`  \x1b[2m${"─".repeat(40)}\x1b[0m\n`);
  }
}

// ── Events search ────────────────────────────────────────────────────────

async function renderEventsSearchPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
  _client: OpenMatesClient,
): Promise<void> {
  const count = resolveResultCount(c);
  if (count !== null) ln(`\x1b[2m+ ${count} events\x1b[0m`);
  else if (str(c.status) === "finished") ln("\x1b[2mNo events found\x1b[0m");
}

async function renderEventsSearchFullscreen(
  c: Record<string, unknown>,
  client: OpenMatesClient,
  write: EmbedWriter,
): Promise<void> {
  const results = await resolveChildResults(c, client);
  if (results.length === 0) {
    writeEmbedLine(write, "No events found.");
    return;
  }
  writeEmbedLine(write, `${results.length} events:\n`);
  for (const r of results) {
    const name = str(r.name) ?? str(r.title) ?? "";
    const date = str(r.date) ?? str(r.start_date) ?? str(r.dateTime) ?? "";
    const venue = str(r.venue) ?? str(r.location) ?? "";
    const url = str(r.url) ?? str(r.link) ?? "";
    const desc = str(r.description) ?? str(r.summary) ?? "";
    const going = typeof r.going_count === "number" ? r.going_count : null;
    if (name) write(`  \x1b[1m${name}\x1b[0m\n`);
    if (date) write(`  \x1b[2m${date}\x1b[0m`);
    if (venue) write(`  \x1b[2m@ ${venue}\x1b[0m`);
    if (date || venue) write("\n");
    if (going !== null)
      write(`  \x1b[2m${going} going\x1b[0m\n`);
    if (desc) write(`  ${desc}\n`);
    if (url) write(`  \x1b[2m${url}\x1b[0m\n`);
    write(`  \x1b[2m${"─".repeat(40)}\x1b[0m\n`);
  }
}

// ── Videos search ────────────────────────────────────────────────────────

async function renderVideosSearchPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
  _client: OpenMatesClient,
): Promise<void> {
  const count = resolveResultCount(c);
  if (count !== null) ln(`\x1b[2m+ ${count} videos\x1b[0m`);
  else if (str(c.status) === "finished") ln("\x1b[2mNo videos found\x1b[0m");
}

async function renderVideosSearchFullscreen(
  c: Record<string, unknown>,
  client: OpenMatesClient,
  write: EmbedWriter,
): Promise<void> {
  const results = await resolveChildResults(c, client);
  if (results.length === 0) {
    writeEmbedLine(write, "No videos found.");
    return;
  }
  writeEmbedLine(write, `${results.length} videos:\n`);
  for (const r of results) {
    const title = str(r.title) ?? "";
    const channel = str(r.channel) ?? str(r.author) ?? "";
    const duration = str(r.duration) ?? "";
    const url = str(r.url) ?? str(r.link) ?? "";
    if (title) write(`  \x1b[1m${title}\x1b[0m\n`);
    if (channel || duration) {
      write(
        `  \x1b[2m${channel}${duration ? `  ${duration}` : ""}\x1b[0m\n`,
      );
    }
    if (url) write(`  \x1b[2m${url}\x1b[0m\n`);
    writeEmbedLine(write);
  }
}

async function renderRemotionCreatePreview(
  embed: DecryptedEmbed,
  c: Record<string, unknown>,
  ln: (s: string) => void,
  client: OpenMatesClient,
): Promise<void> {
  const meta = remotionMeta(c);
  ln(`\x1b[1m${meta.filename}\x1b[0m`);
  ln(`${meta.statusText}  \x1b[2mv${meta.sourceVersion} · ${meta.durationSeconds}s · ${meta.width}x${meta.height}\x1b[0m`);
  if (meta.layers.length > 0) {
    ln(`Timeline: ${meta.layers.slice(0, 4).join(" → ")}`);
  }
  if (meta.error) {
    ln(`\x1b[31m${meta.error}\x1b[0m`);
  }
  if (meta.status === "finished") {
    await renderRemotionShareLink(embed.embedId, client, ln);
  }
}

async function renderRemotionCreateFullscreen(
  embed: DecryptedEmbed,
  c: Record<string, unknown>,
  client: OpenMatesClient,
  write: EmbedWriter,
  createShareLinks: boolean,
): Promise<void> {
  const meta = remotionMeta(c);
  write(`\x1b[1m${meta.filename}\x1b[0m\n`);
  write(`${meta.statusText}  \x1b[2mv${meta.sourceVersion} · ${meta.durationSeconds}s · ${meta.width}x${meta.height}\x1b[0m\n\n`);

  if (meta.layers.length > 0) {
    write("Timeline:\n");
    for (const layer of meta.layers) {
      write(`  - ${layer}\n`);
    }
    write("\n");
  }

  if (meta.source) {
    write("Source:\n");
    write("```tsx\n");
    write(`${meta.source.trim()}\n`);
    write("```\n\n");
  }

  if (meta.error) {
    write(`\x1b[31mError:\x1b[0m ${meta.error}\n\n`);
  }

  if (createShareLinks && meta.status === "finished") {
    await renderRemotionShareLink(embed.embedId, client, (line) => write(`${line}\n`));
  } else if(meta.status !== "finished") {
    write("Run again after rendering finishes to get the rendered video link and QR code.\n");
  }
}

async function renderRemotionShareLink(
  embedId: string,
  client: OpenMatesClient,
  ln: (s: string) => void,
): Promise<void> {
  try {
    const url = await client.createEmbedShareLink(embedId);
    ln(`Rendered video link: ${url}`);
    ln("QR code:");
    const qr = await generateQr(url);
    for (const line of qr.split("\n")) {
      if (line.trim().length > 0) ln(line);
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    ln(`\x1b[2mShare link unavailable: ${message}\x1b[0m`);
  }
}

function generateQr(value: string): Promise<string> {
  return new Promise((resolve) => {
    qrcode.generate(value, { small: true }, (qr) => resolve(qr));
  });
}

function remotionMeta(c: Record<string, unknown>): {
  filename: string;
  status: string;
  statusText: string;
  source: string;
  sourceVersion: number;
  durationSeconds: number;
  width: number;
  height: number;
  layers: string[];
  error: string | null;
} {
  const source = str(c.remotion_source) ?? str(c.source) ?? "";
  const fps = firstInt(source, /fps\s*[:=]\s*(\d+)/) ?? 30;
  const frames = firstInt(source, /durationInFrames\s*[:=]\s*(\d+)/) ?? 150;
  const status = str(c.status) ?? "processing";
  return {
    filename: str(c.filename) ?? str(c.title) ?? "Composition.tsx",
    status,
    statusText: remotionStatusText(status),
    source,
    sourceVersion: numberValue(c.current_source_version ?? c.source_version) ?? 1,
    durationSeconds: Math.max(1, Math.ceil(frames / Math.max(1, fps))),
    width: firstInt(source, /width\s*[:=]\s*(\d+)/) ?? 1920,
    height: firstInt(source, /height\s*[:=]\s*(\d+)/) ?? 1080,
    layers: remotionLayers(source),
    error: str(c.error) ?? str(c.error_message),
  };
}

function remotionStatusText(status: string): string {
  switch (status) {
    case "rendering": return "Rendering video...";
    case "processing": return "Preparing Remotion source...";
    case "finished": return "Rendered video ready";
    case "cancelled": return "Render stopped";
    case "needs_rerender": return "Needs rerender";
    case "error": return "Render failed";
    default: return status;
  }
}

function remotionLayers(source: string): string[] {
  const names = [...source.matchAll(/<([A-Z][A-Za-z0-9]*)\b/g)]
    .map((match) => match[1])
    .filter((name) => name && !["AbsoluteFill", "Sequence", "Img", "Audio", "Video"].includes(name));
  return Array.from(new Set(names.length > 0 ? names : ["Composition"])).slice(0, 6);
}

function firstInt(source: string, regex: RegExp): number | null {
  const match = regex.exec(source);
  if (!match?.[1]) return null;
  const value = Number.parseInt(match[1], 10);
  return Number.isFinite(value) ? value : null;
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
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

function renderMapsSearchFullscreen(c: Record<string, unknown>, write: EmbedWriter): void {
  const results = c.results as Array<Record<string, unknown>> | undefined;
  if (!Array.isArray(results) || results.length === 0) {
    writeEmbedLine(write, "No places found.");
    return;
  }
  writeEmbedLine(write, `${results.length} places:\n`);
  for (const r of results) {
    const name = str(r.displayName) ?? str(r.name) ?? "";
    const address = str(r.formattedAddress) ?? str(r.address) ?? "";
    const rating = typeof r.rating === "number" ? `★ ${r.rating}` : "";
    if (name)
      write(
        `  \x1b[1m${name}\x1b[0m${rating ? `  ${rating}` : ""}\n`,
      );
    if (address) write(`  \x1b[2m${address}\x1b[0m\n`);
    writeEmbedLine(write);
  }
}

// ---------------------------------------------------------------------------
// Travel types
// ---------------------------------------------------------------------------

async function renderTravelConnectionsPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
  _client: OpenMatesClient,
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
      .map((r) => {
        const fare = fareRecord(r.fare);
        const confidence = str(fare?.confidence);
        if (confidence && !["confirmed", "partial"].includes(confidence)) return null;
        return fareNumberValue(fare?.amount ?? r.total_price);
      })
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
  write: EmbedWriter,
): Promise<void> {
  const results = await resolveChildResults(c, client);
  if (results.length === 0) {
    writeEmbedLine(write, "No connections found.");
    return;
  }
  writeEmbedLine(write, `${results.length} connections:\n`);
  for (const r of results) {
    const origin = str(r.origin) ?? "";
    const dest = str(r.destination) ?? "";
    const dep = str(r.departure)?.slice(11, 16) ?? "";
    const arr = str(r.arrival)?.slice(11, 16) ?? "";
    const duration = str(r.duration) ?? "";
    const price = formatFare(r);
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
      write(`  \x1b[1m${origin} → ${dest}\x1b[0m\n`);
    if (dep && arr)
      write(
        `  ${dep} – ${arr}${duration ? `  (${duration})` : ""}\n`,
      );
    if (price || stops || carriers) {
      write(
        `  \x1b[2m${[price, stops, carriers].filter(Boolean).join("  · ")}\x1b[0m\n`,
      );
    }
    writeEmbedLine(write);
  }
}

async function renderTravelStaysPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
  _client: OpenMatesClient,
): Promise<void> {
  const count = resolveResultCount(c);
  if (count !== null) ln(`\x1b[2m${count} stays\x1b[0m`);
}

async function renderTravelStaysFullscreen(
  c: Record<string, unknown>,
  client: OpenMatesClient,
  write: EmbedWriter,
): Promise<void> {
  const results = await resolveChildResults(c, client);
  if (results.length === 0) {
    writeEmbedLine(write, "No stays found.");
    return;
  }
  writeEmbedLine(write, `${results.length} stays:\n`);
  for (const r of results) {
    const name = str(r.name) ?? str(r.hotel_name) ?? "";
    const price = formatPrice(r.total_price ?? r.price, r.currency);
    const rating = typeof r.rating === "number" ? `★ ${r.rating}` : "";
    const address = str(r.address) ?? "";

    if (name)
      write(
        `  \x1b[1m${name}\x1b[0m${rating ? `  ${rating}` : ""}\n`,
      );
    if (price) write(`  ${price}\n`);
    if (address) write(`  \x1b[2m${address}\x1b[0m\n`);
    writeEmbedLine(write);
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

function renderTravelPriceCalendarFullscreen(c: Record<string, unknown>, write: EmbedWriter): void {
  const prices = c.prices as Array<Record<string, unknown>> | undefined;
  if (!Array.isArray(prices) || prices.length === 0) {
    writeEmbedLine(write, "No price data available.");
    return;
  }
  const currency = str(c.currency) ?? "EUR";
  writeEmbedLine(write, `Price calendar (${prices.length} dates):\n`);
  for (const p of prices.slice(0, 14)) {
    const date = str(p.date) ?? "";
    const price = p.price ?? p.amount;
    if (date && price !== undefined) {
      write(`  ${date}  ${currency} ${price}\n`);
    }
  }
  if (prices.length > 14) writeEmbedLine(write, `  ... and ${prices.length - 14} more`);
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

function renderTravelFlightFullscreen(c: Record<string, unknown>, write: EmbedWriter): void {
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
      write(`  \x1b[2m${label.padEnd(14)}\x1b[0m ${value}\n`);
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

function renderCodeDocsFullscreen(c: Record<string, unknown>, write: EmbedWriter): void {
  const results = c.results as Array<Record<string, unknown>> | undefined;
  const first = Array.isArray(results) ? results[0] : null;
  const docs =
    str(first?.documentation as string) ?? str(c.documentation as string) ?? "";
  if (docs) {
    writeEmbedLine(write, docs);
  } else {
    writeEmbedLine(write, "No documentation content.");
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

function renderWebReadFullscreen(c: Record<string, unknown>, write: EmbedWriter): void {
  const url = str(c.url);
  if (url) write(`\x1b[2mURL:\x1b[0m ${url}\n\n`);
  const results = c.results as Array<Record<string, unknown>> | undefined;
  if (Array.isArray(results)) {
    for (const r of results) {
      const content = str(r.content) ?? str(r.text) ?? "";
      if (content) writeEmbedLine(write, content);
      writeEmbedLine(write);
    }
  }
}

function renderMathCalculatePreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
): void {
  const results = c.results as Array<Record<string, unknown>> | undefined;
  const title = str(c.title);
  if (title) ln(trunc(title, 80));
  if (Array.isArray(results) && results.length > 0) {
    const first = results[0];
    const expr = str(first.expression) ?? str(first.input) ?? "";
    const result = str(first.result) ?? str(first.output) ?? "";
    if (expr && result) ln(`${trunc(expr, 40)} = ${trunc(result, 40)}`);
    else if (result) ln(trunc(result, 80));
  }
}

function renderMathCalculateFullscreen(c: Record<string, unknown>, write: EmbedWriter): void {
  const results = c.results as Array<Record<string, unknown>> | undefined;
  const title = str(c.title);
  if (title) write(`  \x1b[2mTitle:\x1b[0m ${title}\n`);
  if (!Array.isArray(results) || results.length === 0) {
    writeEmbedLine(write, "No calculation results.");
    return;
  }
  for (const r of results) {
    const resultTitle = str(r.title);
    const expr = str(r.expression) ?? str(r.input) ?? "";
    const result = str(r.result) ?? str(r.output) ?? "";
    if (resultTitle && resultTitle !== title) write(`  \x1b[2mTitle:\x1b[0m ${resultTitle}\n`);
    if (expr) write(`  \x1b[2mExpression:\x1b[0m ${expr}\n`);
    if (result) write(`  \x1b[1mResult:\x1b[0m ${result}\n`);
    writeEmbedLine(write);
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

function renderReminderFullscreen(c: Record<string, unknown>, write: EmbedWriter): void {
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
      write(`  \x1b[2m${label.padEnd(14)}\x1b[0m ${value}\n`);
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

function renderImageGenerateFullscreen(c: Record<string, unknown>, write: EmbedWriter): void {
  const fields: [string, unknown][] = [
    ["Model", c.model],
    ["Prompt", c.prompt],
    ["Aspect ratio", c.aspect_ratio],
    ["Files", Array.isArray(c.files) ? `${c.files.length} images` : null],
  ];
  for (const [label, value] of fields) {
    if (value !== null && value !== undefined) {
      write(`  \x1b[2m${label.padEnd(14)}\x1b[0m ${value}\n`);
    }
  }
  writeEmbedLine(write, "\n  [Images are encrypted — view in web app]");
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

function renderVideoTranscriptFullscreen(c: Record<string, unknown>, write: EmbedWriter): void {
  const title = str(c.title) ?? str(c.video_title);
  const url = str(c.url) ?? str(c.video_url);
  if (title) write(`\x1b[1m${title}\x1b[0m\n`);
  if (url) write(`\x1b[2m${url}\x1b[0m\n`);
  writeEmbedLine(write);
  const transcript = str(c.transcript) ?? str(c.text) ?? "";
  if (transcript) writeEmbedLine(write, transcript);
  else writeEmbedLine(write, "No transcript available.");
}

async function renderHealthSearchPreview(
  c: Record<string, unknown>,
  ln: (s: string) => void,
  _client: OpenMatesClient,
): Promise<void> {
  const count = resolveResultCount(c);
  if (count !== null) ln(`\x1b[2m+ ${count} appointments\x1b[0m`);
  else if (str(c.status) === "finished")
    ln("\x1b[2mNo appointments found\x1b[0m");
}

async function renderHealthSearchFullscreen(
  c: Record<string, unknown>,
  client: OpenMatesClient,
  write: EmbedWriter,
): Promise<void> {
  const results = await resolveChildResults(c, client);
  if (results.length === 0) {
    writeEmbedLine(write, "No appointments found.");
    return;
  }
  writeEmbedLine(write, `${results.length} appointments:\n`);
  for (const r of results) {
    const slotDt = str(r.slot_datetime) ?? str(r.next_slot) ?? str(r.date) ?? "";
    const name = str(r.name) ?? str(r.doctor_name) ?? str(r.title) ?? "";
    const speciality = str(r.speciality) ?? "";
    const address = str(r.address) ?? "";
    if (slotDt) write(`  \x1b[1m${slotDt}\x1b[0m\n`);
    if (name) write(`  ${name}${speciality ? ` · ${speciality}` : ""}\n`);
    if (address) write(`  \x1b[2m${address}\x1b[0m\n`);
    writeEmbedLine(write);
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

function renderAudioTranscribeFullscreen(c: Record<string, unknown>, write: EmbedWriter): void {
  const text = str(c.text) ?? str(c.transcript) ?? "";
  if (text) writeEmbedLine(write, text);
  else writeEmbedLine(write, "No transcript available.");
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

    case "code-application":
    case "application": {
      const name = str(c.name) ?? str(c.title) ?? "Generated application";
      const framework = str(c.framework) ?? "";
      const runtime = str(c.runtime) ?? "";
      ln(name);
      if (framework || runtime) {
        ln(`\x1b[2m${[framework, runtime].filter(Boolean).join("  ")}\x1b[0m`);
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

    case "document": {
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
      const price = formatFare(c);
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

    case "mindmap":
    case "mindmaps-mindmap": {
      const document = mindMapDocumentFromContent(c);
      const title = str(c.title) ?? str(document?.title) ?? "Mind Map";
      const nodeCount = typeof c.node_count === "number" ? c.node_count : document?.nodes.length;
      const edgeCount = typeof c.edge_count === "number" ? c.edge_count : document?.edges?.length ?? 0;
      ln(title);
      if (nodeCount !== undefined) ln(`\x1b[2m${nodeCount} nodes · ${edgeCount} edges\x1b[0m`);
      const outline = document ? mindMapOutline(document, 8) : "";
      if (outline) {
        for (const line of outline.split("\n")) ln(line);
      }
      break;
    }

    case "images-image-result": {
      const title = str(c.title) ?? "";
      const source = str(c.source) ?? str(c.url) ?? "";
      if (title) ln(trunc(title, 60));
      if (source) ln(`\x1b[2m${trunc(source, 60)}\x1b[0m`);
      break;
    }

    case "tasks-task": {
      for (const line of formatTaskEmbedPreviewLines(c, embed.embedId.slice(0, 8)).slice(1, -1)) {
        ln(line.replace(/^│\s\s/, ""));
      }
      break;
    }

    case "workflows-workflow": {
      for (const line of formatWorkflowEmbedPreviewLines(c, embed.embedId.slice(0, 8)).slice(1, -1)) {
        ln(line.replace(/^│\s\s/, ""));
      }
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
  write: EmbedWriter,
): void {
  const type = embed.type ?? str(c.type) ?? "";

  switch (type) {
    case "code":
    case "code-code": {
      const lang = str(c.language);
      const filename = str(c.filename);
      const code = str(c.code) ?? str(c.content) ?? "";
      if (filename) write(`\x1b[2mFile:\x1b[0m ${filename}\n`);
      if (lang) write(`\x1b[2mLanguage:\x1b[0m ${lang}\n`);
      writeEmbedLine(write);
      if (code) writeEmbedLine(write, code);
      break;
    }

    case "code-application":
    case "application": {
      const name = str(c.name) ?? str(c.title);
      const framework = str(c.framework);
      const runtime = str(c.runtime);
      if (name) write(`\x1b[1m${name}\x1b[0m\n`);
      if (framework) write(`\x1b[2mFramework:\x1b[0m ${framework}\n`);
      if (runtime) write(`\x1b[2mRuntime:\x1b[0m ${runtime}\n`);
      break;
    }

    case "docs-doc":
    case "doc": {
      const title = str(c.title);
      const html = str(c.html) ?? "";
      if (title) write(`\x1b[1m${title}\x1b[0m\n\n`);
      if (html) {
        // Strip HTML for text output
        const text = html
          .replace(/<[^>]+>/g, " ")
          .replace(/\s+/g, " ")
          .trim();
        writeEmbedLine(write, text);
      }
      break;
    }

    case "document": {
      const title = str(c.title);
      const html = str(c.html) ?? "";
      if (title) write(`\x1b[1m${title}\x1b[0m\n\n`);
      if (html) {
        const text = html
          .replace(/<[^>]+>/g, " ")
          .replace(/\s+/g, " ")
          .trim();
        writeEmbedLine(write, text);
      }
      break;
    }

    case "sheets-sheet":
    case "sheet": {
      const title = str(c.title);
      const table = str(c.table) ?? str(c.content) ?? "";
      if (title) write(`\x1b[1m${title}\x1b[0m\n\n`);
      if (table) writeEmbedLine(write, table);
      break;
    }

    case "pdf": {
      const filename = str(c.filename);
      if (filename) write(`\x1b[2mFile:\x1b[0m ${filename}\n`);
      const results = c.results as Array<Record<string, unknown>> | undefined;
      if (Array.isArray(results)) {
        for (const r of results) {
          const content = str(r.content) ?? str(r.text) ?? "";
          if (content) {
            writeEmbedLine(write);
            writeEmbedLine(write, content);
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
      if (title) write(`\x1b[1m${title}\x1b[0m\n`);
      if (url) write(`\x1b[2m${url}\x1b[0m\n`);
      if (age) write(`\x1b[2mAge: ${age}\x1b[0m\n`);
      if (desc) {
        writeEmbedLine(write);
        writeEmbedLine(write, desc);
      }
      break;
    }

    case "videos-video": {
      const title = str(c.title);
      const url = str(c.url);
      const channel = str(c.channel) ?? str(c.author) ?? "";
      const duration = str(c.duration) ?? "";
      const desc = str(c.description) ?? str(c.snippet) ?? "";
      if (title) write(`\x1b[1m${title}\x1b[0m\n`);
      if (url) write(`\x1b[2m${url}\x1b[0m\n`);
      if (channel)
        write(
          `\x1b[2mChannel:\x1b[0m ${channel}${duration ? `  \x1b[2m(${duration})\x1b[0m` : ""}\n`,
        );
      if (desc) {
        writeEmbedLine(write);
        writeEmbedLine(write, desc);
      }
      break;
    }

    case "mail-email": {
      const subject = str(c.subject);
      const receiver = str(c.receiver);
      const content = str(c.content) ?? "";
      if (subject) write(`\x1b[1m${subject}\x1b[0m\n`);
      if (receiver) write(`\x1b[2mTo: ${receiver}\x1b[0m\n`);
      if (content) {
        writeEmbedLine(write);
        writeEmbedLine(write, content);
      }
      break;
    }

    case "mindmap":
    case "mindmaps-mindmap": {
      const document = mindMapDocumentFromContent(c);
      const title = str(c.title) ?? str(document?.title) ?? "Mind Map";
      write(`\x1b[1m${title}\x1b[0m\n`);
      if (!document) {
        writeEmbedLine(write, "Invalid mind map JSON");
        break;
      }
      writeEmbedLine(write, `${document.nodes.length} nodes · ${document.edges?.length ?? 0} edges\n`);
      writeEmbedLine(write, mindMapOutline(document));
      writeEmbedLine(write, "\n```openmates_mindmap");
      writeEmbedLine(write, JSON.stringify(document, null, 2));
      writeEmbedLine(write, "```");
      break;
    }

    case "events-event": {
      const venue = isRecord(c.venue) ? c.venue : {};
      const organizer = isRecord(c.organizer) ? c.organizer : {};
      const fee = isRecord(c.fee) ? c.fee : {};
      const field = (label: string, value: unknown) => {
        if (value !== null && value !== undefined && String(value).trim()) {
          writeEmbedLine(write,label);writeEmbedLine(write,String(value));writeEmbedLine(write);
        }
      };
      writeEmbedLine(write,str(c.title) ?? str(c.name) ?? "Event");writeEmbedLine(write);
      field("When",[c.date_start ?? c.start_time ?? c.date,c.date_end,c.timezone].filter(Boolean).join(" · "));
      field("Location",c.event_type === "online" ? "Online event" : [venue.name ?? c.venue_name,venue.address ?? c.venue_address,venue.city ?? c.venue_city,venue.country ?? c.venue_country,str(c.location)].filter(Boolean).join(", "));
      field("Organizer",organizer.name ?? c.organizer_name);
      field("Description",c.description);
      field("Admission",c.is_paid === false ? "Free" : [fee.amount ?? c.fee_amount,fee.currency ?? c.fee_currency].filter(v=>v!==undefined&&v!==null).join(" "));
      field("Attendees",c.rsvp_count);
      field("Event page",c.url);
      break;
    }

    default: {
      // Generic: show all non-null fields (fullscreen — no truncation)
      for (const [k, v] of Object.entries(c)) {
        if (v === null || v === undefined || k.startsWith("_")) continue;
        if (typeof v === "object") {
          write(
            `  \x1b[2m${k.padEnd(20)}\x1b[0m ${JSON.stringify(v)}\n`,
          );
        } else {
          write(
            `  \x1b[2m${k.padEnd(20)}\x1b[0m ${String(v)}\n`,
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

interface CliMindMapNode {
  id: string;
  label: string;
  children?: string[];
}

interface CliMindMapDocument {
  openmatesType: "mindmap";
  schemaVersion: number;
  title: string;
  rootId: string;
  nodes: CliMindMapNode[];
  edges?: Array<Record<string, unknown>>;
  view?: Record<string, unknown>;
}

function mindMapDocumentFromContent(c: Record<string, unknown>): CliMindMapDocument | null {
  const model = c.model;
  if (isMindMapDocument(model)) return model;
  const source = str(c.source_json);
  if (!source) return null;
  try {
    const parsed = JSON.parse(source);
    return isMindMapDocument(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function isMindMapDocument(value: unknown): value is CliMindMapDocument {
  if (!isRecord(value)) return false;
  return (
    value.openmatesType === "mindmap" &&
    typeof value.schemaVersion === "number" &&
    typeof value.title === "string" &&
    typeof value.rootId === "string" &&
    Array.isArray(value.nodes)
  );
}

function mindMapOutline(document: CliMindMapDocument, maxNodes = 100): string {
  const nodesById = new Map<string, CliMindMapNode>();
  for (const node of document.nodes) {
    if (typeof node.id === "string" && typeof node.label === "string") {
      nodesById.set(node.id, node);
    }
  }
  const lines: string[] = [];
  const visited = new Set<string>();

  const visit = (nodeId: string, depth: number) => {
    if (visited.size >= maxNodes || visited.has(nodeId)) return;
    const node = nodesById.get(nodeId);
    if (!node) return;
    visited.add(nodeId);
    lines.push(`${"  ".repeat(depth)}- ${node.label}`);
    for (const childId of node.children ?? []) visit(childId, depth + 1);
  };

  visit(document.rootId, 0);
  for (const node of document.nodes) {
    if (visited.size >= maxNodes) break;
    if (!visited.has(node.id)) visit(node.id, 0);
  }
  return lines.join("\n");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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
