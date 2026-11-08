// `crypto` unit of the shared Rust core Worker (VITE_OPENMATES_RUST_CORE builds).
// Installed by the shared Worker router on the namespace port (pre-bind allowed:
// share links open logged out). Serves the WebCryptoBatch protocol of
// webCryptoClient.ts on ports[0] against the realm's single WASM binding.
//
// Every op is one Rust export (`webCrypto*`): Rust owns the formats and policy
// (chat OM/legacy, master Formats C/D, share/PBKDF2, short URLs, media, the
// chat-key write guard) and runs the raw AES-GCM primitive through its web AEAD
// adapter on this Worker's WebCrypto. Chat keys are imported non-extractable and
// cached in Rust by digest; master-key ops use the page's own structured-cloned,
// non-extractable master CryptoKey. A `bulk` list is one WASM call. Holds no
// account state: keys arrive per request; caches are dropped by `clearChatKeys`
// and when the unit is disposed.
// Errors cross the port as short fixed codes only (no key or plaintext).
import type {
  WebCryptoBatch,
  WebCryptoBulkResult,
  WebCryptoOp,
  WebCryptoReplies,
  WebCryptoResponse,
} from './webCryptoClient';
import { BULK_EXPORTS, createBulkRunner } from './cryptoUnitBulk';
import { KEY_ASYNC_EXPORTS } from './keyOps';
import { GUEST_ASYNC_EXPORTS } from './guestOps';
import { SHARE_STATE_ASYNC_EXPORTS } from './shareStateOps';
import { WORK_ASYNC_EXPORTS } from './workOps';
import type { UnitInstaller } from '../host/sharedWorkerProtocol';

type Fn = (...args: unknown[]) => unknown;
type Binding = Record<string, unknown>;

/** Async exports called with the request args unchanged. */
const ASYNC_EXPORTS: Partial<Record<WebCryptoOp, string>> = {
  decryptChatContent: 'webCryptoDecryptChatContent',
  encryptChatContent: 'webCryptoEncryptChatContent',
  masterDecrypt: 'webCryptoMasterDecrypt',
  masterEncrypt: 'webCryptoMasterEncrypt',
  generateShareKeyBlob: 'webCryptoGenerateShareKeyBlob',
  decryptShareKeyBlob: 'webCryptoDecryptShareKeyBlob',
  encryptShareUrl: 'webCryptoEncryptShareUrl',
  decryptShareUrl: 'webCryptoDecryptShareUrl',
  decryptMedia: 'webCryptoDecryptMedia',
  guardBegin: 'webCryptoChatKeyGuardBegin',
  guardAfterAnonymous: 'webCryptoChatKeyGuardAfterAnonymous',
  guardAfterPersisted: 'webCryptoChatKeyGuardAfterPersisted',
  ...KEY_ASYNC_EXPORTS,
  ...GUEST_ASYNC_EXPORTS,
  ...SHARE_STATE_ASYNC_EXPORTS,
  ...WORK_ASYNC_EXPORTS,
};

const REQUIRED = [
  ...Object.values(ASYNC_EXPORTS), ...BULK_EXPORTS, 'webCryptoClearChatKeys', 'webCryptoChatKeyCacheSize',
] as const;

function message(error: unknown): string {
  if (typeof error === 'string') return error;
  if (error instanceof Error) return error.message;
  return 'rust_web_crypto_failed';
}

export interface CryptoUnit {
  /**
   * Answers one batch (null when malformed). `emit`, when given, receives each
   * response as soon as it settles, so a reply never waits for a slower
   * request of the same batch; the resolved value still holds all of them.
   */
  handle(batch: unknown, emit?: (replies: WebCryptoReplies) => void): Promise<WebCryptoReplies | null>;
  /** Drops every cached chat-key cipher. */
  clear(): void;
}

export function createCryptoUnit(raw: unknown): CryptoUnit {
  const binding = raw as Binding;
  for (const name of REQUIRED) {
    if (typeof binding?.[name] !== 'function') throw new Error(`rust_web_crypto_export_missing:${name}`);
  }
  const fn = (name: string) => binding[name] as Fn;
  const clearCiphers = () => {
    fn('webCryptoClearChatKeys')();
  };
  // Unit disposal terminates the Worker key state too; the `clearChatKeys` op only
  // drops cached ciphers (it also runs on single-key removal), so the key store
  // is cleared by the explicit `keysStateClear` op or by disposal.
  const clear = () => {
    clearCiphers();
    fn('keysStateClear')();
  };

  const runBulk: (args: unknown[]) => Promise<WebCryptoBulkResult> = createBulkRunner(binding);

  async function run(op: WebCryptoOp, args: unknown[]): Promise<unknown> {
    switch (op) {
      case 'bulk': return runBulk(args);
      case 'clearChatKeys': clearCiphers(); return undefined;
      case 'chatKeyCacheSize': return fn('webCryptoChatKeyCacheSize')() as number;
      case 'echo': return args[0];
      case 'profileChatDecrypt': return profileChatDecrypt(binding, runBulk, args[0], args[1], args[2]);
      default: {
        const name = ASYNC_EXPORTS[op];
        if (!name) throw new Error('rust_web_crypto_unknown_op');
        return fn(name)(...args);
      }
    }
  }

  async function answer({ id, op, args }: { id: number; op: WebCryptoOp; args: unknown[] }): Promise<WebCryptoResponse> {
    try {
      if (!Array.isArray(args)) throw new Error('rust_web_crypto_bad_request');
      return { id, ok: true, value: await run(op, args) };
    } catch (error) {
      return { id, ok: false, error: message(error) };
    }
  }

  return {
    clear,
    async handle(data, emit) {
      const batch = data as WebCryptoBatch | null;
      if (batch?.version !== 1 || !Array.isArray(batch.requests)) return null;
      return {
        version: 1,
        responses: await Promise.all(batch.requests.map(async (request) => {
          const response = await answer(request);
          emit?.({ version: 1, responses: [response] });
          return response;
        })),
      };
    },
  };
}

const medianOf = (values: number[]) => [...values].sort((x, y) => x - y)[Math.floor(values.length / 2)];
const fromBase64 = (value: string) => Uint8Array.from(atob(value), (c) => c.charCodeAt(0));

/**
 * Benchmark attribution only (E2E proof harness): times, inside this Worker, the
 * per-list cost of each decrypt stage over `ciphertexts` (ms per list, median of
 * `reps` after one warm-up). Returns timings only, never key or plaintext bytes.
 */
async function profileChatDecrypt(
  binding: Binding, runBulk: (args: unknown[]) => Promise<WebCryptoBulkResult>, key: unknown, ciphertexts: unknown, reps: unknown): Promise<Record<string, number>> {
  if (!(key instanceof Uint8Array) || key.length !== 32 || !Array.isArray(ciphertexts)
    || !ciphertexts.every((value) => typeof value === 'string') || typeof reps !== 'number' || reps < 1 || reps > 20) {
    throw new Error('rust_web_crypto_bad_request');
  }
  const texts = ciphertexts as string[];
  const decoded = texts.map(fromBase64);
  const one = binding.webCryptoDecryptChatContent as Fn;
  const runs: Record<string, () => Promise<void> | void> = {
    rustSequential: async () => { for (const m of texts) await one(key, m); },
    rustParallel: async () => { await Promise.all(texts.map((m) => one(key, m))); },
    rustBulk: async () => { await runBulk(['decryptChatContent', key, texts]); },
    rustBulkChunks: async () => {
      const chunks: Promise<WebCryptoBulkResult>[] = [];
      for (let start = 0; start < texts.length; start += 256) chunks.push(runBulk(['decryptChatContent', key, texts.slice(start, start + 256)]));
      await Promise.all(chunks);
    },
    subtleParallel: async () => {
      const cryptoKey = await crypto.subtle.importKey('raw', new Uint8Array(key), { name: 'AES-GCM' }, false, ['decrypt']);
      await Promise.all(decoded.map((bytes) => crypto.subtle.decrypt({ name: 'AES-GCM', iv: bytes.subarray(6, 18) }, cryptoKey, bytes.subarray(18))));
    },
    subtleImportPerItem: async () => {
      for (let index = 0; index < texts.length; index += 1) {
        await crypto.subtle.importKey('raw', new Uint8Array(key), { name: 'AES-GCM' }, false, ['decrypt']);
      }
    },
    subtleSequential: async () => {
      const cryptoKey = await crypto.subtle.importKey('raw', new Uint8Array(key), { name: 'AES-GCM' }, false, ['decrypt']);
      // Same layout as the TS reader: "OM" + 4-byte fingerprint + 12-byte IV + body.
      for (const bytes of decoded) await crypto.subtle.decrypt({ name: 'AES-GCM', iv: bytes.subarray(6, 18) }, cryptoKey, bytes.subarray(18));
    },
  };
  const samples: Record<string, number[]> = Object.fromEntries(Object.keys(runs).map((name) => [name, []]));
  for (let rep = 0; rep <= reps; rep += 1) {
    for (const [name, run] of Object.entries(runs)) {
      const start = performance.now();
      await run();
      if (rep > 0) samples[name].push(performance.now() - start);
    }
  }
  return Object.fromEntries(Object.entries(samples).map(([name, values]) => [name, medianOf(values)]));
}

/** Buffers this large move to the page; smaller ones (chat keys) are cheaper to copy than to transfer. */
const TRANSFER_MIN_BYTES = 64 * 1024;

function transferables(replies: WebCryptoReplies): Transferable[] {
  const transfer: Transferable[] = [];
  const add = (value: unknown) => {
    if (value instanceof Uint8Array && value.byteLength >= TRANSFER_MIN_BYTES && value.byteOffset === 0
      && value.byteLength === value.buffer.byteLength) transfer.push(value.buffer);
  };
  for (const response of replies.responses) {
    if (!response.ok) continue;
    add(response.value);
    const bulk = response.value as WebCryptoBulkResult | null;
    if (bulk && Array.isArray(bulk.values)) bulk.values.forEach(add);
  }
  return transfer;
}

/** Shared Worker installer for the `crypto` namespace. */
export const installCryptoUnit: UnitInstaller = ({ binding, ports }) => {
  const unit = createCryptoUnit(binding);
  const port = ports[0];
  port.onmessage = (event: MessageEvent<unknown>) => {
    void unit.handle(event.data, (replies) => port.postMessage(replies, transferables(replies)));
  };
  port.start();
  return () => {
    port.onmessage = null;
    unit.clear();
  };
};
