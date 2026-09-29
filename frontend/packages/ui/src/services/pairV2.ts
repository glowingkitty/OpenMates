import { getApiEndpoint } from '../config/api';
import { hashEmail } from './cryptoService';
import { decryptWithMasterKeyDirect, encryptWithMasterKeyDirect } from './encryption/MetadataEncryptor';

export const PAIR_POLL_MS = 1500;
export const PAIR_REQUEST_TIMEOUT_MS = 10000;

export type PairLifetime = null | 30 | 60 | 240 | 480 | 1440;
export type PairStatus = 'waiting' | 'approved' | 'request' | 'response' | 'finish' | 'ready' | 'claimed' | 'completed' | 'acknowledging' | 'acknowledged' | 'failed' | 'cancelled';

export interface PairInfo {
  protocol_version: 2;
  token?: string;
  session_id: string;
  receiver_token_hash: string;
  authorizer_user_id?: string;
  authorizer_device_name?: string | null;
  auto_logout_minutes?: PairLifetime;
  device_name?: string;
  ip_truncated?: string;
  country_code?: string | null;
  city?: string | null;
  expires_at: number;
}

export interface PairPoll extends Partial<PairInfo> {
  status: PairStatus;
  message?: string;
  receiver_request?: string;
  receiver_finish?: string;
  encrypted_bundle?: string;
  iv?: string;
}

export interface PairAccountCheck {
  user_id: string;
  hashed_email: string;
  user_email_salt: string;
  encrypted_email_with_master_key: string | null;
}

/** Build a receiver-verifiable envelope only for the server-bound account email.
 * A corrupt server envelope must fail closed; local metadata is used only when
 * an older account never had a server envelope in the first place.
 */
export async function resolvePairEmailEnvelope(
  account: PairAccountCheck,
  masterKey: CryptoKey,
  localEmail: string | null,
): Promise<string> {
  const existing = account.encrypted_email_with_master_key;
  const email = existing
    ? await decryptWithMasterKeyDirect(existing, masterKey)
    : localEmail;
  if (!email || await hashEmail(email) !== account.hashed_email) {
    throw new Error('Pairing master key mismatch');
  }
  if (existing) return existing;
  const envelope = await encryptWithMasterKeyDirect(email, masterKey);
  if (!envelope) throw new Error('Pairing account metadata unavailable');
  return envelope;
}

/** Pair requests have a strict local deadline. Never place a PIN or grant in a URL. */
export async function pairRequest<T>(path: string, options: RequestInit = {}, receiverCapability?: string): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), PAIR_REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(getApiEndpoint(`/v1/auth/pair/v2${path}`), {
      ...options,
      credentials: options.credentials ?? 'include',
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
        ...(receiverCapability ? { 'X-OpenMates-Pair-Receiver': receiverCapability } : {}),
      },
      signal: controller.signal,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(typeof body.detail === 'string' ? body.detail : typeof body.message === 'string' ? body.message : `Pairing request failed (${response.status})`);
      Object.assign(error, { status: response.status });
      throw error;
    }
    return body as T;
  } finally {
    clearTimeout(timeout);
  }
}

export function isPairTerminal(status: PairStatus): boolean {
  return status === 'failed' || status === 'cancelled' || status === 'acknowledged';
}

export function pairExpired(expiresAt: number): boolean {
  return !Number.isFinite(expiresAt) || Date.now() >= expiresAt * 1000;
}
