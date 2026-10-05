/** Actual applied-context delivery receipts. Plaintext is transient until chat-key encryption. */
import { encryptWithAesGcmCombined } from "./crypto.js";
import type { OpenMatesWsClient } from "./ws.js";

export const DIRECTION_CORRECTION_NOTICE = "Chat is drifting too far away from the goals. Correction instruction was sent.";
export interface AppliedRule { id: string; title: string; source: string; revision: string; body: string; project_id?: string | null; app_id?: string | null }
interface EventBase { event_id: string; created_at: number; chat_id?: string }
export type ChatContextEvent = EventBase & (
  | { type: "rules_loaded"; count: number; set_key: string; rules: AppliedRule[] }
  | { type: "chat_direction_correction"; notice: string; instruction: string; delivery_id: string; provenance?: Record<string, unknown> }
  | { type: "project_authoring_recommendation"; recommendation_id: string; project_id: string; kind: "focus" | "workflow";
      action: "create" | "update"; target_id?: string | null; expected_revision?: string | null; title?: string; team_id?: string | null }
);

function text(value: unknown, limit: number): value is string { return typeof value === "string" && value.length > 0 && value.length <= limit; }
export function parseChatContextEvent(value: unknown, chatId?: string): ChatContextEvent | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const event = value as Record<string, unknown>;
  if (!text(event.event_id, 128) || !Number.isSafeInteger(event.created_at) || Number(event.created_at) < 0
      || (chatId && event.chat_id !== undefined && event.chat_id !== chatId)) return null;
  if (event.type === "rules_loaded") {
    if (!text(event.set_key, 128) || !Array.isArray(event.rules) || !event.rules.length || event.rules.length > 24
        || event.count !== event.rules.length) return null;
    const ids = new Set<string>();
    let bodyChars = 0;
    for (const rule of event.rules) {
      if (!rule || typeof rule !== "object" || !text(rule.id, 128) || ids.has(rule.id)
          || !text(rule.title, 200) || !["app", "personal", "project"].includes(rule.source)
          || !text(rule.revision, 128) || !text(rule.body, 32_000)) return null;
      ids.add(rule.id); bodyChars += rule.body.length;
    }
    if (bodyChars > 32_000) return null;
  } else if (event.type === "chat_direction_correction") {
    if (event.notice !== DIRECTION_CORRECTION_NOTICE || !text(event.instruction, 8_500) || !text(event.delivery_id, 128)) return null;
  } else if (event.type === "project_authoring_recommendation") {
    if (!text(event.recommendation_id, 128) || !text(event.project_id, 128)
        || !["focus", "workflow"].includes(String(event.kind)) || !["create", "update"].includes(String(event.action))
        || (event.action === "update" && (!text(event.target_id, 128) || !text(event.expected_revision, 128)))
        || (event.action === "create" && event.kind !== "focus")) return null;
  } else return null;
  return event as unknown as ChatContextEvent;
}

export function parseChatContextContent(content: string): ChatContextEvent | null {
  try { return parseChatContextEvent(JSON.parse(content)); } catch { return null; }
}

export function chatContextSummary(event: ChatContextEvent): string {
  if (event.type === "rules_loaded") return `Loaded ${event.count} rules`;
  if (event.type === "chat_direction_correction") return DIRECTION_CORRECTION_NOTICE;
  return `${event.action === "create" ? "Create" : "Update"} Project ${event.kind === "focus" ? "Focus" : "Workflow"}${event.title ? `: ${event.title}` : ""}`;
}

export function chatContextDetails(event: ChatContextEvent): string[] {
  if (event.type === "rules_loaded") return event.rules.flatMap(rule => [
    rule.title, `${rule.source}${rule.project_id ? ` · Project ${rule.project_id}` : rule.app_id ? ` · ${rule.app_id}` : ""} · revision ${rule.revision}`, "", ...rule.body.split("\n"), "",
  ]);
  if (event.type === "chat_direction_correction") return [event.notice, "", ...event.instruction.split("\n")];
  return [chatContextSummary(event), "", "Starts one background authoring job when selected.",
    ...(event.target_id ? [`Target: ${event.target_id}`, `Revision: ${event.expected_revision}`] : [])];
}

export function registerChatContextEvents(options: {
  ws: OpenMatesWsClient; chatId: string; chatKey: Uint8Array; existingMessageIds: Iterable<string>; previousRulesSetKey?: string;
  onApplied?: (event: ChatContextEvent) => void | Promise<void>;
}) {
  const seen = new Set(options.existingMessageIds);
  let previousRulesSetKey = options.previousRulesSetKey;
  let pending = Promise.resolve();
  let error: unknown;
  const persist = (event: ChatContextEvent) => {
    if (seen.has(event.event_id)) return;
    seen.add(event.event_id);
    if (event.type === "rules_loaded") {
      if (event.set_key === previousRulesSetKey) return;
      previousRulesSetKey = event.set_key;
    }
    pending = pending.then(async () => {
      await options.ws.sendAsync("chat_system_message_added", { chat_id: options.chatId,
        message: { message_id: event.event_id, role: "system", status: "synced", created_at: event.created_at,
          encrypted_content: await encryptWithAesGcmCombined(JSON.stringify(event), options.chatKey) } });
      await options.onApplied?.(event);
    }).catch(reason => { error = reason; });
  };
  const off = options.ws.onMessageType("chat_context_applied", payload => {
    if (!payload || typeof payload !== "object") return;
    const frame = payload as { chat_id?: string; event?: unknown };
    if (frame.chat_id !== options.chatId) return;
    const event = parseChatContextEvent(frame.event, options.chatId);
    if (!event || seen.has(event.event_id)) return;
    persist(event);
  });
  return { stop: off, persist, async flush() { await pending; if (error) throw error; } };
}
