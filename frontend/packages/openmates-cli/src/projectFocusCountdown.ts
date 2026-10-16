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
}) {
  let current: { requestId: string; timer: ReturnType<typeof setTimeout> | null; cancelled: boolean; done: Promise<void>; finish: () => void } | null = null;
  let closed = false;
  const off = options.ws.onMessageType("focus_mode_pending", value => {
    if (!value || typeof value !== "object") return;
    const pending = value as Record<string, unknown>;
    if (closed || pending.chat_id !== options.chatId || typeof pending.focus_id !== "string"
        || !/^project-[a-f0-9-]{36}$/i.test(pending.focus_id) || typeof pending.embed_id !== "string"
        || !pending.embed_id || pending.embed_id.length > 128 || typeof pending.expires_at !== "number"
        || !Number.isFinite(pending.expires_at) || pending.expires_at * 1000 > Date.now() + 10_000
        || pending.expires_at * 1000 < Date.now() - 10_000 || current?.requestId === pending.embed_id) return;
    if (current?.timer) clearTimeout(current.timer);
    if (current) { current.cancelled = true; current.finish(); }
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
      try { await options.ws.sendAsync("focus_mode_decision", { chat_id: options.chatId, focus_id: focusId, embed_id: requestId, accepted: false }); }
      finally { options.onPending?.(null); entry.finish(); }
    };
    options.onPending?.({ chatId: options.chatId, projectId, focusId, requestId, expiresAt: pending.expires_at, reject });
    entry.timer = setTimeout(() => {
      void (async () => {
        if (closed || current !== entry || entry.cancelled) return;
        // The server checks its actual deadline, latest turn and membership
        // BEFORE any private settings/default Focus are loaded or decrypted.
        await options.client.confirmProjectFocusCountdown(projectId, { chat_id: options.chatId, activation_request_id: requestId },
          { teamId: options.teamId, personal: !options.teamId });
        if (closed || current !== entry || entry.cancelled) return;
        await activateCliProjectFocus(options.client, projectId, options.chatId, options.teamId, requestId, () => !closed && current === entry && !entry.cancelled);
        options.onPending?.(null);
      })().catch(error => { options.onPending?.(null); options.onError?.(error); }).finally(entry.finish);
    }, Math.max(0, Math.ceil(pending.expires_at * 1000 - Date.now())));
  });
  const stop = () => { closed = true; off(); if (current?.timer) clearTimeout(current.timer); if (current) { current.cancelled = true; current.finish(); } };
  options.ws.onClose(stop);
  return Object.assign(stop, { async flush() { while (current) { const entry = current; await entry.done; if (current === entry) return; } } });
}
