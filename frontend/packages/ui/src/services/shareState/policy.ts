// frontend/packages/ui/src/services/shareState/policy.ts
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
// Table of every share-state decision as its TypeScript rule (the flag-off path
// and the reference the Rust ops are proven against). Keys are the Rust op names.
import { ANONYMOUS_OPS, anonymousTitleWire } from "./anonymousChatPolicy";
import { DETAILS_OPS } from "./sharedChatDetailsPolicy";
import { INCOGNITO_OPS } from "./incognitoChatPolicy";
import { QUEUE_OPS } from "./shareMetadataQueuePolicy";
import { SHARED_KEY_OPS } from "./sharedChatKeyPolicy";
import { SHORT_URL_OPS } from "./shortUrlPolicy";

export const SHARE_STATE_POLICY = {
  ...SHORT_URL_OPS, ...SHARED_KEY_OPS, ...QUEUE_OPS, ...DETAILS_OPS, ...INCOGNITO_OPS, ...ANONYMOUS_OPS,
};

/** The rules as the Rust ops answer them (identical except where JSON/Rust strings cannot carry a lone surrogate). */
export const SHARE_STATE_WIRE_POLICY = { ...SHARE_STATE_POLICY, anonymousTitle: anonymousTitleWire };

export type ShareStateOpName = keyof typeof SHARE_STATE_POLICY;

/** Runs a TS rule (wire form) on a JSON-shaped input and answers the JSON document the Rust op answers ({error} for a thrown Error). */
export function runShareStatePolicy(op: ShareStateOpName, input: unknown): unknown {
  try {
    const rule = SHARE_STATE_WIRE_POLICY[op] as (value: unknown) => unknown;
    return JSON.parse(JSON.stringify(rule(input)) ?? "null");
  } catch (error) {
    return { error: (error as Error).message };
  }
}
