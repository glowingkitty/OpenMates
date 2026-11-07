// frontend/packages/ui/src/services/shareState/shortUrlPolicy.ts
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
// Pure short-URL parsing/building rules moved out of shortUrlEncryption.ts. With
// VITE_OPENMATES_RUST_CORE=1 the shared Rust core (web_share_state, crypto unit)
// decides through shareState/decide.ts; flag-off builds run these rules directly.
// Each op takes and returns the same JSON document as its Rust counterpart.

const MAX_SHORT_KEY_LENGTH = 22;
const BASE62_PATTERN = /^[A-Za-z0-9]+$/;

type Parts = { token: string; shortKey: string } | null;

/** Legacy `token-shortKey` fragment (`/s/#token-shortKey`). */
export function parseShortUrlFragment(input: { fragment: string }): Parts {
  const clean = input.fragment.startsWith("#") ? input.fragment.slice(1) : input.fragment;

  const dashIndex = clean.indexOf("-");
  if (dashIndex === -1) return null;

  const token = clean.slice(0, dashIndex);
  const shortKey = clean.slice(dashIndex + 1);

  // Legacy keys start at four characters; current keys carry 128+ random bits.
  if (
    token.length < 6 || token.length > 12 ||
    shortKey.length < 4 || shortKey.length > MAX_SHORT_KEY_LENGTH ||
    !BASE62_PATTERN.test(token) ||
    !BASE62_PATTERN.test(shortKey)
  ) {
    return null;
  }

  return { token, shortKey };
}

/** Durable `/s/{token}#{shortKey}` path with the legacy fragment as fallback. */
export function parseShortUrlParts(input: { pathname: string; fragment: string }): Parts {
  const cleanHash = input.fragment.startsWith("#") ? input.fragment.slice(1) : input.fragment;
  const pathMatch = input.pathname.match(/^\/s\/([A-Za-z0-9]{6,12})\/?$/);

  if (pathMatch) {
    const token = pathMatch[1];
    if (
      cleanHash.length >= 4 &&
      cleanHash.length <= MAX_SHORT_KEY_LENGTH &&
      BASE62_PATTERN.test(cleanHash)
    ) {
      return { token, shortKey: cleanHash };
    }
    return null;
  }

  return parseShortUrlFragment({ fragment: cleanHash });
}

/** Custom short domain when configured, else the given origin. */
export function buildShortUrl(input: { token: string; short_key: string; short_domain?: string; origin: string }): string {
  if (input.short_domain) {
    return `https://${input.short_domain}/s/${input.token}#${input.short_key}`;
  }
  return `${input.origin}/s/${input.token}#${input.short_key}`;
}

export const SHORT_URL_OPS = {
  shortUrlParseFragment: parseShortUrlFragment,
  shortUrlParseParts: parseShortUrlParts,
  shortUrlBuild: buildShortUrl,
};
