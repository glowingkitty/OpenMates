/**
 * Ephemeral audio I/O for the isolated video call experiment.
 * Browser echo cancellation prepares the microphone before the WebSocket opens.
 * PCM16 input is sent at 16 kHz and model PCM16 is scheduled at 24 kHz.
 * Every track, node, context and queued source is released on stop.
 */
export function pcm16Base64(samples: Float32Array): string {
  const bytes = new Uint8Array(samples.length * 2);
  const view = new DataView(bytes.buffer);
  samples.forEach((sample, index) => {
    const clipped = Math.max(-1, Math.min(1, sample));
    view.setInt16(index * 2, clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff, true);
  });
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...Array.from(bytes.subarray(offset, offset + 0x8000)));
  }
  return btoa(binary);
}

export function downsample(samples: Float32Array, sourceRate: number, targetRate = 16_000): Float32Array {
  if (sourceRate <= targetRate) return samples;
  const ratio = sourceRate / targetRate;
  const result = new Float32Array(Math.floor(samples.length / ratio));
  for (let index = 0; index < result.length; index += 1) {
    const start = Math.floor(index * ratio);
    const end = Math.min(samples.length, Math.floor((index + 1) * ratio));
    let sum = 0;
    for (let sample = start; sample < end; sample += 1) sum += samples[sample];
    result[index] = sum / Math.max(1, end - start);
  }
  return result;
}

export function decodePcm16(data: string): Float32Array {
  const binary = atob(data);
  if (binary.length % 2) throw new Error('Invalid PCM chunk');
  const result = new Float32Array(binary.length / 2);
  for (let index = 0; index < result.length; index += 1) {
    const value = binary.charCodeAt(index * 2) | (binary.charCodeAt(index * 2 + 1) << 8);
    const signed = value >= 0x8000 ? value - 0x10000 : value;
    result[index] = signed / (signed < 0 ? 0x8000 : 0x7fff);
  }
  return result;
}

export class CallAudio {
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private silentGain: GainNode | null = null;
  private playback = new Set<AudioBufferSourceNode>();
  private nextStart = 0;
  private generation = 0;
  private stopped = false;
  private speakingTimeout: ReturnType<typeof setTimeout> | null = null;

  constructor(private onMicAudio: (data: string) => void, private onSpeaking: (user: boolean, model: boolean) => void) {}

  async start(): Promise<void> {
    const generation = ++this.generation;
    this.stopped = false;
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      video: false,
    });
    if (this.stopped || generation !== this.generation) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    this.stream = stream;
    const context = new AudioContext();
    this.context = context;
    this.source = context.createMediaStreamSource(stream);
    this.processor = context.createScriptProcessor(2048, 1, 1);
    this.silentGain = context.createGain();
    this.silentGain.gain.value = 0;
    this.source.connect(this.processor);
    this.processor.connect(this.silentGain);
    this.silentGain.connect(context.destination);
    this.processor.onaudioprocess = (event) => {
      if (this.stopped) return;
      const input = event.inputBuffer.getChannelData(0);
      const rms = Math.sqrt(input.reduce((sum, value) => sum + value * value, 0) / input.length);
      this.onSpeaking(rms > 0.045, this.playback.size > 0);
      this.onMicAudio(pcm16Base64(downsample(input, event.inputBuffer.sampleRate)));
    };
    if (context.state === 'suspended') await context.resume();
  }

  playPcm16(data: string, sampleRate = 24_000): void {
    if (this.stopped || !this.context) return;
    const samples = decodePcm16(data);
    if (!samples.length) return;
    const buffer = this.context.createBuffer(1, samples.length, sampleRate);
    const channel = new Float32Array(samples.length);
    channel.set(samples);
    buffer.copyToChannel(channel, 0);
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);
    const start = Math.max(this.context.currentTime + 0.025, this.nextStart);
    this.nextStart = start + buffer.duration;
    this.playback.add(source);
    this.onSpeaking(false, true);
    source.onended = () => {
      this.playback.delete(source);
      source.disconnect();
      if (this.playback.size === 0) this.onSpeaking(false, false);
    };
    source.start(start);
  }

  interrupt(): void {
    this.nextStart = 0;
    this.playback.forEach((source) => {
      source.onended = null;
      try { source.stop(); } catch { /* Already ended. */ }
      source.disconnect();
    });
    this.playback.clear();
    this.onSpeaking(false, false);
  }

  stop(): void {
    if (this.stopped) return;
    this.stopped = true;
    this.generation += 1;
    this.interrupt();
    if (this.speakingTimeout) clearTimeout(this.speakingTimeout);
    if (this.processor) this.processor.onaudioprocess = null;
    this.source?.disconnect();
    this.processor?.disconnect();
    this.silentGain?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    const context = this.context;
    this.context = null;
    if (context && context.state !== 'closed') void context.close();
  }
}
