// src/components/MessageInput/utils/audioHelpers.ts

/**
 * Formats a duration in seconds to a MM:SS string.
 * @param seconds The duration in seconds.
 * @returns The formatted duration string.
 */
export function formatDuration(seconds: number): string {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.floor(seconds % 60);
    return `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
}