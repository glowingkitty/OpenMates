/// <reference lib="webworker" />
/** Silero v5 runs entirely on this worker. No audio, probabilities or state are persisted. */
import * as ort from 'onnxruntime-web/wasm';
import modelUrl from '@ricky0123/vad-web/dist/silero_vad_v5.onnx?url';
import wasmUrl from 'onnxruntime-web/ort-wasm-simd-threaded.wasm?url';
import wasmModuleUrl from 'onnxruntime-web/ort-wasm-simd-threaded.mjs?url';

declare const self: DedicatedWorkerGlobalScope;

interface DetectorMessage {
  type: 'audio' | 'reset';
  epoch: number;
  samples?: Float32Array;
}

// Vite emits all three pinned assets at hashed, same-origin URLs. No CDN fallback.
ort.env.wasm.wasmPaths = { wasm: wasmUrl, mjs: wasmModuleUrl };
ort.env.wasm.numThreads = 1;
ort.env.wasm.proxy = false;
let session: ort.InferenceSession;
let state = new ort.Tensor('float32', new Float32Array(256), [2, 1, 128]);
const sampleRate = new ort.Tensor('int64', BigInt64Array.from([16_000n]), [1]);
let context = new Float32Array(64);
let pending = new Float32Array(0);
let epoch = 0;
let failed = false;

function reset(): void {
  state.dispose();
  state = new ort.Tensor('float32', new Float32Array(256), [2, 1, 128]);
  context = new Float32Array(64);
  pending = new Float32Array(0);
}

async function infer(frame: Float32Array): Promise<number> {
  const input = new Float32Array(576);
  input.set(context);
  input.set(frame, 64);
  const tensor = new ort.Tensor('float32', input, [1, 576]);
  const outputs = await session.run({ input: tensor, state, sr: sampleRate });
  tensor.dispose();
  const probability = Number(outputs.output?.data[0]);
  if (!outputs.stateN || !Number.isFinite(probability) || probability < 0 || probability > 1) {
    Object.values(outputs).forEach((output) => output.dispose());
    throw new Error('Invalid detector output');
  }
  state.dispose();
  state = outputs.stateN;
  for (const [name, tensor] of Object.entries(outputs)) if (name !== 'stateN') tensor.dispose();
  context = frame.slice(-64);
  return probability;
}

async function initialize(): Promise<void> {
  // Browser HTTP caching reuses hashed model/WASM assets; PCM never enters a cache.
  const response = await fetch(modelUrl, { cache: 'force-cache', credentials: 'same-origin' });
  if (!response.ok) throw new Error('Detector model unavailable');
  session = await ort.InferenceSession.create(await response.arrayBuffer(), {
    executionProviders: ['wasm'], graphOptimizationLevel: 'all',
  });
  await infer(new Float32Array(512));
  reset();
  self.postMessage({ type: 'ready' });
}

async function process(message: DetectorMessage): Promise<void> {
  if (message.type === 'reset') {
    epoch = message.epoch;
    reset();
    return;
  }
  if (message.epoch !== epoch || !message.samples || message.samples.length > 4096) {
    throw new Error('Invalid detector input');
  }
  // At most 511 previous samples plus one bounded capture chunk, never an utterance.
  const samples = new Float32Array(pending.length + message.samples.length);
  samples.set(pending);
  samples.set(message.samples, pending.length);
  const probabilities: number[] = [];
  let offset = 0;
  while (offset + 512 <= samples.length) {
    probabilities.push(await infer(samples.subarray(offset, offset + 512)));
    offset += 512;
  }
  pending = samples.slice(offset);
  self.postMessage({ type: 'result', epoch, probabilities });
}

// Serialize resets with in-flight inference, including mute/unmute before a reply.
let chain = initialize();
self.onmessage = ({ data }: MessageEvent<DetectorMessage>) => {
  if (failed) return;
  chain = chain.then(() => process(data));
  void chain.catch(fail);
};
function fail(): void {
  if (failed) return;
  failed = true;
  self.postMessage({ type: 'error' });
  state.dispose();
  sampleRate.dispose();
  if (session) void session.release();
  self.close();
}
void chain.catch(fail);
