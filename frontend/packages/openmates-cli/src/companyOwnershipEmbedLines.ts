/** Terminal lines for business/company_ownership embeds (preview and fullscreen detail). */
import { terminalText } from "./tuiText.js";

const row = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
const text = (value: unknown): string => (typeof value === "string" ? terminalText(value) : "");
const rows = (value: unknown): Record<string, unknown>[] =>
  (Array.isArray(value) ? value : []).map(row).filter((item): item is Record<string, unknown> => item !== null).slice(0, 100);

function safeLink(value: unknown): string {
  try {
    const url = new URL(text(value));
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : "";
  } catch { return ""; }
}

function share(item: Record<string, unknown>): string {
  if (typeof item.share_percent === "number" && Number.isFinite(item.share_percent)) return `${Number(item.share_percent.toFixed(2))}%`;
  return text(item.share_band);
}

export function companyOwnershipLines(content: Record<string, unknown>, fullscreen = false): string[] {
  const records = rows(content.records).filter((rec) => text(row(rec.subject)?.name) !== "");
  const count = typeof content.result_count === "number" ? content.result_count : records.length;
  const lines = [`Ownership: ${count}${text(content.query) ? " · " + text(content.query) : ""}`];
  for (const rec of records.slice(0, fullscreen ? records.length : 1)) {
    const subject = row(rec.subject) ?? {};
    const owners = rows(rec.owners);
    const holdings = rows(rec.holdings);
    const officers = rows(rec.officers);
    lines.push([text(subject.name), text(subject.country), text(subject.legal_form), text(subject.status)].filter(Boolean).join(" · "));
    lines.push(`  Owners: ${owners.length} · Holdings: ${holdings.length} · Officers: ${officers.length}`);
    for (const owner of owners.slice(0, fullscreen ? owners.length : 3)) {
      lines.push(`  ${[text(owner.name), share(owner)].filter(Boolean).join(" · ")}`);
    }
    if (!fullscreen) continue;
    for (const holding of holdings) {
      const ended = text(holding.until);
      lines.push(`  Holding: ${[text(holding.name), share(holding), text(holding.relation).replace(/_/g, " "), ended ? `ended ${ended}` : ""].filter(Boolean).join(" · ")}`);
    }
    for (const officer of officers) lines.push(`  Officer: ${[text(officer.name), text(officer.role)].filter(Boolean).join(" · ")}`);
    for (const warning of Array.isArray(rec.warnings) ? rec.warnings : []) lines.push(`  ${text(warning)}`);
    const link = safeLink(subject.source_url);
    if (link) lines.push(`  ${link}`);
    if (text(rec.provider)) lines.push(`  Source: ${text(rec.provider)}`);
    if (text(rec.limitation)) lines.push(`  ${text(rec.limitation)}`);
  }
  for (const err of rows(content.errors)) {
    lines.push(`Not found: ${[text(err.query), text(err.country)].filter(Boolean).join(" · ")} (${text(err.code)})${text(err.message) ? " " + text(err.message) : ""}`);
    for (const cand of rows(err.candidates)) {
      lines.push(`  Candidate: ${[text(cand.name), text(cand.register_id), text(cand.city)].filter(Boolean).join(" · ")}`);
    }
  }
  for (const warning of Array.isArray(content.warnings) ? content.warnings : []) lines.push(`Skipped: ${text(warning)}`);
  if (text(content.error)) lines.push(`Error: ${text(content.error)}`);
  if (fullscreen && text(content.limitation)) lines.push(text(content.limitation));
  return lines;
}
