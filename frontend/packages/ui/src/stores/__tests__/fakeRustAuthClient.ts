// frontend/packages/ui/src/stores/__tests__/fakeRustAuthClient.ts
// Synthetic Rust auth client for store unit tests. The real policy lives in the
// Rust core (`openmates_sdk::web_auth`); this double answers the same ops with the
// documented decisions so the page-side lifecycle (cleanup, generation guards,
// session-expiry handling) can be pinned without a Worker.

import type { RustAuthClient } from "../../services/rustCore/auth/authClient";
import type { AuthCall } from "../../services/rustCore/auth/authProtocol";

/** A `fetch` reply as `executeAuthRequest` reads it (status + text body). */
export function fetchReply(status: number, body: unknown = {}): Response {
  return { status, ok: status >= 200 && status < 300, text: async () => JSON.stringify(body) } as Response;
}

function parseArgs(raw: string): Record<string, unknown> {
  return JSON.parse(raw) as Record<string, unknown>;
}

function flow(name: string, args: Record<string, unknown>): unknown {
  switch (name) {
    case "language_reconcile": {
      const server = (args.serverLanguage as string | null) ?? null;
      const local = (args.localPreferred as string | null) ?? null;
      const effective = server ?? (args.defaultLanguage as string);
      const pushLocal = Boolean(local && local !== effective && server);
      return { pushLocal, applyAccount: effective, effectiveIsLocal: pushLocal };
    }
    case "debug_session_resume": {
      const expiresAtMs = args.expiresAtMs as number | null;
      const live = (expiresAtMs ?? Infinity) > (args.nowMs as number) && Boolean(args.debuggingId);
      return live ? { action: "start", debuggingId: args.debuggingId } : { action: "remove" };
    }
    default:
      throw new Error(`fake rust auth client: unhandled flow ${name}`);
  }
}

export function createFakeRustAuthClient(): RustAuthClient {
  return {
    async call<T>(call: AuthCall): Promise<T> {
      switch (call.op) {
        case "session_request":
          return { method: "POST", path: "/v1/auth/session", headers: [], body: "{}" } as T;
        case "classify_session": {
          if (call.status === 401) return { kind: "expired", data: { success: false, message: "Session expired or revoked" } } as T;
          if (call.status < 200 || call.status >= 300) return { kind: "unreachable", status: call.status } as T;
          const data = JSON.parse(call.body ?? "{}");
          return { kind: data.success ? "authenticated" : "unauthenticated", data } as T;
        }
        case "missing_key_plan": {
          const c = parseArgs(call.context);
          const kept = Boolean(c.sharedChatSession) || Boolean(c.pairLoginPending);
          const notify = !c.alreadyForced && !kept && c.hadLocalSession ? (c.storageEvicted ? "storage_evicted" : "session_ended") : null;
          return { setForced: true, clearActiveChat: !kept && !c.ogImageMode, notify, destructiveLogout: !kept, deleteCookies: !c.pairLoginPending } as T;
        }
        case "logout_server_step": {
          if (call.current !== call.captured) return { kind: "skip_newer_login" } as T;
          if (call.policyViolation) return { kind: "request", request: { method: "POST", path: "/v1/auth/policy-violation-logout", headers: [], body: null }, broadcast: false } as T;
          if (call.skipServerLogout) return { kind: "none" } as T;
          return { kind: "request", request: { method: "POST", path: "/v1/auth/logout", headers: [], body: null }, broadcast: false } as T;
        }
        case "logout_may_delete_cookies":
          return (call.captured === call.current) as T;
        case "flow":
          return flow(call.name, parseArgs(call.args)) as T;
        default:
          throw new Error(`fake rust auth client: unhandled op ${call.op}`);
      }
    },
    close() {},
  };
}
