// Guest promotion op of the shared Worker `crypto` unit (share-guest-crypto lane).
// spec: specifications/features/auth#auth.keys.client-wrapped
//
// Rust (`openmates_sdk::web_guest`, export in browser_guest.rs) owns which
// anonymous messages are promoted after signup, which system rows are deleted,
// which rows need a "synced" re-save and the version/timestamp numbers of the
// promoted chat. Only imported by flag-on code (the Worker installer and the
// promotion adapter), so flag-off builds never reference it. Keys are not
// involved: wrapping the chat key reuses the master-key ops.
import type { WebCryptoOp } from './webCryptoClient';

export type GuestOp = 'guestPromotionPlan';

/** Worker export behind each op; spread into the crypto unit's async export table. */
export const GUEST_ASYNC_EXPORTS: Record<GuestOp, string> = {
  guestPromotionPlan: 'guestPromotionPlan',
};

export interface GuestPlanMessage {
  role?: string | null;
  status?: string | null;
  content?: unknown;
  created_at?: number | null;
}

export interface GuestPromotionPlan {
  promotable: number[];
  delete: number[];
  resave: number[];
  messages_v: number;
  created_at: number | null;
  last_edited: number | null;
}

/** The slice of WebCryptoClient this helper needs (so tests can pass a fake). */
export interface GuestOpsClient {
  call<T>(op: WebCryptoOp, ...args: unknown[]): Promise<T>;
}

/** Promotion plan for one anonymous chat, computed in the Worker. */
export async function guestPromotionPlan(
  client: GuestOpsClient,
  chat: { created_at?: number | null; updated_at?: number | null },
  messages: GuestPlanMessage[],
): Promise<GuestPromotionPlan> {
  const slim = messages.map((m) => ({ role: m.role, status: m.status, content: m.content, created_at: m.created_at }));
  const json = await client.call<string>('guestPromotionPlan', JSON.stringify({
    chat: { created_at: chat.created_at ?? null, updated_at: chat.updated_at ?? null },
    messages: slim,
  }));
  return JSON.parse(json) as GuestPromotionPlan;
}
