/** Server-authorized cancellable Project activation; discovery never decrypts private context. */
import type { OpenMatesClient } from "./client.js";
import type { OpenMatesWsClient } from "./ws.js";
import { activateCliProjectFocus } from "./projectFileExecutor.js";

export interface ProjectFocusCountdown {
  chatId: string; projectId: string; focusId: string; requestId: string; expiresAt: number;
  reject: () => Promise<void>;
}

export function registerProjectFocusCountdown(options: {
  client: OpenMatesClient; ws: OpenMatesWsClient; chatId: string; teamId: string | null;
  onPending?: (countdown: ProjectFocusCountdown | null) => void;
  onError?: (error: unknown) => void;
  isCurrent?: () => boolean;
}) {
  let current: { requestId: string; timer: ReturnType<typeof setTimeout> | null; cancelled: boolean; done: Promise<void>; finish: () => void } | null = null;
  let closed = false;
  const assertCurrent = () => {
    if (closed || options.isCurrent?.() === false) throw new Error("Project Focus turn is no longer current");
  };
  const pendingDecisions = new Map<string, () => void>();
  const sendDecision = async (requestId: string, accepted: boolean) => {
    assertCurrent();
    let settle!: (error?: Error) => void;
    const ack = new Promise<void>((resolve, reject) => {
      const cleanups: Array<() => void> = [];
      let settled = false;
      settle = error => {
        if (settled) return;
        settled = true;
        for (const cleanup of cleanups) cleanup();
        if (pendingDecisions.get(requestId) === cancel) pendingDecisions.delete(requestId);
        if (error) reject(error); else resolve();
      };
      const cancel = () => settle(new Error("Project Focus decision interrupted"));
      pendingDecisions.set(requestId, cancel);
      const matches = (value: unknown) => !!value && typeof value === "object"
        && (value as Record<string, unknown>).chat_id === options.chatId
        && (value as Record<string, unknown>).request_id === requestId;
      cleanups.push(options.ws.onMessageType("project_focus_decision_confirmed", value => {
        if (matches(value)) { try { assertCurrent(); settle(); } catch (error) { settle(error as Error); } }
      }));
      cleanups.push(options.ws.onMessageType("project_focus_decision_error", value => {
        if (matches(value)) settle(new Error("Project Focus decision rejected"));
      }));
      const timer = setTimeout(() => settle(new Error("Project Focus decision acknowledgement timed out")), 20_000);
      cleanups.push(() => clearTimeout(timer));
    });
    void ack.catch(() => {});
    try {
      await options.ws.sendAsync("project_focus_decision", { chat_id: options.chatId, request_id: requestId, accepted });
      await ack;
    } catch (error) { settle(error instanceof Error ? error : new Error("Project Focus decision delivery failed")); throw error; }
  };
  const off = options.ws.onMessageType("focus_mode_pending", value => {
    if (!value || typeof value !== "object") return;
    const pending = value as Record<string, unknown>;
    if (closed || options.isCurrent?.() === false || pending.chat_id !== options.chatId || typeof pending.focus_id !== "string"
        || !/^project-[a-f0-9-]{36}$/i.test(pending.focus_id) || typeof pending.embed_id !== "string"
        || !pending.embed_id || pending.embed_id.length > 128 || typeof pending.expires_at !== "number"
        || !Number.isFinite(pending.expires_at) || current?.requestId === pending.embed_id) return;
    const policy = pending.activation_policy ?? "delayed";
    if (policy !== "delayed" && policy !== "immediate" && policy !== "approval") return;
    const remaining = pending.expires_at * 1000 - Date.now();
    if (remaining < -10_000 || remaining > (policy === "delayed" ? 10_000 : 20 * 60_000)) return;
    if (current?.timer) clearTimeout(current.timer);
    if (current) { current.cancelled = true; pendingDecisions.get(current.requestId)?.(); current.finish(); current = null; }
    if (policy === "approval") {
      options.onError?.(new Error("Project Focus requires explicit approval; this client does not support that approval yet"));
      return;
    }
    const requestId = pending.embed_id;
    const focusId = pending.focus_id;
    const projectId = focusId.slice("project-".length);
    let finish = () => {};
    const done = new Promise<void>(resolve => { finish = resolve; });
    const entry = { requestId, timer: null as ReturnType<typeof setTimeout> | null, cancelled: false, done, finish };
    current = entry;
    const reject = async () => {
      if (closed || current !== entry || entry.cancelled) return;
      entry.cancelled = true;
      if (entry.timer) clearTimeout(entry.timer);
      try { await sendDecision(requestId, false); }
      catch (error) { options.onError?.(error); throw error; }
      finally { if (current === entry) options.onPending?.(null); entry.finish(); }
    };
    options.onPending?.({ chatId: options.chatId, projectId, focusId, requestId, expiresAt: pending.expires_at, reject });
    entry.timer = setTimeout(() => {
      void (async () => {
        if (closed || current !== entry || entry.cancelled) return;
        // The server checks its actual deadline, latest turn and membership
        // BEFORE any private settings/default Focus are loaded or decrypted.
        assertCurrent();
        await options.client.confirmProjectFocusCountdown(projectId, { chat_id: options.chatId, activation_request_id: requestId },
          { teamId: options.teamId, personal: !options.teamId });
        if (closed || current !== entry || entry.cancelled) return;
        await activateCliProjectFocus(options.client, projectId, options.chatId, options.teamId, requestId, () => !closed && current === entry && !entry.cancelled && options.isCurrent?.() !== false);
        if (closed || current !== entry || entry.cancelled) return;
        assertCurrent();
        await sendDecision(requestId, true);
        if (current === entry && !entry.cancelled) options.onPending?.(null);
      })().catch(error => { if (current === entry && !entry.cancelled) { options.onPending?.(null); options.onError?.(error); } }).finally(() => { entry.finish(); if (current === entry) current = null; });
    }, policy === "immediate" ? 0 : Math.max(0, Math.ceil(pending.expires_at * 1000 - Date.now())));
  });
  const stop = () => { closed = true; off(); offClose(); for (const cancel of [...pendingDecisions.values()]) cancel(); if (current?.timer) clearTimeout(current.timer); if (current) { current.cancelled = true; current.finish(); } };
  const offClose = options.ws.onClose(() => {
    if (current && !current.cancelled) options.onError?.(new Error("Project Focus transport closed"));
    stop();
  });
  return Object.assign(stop, { async flush() { while (current) { const entry = current; await entry.done; if (current === entry) return; } } });
}
