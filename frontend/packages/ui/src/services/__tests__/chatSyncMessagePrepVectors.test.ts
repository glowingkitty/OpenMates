// Synced-message storage preparation: pins the real flag-off TypeScript loops
// (chatSyncMessagePrep.ts) to web_sync/message_prep_vectors.json, which the
// shared Rust plan (web_sync/message_prep.rs) replays in cargo, and proves the
// flag-on page adapter (rustCore/sync/messagePrepOps.ts) applying those plans
// yields records strictly equal to the TypeScript ones, processing fences included.
// On drift the test prints the regenerated vectors after MESSAGE_PREP_VECTORS_JSON=.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({ requests: [] as { mode: string; messages: unknown[] }[] }));

type Entry = Record<string, unknown> | null;
const ID_KEYS = { phased: ["message_id", "id"], batch: ["message_id", "client_message_id", "id"] } as const;

/** Reference of the committed plan shape; the vectors bind it to Rust (cargo) and to the real loops (below). */
function referencePlan(mode: "phased" | "batch", entries: Entry[]) {
  return entries.map((entry) => {
    if (entry === null) return { skip: "parse" };
    const idKey = ID_KEYS[mode].find((key) => entry[key]);
    if (!idKey) return { skip: "id" };
    const status = entry.queue_dispatch_status;
    const mode2 = entry.queue_dispatch_mode;
    const queue = status === "paused" ? "paused" : status === "processing" ? "processing"
      : status === "queued" && (mode2 === "follow_up" || mode2 === "steer") ? "queued" : "none";
    return { skip: null, idKey, chatOwn: !!entry.chat_id, roleOwn: !!entry.role, statusOwn: !!entry.status, queue };
  });
}

vi.mock("../rustCore/sync/syncUnitClient", () => ({
  syncCall: async (op: string, request: { mode: "phased" | "batch"; messages: Entry[] }) => {
    if (op !== "messagePrep") throw new Error("protocol");
    const copy = JSON.parse(JSON.stringify(request));
    calls.requests.push(copy);
    return { plans: referencePlan(copy.mode, copy.messages) };
  },
}));

import * as ts from "../chatSyncMessagePrep";
import * as rust from "../rustCore/sync/messagePrepOps";
import { clearQueuedProcessing, hasQueuedProcessing, recordQueuedProcessing } from "../queuedMessageLifecycle";
import type { Message } from "../../types/chat";

const VECTORS = resolve(__dirname, "../../../../../../packages/openmates-rust/src/web_sync/message_prep_vectors.json");

type Fn = "phased" | "background" | "phase1b" | "batch";
interface Case { name: string; fn: Fn; rows: unknown[]; fences: [string, string][] }

const CHAT = "chat-1";
const enc = { encrypted_content: "ct", created_at: 10, role: "assistant" };
const ROWS: unknown[] = [
  { message_id: "m1", ...enc },
  { id: "m2", ...enc, status: "sending" },
  { message_id: "", id: "m3", ...enc },
  { message_id: 0, id: "m4", ...enc, chat_id: "chat-other" },
  { message_id: 7, ...enc },
  { encrypted_content: "ct" },
  { client_message_id: "c5", ...enc },
  { message_id: "m6", client_message_id: "c6", ...enc, role: "" },
  JSON.stringify({ message_id: "m7", ...enc }),
  JSON.stringify({ id: "m8", ...enc, chat_id: "chat-2" }),
  "{not json",
  JSON.stringify("text"),
  JSON.stringify(5),
  5,
  { message_id: "m9", ...enc, queue_dispatch_status: "paused", queue_dispatch_mode: "steer", queue_mode: "steer", status: "queued" },
  { message_id: "m10", ...enc, queue_dispatch_status: "processing", queue_mode: "follow_up" },
  { message_id: "m11", ...enc, status: "queued" },
  { message_id: "m12", ...enc, queue_dispatch_status: "queued", queue_dispatch_mode: "follow_up", status: "sending" },
  { message_id: "m13", ...enc, queue_dispatch_status: "queued", queue_dispatch_mode: "steer" },
  { message_id: "m14", ...enc, queue_dispatch_status: "queued", queue_dispatch_mode: "other", status: "failed" },
  { message_id: "m15", ...enc, queue_dispatch_status: "queued" },
  { message_id: "m16", ...enc, queue_dispatch_status: "unknown", queue_dispatch_task_id: "t", queue_revision: 2 },
  { message_id: "m17", ...enc, chat_id: "chat-2", queue_dispatch_status: "queued", queue_dispatch_mode: "follow_up" },
  { message_id: "m18", ...enc, chat_id: "chat-2", queue_dispatch_status: "paused" },
  { message_id: "m19", role: "user", encrypted_pii_mappings: "pii", has_thinking: true, thinking_token_count: 3,
    encrypted_thinking_content: "tc", encrypted_thinking_signature: "ts", encrypted_sender_name: "sn",
    encrypted_category: "cat", encrypted_model_name: "mn", hashed_user_id: "h", user_message_id: "u", created_at: 1 },
];
// Fences on the handler chat and on a row's own chat: the loops differ in which chat they key by.
const FENCES: [string, string][] = [[CHAT, "m9"], [CHAT, "m11"], [CHAT, "m12"], ["chat-2", "m17"], ["chat-2", "m18"], [CHAT, "c5"], [CHAT, "7"]];
const NULL_ROWS: unknown[] = [{ message_id: "m9", ...enc, queue_dispatch_status: "paused" }, { id: "m2", ...enc }, null, { message_id: "m1" }];
const NULL_JSON_ROWS: unknown[] = [{ message_id: "m9", ...enc, queue_dispatch_status: "paused" }, "null", { id: "m3" }];

const CASES: Case[] = (["phased", "background", "phase1b", "batch"] as Fn[]).flatMap((fn) => [
  { name: `${fn}-rows`, fn, rows: ROWS, fences: FENCES },
  { name: `${fn}-rows-unfenced`, fn, rows: ROWS, fences: [] },
  { name: `${fn}-empty`, fn, rows: [], fences: [] },
  { name: `${fn}-null-row-throws`, fn, rows: NULL_ROWS, fences: FENCES },
  { name: `${fn}-null-json`, fn, rows: NULL_JSON_ROWS, fences: FENCES },
]);

const clone = <T>(value: T): T => (value === undefined ? value : structuredClone(value));

function runTs(c: Case, rows: unknown[]): Message[] {
  if (c.fn === "phased") return ts.prepareMessagesForStorage(rows as Message[], CHAT, "Phase 2");
  if (c.fn === "background") return ts.prepareBackgroundMessages(rows as Message[], CHAT);
  if (c.fn === "phase1b") return ts.preparePhase1bMessages(rows as Message[], CHAT);
  return ts.prepareBatchMessagesForStorage(rows, CHAT);
}

function runRust(c: Case, rows: unknown[]): Promise<Message[]> {
  if (c.fn === "phased") return rust.prepareMessagesForStorage(rows as Message[], CHAT, "Phase 2");
  if (c.fn === "background") return rust.prepareBackgroundMessages(rows as Message[], CHAT);
  if (c.fn === "phase1b") return rust.preparePhase1bMessages(rows as Message[], CHAT);
  return rust.prepareBatchMessagesForStorage(rows, CHAT);
}

const fenceKeys = () => [...new Set(FENCES.concat(ROWS.flatMap((row) => {
  const r = row as Record<string, unknown> | null;
  return r && typeof r === "object" ? [[CHAT, String(r.message_id ?? r.id)], ["chat-2", String(r.message_id ?? r.id)]] as [string, string][] : [];
})).map((f) => f.join("\0")))].map((k) => k.split("\0") as [string, string]);
const fenceState = () => fenceKeys().filter(([chat, id]) => hasQueuedProcessing(chat, id));

describe("synced-message storage preparation vectors", () => {
  // contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy,chats.persistence.client-encrypted
  it("applies the Rust plans exactly like the TypeScript loops and matches the committed vectors", async () => {
    vi.spyOn(console, "debug").mockImplementation(() => undefined);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const generated: Record<string, unknown>[] = [];
    for (const c of CASES) {
      const mode = c.fn === "batch" ? "batch" : "phased";
      // Flag-off TypeScript arm.
      clearQueuedProcessing();
      for (const [chat, id] of c.fences) recordQueuedProcessing(chat, id);
      const tsRows = clone(c.rows);
      let tsOut: Message[] | null = null;
      let tsError: string | null = null;
      try {
        tsOut = runTs(c, tsRows);
      } catch (error) {
        tsError = (error as Error).message;
      }
      const tsFences = fenceState();

      // Flag-on adapter arm over the Rust plan.
      clearQueuedProcessing();
      for (const [chat, id] of c.fences) recordQueuedProcessing(chat, id);
      calls.requests.length = 0;
      const rustRows = clone(c.rows);
      let rustOut: Message[] | null = null;
      let rustError: string | null = null;
      try {
        rustOut = await runRust(c, rustRows);
      } catch (error) {
        rustError = (error as Error).message;
      }
      expect(rustError, c.name).toBe(tsError);
      expect(rustOut, c.name).toStrictEqual(tsOut);
      if (tsOut && rustOut) tsOut.forEach((m, i) => expect(Object.keys(rustOut![i]), c.name).toEqual(Object.keys(m)));
      expect(rustRows, `${c.name}: input rows mutated identically`).toStrictEqual(tsRows);
      expect(fenceState(), `${c.name}: processing fences`).toEqual(tsFences);
      expect(calls.requests.length, c.name).toBeLessThanOrEqual(1);
      const request = calls.requests[0] ?? null;
      if (request) {
        expect(request.mode).toBe(mode);
        // Ciphertext never crosses into the Worker request.
        expect(JSON.stringify(request)).not.toContain("\"ct\"");
      }
      // One vector per distinct Worker request (the three phased loops send identical requests).
      if (request && !generated.some((g) => JSON.stringify(g.request) === JSON.stringify(request))) {
        generated.push({ name: c.name, request, plans: referencePlan(mode, request.messages as Entry[]) });
      }
    }
    const regenerated = { note: "Generated by chatSyncMessagePrepVectors.test.ts from the flag-off TypeScript loops.", cases: generated };
    const committed = JSON.parse(readFileSync(VECTORS, "utf8"));
    if (JSON.stringify(committed) !== JSON.stringify(regenerated)) {
      console.log(`MESSAGE_PREP_VECTORS_JSON=${JSON.stringify(regenerated)}`);
    }
    expect(committed).toEqual(regenerated);
  });
});
