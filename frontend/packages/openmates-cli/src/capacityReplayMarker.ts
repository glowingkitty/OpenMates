/** Narrow client-side gate for the isolated storage-capacity replay marker. */
export function capacityReplayMarker(
  marker: string | undefined,
  apiUrl: string,
  enabled: boolean,
): string | undefined {
  if (marker === undefined) return undefined;
  if (!enabled || marker !== "<<<TEST_LIVE_MOCK:storage_capacity_v1>>>" ||
      !/^https?:\/\/(?:localhost|127\.0\.0\.1|[^/]+\.ci\.test)(?::\d+)?$/.test(apiUrl)) {
    throw new Error("Storage capacity replay marker requires the isolated CI API and replay-only mode.");
  }
  return marker;
}
