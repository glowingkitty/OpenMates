// TEST-ONLY E2E proof hooks for the Rust web crypto facades
// (VITE_OPENMATES_RUST_CORE builds only; loaded on demand through
// window.__openmatesRustCryptoProof, which webCryptoRegistration installs only
// under browser automation). It calls decryptChatKeyWithMasterKey directly on
// purpose: it compares that facade (Rust vs TS) on fixture/benchmark keys and
// never loads or caches application chat keys, so ChatKeyManager (the
// ENC-DIRECT-CHAT-KEY-DECRYPT sanctioned path) does not apply to this harness.
// 1. Corpus: replays the TS-generated vectors (packages/openmates-rust/tests/
//    crypto_fixtures/ts_web_*.json) through the public TS module functions with
//    the Rust facade ON (shared Worker crypto unit), and through the original TS
//    code in the same page.
// 2. Benchmark: N TS-encrypted messages decrypted and encrypted plus chat-key
//    unwraps with the account's real (non-extractable) master key, original TS
//    vs Rust, sequential (one awaited op at a time) and parallel (Promise.all,
//    the chat-open shape), plus a round-trip/WASM/key-import attribution.
// Holds only synthetic fixtures and benchmark keys created in this page. Imports
// no WASM: every Rust call goes through the crypto unit port.
import { decryptWithChatKey, encryptWithChatKey, generateChatKey } from '@openmates/ui/src/services/encryption/MessageEncryptor';
import {
	decryptChatKeyWithMasterKey,
	decryptWithMasterKeyDirect,
	encryptChatKeyWithMasterKey
} from '@openmates/ui/src/services/encryption/MetadataEncryptor';
import { decryptShareKeyBlob } from '@openmates/ui/src/services/shareEncryption';
import { decryptEmbedShareKeyBlob } from '@openmates/ui/src/services/embedShareEncryption';
import { decryptShareUrl } from '@openmates/ui/src/services/shortUrlEncryption';
import { decryptMediaPayload } from '@openmates/ui/src/services/encryption/mediaEncryption';
import { getKeyFromStorage } from '@openmates/ui/src/services/cryptoService';
import { runTypeScriptCryptoBaseline, rustWebCrypto } from '@openmates/ui/src/services/rustCore/crypto/webCryptoClient';

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any -- fixture JSON is validated field by field below
export interface ProofCase { label: string; expected: string | null; rust: string | null; ts: string | null; ok: boolean }

const b64 = (value: string) => Uint8Array.from(atob(value), (c) => c.charCodeAt(0));
const hex = (bytes: Uint8Array | null | undefined) => (bytes ? Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('') : null);
/** Plaintext of every ts_web_policy chat_content vector (see its generate.cjs). */
const POLICY_PLAINTEXT = 'policy \u2713 text';
const bytesToB64 = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes));

async function both<T>(run: () => Promise<T>): Promise<{ rust: T | string; ts: T | string }> {
	const settle = (promise: Promise<T>) => promise.catch((error: unknown) => `threw:${error instanceof Error ? error.name : 'error'}`);
	if (!rustWebCrypto()) throw new Error('rust_web_crypto_not_registered');
	const rust = await settle(run());
	const ts = await settle(runTypeScriptCryptoBaseline(run));
	return { rust, ts };
}

/** Replays the TS corpus; `ok` requires Rust == TS-recorded expectation. */
export async function runCorpus(formats: Json, policy: Json): Promise<{ cases: ProofCase[]; failures: number }> {
	if (!rustWebCrypto()) throw new Error('rust_web_crypto_not_registered');
	const cases: ProofCase[] = [];
	const push = (label: string, expected: string | null, result: { rust: unknown; ts: unknown }, tsMayDiffer = false) => {
		const rust = result.rust as string | null;
		const ts = result.ts as string | null;
		cases.push({ label, expected, rust, ts, ok: rust === expected && (tsMayDiffer || ts === expected) });
	};
	const chatKey = b64(formats.keys.chat_key_b64);
	for (const c of formats.chat_content) {
		push(`chat:${c.layout}:${c.label}`, c.plaintext, await both(() => decryptWithChatKey(c.ciphertext, chatKey)));
	}
	// Writers: each implementation encrypts, the ORIGINAL TS reader must read it back.
	const writerText = formats.chat_content[0].plaintext as string;
	push('chat:writer-read-by-ts', writerText, await both(async () => {
		const sealed = await encryptWithChatKey(writerText, chatKey);
		return runTypeScriptCryptoBaseline(() => decryptWithChatKey(sealed, chatKey));
	}));
	push('chat:other-key', null, await both(() => decryptWithChatKey(formats.chat_content_other_key, chatKey)));
	const policyKeys: Record<string, Uint8Array> = { k1: b64(policy.keys.k1_b64), k2: b64(policy.keys.k2_b64) };
	for (const c of policy.chat_content) {
		// Documented superset: Rust also reads the historical Python marker and
		// legacy buffers whose random IV starts with "OM" (TS returns null).
		const superset = c.label === 'python-marker' || c.label === 'legacy-iv-starts-om';
		const expected = superset ? POLICY_PLAINTEXT : c.ts_plaintext;
		push(`policy:${c.label}`, expected, await both(() => decryptWithChatKey(c.ciphertext, policyKeys[c.key])), superset);
	}

	const master = await crypto.subtle.importKey('raw', b64(formats.keys.master_b64), { name: 'AES-GCM' }, false, ['encrypt', 'decrypt']);
	for (const c of formats.master_text) {
		push(`master:${c.label}`, c.plaintext, await both(() => decryptWithMasterKeyDirect(c.ciphertext, master)));
	}
	push(
		'master:chat-key-format-c',
		hex(chatKey),
		await both(async () => hex(await decryptChatKeyWithMasterKey(formats.wrappers.chat_key_master_format_c, master)))
	);

	const share = formats.share;
	const now = share.generated_at + 60;
	for (const c of share.chat) {
		push(
			`share:chat:${c.label}`,
			formats.keys.chat_key_b64,
			await both(async () => (await decryptShareKeyBlob(share.chat_id, c.blob, now, c.password ?? undefined)).chatEncryptionKey ?? null)
		);
		if (c.password) {
			push(`share:chat:${c.label}:missing-password`, 'password_required',
				await both(async () => (await decryptShareKeyBlob(share.chat_id, c.blob, now)).error ?? null));
			push(`share:chat:${c.label}:wrong-password`, 'invalid_password',
				await both(async () => (await decryptShareKeyBlob(share.chat_id, c.blob, now, 'wrong')).error ?? null));
		}
		if (c.duration_seconds > 0) {
			push(`share:chat:${c.label}:expired`, 'expired',
				await both(async () => (await decryptShareKeyBlob(share.chat_id, c.blob, share.generated_at + c.duration_seconds + 1, c.password)).error ?? null));
		}
	}
	const embedId = formats.wrappers.embed_id;
	for (const c of share.embed) {
		push(
			`share:embed:${c.label}`,
			hex(b64(formats.wrappers.derived_embed_key_b64)),
			await both(async () => hex((await decryptEmbedShareKeyBlob(embedId, c.blob, now, c.password ?? undefined)).embedKey))
		);
	}
	push('share:embed:tampered', 'decryption_failed',
		await both(async () => (await decryptEmbedShareKeyBlob(embedId, `${share.embed[0].blob.slice(0, -2)}AA`, now)).error ?? null));
	const short = share.short_url;
	push('short-url', short.url, await both(() => decryptShareUrl(short.encrypted, short.token, short.short_key)));
	push('short-url:wrong-key', 'threw:OperationError',
		await both(() => decryptShareUrl(short.encrypted, short.token, `${short.short_key.slice(0, -1)}A`)), true);

	const media = formats.media;
	for (const c of media.cases) {
		push(
			`media:${c.label}`,
			media.plaintext_b64,
			await both(async () => bytesToB64(new Uint8Array(await decryptMediaPayload({
				encryptedData: b64(c.data_b64).buffer as ArrayBuffer,
				aesKeyBase64: media.key_b64,
				variant: { encryption: c.encryption, aes_nonce: c.aes_nonce },
				legacyNonceBase64: c.legacy_nonce
			}))))
		);
	}
	push('media:unknown-marker', 'threw:MediaEncryptionError', await both(async () => bytesToB64(new Uint8Array(await decryptMediaPayload({
		encryptedData: b64(media.cases[0].data_b64).buffer as ArrayBuffer, aesKeyBase64: media.key_b64,
		variant: { encryption: 'aes-gcm-future-v9' }, legacyNonceBase64: null
	})))));
	// TS rejects wrong short keys with a DOMException; the Rust facade rejects with Error.
	const shortWrong = cases.find((c) => c.label === 'short-url:wrong-key');
	if (shortWrong) {
		const threw = (value: string | null) => typeof value === 'string' && value.startsWith('threw:');
		shortWrong.ok = threw(shortWrong.rust) && threw(shortWrong.ts);
	}
	return { cases, failures: cases.filter((c) => !c.ok).length };
}

// ── Benchmark ──

interface BenchFixture { chatKey: Uint8Array; messages: string[]; plaintexts: string[]; wrapped: string; masterKey: CryptoKey }
let fixture: BenchFixture | null = null;

/** Encrypts `count` messages with the ORIGINAL TS code and wraps one chat key with the account master key. */
export async function prepareBenchmark(count: number): Promise<{ messages: number; bytes: number }> {
	const masterKey = await getKeyFromStorage();
	if (!masterKey) throw new Error('benchmark_requires_logged_in_master_key');
	return runTypeScriptCryptoBaseline(async () => {
		const chatKey = generateChatKey();
		const plaintexts = Array.from({ length: count }, (_, index) =>
			JSON.stringify({ type: 'doc', content: [{ type: 'paragraph', text: `Benchmark message ${index} — ${'lorem ipsum '.repeat(1 + (index % 24))}` }] })
		);
		const messages = await Promise.all(plaintexts.map((text) => encryptWithChatKey(text, chatKey)));
		const wrapped = await encryptChatKeyWithMasterKey(chatKey);
		if (!wrapped) throw new Error('benchmark_wrap_failed');
		fixture = { chatKey, messages, plaintexts, wrapped, masterKey };
		return { messages: messages.length, bytes: messages.reduce((sum, value) => sum + value.length, 0) };
	});
}

export type BenchArm = 'ts' | 'rust';
export type BenchMode = 'parallel' | 'sequential';
export interface BenchArmResult {
	arm: BenchArm; mode: BenchMode; decryptMs: number; encryptMs: number; unwrapMs: number; unwraps: number; failures: number;
}

/** One arm: chat-key unwraps (real master key), then all message decrypts, then all re-encrypts, each in `mode`. */
export async function runBenchmarkArm(arm: BenchArm, mode: BenchMode, unwraps: number): Promise<BenchArmResult> {
	const current = fixture;
	if (!current) throw new Error('benchmark_not_prepared');
	const each = async <T, R>(items: T[], op: (item: T) => Promise<R>): Promise<R[]> => {
		if (mode === 'parallel') return Promise.all(items.map(op));
		const out: R[] = [];
		for (const item of items) out.push(await op(item));
		return out;
	};
	const body = async (): Promise<BenchArmResult> => {
		let failures = 0;
		// The page-side decrypt memo (a7776007ad) would answer repeat decrypts/unwraps without the
		// Worker, so the benchmark would stop measuring (and coalescing) them; start each arm cold.
		if (arm === 'rust') rustWebCrypto()?.dropResultMemo();
		const expectedKey = hex(current.chatKey);
		const unwrapStart = performance.now();
		const keys = await each(Array.from({ length: unwraps }), () => decryptChatKeyWithMasterKey(current.wrapped, current.masterKey));
		const unwrapMs = performance.now() - unwrapStart;
		for (const key of keys) if (!key || hex(key) !== expectedKey) failures += 1;
		const decryptStart = performance.now();
		const results = await each(current.messages, (message) => decryptWithChatKey(message, current.chatKey));
		const decryptMs = performance.now() - decryptStart;
		results.forEach((text, index) => { if (text !== current.plaintexts[index]) failures += 1; });
		const encryptStart = performance.now();
		const sealed = await each(current.plaintexts, (text) => encryptWithChatKey(text, current.chatKey));
		const encryptMs = performance.now() - encryptStart;
		if (sealed.length !== current.plaintexts.length || sealed.some((value) => typeof value !== 'string' || value.length === 0)) failures += 1;
		return { arm, mode, decryptMs, encryptMs, unwrapMs, unwraps, failures };
	};
	if (arm === 'ts') return runTypeScriptCryptoBaseline(body);
	if (!rustWebCrypto()) throw new Error('rust_web_crypto_not_registered');
	return body();
}

const medianOf = (values: number[]) => [...values].sort((x, y) => x - y)[Math.floor(values.length / 2)];

/**
 * Attribution of the Rust decrypt cost (ms per full message set, median of
 * `reps`): sequential page<->Worker round trips (`echo` with no payload and
 * with the same key + ciphertext payload as a decrypt), the whole list as one
 * batch (`echo` only, then the bulk decrypt), and inside the Worker the Rust
 * decrypt stages, the bulk path (Rust plan + WebCrypto AES-GCM, one list and
 * 256-item chunks) and the bare WebCrypto primitives for comparison.
 */
export async function profileDecrypt(reps: number): Promise<Record<string, number>> {
	const current = fixture;
	const client = rustWebCrypto();
	if (!current) throw new Error('benchmark_not_prepared');
	if (!client) throw new Error('rust_web_crypto_not_registered');
	const roundTrip: Record<string, number[]> = {
		pageRoundTripEmpty: [], pageRoundTripPayload: [], pageSequentialDecrypt: [], pageParallelEcho: [], pageParallelDecrypt: []
	};
	for (let rep = 0; rep <= reps; rep += 1) {
		let start = performance.now();
		for (let index = 0; index < current.messages.length; index += 1) await client.call('echo', null);
		const empty = performance.now() - start;
		start = performance.now();
		for (const message of current.messages) await client.call('echo', [new Uint8Array(current.chatKey), message]);
		const payload = performance.now() - start;
		start = performance.now();
		for (const message of current.messages) await client.call('decryptChatContent', new Uint8Array(current.chatKey), message);
		const decrypt = performance.now() - start;
		// One batch of the whole list: messaging cost alone (echo is never coalesced), then the bulk decrypt.
		start = performance.now();
		await Promise.all(current.messages.map((message) => client.call('echo', message)));
		const parallelEcho = performance.now() - start;
		start = performance.now();
		await Promise.all(current.messages.map((message) => client.call('decryptChatContent', new Uint8Array(current.chatKey), message)));
		const parallelDecrypt = performance.now() - start;
		if (rep === 0) continue; // warm-up
		roundTrip.pageParallelEcho.push(parallelEcho);
		roundTrip.pageParallelDecrypt.push(parallelDecrypt);
		roundTrip.pageRoundTripEmpty.push(empty);
		roundTrip.pageRoundTripPayload.push(payload);
		roundTrip.pageSequentialDecrypt.push(decrypt);
	}
	const worker = await client.call<Record<string, number>>('profileChatDecrypt', new Uint8Array(current.chatKey), current.messages, reps);
	const page = Object.fromEntries(Object.entries(roundTrip).map(([name, values]) => [name, medianOf(values)]));
	return { ...page, ...Object.fromEntries(Object.entries(worker).map(([name, value]) => [`worker.${name}`, value])) };
}

/** Cached chat-key ciphers in the crypto unit; logout proof. */
export async function chatKeyCacheSize(): Promise<number> {
	const client = rustWebCrypto();
	if (!client) throw new Error('rust_web_crypto_not_registered');
	return client.chatKeyCacheSize();
}

/** Main-thread JS heap (Chromium only); Worker + WASM memory is measured via process RSS by the spec. */
export function mainHeapBytes(): number | null {
	const memory = (performance as Performance & { memory?: { usedJSHeapSize: number } }).memory;
	return memory ? memory.usedJSHeapSize : null;
}

/** WASM fetched by the page realm itself (Workers' fetches are not listed here); must be empty. */
export function mainThreadWasmResources(): string[] {
	return performance.getEntriesByType('resource').map((entry) => entry.name).filter((name) => /\.wasm(?:$|\?)/.test(name));
}
