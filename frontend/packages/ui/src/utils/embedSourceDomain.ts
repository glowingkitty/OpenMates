/**
 * frontend/packages/ui/src/utils/embedSourceDomain.ts
 *
 * Shared source-domain resolver for image result embeds.
 * Image search providers do not use one stable field name: some return
 * `source`, some `source_domain`, and some only include the source page URL.
 * Keeping this logic shared makes small and large preview cards match the
 * Apple app behavior and avoids generic "Image" labels when a source exists.
 */

function cleanDomain(value: string): string {
  return value.trim().replace(/^https?:\/\//i, "").replace(/^www\./i, "").split("/")[0];
}

function hostFromUrl(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;

  try {
    return new URL(value).hostname.replace(/^www\./i, "");
  } catch {
    return null;
  }
}

export function resolveImageSourceDomain(content: Record<string, unknown> | null | undefined): string {
  if (!content) return "";

  for (const key of ["source", "source_domain"]) {
    const value = content[key];
    if (typeof value === "string" && value.trim()) {
      return cleanDomain(value);
    }
  }

  return hostFromUrl(content.source_page_url) ?? hostFromUrl(content.url) ?? "";
}
