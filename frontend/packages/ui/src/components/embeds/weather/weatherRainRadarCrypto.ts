/**
 * frontend/packages/ui/src/components/embeds/weather/weatherRainRadarCrypto.ts
 *
 * Client-side loader for encrypted Weather / Rain radar blobs.
 * Fetches private S3 objects through the shared presigned URL service, decrypts
 * AES-GCM payloads locally, and inflates the compact radar-grid JSON for canvas
 * rendering without exposing raw grids to the LLM context.
 */

import { fetchWithPresignedUrl } from '../../../services/presignedUrlService';

const NONCE_BYTES = 12;

export interface RadarBlobFrame {
  frame_id: string;
  timestamp?: string;
  kind?: string;
  values: number[];
}

export interface RadarBlobPayload {
  version: number;
  bounds?: {
    north: number;
    west: number;
    south: number;
    east: number;
  } | null;
  grid: {
    width: number;
    height: number;
    resolution_km?: number;
    unit?: string;
  };
  frames: RadarBlobFrame[];
}

export async function loadRainRadarBlob(options: {
  radarBlobBase64?: string;
  s3Key?: string;
  aesKeyBase64?: string;
  nonceBase64?: string;
}): Promise<RadarBlobPayload> {
  const compressed = options.radarBlobBase64
    ? base64ToBytes(options.radarBlobBase64)
    : await fetchDecryptRadarBlob(options);

  const inflated = await inflateZlib(compressed);
  const decoded = new TextDecoder().decode(inflated);
  return JSON.parse(decoded) as RadarBlobPayload;
}

async function fetchDecryptRadarBlob(options: {
  s3Key?: string;
  aesKeyBase64?: string;
  nonceBase64?: string;
}): Promise<Uint8Array> {
  const { s3Key, aesKeyBase64, nonceBase64 = '' } = options;
  if (!s3Key || !aesKeyBase64) {
    throw new Error('Rain radar blob is missing encrypted storage metadata.');
  }

  const encrypted = new Uint8Array(await fetchWithPresignedUrl(s3Key));
  const nonce = nonceBase64
    ? base64ToBytes(nonceBase64)
    : encrypted.slice(0, NONCE_BYTES);
  const ciphertext = nonceBase64 ? encrypted : encrypted.slice(NONCE_BYTES);
  const cryptoKey = await crypto.subtle.importKey(
    'raw',
    bytesToArrayBuffer(base64ToBytes(aesKeyBase64)),
    { name: 'AES-GCM' },
    false,
    ['decrypt'],
  );
  const decrypted = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: bytesToArrayBuffer(nonce) },
    cryptoKey,
    bytesToArrayBuffer(ciphertext),
  );
  return new Uint8Array(decrypted);
}

async function inflateZlib(compressed: Uint8Array): Promise<Uint8Array> {
  const Decompression = (globalThis as typeof globalThis & {
    DecompressionStream?: new (format: string) => GenericTransformStream;
  }).DecompressionStream;
  if (!Decompression) {
    throw new Error('This browser does not support radar blob decompression.');
  }

  const stream = new Blob([bytesToArrayBuffer(compressed)]).stream().pipeThrough(new Decompression('deflate'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

function base64ToBytes(base64: string): Uint8Array {
  const normalized = base64.replace(/-/g, '+').replace(/_/g, '/');
  const binary = atob(normalized);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function bytesToArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
}
