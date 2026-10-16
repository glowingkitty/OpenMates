/** Only reviewed, same-origin static example audio may bypass encrypted storage. */
export function publicRecordingAudioUrl(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  return /^\/store-examples\/[a-zA-Z0-9_-]+\.(?:wav|mp3|ogg|m4a|webm)$/.test(value)
    ? value
    : undefined;
}
