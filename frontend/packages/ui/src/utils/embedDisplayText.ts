/**
 * frontend/packages/ui/src/utils/embedDisplayText.ts
 *
 * Shared fallback-label logic for inline embed references.
 * Keeps technical embed_ref slugs out of user-facing labels when the model
 * writes empty or placeholder display text like [](embed:ice-0800-PsB).
 * Used by message parsing and embed-link hydration paths.
 */

const EMBED_REF_SUFFIX_RE = /-[a-zA-Z0-9]{2,4}(?:\s*\(\d+\))?$/;
const DOMAIN_PREFIX_RE =
  /^([a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?)/;
const CONNECTION_REF_RE = /^([a-zA-Z][a-zA-Z0-9_-]*)-(\d{4})$/;

const CARRIER_LABELS: Record<string, string> = {
  db: "DB",
  ice: "ICE",
  ic: "IC",
  ec: "EC",
  flixtrain: "FlixTrain",
  flixzug: "FlixTrain",
};

function formatCarrierLabel(raw: string): string {
  const text = raw.trim();
  if (!text) return "";

  const known = CARRIER_LABELS[text.toLowerCase()];
  if (known) return known;
  if (text.length <= 4) return text.toUpperCase();

  return text
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

function formatHHMM(raw: string): string {
  const match = raw.match(/^(\d{1,2})(\d{2})$/);
  if (!match) return "";
  return `${match[1].padStart(2, "0")}:${match[2]}`;
}

function stripEmbedRefSuffix(embedRef: string): string {
  return embedRef.replace(EMBED_REF_SUFFIX_RE, "").trim();
}

export function isTechnicalEmbedDisplayText(
  displayText: string,
  embedRef: string,
): boolean {
  const text = displayText.trim();
  const ref = embedRef.trim();
  if (!ref) return false;
  if (text === "!") return false;
  if (!text) return true;
  if (text === ref) return true;

  const refBase = stripEmbedRefSuffix(ref);
  if (text === refBase) return true;

  const suffixMatch = ref.match(EMBED_REF_SUFFIX_RE);
  if (suffixMatch && text === suffixMatch[0].replace(/^-/, "")) return true;

  return false;
}

export function deriveEmbedDisplayTextFromRef(embedRef: string): string {
  const ref = embedRef.trim();
  if (!ref) return "Open result";

  const domainMatch = ref.match(DOMAIN_PREFIX_RE);
  if (domainMatch) return domainMatch[1];

  const base = stripEmbedRefSuffix(ref).replace(/\s*\(\d+\)$/, "").trim();
  const connectionMatch = base.match(CONNECTION_REF_RE);
  if (connectionMatch) {
    const carrier = formatCarrierLabel(connectionMatch[1]);
    const time = formatHHMM(connectionMatch[2]);
    if (carrier && time) return `${carrier} ${time}`;
  }

  const words = base.split(/[-_]+/).filter(Boolean);
  if (words.length > 0 && !["embed", "item", "result"].includes(base.toLowerCase())) {
    return words.slice(0, 4).map(formatCarrierLabel).join(" ");
  }

  return "Open result";
}

export function resolveEmbedDisplayText(
  displayText: string,
  embedRef: string,
): string {
  if (!isTechnicalEmbedDisplayText(displayText, embedRef) && displayText.trim().length > 3) {
    return displayText;
  }
  return deriveEmbedDisplayTextFromRef(embedRef);
}
