/**
 * Web screen sharing for voice calls: capability detection and display capture.
 *
 * Shared frames reuse the camera frame path (sampling, JPEG bounds, upload
 * cleanup, `camera_frame` socket event marked `source: 'screen'`) in
 * `VoiceCallCamera`; this module only decides whether sharing is offered and
 * acquires the display stream.
 */

/** Browser capabilities consulted by the detection; injectable for tests. */
export interface ScreenShareEnvironment {
  mediaDevices?: { getDisplayMedia?: unknown } | null;
  matchMedia?: (query: string) => { matches: boolean };
}

/**
 * Offer screen sharing only where the browser can capture a display.
 *
 * Feature detection, never user-agent sniffing: `getDisplayMedia` must exist
 * (desktop Chrome, Edge, Firefox, macOS Safari). iOS, iPadOS and Android
 * browsers do not expose it. As a guard for a mobile browser that ever does,
 * a device whose primary input is touch-only (`pointer: coarse` and
 * `hover: none`) is treated as mobile; touch laptops report a fine/hovering
 * primary pointer and keep the button.
 */
export function isScreenShareSupported(env?: ScreenShareEnvironment): boolean {
  const resolved: ScreenShareEnvironment = env ?? {
    mediaDevices: typeof navigator === 'undefined' ? null : navigator.mediaDevices,
    matchMedia: typeof window === 'undefined' || !window.matchMedia ? undefined : window.matchMedia.bind(window),
  };
  if (typeof resolved.mediaDevices?.getDisplayMedia !== 'function') return false;
  const matches = (query: string) => resolved.matchMedia?.(query).matches === true;
  return !(matches('(pointer: coarse)') && matches('(hover: none)'));
}

/** Ask the browser's own picker for one display, video only (no system audio). */
export async function acquireScreenStream(): Promise<MediaStream> {
  if (!isScreenShareSupported()) throw new Error('Screen sharing unavailable');
  return navigator.mediaDevices.getDisplayMedia({ audio: false, video: true });
}
