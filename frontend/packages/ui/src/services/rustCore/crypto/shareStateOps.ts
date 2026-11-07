// Share-state decision op of the shared Worker `crypto` unit (share-guest-crypto lane).
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//
// One op carries every JSON decision of `openmates_sdk::web_share_state` (export in
// browser_share_state.rs): short-URL parsing, shared-chat key entries, the share
// metadata queue, shared plan/task/sub-chat page checks, incognito persistence and
// anonymous-chat helpers. Only imported by flag-on code (the Worker installer and
// shareState/decide.ts), so flag-off builds never reference it. No keys involved.
import type { WebCryptoOp } from './webCryptoClient';

export type ShareStateOp = 'shareState';

/** Worker export behind the op; spread into the crypto unit's async export table. */
export const SHARE_STATE_ASYNC_EXPORTS: Record<ShareStateOp, string> = {
  shareState: 'shareStateDecide',
};

/** The slice of WebCryptoClient this helper needs (so tests can pass a fake). */
export interface ShareStateClient {
  call<T>(op: WebCryptoOp, ...args: unknown[]): Promise<T>;
}

/** Runs one named decision in the Worker; a `{error}` answer is rethrown as the original Error text. */
export async function shareStateCall<T>(client: ShareStateClient, name: string, input: unknown): Promise<T> {
  const json = await client.call<string>('shareState', name, JSON.stringify(input));
  const output = JSON.parse(json) as unknown;
  if (output && typeof output === 'object' && typeof (output as { error?: unknown }).error === 'string') {
    throw new Error((output as { error: string }).error);
  }
  return output as T;
}
