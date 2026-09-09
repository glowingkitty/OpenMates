/**
 * Local Codex connection for explicitly invoked Tasks commands.
 * Uses the installed CLI to discover its already-running daemon, then reads
 * thread metadata over the supported Unix WebSocket control transport.
 * Never reads internal databases, starts a daemon, sends prompts or polls.
 * Legacy OpenCode links remain data and cannot enter the resume path.
 * Architecture: docs/architecture/platforms/tasks-v1.md.
 */
import { execFile, spawn } from "node:child_process";
import { promisify } from "node:util";
import { isAbsolute } from "node:path";
import WebSocket from "ws";

const execFileAsync = promisify(execFile);
const CONNECTION_TIMEOUT_MS = 10_000;
const MAX_RESPONSE_BYTES = 4 * 1024 * 1024;
const THREAD_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface CodexThreadConnection {
  provider: "codex";
  id: string;
  title: string;
  status: string;
  url: string;
}

export function codexResumeArguments(context: { provider: string; id: string }): string[] {
  if (context.provider !== "codex") throw new Error("Legacy OpenCode links are read-only. Connect this Task to a Codex thread explicitly.");
  if (!THREAD_ID.test(context.id)) throw new Error("Codex connection requires a valid thread UUID.");
  return ["resume", context.id];
}

async function daemonSocket(): Promise<string> {
  let result;
  try {
    result = await execFileAsync("codex", ["app-server", "daemon", "version"], {
      timeout: CONNECTION_TIMEOUT_MS, maxBuffer: 64 * 1024,
    });
  } catch {
    throw new Error("The installed Codex daemon is unavailable. Start Codex explicitly before connecting a Task.");
  }
  const metadata = JSON.parse(result.stdout);
  if (metadata.status !== "running" || typeof metadata.socketPath !== "string" || !isAbsolute(metadata.socketPath)) {
    throw new Error("The installed Codex CLI did not report a running local daemon.");
  }
  return metadata.socketPath;
}

export async function readCodexThread(threadId: string, socketPath?: string): Promise<CodexThreadConnection> {
  codexResumeArguments({ provider: "codex", id: threadId });
  const socket = socketPath ?? await daemonSocket();
  if (!isAbsolute(socket) || socket.includes(":")) throw new Error("Codex requires an absolute local socket path.");
  return new Promise((resolve, reject) => {
    // Compression negotiation is not accepted by the installed Unix listener.
    const ws = new WebSocket(`ws+unix://${socket}:/`, {
      perMessageDeflate: false, handshakeTimeout: CONNECTION_TIMEOUT_MS, maxPayload: MAX_RESPONSE_BYTES,
    });
    let settled = false;
    const finish = (error?: Error, value?: CodexThreadConnection) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (ws.readyState === WebSocket.OPEN) ws.close();
      else if (ws.readyState !== WebSocket.CLOSED) ws.terminate();
      if (error) reject(error); else resolve(value!);
    };
    const timer = setTimeout(() => finish(new Error("Codex connection timed out.")), CONNECTION_TIMEOUT_MS);
    ws.on("error", () => finish(new Error("Could not connect to the local Codex daemon.")));
    ws.on("close", () => finish(new Error("Codex closed the connection before returning thread metadata.")));
    ws.on("open", () => ws.send(JSON.stringify({
      id: 1, method: "initialize", params: { clientInfo: { name: "openmates-tasks", version: "1.0.0" } },
    })));
    ws.on("message", raw => {
      try {
        const message = JSON.parse(raw.toString());
        if (message.id !== 1 && message.id !== 2) return;
        if (message.error) return finish(new Error("Codex rejected the thread metadata request."));
        if (message.id === 1) {
          ws.send(JSON.stringify({ method: "initialized" }));
          ws.send(JSON.stringify({ id: 2, method: "thread/read", params: { threadId, includeTurns: false } }));
          return;
        }
        const thread = message.result?.thread;
        if (thread?.id !== threadId || typeof thread?.status?.type !== "string") {
          return finish(new Error("Codex returned invalid thread metadata."));
        }
        finish(undefined, {
          provider: "codex", id: thread.id, title: typeof thread.name === "string" ? thread.name : "",
          status: thread.status.type, url: `codex://threads/${thread.id}`,
        });
      } catch {
        finish(new Error("Codex returned malformed connection data."));
      }
    });
  });
}

export async function resumeCodexTask(context: { provider: string; id: string }): Promise<void> {
  const args = codexResumeArguments(context);
  if (!process.stdin.isTTY || !process.stdout.isTTY) throw new Error("Task resume requires an interactive terminal; status and connect never launch work.");
  await readCodexThread(context.id);
  await new Promise<void>((resolve, reject) => {
    const child = spawn("codex", args, { stdio: "inherit" });
    child.once("error", () => reject(new Error("Could not open the installed Codex CLI.")));
    child.once("exit", code => code === 0 ? resolve() : reject(new Error(`Codex resume exited with status ${code ?? "interrupted"}.`)));
  });
}

/** Render decrypted ownership only at the client, never in a server error. */
export function taskOwnerConflict(owner: { provider: string; id: string; title?: string | null }): string {
  const title = JSON.stringify(owner.title || "Untitled chat");
  const location = owner.provider === "openmates"
    ? `OpenMates chat ID: ${owner.id}. View: openmates chats show ${owner.id}`
    : `${owner.provider === "codex" ? "Codex" : "OpenCode"} chat ID: ${owner.id}`;
  return `Task is already linked to ${title}. ${location}. Release that link before claiming the task in another chat.`;
}

/** A link mutation must originate in that chat, not an orchestrator claiming for it. */
export function assertCodexClaimCaller(threadId: string, currentThread = process.env.CODEX_THREAD_ID): void {
  codexResumeArguments({ provider: "codex", id: threadId });
  if (!currentThread || currentThread !== threadId) {
    throw new Error("Only the owning Codex chat can claim a Task. Run this command inside Codex chat ID: " + threadId + ". Ordinary CLI creation can omit --external-chat to leave the Task unlinked.");
  }
}
