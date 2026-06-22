// frontend/packages/ui/src/services/connectedAccountCliTransfer.ts
//
// Passcode-protected connected-account transfer payloads for testing. The
// browser decrypts one selected connected account locally, encrypts the transfer
// payload with a user-entered passcode, and copies only ciphertext into the CLI
// command. Plaintext token material must never leave this module except inside
// the encrypted OMCA1 payload.
//
// Spec: docs/specs/connected-account-cli-import/spec.yml

import { decryptWithMasterKey } from './cryptoService';
import type { EncryptedConnectedAccountRow } from './connectedAccountStorageService';

const TRANSFER_PREFIX = 'OMCA1.';
const KDF_ITERATIONS = 100_000;
const SALT_BYTES = 16;
const IV_BYTES = 12;

interface ConnectedAccountDirectoryHint {
	account_ref?: string;
	label?: string;
	capabilities?: string[];
	runtime_modes?: Record<string, string>;
}

interface ConnectedAccountPermissionsEnvelope {
	app_id?: string;
	allowed_actions?: string[];
	scopes?: string[];
}

export interface ConnectedAccountCliTransferPayload {
	version: 1;
	provider_id: string;
	app_id: string;
	label: string;
	account_ref?: string;
	capabilities: string[];
	runtime_modes: Record<string, string>;
	refresh_token_bundle: Record<string, unknown>;
	created_at: string;
}

interface EncryptedTransferEnvelope {
	version: 1;
	kdf: {
		name: 'PBKDF2-SHA256';
		iterations: number;
		salt: string;
	};
	cipher: {
		name: 'AES-256-GCM';
		iv: string;
		text: string;
	};
}

export async function buildConnectedAccountCliImportCommand(params: {
	row: EncryptedConnectedAccountRow;
	passcode: string;
}): Promise<string> {
	const payload = await buildTransferPayload(params.row);
	const encryptedPayload = await encryptTransferPayload(payload, params.passcode);
	if (encryptedPayload.includes('refresh_token')) {
		throw new Error('Connected account transfer command unexpectedly contains token field names');
	}
	return `openmates connected-accounts import --payload "${encryptedPayload}"`;
}

export async function encryptTransferPayload(
	payload: ConnectedAccountCliTransferPayload,
	passcode: string
): Promise<string> {
	if (!passcode.trim()) {
		throw new Error('A passcode is required to export a connected account');
	}
	const salt = crypto.getRandomValues(new Uint8Array(SALT_BYTES));
	const iv = crypto.getRandomValues(new Uint8Array(IV_BYTES));
	const key = await deriveTransferKey(passcode, salt);
	const encodedPayload = new TextEncoder().encode(JSON.stringify(payload));
	const ciphertext = await crypto.subtle.encrypt(
		{ name: 'AES-GCM', iv: toArrayBuffer(iv) },
		key,
		toArrayBuffer(encodedPayload)
	);
	const envelope: EncryptedTransferEnvelope = {
		version: 1,
		kdf: {
			name: 'PBKDF2-SHA256',
			iterations: KDF_ITERATIONS,
			salt: base64UrlEncode(salt)
		},
		cipher: {
			name: 'AES-256-GCM',
			iv: base64UrlEncode(iv),
			text: base64UrlEncode(new Uint8Array(ciphertext))
		}
	};
	return `${TRANSFER_PREFIX}${base64UrlEncode(new TextEncoder().encode(JSON.stringify(envelope)))}`;
}

async function buildTransferPayload(row: EncryptedConnectedAccountRow): Promise<ConnectedAccountCliTransferPayload> {
	const [providerId, label, capabilitiesValue, permissions, directoryHint, refreshTokenBundle] = await Promise.all([
		decryptConnectedAccountValue<string>(row.encrypted_provider_type, 'encrypted_provider_type'),
		decryptConnectedAccountValue<string>(row.encrypted_account_label, 'encrypted_account_label'),
		decryptConnectedAccountValue<string[] | { capabilities?: string[] }>(
			row.encrypted_capabilities,
			'encrypted_capabilities'
		),
		decryptConnectedAccountValue<ConnectedAccountPermissionsEnvelope>(
			row.encrypted_app_permissions,
			'encrypted_app_permissions'
		),
		row.encrypted_account_directory_hint
			? decryptConnectedAccountValue<ConnectedAccountDirectoryHint>(
				row.encrypted_account_directory_hint,
				'encrypted_account_directory_hint'
			)
			: Promise.resolve(undefined),
		decryptConnectedAccountValue<Record<string, unknown>>(
			row.encrypted_refresh_token_bundle,
			'encrypted_refresh_token_bundle'
		)
	]);

	if (typeof refreshTokenBundle.refresh_token !== 'string' || !refreshTokenBundle.refresh_token) {
		throw new Error('Connected account refresh token bundle is missing a refresh token');
	}
	const capabilities = normalizeCapabilityList(directoryHint?.capabilities).length
		? normalizeCapabilityList(directoryHint?.capabilities)
		: normalizeCapabilityList(capabilitiesValue);
	return {
		version: 1,
		provider_id: providerId,
		app_id: normalizeAppId(permissions.app_id ?? appIdForProvider(providerId)),
		label: directoryHint?.label ?? label,
		...(directoryHint?.account_ref ? { account_ref: directoryHint.account_ref } : {}),
		capabilities,
		runtime_modes: directoryHint?.runtime_modes ?? runtimeModesForActions(permissions.allowed_actions ?? []),
		refresh_token_bundle: refreshTokenBundle,
		created_at: new Date().toISOString()
	};
}

async function decryptConnectedAccountValue<T>(encryptedValue: string, fieldName: string): Promise<T> {
	const decrypted = await decryptWithMasterKey(encryptedValue);
	if (!decrypted) {
		throw new Error(`Failed to decrypt connected account field: ${fieldName}`);
	}
	try {
		return JSON.parse(decrypted) as T;
	} catch {
		return decrypted as T;
	}
}

async function deriveTransferKey(passcode: string, salt: Uint8Array): Promise<CryptoKey> {
	const keyMaterial = await crypto.subtle.importKey(
		'raw',
		new TextEncoder().encode(passcode),
		'PBKDF2',
		false,
		['deriveKey']
	);
	return crypto.subtle.deriveKey(
		{
			name: 'PBKDF2',
			salt: toArrayBuffer(salt),
			iterations: KDF_ITERATIONS,
			hash: 'SHA-256'
		},
		keyMaterial,
		{ name: 'AES-GCM', length: 256 },
		false,
		['encrypt', 'decrypt']
	);
}

function normalizeCapabilityList(value: unknown): string[] {
	if (Array.isArray(value)) {
		return value.filter((item): item is string => typeof item === 'string');
	}
	if (value && typeof value === 'object' && Array.isArray((value as { capabilities?: unknown }).capabilities)) {
		return normalizeCapabilityList((value as { capabilities?: unknown }).capabilities);
	}
	return [];
}

function runtimeModesForActions(actions: string[]): Record<string, string> {
	return Object.fromEntries(actions.map((action) => [action, action === 'read' ? 'allow_automatically' : 'always_ask']));
}

function normalizeAppId(appId: string): string {
	if (appId === 'google_calendar') return 'calendar';
	return appId;
}

function appIdForProvider(providerId: string): string {
	if (providerId === 'google_calendar') return 'calendar';
	return providerId;
}

function base64UrlEncode(bytes: Uint8Array): string {
	let binary = '';
	for (let index = 0; index < bytes.length; index += 1) {
		binary += String.fromCharCode(bytes[index] ?? 0);
	}
	return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function toArrayBuffer(input: Uint8Array): ArrayBuffer {
	const output = new ArrayBuffer(input.byteLength);
	new Uint8Array(output).set(input);
	return output;
}
