// frontend/packages/ui/src/services/shareState/decide.ts
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
// Entry point for share / guest / incognito decisions. With VITE_OPENMATES_RUST_CORE=1
// every decision is answered by the shared Rust core in the Worker `crypto` unit
// (web_share_state) and there is no TypeScript fallback; flag-off builds run the
// original TypeScript rules from policy.ts. The compile-time flag check lets the
// bundler drop the Rust branch from default builds.
import { rustWebCrypto } from "../rustCore/crypto/webCryptoClient";
import { shareStateCall, type ShareStateClient } from "../rustCore/crypto/shareStateOps";
import { SHARE_STATE_POLICY, type ShareStateOpName } from "./policy";

type Rule<K extends ShareStateOpName> = (typeof SHARE_STATE_POLICY)[K];
export type ShareStateInput<K extends ShareStateOpName> = Parameters<Rule<K>>[0];
export type ShareStateOutput<K extends ShareStateOpName> = ReturnType<Rule<K>>;

/** The Worker client when the Rust core is enabled, else null. */
export function shareStateClient(): ShareStateClient | null {
  return import.meta.env.VITE_OPENMATES_RUST_CORE === "1" ? rustWebCrypto() : null;
}

/** Answers one decision: Rust in the Worker with the flag on, the TypeScript rule otherwise. */
export async function decideShareState<K extends ShareStateOpName>(
  op: K, input: ShareStateInput<K>,
): Promise<ShareStateOutput<K>> {
  const rust = shareStateClient();
  if (rust) return shareStateCall<ShareStateOutput<K>>(rust, op, input);
  return (SHARE_STATE_POLICY[op] as (value: ShareStateInput<K>) => ShareStateOutput<K>)(input);
}

/** The TypeScript rule run synchronously; only for call sites that keep the flag-off path synchronous. */
export function directShareState<K extends ShareStateOpName>(op: K, input: ShareStateInput<K>): ShareStateOutput<K> {
  return (SHARE_STATE_POLICY[op] as (value: ShareStateInput<K>) => ShareStateOutput<K>)(input);
}
