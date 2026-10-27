import { sanitizeUploadBytes } from '@repo/upload-privacy';
import { base64ToUint8Array, uint8ArrayToBase64 } from './cryptoService';

/** Video-only live preview with bounded, ephemeral JPEG observations. */
export interface VoiceCallCameraFrame {
  frameId: string;
  data: string;
  capturedAt: number;
  width: number;
  height: number;
}
export type VoiceCallCameraFacing = 'user' | 'environment';
export interface VoiceCallCameraCallbacks {
  onFrame: (frame: VoiceCallCameraFrame) => void;
  onStream: (stream: MediaStream | null, facing: VoiceCallCameraFacing) => void;
  onError: (error: 'camera_denied' | 'camera_missing' | 'camera_failed') => void;
}

export class VoiceCallCamera {
  private generation = 0;
  private stream: MediaStream | null = null;
  private video: HTMLVideoElement | null = null;
  private timer: ReturnType<typeof setInterval> | undefined;
  private currentFacing: VoiceCallCameraFacing = 'environment';
  private lastCapture = -Infinity;
  private lastEmission = -Infinity;
  private capturingGeneration: number | null = null;
  get facing(): VoiceCallCameraFacing { return this.currentFacing; }

  constructor(private callbacks: VoiceCallCameraCallbacks) {}

  async start(): Promise<void> {
    this.stop();
    const generation = this.generation;
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera unavailable');
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: this.currentFacing }, width: { ideal: 1280 }, height: { ideal: 720 } },
      });
      if (generation !== this.generation) {
        stream.getTracks().forEach(track => track.stop());
        return;
      }
      this.stream = stream;
      const video = document.createElement('video');
      this.video = video;
      video.muted = true;
      video.playsInline = true;
      video.srcObject = stream;
      this.callbacks.onStream(stream, this.currentFacing);
      if (generation !== this.generation) return;
      // Preview plays at the camera's native rate; observations have a separate 1Hz cadence.
      void video.play().catch(() => {
        if (generation === this.generation) this.fail('camera_failed');
      });
      this.lastCapture = -Infinity;
      this.lastEmission = -Infinity;
      this.timer = setInterval(() => { void this.capture(generation); }, 1000);
      for (const track of stream.getVideoTracks()) {
        track.onended = () => { if (generation === this.generation) this.fail('camera_failed'); };
      }
    } catch (error) {
      if (generation !== this.generation) return;
      const name = error instanceof Error || error instanceof DOMException ? error.name : '';
      this.fail(name === 'NotAllowedError' || name === 'SecurityError' ? 'camera_denied'
        : name === 'NotFoundError' || name === 'DevicesNotFoundError' ? 'camera_missing' : 'camera_failed');
    }
  }

  stop(): void {
    this.generation++;
    this.capturingGeneration = null;
    if (this.timer !== undefined) clearInterval(this.timer);
    this.timer = undefined;
    if (this.stream) {
      for (const track of this.stream.getTracks()) { track.onended = null; track.stop(); }
    }
    this.stream = null;
    if (this.video) { this.video.pause(); this.video.srcObject = null; }
    this.video = null;
    this.callbacks.onStream(null, this.currentFacing);
  }

  async flip(): Promise<void> {
    this.currentFacing = this.currentFacing === 'environment' ? 'user' : 'environment';
    await this.start();
  }

  private fail(error: Parameters<VoiceCallCameraCallbacks['onError']>[0]): void {
    this.stop();
    this.callbacks.onError(error);
  }

  private async capture(generation: number): Promise<void> {
    const video = this.video;
    const now = performance.now();
    if (generation !== this.generation || this.capturingGeneration !== null || !video || video.readyState < 2 ||
      !video.videoWidth || !video.videoHeight || now - this.lastCapture < 1000) return;
    this.lastCapture = now;
    this.capturingGeneration = generation;
    const capturedAt = Date.now();
    try {
      const canvas = document.createElement('canvas');
      const scale = Math.min(1, 1280 / video.videoWidth, 720 / video.videoHeight);
      canvas.width = Math.max(1, Math.floor(video.videoWidth * scale));
      canvas.height = Math.max(1, Math.floor(video.videoHeight * scale));
      const context = canvas.getContext('2d');
      if (!context) throw new Error('Camera capture unavailable');
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      let data = '';
      // The server bounds decoded JPEGs to 256KiB. A noisy frame must fit too.
      for (const quality of [0.72, 0.5, 0.3]) {
        const url = canvas.toDataURL('image/jpeg', quality);
        if (!url.startsWith('data:image/jpeg;base64,')) throw new Error('JPEG capture unavailable');
        data = url.slice(url.indexOf(',') + 1);
        if (Math.ceil(data.length * 3 / 4) <= 256 * 1024) break;
      }
      if (!data || Math.ceil(data.length * 3 / 4) > 256 * 1024) return;
      // Provider input and a later ordinary attachment upload must hash the same
      // bytes. Canvas JPEGs include JFIF APP0; the upload boundary removes it.
      // Apply that existing cleanup before either consumer sees this frame.
      const sanitized = await sanitizeUploadBytes(base64ToUint8Array(data), 'image/jpeg', 'camera-frame.jpg');
      if (generation !== this.generation) return;
      if (sanitized.status !== 'sanitized' || sanitized.mimeType !== 'image/jpeg' ||
        !sanitized.bytes.byteLength || sanitized.bytes.byteLength > 256 * 1024) throw new Error('Camera JPEG cleanup failed');
      const frame: VoiceCallCameraFrame = {
        frameId: crypto.randomUUID(), data: uint8ArrayToBase64(sanitized.bytes), capturedAt,
        width: canvas.width, height: canvas.height,
      };
      if (performance.now() - this.lastEmission < 1000) return;
      this.lastEmission = performance.now();
      this.callbacks.onFrame(frame);
    } catch {
      if (generation === this.generation) this.fail('camera_failed');
    } finally {
      if (this.capturingGeneration === generation) this.capturingGeneration = null;
    }
  }
}
