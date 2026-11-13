// Work decision op of the shared Worker `crypto` unit (parked wave-5 `work` lane).
// spec: specifications/features/plans#plans.content.client-encrypted
//
// One op carries every JSON decision of `openmates_sdk::web_work` (export in
// browser_work.rs): user Plan view projections, request paths and ordered
// request bodies. Only imported by flag-on code (the Worker installer and
// services/work/workRust.ts), so flag-off builds never reach it. No keys cross:
// the page decrypts and encrypts with its own plan/task keys.
import type { WebCryptoOp } from './webCryptoClient';

export type WorkOp = 'work';

/** Worker export behind the op; spread into the crypto unit's async export table. */
export const WORK_ASYNC_EXPORTS: Record<WorkOp, string> = {
  work: 'workDecide',
};

/** The slice of WebCryptoClient this helper needs (so tests can pass a fake). */
export interface WorkClient {
  call<T>(op: WebCryptoOp, ...args: unknown[]): Promise<T>;
}

/** Runs one named decision in the Worker; a `{error}` answer is rethrown as the original Error text. */
export async function workCall<T>(client: WorkClient, name: string, input: unknown): Promise<T> {
  const json = await client.call<string>('work', name, JSON.stringify(input));
  const output = JSON.parse(json) as unknown;
  if (output && typeof output === 'object' && typeof (output as { error?: unknown }).error === 'string') {
    throw new Error((output as { error: string }).error);
  }
  return output as T;
}
