/** Shared signed recovery fixture helpers. */
/* eslint-disable @typescript-eslint/no-require-imports */
const { expect } = require('./console-monitor');
const { getTestAccount } = require('./signup-flow-helpers');
import type { Page } from '@playwright/test';

export type RecoveryOutput = {
	root_chat_id: string;
	record_id: string;
	output_kind: string;
	output_version: number;
	message_role?: string;
};

type RecoveryPayload = {
	outputs?: RecoveryOutput[];
	status?: string;
	state?: string;
	request_id?: string;
	record_id?: string;
	recovery_record_id?: string;
	canonical_digest?: string;
	canonical_source?: string;
	chat_id?: string;
	code?: string;
	message?: string;
	message_id?: string;
	explicit_deleted_chat_ids?: string[];
	[key: string]: unknown;
};

export type RecoveryFrame = { direction?: 'sent' | 'received'; type: string; payload: RecoveryPayload };

function parseRecoveryFrame(raw: unknown): Pick<RecoveryFrame, 'type' | 'payload'> | null {
	try {
		const value: unknown = JSON.parse(String(raw));
		if (typeof value !== 'object' || value === null || !('type' in value) || typeof value.type !== 'string') return null;
		const payload = 'payload' in value && typeof value.payload === 'object' && value.payload !== null
			? value.payload as RecoveryPayload : {};
		return { type: value.type, payload };
	} catch {
		return null;
	}
}

export function requireSignedRecoveryProfile(): void {
	if (process.env.E2E_STORAGE_CAPACITY !== '1') {
		throw new Error('Storage recovery replay requires the isolated signed zero-provider CI profile.');
	}
	if (!getTestAccount().email) {
		throw new Error('Storage recovery replay requires a disposable isolated test account.');
	}
}

export function observeRecoveryFrames(page: Page, includeSent = false): RecoveryFrame[] {
	const frames: RecoveryFrame[] = [];
	page.on('websocket', (socket) => {
		const capture = (direction: 'sent' | 'received') => (frame: { payload: string | Buffer }) => {
			const parsed = parseRecoveryFrame(frame.payload);
			if (parsed) frames.push({ direction, ...parsed });
		};
		socket.on('framereceived', capture('received'));
		if (includeSent) socket.on('framesent', capture('sent'));
	});
	return frames;
}

export function availableOutputs(frames: RecoveryFrame[], chatId: string): RecoveryOutput[] {
	return frames.filter((frame) => frame.type === 'recovery_outputs_available')
		.flatMap((frame) => frame.payload.outputs ?? [])
		.filter((output) => output.root_chat_id === chatId);
}

export async function requireActiveRecoveryDiscovery(frames: RecoveryFrame[]): Promise<void> {
	await expect.poll(() => frames.find((frame) => frame.type === 'recovery_outputs_discovery_complete')?.payload.status,
		{ timeout: 30_000, message: 'Recovery discovery must complete under the active protocol epoch' })
		.toBe('completed');
}

export async function disconnectCanonicalWrites(page: Page, frames: RecoveryFrame[] = []): Promise<void> {
	await page.routeWebSocket(/\/v1\/ws(?:\?|$)/, (socket) => {
		const server = socket.connectToServer();
		const blocked = new Set([
			'store_embed', 'store_embed_diff', 'store_embed_keys',
			'store_chat_compression_checkpoint', 'recovery_output_persist_message',
			'recovery_output_persist_summary', 'recovery_output_ack_checkpoint',
			'recovery_output_ack_embed', 'recovery_job_claim',
		]);
		socket.onMessage((raw) => {
			let type = '';
			try { type = JSON.parse(String(raw)).type; } catch { /* Preserve non-JSON frames. */ }
			if (!blocked.has(type)) server.send(raw);
		});
		server.onMessage((raw) => {
			const parsed = parseRecoveryFrame(raw);
			if (parsed) frames.push(parsed);
			socket.send(raw);
		});
	});
}

export async function installLegacyRecoverySocket(page: Page): Promise<void> {
	await page.addInitScript(() => {
		const NativeWebSocket = window.WebSocket;
		const LegacyWebSocket = function(url: string | URL, protocols?: string | string[]) {
			const next = new URL(String(url), window.location.href);
			next.searchParams.delete('client_capabilities');
			const socket = protocols === undefined ? new NativeWebSocket(next) : new NativeWebSocket(next, protocols);
			Object.assign(window, { __legacyRecoverySocket: socket });
			return socket;
		} as unknown as typeof WebSocket;
		LegacyWebSocket.prototype = NativeWebSocket.prototype;
		for (const field of ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'] as const) {
			Object.defineProperty(LegacyWebSocket, field, { value: NativeWebSocket[field] });
		}
		Object.defineProperty(window, 'WebSocket', { value: LegacyWebSocket, configurable: true });
	});
}
