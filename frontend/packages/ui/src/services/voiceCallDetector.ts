import type { VoiceDetector, VoiceDetectorCallbacks } from './voiceCallAudioGate';

export interface DetectorReply {
  type: 'ready' | 'result' | 'error';
  epoch?: number;
  probabilities?: number[];
}

/** The only PCM copy outside capture is sent to a dedicated, CPU-only worker. */
export function createVoiceCallDetector(callbacks: VoiceDetectorCallbacks, signal: AbortSignal): Promise<VoiceDetector> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new Error('Detector cancelled')); return; }
    const worker = new Worker(new URL('./voiceCallDetector.worker.ts', import.meta.url), { type: 'module' });
    let stopped = false;
    let ready = false;
    let epoch = 0;
    let busy = false;
    let queue: Float32Array[] = [];
    let queuedSamples = 0;
    const stop = () => {
      if (stopped) return;
      stopped = true;
      queue = [];
      queuedSamples = 0;
      worker.onmessage = null;
      worker.onerror = null;
      worker.onmessageerror = null;
      worker.terminate();
      signal.removeEventListener('abort', cancel);
    };
    const cancel = () => { stop(); reject(new Error('Detector cancelled')); };
    const fail = () => {
      if (stopped) return;
      stop();
      if (ready) callbacks.onFailure();
      else reject(new Error('Local detector failed'));
    };
    const dispatch = () => {
      if (stopped || busy || !queue.length) return;
      const samples = queue.shift()!;
      queuedSamples -= samples.length;
      busy = true;
      worker.postMessage({ type: 'audio', epoch, samples }, [samples.buffer]);
    };
    worker.onerror = fail;
    worker.onmessageerror = fail;
    worker.onmessage = ({ data }: MessageEvent<DetectorReply>) => {
      if (stopped) return;
      if (data.type === 'error') { fail(); return; }
      if (data.type === 'ready') {
        if (ready) { fail(); return; }
        ready = true;
        resolve({
          push(samples) {
            if (stopped) return;
            // Gate bounds processing+queued samples too; this independent cap protects the adapter.
            if (queuedSamples + samples.length > 4096) { fail(); return; }
            queue.push(samples);
            queuedSamples += samples.length;
            dispatch();
          },
          reset() {
            if (stopped) return;
            epoch++;
            queue = [];
            queuedSamples = 0;
            busy = false;
            worker.postMessage({ type: 'reset', epoch });
          },
          stop,
        });
      } else if (data.type === 'result' && data.epoch === epoch) {
        if (!busy || !Array.isArray(data.probabilities)) { fail(); return; }
        busy = false;
        for (const probability of data.probabilities) {
          if (stopped) break;
          callbacks.onResult(probability, 512);
        }
        dispatch();
      }
    };
    signal.addEventListener('abort', cancel, { once: true });
  });
}
