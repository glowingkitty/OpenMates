/**
 * profileImageService.ts
 *
 * Fetch-and-cache service for profile images served by the authenticated
 * API proxy endpoint GET /v1/users/{userId}/profile-image.
 *
 * Architecture:
 *   - New profile images are AES-256-GCM encrypted in a private S3 bucket.
 *   - The API serves them via an authenticated endpoint that requires a
 *     session cookie (or Bearer token), so `<img src="...">` and
 *     CSS `background-image: url(...)` cannot be used directly — browsers
 *     do not send credentials for those requests.
 *   - This service fetches via `fetch(..., { credentials: 'include' })`,
 *     creates a blob URL, and caches it in memory.
 *   - Legacy public-read profile images (users who haven't re-uploaded) are
 *     detected by checking whether the URL starts with 'http'. Those are
 *     returned as-is without fetching.
 *
 * Cache behaviour:
 *   - In-memory Map<userId, blobUrl> — persists for the lifetime of the page.
 *   - Call `invalidateProfileImageCache(userId)` after an upload to revoke
 *     the old blob URL and force a fresh fetch on next render.
 */

/** In-memory cache: userId → blob URL (or direct legacy URL) */
const _cache = new Map<string, string>();

/**
 * Determine whether a profile_image_url is a legacy public URL or a proxy path.
 *
 * Legacy URLs start with 'http' (absolute URL pointing to a public S3 bucket).
 * New proxy paths look like '/v1/users/{userId}/profile-image'.
 */
function isLegacyUrl(url: string): boolean {
  return url.startsWith("http://") || url.startsWith("https://");
}

/**
 * Resolve a profile_image_url to a displayable URL.
 *
 * - Legacy public URLs: returned immediately without fetching.
 * - Proxy paths: fetched with credentials, blob URL created and cached.
 *
 * @param profileImageUrl   The value of userProfile.profile_image_url
 *                          (e.g. '/v1/users/abc123/profile-image' or a full https:// URL)
 * @param apiBaseUrl        Base URL of the API (e.g. 'https://app.openmates.org').
 *                          Required for relative proxy paths.
 * @param userId            Owner user ID — used as cache key.
 * @returns                 A URL safe to use in `<img src>` or `style="background-image: url(...)"`
 *                          Returns `null` if the fetch fails or profileImageUrl is falsy.
 */
export async function getProfileImageBlobUrl(
  profileImageUrl: string | null | undefined,
  apiBaseUrl: string,
  userId: string,
): Promise<string | null> {
  if (!profileImageUrl) return null;

  // Legacy public-read URL — no auth needed, return directly.
  if (isLegacyUrl(profileImageUrl)) {
    return profileImageUrl;
  }

  // Check in-memory cache first.
  const cached = _cache.get(userId);
  if (cached) return cached;

  // Fetch with credentials to authenticate the request.
  try {
    const fullUrl = profileImageUrl.startsWith("/")
      ? `${apiBaseUrl}${profileImageUrl}`
      : profileImageUrl;

    const response = await fetch(fullUrl, { credentials: "include" });

    if (!response.ok) {
      console.error(
        `[profileImageService] Failed to fetch profile image for ${userId}: ` +
          `HTTP ${response.status}`,
      );
      return null;
    }

    const blob = await response.blob();
    const blobUrl = URL.createObjectURL(blob);
    _cache.set(userId, blobUrl);
    return blobUrl;
  } catch (err) {
    console.error(
      `[profileImageService] Error fetching profile image for ${userId}:`,
      err,
    );
    return null;
  }
}

/**
 * Invalidate the cached blob URL for a user.
 *
 * Call this after the user successfully uploads a new profile image so the
 * next render triggers a fresh fetch.  The old blob URL is revoked to free
 * browser memory.
 *
 * @param userId  The user whose cached profile image should be cleared.
 */
export function invalidateProfileImageCache(userId: string): void {
  const existing = _cache.get(userId);
  if (existing && !isLegacyUrl(existing)) {
    // Only revoke blob: URLs — legacy https:// URLs should not be revoked.
    URL.revokeObjectURL(existing);
  }
  _cache.delete(userId);
}
