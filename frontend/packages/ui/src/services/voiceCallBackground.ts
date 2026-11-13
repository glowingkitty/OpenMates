/**
 * Keeps a live voice call usable while the page is away (Safari in the
 * background, another app in front, locked screen).
 *
 * Browsers suspend pages that are neither audible nor capturing. A call stays
 * alive on iOS only while the page plays audio, so this keeps one inaudible
 * looping clip running, registers lock-screen call controls and asks for a
 * play-and-record audio session. It never claims the call survives: the
 * controller still verifies the microphone and sockets on return.
 */

/** A return within this window of being away may legitimately find dead sockets. */
export const VOICE_CALL_AWAY_GRACE_MS = 90_000;

/** One second of 16-bit mono PCM at 8 kHz whose ±1 LSB samples are inaudible. */
function inaudibleLoopUrl(): string {
  const samples = 8_000;
  const bytes = new Uint8Array(44 + samples * 2);
  const view = new DataView(bytes.buffer);
  const text = (offset: number, value: string) => [...value].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0)));
  text(0, 'RIFF'); view.setUint32(4, 36 + samples * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, 8_000, true); view.setUint32(28, 16_000, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, 'data'); view.setUint32(40, samples * 2, true);
  for (let index = 0; index < samples; index++) view.setInt16(44 + index * 2, index % 2 ? 1 : -1, true);
  return URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }));
}

export interface VoiceCallBackgroundOptions {
  /** The page left the foreground. */
  onAway: () => void;
  /** The page is back; ``awayMs`` is how long it was gone. */
  onReturn: (awayMs: number) => void;
  /** Lock-screen or headset control asked to end the call. */
  onHangup: () => void;
  title: string;
}

type AudioSessionNavigator = Navigator & { audioSession?: { type: string } };

export class VoiceCallBackground {
  private element: HTMLAudioElement | null = null;
  private url: string | null = null;
  private awaySince: number | null = null;
  private returnedAt = Number.NEGATIVE_INFINITY;
  private listening = false;

  constructor(private readonly options: VoiceCallBackgroundOptions) {}

  /** Must run inside the user's start gesture so the browser allows playback. */
  prime(): void {
    if (this.element || typeof document === 'undefined') return;
    const session = (navigator as AudioSessionNavigator).audioSession;
    if (session) session.type = 'play-and-record';
    this.url = inaudibleLoopUrl();
    const element = new Audio(this.url);
    element.loop = true;
    element.setAttribute('playsinline', '');
    element.setAttribute('data-testid', 'voice-call-keepalive');
    this.element = element;
    void element.play().catch(() => {
      // Autoplay refusal only costs background survival; the call itself continues.
      console.warn('[VoiceCall] Background keep-alive audio could not start');
    });
  }

  /** Attach lifecycle listeners and lock-screen controls once the call is live. */
  start(): void {
    if (this.listening || typeof document === 'undefined') return;
    this.listening = true;
    document.addEventListener('visibilitychange', this.onVisibility);
    window.addEventListener('pageshow', this.onPageShow);
    window.addEventListener('pagehide', this.onPageHide);
    if ('mediaSession' in navigator) {
      navigator.mediaSession.metadata = new MediaMetadata({ title: this.options.title, artist: 'OpenMates' });
      navigator.mediaSession.playbackState = 'playing';
      for (const action of ['pause', 'stop'] as const) {
        navigator.mediaSession.setActionHandler(action, () => this.options.onHangup());
      }
    }
    if (document.visibilityState === 'hidden') this.markAway();
  }

  stop(): void {
    if (this.listening) {
      document.removeEventListener('visibilitychange', this.onVisibility);
      window.removeEventListener('pageshow', this.onPageShow);
      window.removeEventListener('pagehide', this.onPageHide);
      if ('mediaSession' in navigator) {
        for (const action of ['pause', 'stop'] as const) navigator.mediaSession.setActionHandler(action, null);
        navigator.mediaSession.metadata = null;
        navigator.mediaSession.playbackState = 'none';
      }
    }
    this.listening = false;
    this.awaySince = null;
    this.element?.pause();
    this.element?.removeAttribute('src');
    this.element = null;
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = null;
  }

  /** True while away, and for a grace period after returning. */
  get awayRecently(): boolean {
    return this.awaySince !== null || performance.now() - this.returnedAt < VOICE_CALL_AWAY_GRACE_MS;
  }

  get away(): boolean { return this.awaySince !== null; }

  private markAway(): void {
    if (this.awaySince !== null) return;
    this.awaySince = performance.now();
    this.options.onAway();
  }

  private markReturned(): void {
    if (this.awaySince === null) return;
    const awayMs = performance.now() - this.awaySince;
    this.awaySince = null;
    this.returnedAt = performance.now();
    // A suspended page may have paused the loop; resume it for the next absence.
    if (this.element?.paused) void this.element.play().catch(() => {});
    this.options.onReturn(awayMs);
  }

  private onVisibility = (): void => {
    if (document.visibilityState === 'hidden') this.markAway();
    else this.markReturned();
  };

  private onPageHide = (): void => { this.markAway(); };
  private onPageShow = (): void => { this.markReturned(); };
}
