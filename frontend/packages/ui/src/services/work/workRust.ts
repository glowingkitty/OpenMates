// frontend/packages/ui/src/services/work/workRust.ts
// Flag-on page adapter of the shared Rust core `work` op (parked wave-5 `work`
// lane, slice 1: user Plans). Rust (packages/openmates-rust/src/web_work) owns
// the view projections, flow validation, request paths and request bodies of
// userPlanService.ts; this adapter keeps only page IO: it decrypts the record's
// ciphertext members and performs the ordered body steps with the page's own
// plan/task keys and slot builders (key wrappers), so no key bytes cross.
// Only reached from `RUST_WORK` branches (VITE_OPENMATES_RUST_CORE === "1");
// flag-off builds keep the original synchronous TypeScript paths.
// spec: specifications/features/plans#plans.content.client-encrypted

import { decryptWithEmbedKey, encryptWithEmbedKey } from "../cryptoService";
import { rustWebCrypto } from "../rustCore/crypto/webCryptoClient";
import { workCall, type WorkClient } from "../rustCore/crypto/workOps";

/** One ordered body step answered by a `*Body` op. */
export type WorkBodyStep =
  | { value: unknown }
  | { encrypt: string; key: string; aad?: string }
  | { encrypt_input: string; key: string }
  | { slot: string };

/** A request document answered by a `*Body` op (plus op-specific facts such as wrapper targets). */
export interface WorkRequest {
  path: string;
  method: string;
  steps: Array<[string, WorkBodyStep]>;
  create_task?: boolean;
  wrapper_chat_id?: string | null;
  wrapper_project_ids?: string[];
}

/** The Worker client when the Rust core is registered (benchmarks' TS baseline answers null). */
export function workClient(): WorkClient | null {
  return rustWebCrypto();
}

/** Runs one named work decision in the Worker. */
export function workDecide<T>(client: WorkClient, op: string, input: unknown): Promise<T> {
  return workCall<T>(client, op, input);
}

/**
 * The plaintext of every non-empty string `encrypted_*` member (wrapped keys
 * excluded), with the services' `decryptOptional` rule: a failed decrypt is "".
 */
export async function decryptWorkFields(record: object, key: Uint8Array): Promise<Record<string, string>> {
  const names = Object.entries(record)
    .filter(([name, value]) => name.startsWith("encrypted_") && !name.endsWith("_key") && typeof value === "string" && value)
    .map(([name]) => name);
  const plaintexts = await Promise.all(names.map(async (name) =>
    (await decryptWithEmbedKey((record as Record<string, string>)[name], key)) ?? ""));
  return Object.fromEntries(names.map((name, index) => [name, plaintexts[index]]));
}

/** A `*View` op over one record; the page's own record object is reattached as `encrypted`. */
export async function workView<R extends object, V>(client: WorkClient, op: string, record: R, key: Uint8Array): Promise<V> {
  const fields = await decryptWorkFields(record, key);
  const view = await workDecide<Record<string, unknown>>(client, op, { record, fields });
  return { ...view, encrypted: record } as V;
}

/**
 * Performs the body steps in order (the TS originals' encryption call order).
 * `source` is the page input `encrypt_input` steps stringify; `slots` build the
 * values only the page can make. A missing key or slot builder is a bug and throws.
 */
export async function buildWorkBody(
  steps: WorkRequest["steps"],
  source: object,
  keys: Record<string, Uint8Array | null | undefined>,
  slots: Record<string, () => unknown> = {},
): Promise<Record<string, unknown>> {
  const body: Record<string, unknown> = {};
  const sealWith = (role: string): Uint8Array => {
    const key = keys[role];
    if (!key) throw new Error(`rust_work: no ${role} key for body step`);
    return key;
  };
  for (const [name, step] of steps) {
    if ("value" in step) body[name] = step.value;
    else if ("encrypt" in step) body[name] = await encryptWithEmbedKey(step.encrypt, sealWith(step.key), step.aad);
    else if ("encrypt_input" in step) {
      const member = (source as Record<string, unknown>)[step.encrypt_input];
      body[name] = await encryptWithEmbedKey(JSON.stringify(member ?? []), sealWith(step.key));
    } else {
      const build = slots[step.slot];
      if (!build) throw new Error(`rust_work: no builder for slot ${step.slot}`);
      body[name] = await build();
    }
  }
  return body;
}
