/**
 * embedSenderPolicy.ts — pure decisions of the canonical embed sender
 * (embedSenders.ts): the availability request, the availability verdict, the
 * canonical-head identity and history-page checks, wrapper-row classification,
 * the missing-wrapper plan, receipt checks and failure classification.
 *
 * Flag off (default) embedSenders.ts calls these synchronously at the exact
 * places the logic used to be inline, so behaviour and await windows are
 * unchanged. With VITE_OPENMATES_RUST_CORE=1 the same JSON documents are
 * decided by the shared Rust core (`embed_read::sender`, op `decideSender` on
 * the embedData unit). Page IO (IndexedDB, fetch, WebSocket), SHA-256, key
 * lookups and every unwrap/decrypt stay in embedSenders.ts: no key bytes or
 * plaintext cross. Parity: embed_sender_ts_vectors.json, regenerated from these
 * functions by rustCore/__tests__/embedSenderVectors.test.ts.
 * spec: specifications/architecture/storage-lifecycle#storage.client.shared-policy-existing-adapters
 */

/** Durable precondition of one canonical write. */
export interface CanonicalPrecondition {
  version: number | null;
  ciphertext_sha256: string | null;
}

/** Validated canonical revision of the availability reply. */
export interface SenderCanonicalRevision {
  version: number;
  ciphertext_sha256: string;
  write_state: "mutable" | "immutable";
}

export interface AvailabilityRequestInput {
  chat_id: string;
  team_id: string | null;
  embed_id: string;
  parent_embed_id: string | null;
  version: number;
}

export interface AvailabilityRequest {
  path: string;
  body: { embed_ids: string[]; required_recovery_versions: Record<string, number> };
}

export interface AvailabilityPlanInput {
  embed_id: string;
  parent_embed_id: string | null;
  requested_version: number;
  read_only: boolean;
  reply: unknown;
  /**
   * Origin of the queued operation. Only the Rust decision reads it:
   * `"child-revision"` (version N+1 of a generated-image child) answers
   * `read_advance`. Child revisions run only in VITE_OPENMATES_RUST_CORE builds.
   */
  origin?: string | null;
}

/**
 * What persistCanonicalEmbedOperation does with the availability reply:
 * throw (`unknown_identity` plain error, `recovery_pending`, `conflict`), write
 * with `precondition`, or prove equivalence by reading the canonical head.
 */
export type AvailabilityPlan =
  | { outcome: "unknown_identity" | "recovery_pending" }
  | { outcome: "conflict"; code: string }
  | { outcome: "write"; precondition: CanonicalPrecondition; allow_wrapper_writes: boolean }
  | { outcome: "read_current"; allow_wrapper_writes: boolean }
  /** Rust only: read the canonical child head and let the identity verdict grant the N -> N+1 write. */
  | { outcome: "read_advance"; allow_wrapper_writes: boolean }
  | {
    outcome: "read_current_revision" | "read_historical";
    precondition: CanonicalPrecondition;
    allow_wrapper_writes: boolean;
  };

/** Queued head fields the canonical identity check compares (absent = undefined). */
export interface SenderHeadFacts {
  embed_id: string;
  hashed_chat_id?: string | null;
  hashed_user_id?: string | null;
  hashed_message_id?: string | null;
  parent_embed_id?: string | null;
  version_number?: number | null;
  status?: unknown;
  app_id?: unknown;
  skill_id?: unknown;
  hashed_task_id?: unknown;
  is_private?: unknown;
  is_shared?: unknown;
}

export interface CanonicalIdentityInput {
  head: SenderHeadFacts;
  /** The parsed canonical embed page (may be anything the server answered). */
  page: unknown;
  historical: boolean;
  revision: SenderCanonicalRevision | null;
  /** SHA-256 of `page.embed.encrypted_content`, present exactly when the revision check reads it. */
  content_sha256: string | null;
  /** `JSON.stringify(head.embed_ids ?? [])` when the head carries `embed_ids`, else null. */
  head_embed_ids_json: string | null;
  /** `JSON.stringify(page.embed.embed_ids ?? [])` when `page.embed` is an object, else null. */
  embed_ids_json: string | null;
  /**
   * Rust only, after a `read_advance` plan: a canonical head one version below
   * the queued head answers `advance` (`content_sha256` must then be present).
   */
  advance?: boolean;
}

export type CanonicalIdentityVerdict =
  | { outcome: "ok" | "recovery_pending" | "wrappers_incomplete" }
  | { outcome: "conflict"; code: string }
  /** Rust only: the canonical head is this child at N; write N+1 under `precondition`. */
  | { outcome: "advance"; precondition: CanonicalPrecondition };

export interface HistoryPageInput {
  embed_id: string;
  version: number;
  page: unknown;
}

export type HistoryPageVerdict = { outcome: "ok" } | { outcome: "conflict"; code: string };

/** How one key wrapper row is handled: ignored, refused, or unwrapped with the master/chat key. */
export type WrapperRowAction = "skip" | "conflict" | "master" | "chat";

export interface WrapperRowInput {
  hashed_subject: string;
  hashed_user_id: unknown;
  hashed_chat_id: unknown;
}

export interface MissingKeysInput {
  key_types: unknown[];
  /** Wrapper types proven by the canonical head; null when no canonical head was read. */
  verified_key_types: string[] | null;
  allow_wrapper_writes: boolean;
  requested_version: number;
  canonical_version: number | null;
}

export interface MissingKeysPlan {
  /** Indices (into the queued wrappers) still missing on the server. */
  missing: number[];
  outcome: "none" | "send" | "recovery_pending";
}

export type ReceiptInput =
  | { kind: "head"; receipt: Record<string, unknown>; embed_id: string; expected_digest: string }
  | { kind: "keys"; receipt: Record<string, unknown>; count: number }
  | { kind: "diff"; receipt: Record<string, unknown>; embed_id: string; version_number: number; expected_digest: string };

/** A sender failure as embedSenders.ts classified the thrown error. */
export interface FailureInput {
  kind: "rejected" | "conflict" | "other";
  code: string | null;
  reason: string | null;
}

export interface FailureVerdict {
  /** A rejected head write another consumer already settled: reconcile read-only. */
  reconcile: boolean;
  settle: { outcome: "waiting" } | { outcome: "denied" | "conflict"; failure_code: string };
}

/** Write rejections whose winner may already hold an equivalent canonical head. */
export const RECONCILABLE_WRITE_REJECTIONS: ReadonlySet<string> = new Set([
  "canonical_precondition_mismatch", "acknowledged_embed_revision_immutable",
]);

const WRAPPER_SCOPE_FIELDS = ["hashed_project_id", "hashed_plan_id", "hashed_team_id", "team_key_epoch"];

/** Path and body of the references availability request. */
export function availabilityRequest(input: AvailabilityRequestInput): AvailabilityRequest {
  const query = input.team_id ? `?team_id=${encodeURIComponent(input.team_id)}` : "";
  return {
    path: `/v1/embeds/chats/${encodeURIComponent(input.chat_id)}/references/availability${query}`,
    body: {
      embed_ids: input.parent_embed_id ? [input.embed_id, input.parent_embed_id] : [input.embed_id],
      required_recovery_versions: { [input.embed_id]: input.version },
    },
  };
}

/**
 * The availability verdict. Missing/invalid proof is UNKNOWN: a missing
 * recovery ACK never grants permission. Throws a TypeError exactly where the
 * original inline code did (a null reply or result entry).
 */
export function availabilityPlan(input: AvailabilityPlanInput): AvailabilityPlan {
  const result = input.reply as {
    results?: Array<{ embed_id?: string; state?: string; canonical_revision?: SenderCanonicalRevision }>;
  };
  if (!Array.isArray(result.results) || result.results.length !== (input.parent_embed_id ? 2 : 1)
    || result.results[0].embed_id !== input.embed_id
    || (input.parent_embed_id && result.results[1].embed_id !== input.parent_embed_id)) {
    return { outcome: "unknown_identity" };
  }
  if (input.parent_embed_id && result.results[1].state !== "ready") return { outcome: "recovery_pending" };
  const head = result.results[0];
  const revision = head.canonical_revision;
  const requested = input.requested_version;
  if (head.state === "missing") {
    if (input.read_only || requested > 1) return { outcome: "recovery_pending" };
    return {
      outcome: "write", precondition: { version: null, ciphertext_sha256: null },
      allow_wrapper_writes: !input.read_only,
    };
  }
  if (!revision || !Number.isSafeInteger(revision.version) || revision.version < 1
    || typeof revision.ciphertext_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(revision.ciphertext_sha256)
    || (revision.write_state !== "mutable" && revision.write_state !== "immutable")) {
    if (head.state !== "ready") return { outcome: "recovery_pending" };
    // Read-only equivalence can prove durable canonical bytes even when
    // availability cannot grant a write capability (notably child embeds).
    return { outcome: "read_current", allow_wrapper_writes: false };
  }
  if (revision.version === requested - 1) return { outcome: "recovery_pending" };
  const precondition = { version: revision.version, ciphertext_sha256: revision.ciphertext_sha256 };
  const allow_wrapper_writes = !input.read_only;
  if (revision.version > requested) return { outcome: "read_historical", precondition, allow_wrapper_writes };
  if (revision.version !== requested) return { outcome: "conflict", code: "embed_version_conflict" };
  if (input.read_only || revision.write_state === "immutable") {
    return { outcome: "read_current_revision", precondition, allow_wrapper_writes };
  }
  return { outcome: "write", precondition, allow_wrapper_writes };
}

/** True when the identity revision check needs `content_sha256` (the page computes it only then). */
export function identityNeedsContentDigest(
  page: unknown, revision: SenderCanonicalRevision | null,
): boolean {
  const embed = (page as { embed?: Record<string, unknown> } | null | undefined)?.embed;
  return !!revision && !!embed && (embed.version_number ?? 1) === revision.version
    && typeof embed.encrypted_content === "string";
}

/** Proves a canonical embed page is the queued head's identity/version (no key or content). */
export function canonicalIdentity(input: CanonicalIdentityInput): CanonicalIdentityVerdict {
  const { head, historical, revision } = input;
  const page = input.page as {
    embed?: Record<string, unknown>; embed_keys?: unknown;
    embed_keys_has_more_after?: unknown; oversized_embed_key_id?: unknown;
  };
  const embed = page.embed;
  const canonicalVersion = embed?.version_number ?? 1;
  if (typeof canonicalVersion !== "number" || !Number.isSafeInteger(canonicalVersion) || canonicalVersion < 1) {
    return { outcome: "conflict", code: "embed_version_conflict" };
  }
  if (revision && embed && (canonicalVersion !== revision.version
    || typeof embed.encrypted_content !== "string"
    || input.content_sha256 !== revision.ciphertext_sha256)) {
    return { outcome: "recovery_pending" };
  }
  const same = (value: unknown, expected: unknown) => value === expected;
  if (!embed || !same(embed.embed_id, head.embed_id)
    || !same(embed.hashed_chat_id, head.hashed_chat_id)
    || !same(embed.hashed_user_id, head.hashed_user_id)
    || !same(embed.hashed_message_id, head.hashed_message_id)
    || !same(embed.parent_embed_id ?? null, head.parent_embed_id ?? null)
    || (historical
      ? canonicalVersion <= (head.version_number ?? 1)
      : !same(canonicalVersion, head.version_number ?? 1))
    || (!historical && !same(embed.status, head.status))
    || (head.app_id !== undefined && !same(embed.app_id, head.app_id))
    // Child TOON carries its parent's skill_id, so a replayed child can be
    // queued with the parent's catalog projection while the canonical row holds
    // the child's own skill (issue BMKRJ). Content/type/keys/parent are still
    // proven equal later; the canonical catalog identity is adopted.
    || (head.skill_id !== undefined && !head.parent_embed_id && !same(embed.skill_id, head.skill_id))
    // Older recovered heads omitted optional task indexing. Missing metadata is
    // compatible only after all scope/key/content checks; a different
    // non-null task identity still conflicts.
    || (!historical && head.hashed_task_id !== undefined && embed.hashed_task_id != null
      && !same(embed.hashed_task_id, head.hashed_task_id))
    || (!historical && input.head_embed_ids_json !== null && input.embed_ids_json !== input.head_embed_ids_json)
    || (!historical && head.is_private !== undefined && !same(embed.is_private, head.is_private))
    || (!historical && head.is_shared !== undefined && !same(embed.is_shared, head.is_shared))
    || typeof embed.encrypted_content !== "string" || typeof embed.encrypted_type !== "string") {
    return { outcome: "conflict", code: "embed_identity_or_version_conflict" };
  }
  if (page.embed_keys_has_more_after || page.oversized_embed_key_id
    || !Array.isArray(page.embed_keys) || page.embed_keys.length > 128) {
    return { outcome: "wrappers_incomplete" };
  }
  return { outcome: "ok" };
}

/** The bounded version-history page must end at the queued version. */
export function historyPage(input: HistoryPageInput): HistoryPageVerdict {
  const page = input.page as { embed_id?: string; version_number?: number; rows?: Array<{ version_number?: unknown }> };
  if (page.embed_id !== input.embed_id || page.version_number !== input.version
    || !Array.isArray(page.rows)
    || page.rows[page.rows.length - 1]?.version_number !== input.version) {
    return { outcome: "conflict", code: "embed_version_conflict" };
  }
  return { outcome: "ok" };
}

/**
 * A canonical page wrapper row. Other authorized key scopes are not evidence
 * that this owner's queued master/chat wrapper already exists: those are
 * skipped, every reusable row is validated. Throws a TypeError for a null row.
 */
export function canonicalWrapperRow(row: unknown, input: WrapperRowInput): WrapperRowAction {
  const wrapper = row as Record<string, unknown>;
  if (wrapper.hashed_embed_id !== input.hashed_subject
    || wrapper.hashed_user_id !== input.hashed_user_id
    || (wrapper.key_type !== "master" && wrapper.key_type !== "chat")) return "skip";
  if (typeof wrapper.encrypted_embed_key !== "string"
    || (wrapper.key_type === "master" ? wrapper.hashed_chat_id != null
      : wrapper.hashed_chat_id !== input.hashed_chat_id)
    || WRAPPER_SCOPE_FIELDS.some((field) => wrapper[field] != null)) {
    return "conflict";
  }
  return wrapper.key_type as "master" | "chat";
}

/** A queued wrapper must not rotate an already canonical head to a different key. */
export function queuedWrapperRow(row: unknown, input: WrapperRowInput): Exclude<WrapperRowAction, "skip"> {
  const wrapper = row as Record<string, unknown>;
  if (wrapper.hashed_embed_id !== input.hashed_subject
    || wrapper.hashed_user_id !== input.hashed_user_id
    || typeof wrapper.encrypted_embed_key !== "string") {
    return "conflict";
  }
  if (wrapper.key_type === "master" && wrapper.hashed_chat_id == null) return "master";
  if (wrapper.key_type === "chat" && wrapper.hashed_chat_id === input.hashed_chat_id) return "chat";
  return "conflict";
}

/** Queued wrappers still missing on the server and whether they may be sent now. */
export function missingKeys(input: MissingKeysInput): MissingKeysPlan {
  const existing = input.verified_key_types ? new Set(input.verified_key_types) : null;
  const missing = input.key_types.flatMap((keyType, index) =>
    (!existing || typeof keyType !== "string" || !existing.has(keyType) ? [index] : []));
  if (missing.length > 0 && !input.allow_wrapper_writes) return { missing, outcome: "recovery_pending" };
  const canonical = existing !== null;
  if (missing.length > 0 && !(canonical && (input.requested_version > 1
    || Number(input.canonical_version ?? 1) > input.requested_version))) {
    return { missing, outcome: "send" };
  }
  return { missing, outcome: "none" };
}

/** True when a write receipt confirms exactly what was submitted. */
export function receiptMatches(input: ReceiptInput): boolean {
  const receipt = input.receipt;
  switch (input.kind) {
    case "head":
      return receipt.embed_id === input.embed_id && receipt.canonical_digest === input.expected_digest;
    case "keys":
      return receipt.failed_count === 0 && receipt.created_count === input.count;
    case "diff":
      return receipt.embed_id === input.embed_id && receipt.version_number === input.version_number
        && receipt.canonical_digest === input.expected_digest && receipt.canonical_source === "version_row";
  }
}

/** Reconcile/settle classification of a sender failure. */
export function classifyFailure(input: FailureInput): FailureVerdict {
  const rejected = input.kind === "rejected";
  const reconcile = rejected && input.code === "embed_revision_conflict"
    && RECONCILABLE_WRITE_REJECTIONS.has(input.reason ?? "");
  const denied = rejected && input.code === "embed_write_denied";
  const conflict = input.kind === "conflict" || (rejected && input.code === "embed_revision_conflict");
  if (!denied && !conflict) return { reconcile, settle: { outcome: "waiting" } };
  const failure_code = (rejected ? input.reason ?? input.code : input.code) as string;
  return { reconcile, settle: { outcome: denied ? "denied" : "conflict", failure_code } };
}

/** Op name → input/output document of every sender decision (the Rust `decideSender` ops). */
export interface EmbedSenderDecisions {
  senderAvailabilityRequest: { input: AvailabilityRequestInput; output: AvailabilityRequest };
  senderAvailabilityPlan: { input: AvailabilityPlanInput; output: AvailabilityPlan | { outcome: "malformed" } };
  senderCanonicalIdentity: { input: CanonicalIdentityInput; output: CanonicalIdentityVerdict | { outcome: "malformed" } };
  senderHistoryPage: { input: HistoryPageInput; output: HistoryPageVerdict | { outcome: "malformed" } };
  senderWrapperRows: {
    input: WrapperRowInput & { mode: "canonical" | "queued"; rows: unknown[] };
    output: Array<WrapperRowAction | "malformed">;
  };
  senderMissingKeys: { input: MissingKeysInput; output: MissingKeysPlan };
  senderReceipt: { input: ReceiptInput; output: boolean };
  senderFailure: { input: FailureInput; output: FailureVerdict };
}
export type EmbedSenderOp = keyof EmbedSenderDecisions;

/** The TypeError the inline code raised on a null document, as a `malformed` verdict. */
function orMalformed<T>(decide: () => T): T | { outcome: "malformed" } {
  try {
    return decide();
  } catch (error) {
    if (error instanceof TypeError) return { outcome: "malformed" };
    throw error;
  }
}

/** One decision by op name: the document the Rust op answers for the same input. */
export function decideEmbedSender<O extends EmbedSenderOp>(
  op: O, input: EmbedSenderDecisions[O]["input"],
): EmbedSenderDecisions[O]["output"] {
  type Out = EmbedSenderDecisions[O]["output"];
  switch (op) {
    case "senderAvailabilityRequest": return availabilityRequest(input as AvailabilityRequestInput) as Out;
    case "senderAvailabilityPlan": return orMalformed(() => availabilityPlan(input as AvailabilityPlanInput)) as Out;
    case "senderCanonicalIdentity": return orMalformed(() => canonicalIdentity(input as CanonicalIdentityInput)) as Out;
    case "senderHistoryPage": return orMalformed(() => historyPage(input as HistoryPageInput)) as Out;
    case "senderWrapperRows": {
      const rows = input as EmbedSenderDecisions["senderWrapperRows"]["input"];
      const classify = rows.mode === "canonical" ? canonicalWrapperRow : queuedWrapperRow;
      return rows.rows.map((row) => {
        const action = orMalformed(() => classify(row, rows));
        return typeof action === "string" ? action : "malformed";
      }) as Out;
    }
    case "senderMissingKeys": return missingKeys(input as MissingKeysInput) as Out;
    case "senderReceipt": return receiptMatches(input as ReceiptInput) as Out;
    case "senderFailure": return classifyFailure(input as FailureInput) as Out;
  }
  throw new Error(`unknown embed sender op ${String(op)}`);
}
