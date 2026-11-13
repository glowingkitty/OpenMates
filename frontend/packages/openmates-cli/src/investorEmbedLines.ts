/** Terminal lines for business/search_investors embeds (preview and fullscreen detail). */
import { terminalText } from "./tuiText.js";

const row = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
const text = (value: unknown): string => (typeof value === "string" ? terminalText(value) : "");
const list = (value: unknown): string =>
  Array.isArray(value) ? value.map((item) => terminalText(String(item))).join(", ") : text(value);

function safeLink(value: unknown): string {
  try {
    const url = new URL(text(value));
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : "";
  } catch { return ""; }
}

export function investorLines(content: Record<string, unknown>, fullscreen = false): string[] {
  const investors = (Array.isArray(content.investors) ? content.investors : []).map(row).filter(
    (item): item is Record<string, unknown> => item !== null && text(item.name) !== "").slice(0, 100);
  const count = typeof content.result_count === "number" ? content.result_count : investors.length;
  const lines = [`Investors: ${count}${list(content.regions) ? " · " + list(content.regions) : ""}`];
  for (const item of investors.slice(0, fullscreen ? investors.length : 3)) {
    const head = [text(item.name), text(item.investor_type).replace(/_/g, " "), text(item.organization)].filter(Boolean).join(" · ");
    lines.push(head);
    if (!fullscreen) continue;
    const facts = [list(item.city), list(item.regions), list(item.stages), list(item.sectors)].filter(Boolean).join(" · ");
    if (facts) lines.push(`  ${facts}`);
    const min = typeof item.ticket_min === "number" ? item.ticket_min : null;
    const max = typeof item.ticket_max === "number" ? item.ticket_max : null;
    if (min !== null || max !== null) {
      lines.push(`  Ticket: ${[min, max].map((v) => (v === null ? "" : String(v))).join(" – ")} ${text(item.currency)}`.trimEnd());
    }
    if (text(item.thesis)) lines.push(`  ${text(item.thesis)}`);
    if (list(item.example_investments)) lines.push(`  Examples: ${list(item.example_investments)}`);
    if (text(item.contact_route)) lines.push(`  Contact: ${text(item.contact_route)}`);
    for (const link of [safeLink(item.profile_url), safeLink(item.website_url)]) if (link) lines.push(`  ${link}`);
  }
  for (const warning of Array.isArray(content.warnings) ? content.warnings : []) lines.push(`Skipped: ${text(warning)}`);
  if (text(content.error)) lines.push(`Error: ${text(content.error)}`);
  if (fullscreen && text(content.limitation)) lines.push(text(content.limitation));
  return lines;
}
