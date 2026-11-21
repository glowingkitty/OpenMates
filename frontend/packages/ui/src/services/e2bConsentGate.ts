/**
 * Web gate for E2B uploads (assertion code-run.e2b.upload-consent). The server
 * is the authority and refuses with HTTP 403 e2b_consent_*; this gate only
 * avoids a doomed request and asks the user before a run they start. Automatic
 * preview starts never prompt and never start without a recorded "allowed".
 */
import { get } from 'svelte/store';
import { text } from '../i18n/translations';
import { requestE2bConsentDialog } from '../stores/e2bConsentDialogStore';
import { readE2bConsent, writeE2bConsent } from './rustCore/e2bConsent/e2bConsentClient';
import type { E2bDecision } from './rustCore/e2bConsent/e2bConsentProtocol';

export type E2bStartKind = 'user' | 'auto';
export type E2bStartAction = 'start' | 'ask' | 'blocked';

export const E2B_CONSENT_REQUIRED_CODE = 'e2b_consent_required';
export const E2B_CONSENT_DECLINED_CODE = 'e2b_consent_declined';

/** What a start does for the account decision: only user starts may ask. */
export function e2bStartAction(decision: E2bDecision | null, kind: E2bStartKind): E2bStartAction {
  if (decision === 'allowed') return 'start';
  if (decision === 'declined') return 'blocked';
  return kind === 'user' ? 'ask' : 'blocked';
}

export function isE2bConsentRefusalCode(code: unknown): code is string {
  return code === E2B_CONSENT_REQUIRED_CODE || code === E2B_CONSENT_DECLINED_CODE;
}

/** The refusal code in a FastAPI `{detail: {code}}` error body, if any. */
export function e2bConsentCodeFromPayload(payload: unknown): string | undefined {
  const detail = (payload as { detail?: { code?: unknown } } | null)?.detail;
  return isE2bConsentRefusalCode(detail?.code) ? detail.code : undefined;
}

/** Nothing was started: no decision, or declined. Message names the settings path. */
export class E2bConsentRefusedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'E2bConsentRefusedError';
  }
}

function refused(): E2bConsentRefusedError {
  return new E2bConsentRefusedError(get(text)('e2b_consent.run.declined_notice'));
}

async function decideByDialog(): Promise<void> {
  const choice = await requestE2bConsentDialog();
  if (choice === 'allow') {
    await writeE2bConsent('allowed');
    return;
  }
  if (choice === 'own_machine' || choice === 'not_now') await writeE2bConsent('declined');
  throw refused();
}

/** Before a user-started run: allowed starts, undecided asks, declined refuses. */
export async function ensureE2bConsentForUserStart(): Promise<void> {
  let decision: E2bDecision | null;
  try {
    decision = (await readE2bConsent()).decision;
  } catch (error) {
    // The server refuses with 403 e2b_consent_* when undecided; that response is handled by
    // resolveServerE2bConsentRefusal, so an unreadable decision does not block the request.
    console.warn('[e2bConsentGate] decision unreadable, server will decide:', error instanceof Error ? error.message : error);
    return;
  }
  const action = e2bStartAction(decision, 'user');
  if (action === 'start') return;
  if (action === 'blocked') throw refused();
  await decideByDialog();
}

/** After a server 403 e2b_consent_*: ask (required) or refuse (declined); returns when allowed. */
export async function resolveServerE2bConsentRefusal(code: string): Promise<void> {
  if (code === E2B_CONSENT_DECLINED_CODE) throw refused();
  await decideByDialog();
}

/** Automatic starts: only when the account decision is "allowed"; never prompts. */
export async function isE2bAutoStartAllowed(): Promise<boolean> {
  try {
    return e2bStartAction((await readE2bConsent()).decision, 'auto') === 'start';
  } catch (error) {
    console.warn('[e2bConsentGate] decision unreadable, not auto-starting:', error instanceof Error ? error.message : error);
    return false;
  }
}
