/** One private local daemon per OS user; the classifier child cannot use sockets. */
import { createHash } from "node:crypto";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { chmod, lstat, readFile, rm } from "node:fs/promises";
import { availableParallelism, freemem } from "node:os";
import { createConnection, createServer } from "node:net";
import { fileURLToPath } from "node:url";
import lockfile from "proper-lockfile";
import {
  privacyRoot, privacySocketPath, privacyModelPath, privacyRuntimeDirectory, privacyError,
  privateDirectory, verifyInstalledModel, verifyPrivacyRuntime, PRIVACY_MODEL, privacyStatus,
} from "./privacyModel.js";

export type NativePrivacyRange = { start: number; end: number; label: string };
const MAX_TEXT = 1024 * 1024;
const MAX_WIRE = 8 * MAX_TEXT;
const TIMEOUT = 5 * 60_000;
type Reply = { ready?: boolean; protocol?: number; model?: string; spans?: NativePrivacyRange[]; state?: string; error?: string };

class NativeWorker {
  child: ChildProcessWithoutNullStreams;
  ready: Promise<Reply>;
  buffer = Buffer.alloc(0);
  waiting: Array<{ resolve: (value: Reply) => void; reject: (error: Error) => void }> = [];
  failed = false;
  loaded = false;
  constructor(executable: string) {
    this.child = spawn(executable, [privacyModelPath(), String(Math.max(1, Math.min(4, availableParallelism() - 1)))], {
      cwd: privacyRoot(), env: { LANG: "C.UTF-8", LD_LIBRARY_PATH: privacyRuntimeDirectory() }, stdio: "pipe",
    });
    // Third-party diagnostic output never becomes a model result or a log.
    this.child.stderr.resume();
    this.ready = this.frame().then((reply) => { this.loaded = reply.ready === true; return reply; });
    this.child.stdout.on("data", (chunk: Buffer) => {
      this.buffer = Buffer.concat([this.buffer, chunk]);
      while (this.buffer.length >= 4) {
        const size = this.buffer.readUInt32BE(0);
        if (size > MAX_WIRE) { this.fail(); return; }
        if (this.buffer.length < size + 4) break;
        const payload = this.buffer.subarray(4, size + 4); this.buffer = this.buffer.subarray(size + 4);
        const next = this.waiting.shift();
        if (!next) { this.fail(); return; }
        try { next.resolve(JSON.parse(payload.toString("utf8")) as Reply); } catch { next.reject(privacyError("privacy_worker_protocol_failed")); this.fail(); }
      }
    });
    this.child.on("error", () => this.fail());
    this.child.on("exit", () => this.fail());
  }
  frame(): Promise<Reply> {
    if (this.failed) return Promise.reject(privacyError("privacy_worker_failed"));
    return new Promise((resolve, reject) => this.waiting.push({ resolve, reject }));
  }
  fail(): void {
    this.failed = true; this.child.kill("SIGKILL");
    for (const waiter of this.waiting.splice(0)) waiter.reject(privacyError("privacy_worker_failed"));
  }
  async scan(text: string): Promise<NativePrivacyRange[]> {
    if (!(await this.ready).ready) throw privacyError("privacy_worker_protocol_failed");
    const payload = Buffer.from(text, "utf8"); const header = Buffer.alloc(4); header.writeUInt32BE(payload.length);
    const pending = this.frame(); this.child.stdin.write(Buffer.concat([header, payload]));
    const reply = await pending; if (reply.error || !Array.isArray(reply.spans)) throw privacyError("privacy_worker_failed");
    return reply.spans;
  }
}

export async function privacyRpc(request: Record<string, unknown>, timeout = TIMEOUT): Promise<Reply> {
  const path = privacySocketPath(); const info = await lstat(path);
  if (!info.isSocket() || (info.mode & 0o077) || (process.getuid && info.uid !== process.getuid())) throw privacyError("privacy_unsafe_socket");
  return new Promise((resolveReply, reject) => {
    const socket = createConnection(path); let data = "";
    const timer = setTimeout(() => { socket.destroy(); reject(privacyError("privacy_scan_timed_out")); }, timeout);
    const finish = (error?: Error, reply?: Reply) => { clearTimeout(timer); socket.destroy(); if (error) reject(error); else resolveReply(reply!); };
    socket.on("connect", () => socket.write(JSON.stringify(request) + "\n"));
    socket.on("data", (chunk: Buffer) => {
      data += chunk.toString("utf8"); if (Buffer.byteLength(data) > MAX_WIRE) { finish(privacyError("privacy_worker_protocol_failed")); return; }
      const end = data.indexOf("\n"); if (end === -1) return;
      try { const reply = JSON.parse(data.slice(0, end)) as Reply; finish(reply.error ? privacyError(reply.error) : undefined, reply); }
      catch { finish(privacyError("privacy_worker_protocol_failed")); }
    });
    socket.on("error", () => finish(privacyError("privacy_worker_unavailable")));
    socket.on("end", () => { if (!data.includes("\n")) finish(privacyError("privacy_worker_unavailable")); });
  });
}

export async function ensurePrivacyDaemon(): Promise<void> {
  try { const reply = await privacyRpc({ op: "status" }, 1000); if (reply.protocol === 1 && reply.model === PRIVACY_MODEL.sha256) return; }
  catch { /* No running daemon; take the owner-only start lock. */ }
  if (!(await privacyStatus()).installed) throw privacyError("privacy_model_not_installed");
  const root = privacyRoot(); await privateDirectory(root);
  const unlock = await lockfile.lock(root, { lockfilePath: root + "/worker-start.lock", stale: 30_000, retries: { retries: 40, minTimeout: 100, maxTimeout: 200 } });
  try {
    try { const reply = await privacyRpc({ op: "status" }, 1000); if (reply.protocol === 1 && reply.model === PRIVACY_MODEL.sha256) return; await stopPrivacyDaemon(); } catch { /* stale socket */ }
    await rm(privacySocketPath(), { force: true });
    const entry = fileURLToPath(new URL("./privacyDaemon.js", import.meta.url));
    const child = spawn(process.execPath, [entry], { detached: true, stdio: "ignore", env: { PATH: process.env.PATH, LANG: "C.UTF-8", OPENMATES_PRIVACY_DIR: root } });
    child.unref();
    const start = Date.now();
    while (Date.now() - start < 10_000) {
      await new Promise((resolveWait) => setTimeout(resolveWait, 100));
      try { const reply = await privacyRpc({ op: "status" }, 1000); if (reply.protocol === 1 && reply.model === PRIVACY_MODEL.sha256) return; await stopPrivacyDaemon(); } catch { /* process startup */ }
    }
    throw privacyError("privacy_worker_unavailable");
  } finally { await unlock(); }
}

export async function stopPrivacyDaemon(): Promise<void> {
  try { await privacyRpc({ op: "stop" }, 1000); } catch { /* already stopped */ }
  for (let i = 0; i < 20; i++) {
    try { await lstat(privacySocketPath()); } catch { return; }
    await new Promise((done) => setTimeout(done, 50));
  }
}

export async function runPrivacyDaemon(): Promise<void> {
  await privateDirectory(privacyRoot());
  let native: NativeWorker | null = null;
  let initializing: Promise<NativeWorker> | null = null;
  const cache = new Map<string, NativePrivacyRange[]>();
  let tail: Promise<unknown> = Promise.resolve(); let queued = 0; let pendingBytes = 0;
  let idle: ReturnType<typeof setTimeout> | undefined;
  const close = async () => { native?.fail(); cache.clear(); server.close(); await rm(privacySocketPath(), { force: true }); process.exit(0); };
  const armIdle = (seconds = 120) => { clearTimeout(idle); idle = setTimeout(() => { if (!queued) void close(); }, seconds * 1000); };
  const getNative = () => initializing ??= (async () => {
    const memory = await readFile("/proc/meminfo", "utf8").catch(() => "");
    const available = Number(/^MemAvailable:\s+(\d+)/m.exec(memory)?.[1] ?? 0) * 1024 || freemem();
    if (available < 2.5 * 2 ** 30) throw privacyError("privacy_insufficient_available_memory");
    await verifyInstalledModel(); const executable = await verifyPrivacyRuntime();
    native = new NativeWorker(executable); await native.ready; return native;
  })();
  const watchdog = setInterval(() => {
    if (!native?.child.pid) return;
    void readFile(`/proc/${native.child.pid}/status`, "utf8").then((data) => {
      const rss = Number(/^VmRSS:\s+(\d+)/m.exec(data)?.[1] ?? 0) * 1024;
      if (rss > 3 * 2 ** 30) native?.fail();
    }).catch(() => {});
  }, 1000);
  watchdog.unref();
  const server = createServer((socket) => {
    let data = Buffer.alloc(0); let accepted = false;
    socket.setTimeout(TIMEOUT, () => socket.destroy());
    socket.on("error", () => {});
    socket.on("data", (chunk: Buffer) => {
      if (accepted) return;
      data = Buffer.concat([data, chunk]); if (data.length > MAX_WIRE) { socket.destroy(); return; }
      const end = data.indexOf(10); if (end < 0) return; accepted = true;
      let request: { op: string; text?: string; scope?: string; idleSeconds?: number };
      try { request = JSON.parse(data.subarray(0, end).toString("utf8")); } catch { socket.destroy(); return; }
      data.fill(0); data = Buffer.alloc(0);
      if (request.op === "status") { socket.end(JSON.stringify({ protocol: 1, model: PRIVACY_MODEL.sha256, state: native?.failed ? "failed" : native?.loaded ? "ready" : initializing ? "loading" : "installed_enabled" }) + "\n"); return; }
      if (request.op === "stop") { socket.end('{"state":"stopped"}\n'); void close(); return; }
      if (request.op !== "scan" || typeof request.text !== "string" || !/^[a-f0-9]{64}$/.test(request.scope ?? "") || Buffer.byteLength(request.text) > MAX_TEXT || queued >= 8 || pendingBytes + Buffer.byteLength(request.text) > 4 * MAX_TEXT) {
        socket.end('{"error":"privacy_request_rejected"}\n'); return;
      }
      const text = request.text; request.text = undefined;
      const bytes = Buffer.byteLength(text); pendingBytes += bytes; queued++; clearTimeout(idle);
      const key = request.scope + ":" + createHash("sha256").update(text).digest("hex");
      tail = tail.catch(() => {}).then(async () => {
        try {
          let spans = cache.get(key);
          if (!spans) {
            spans = await (await getNative()).scan(text);
            if (cache.size >= 128) cache.delete(cache.keys().next().value!);
            cache.set(key, spans);
          }
          socket.end(JSON.stringify({ spans }) + "\n");
        } catch { socket.end('{"error":"privacy_scan_failed"}\n'); }
        finally { queued--; pendingBytes -= bytes; armIdle(Math.max(15, Math.min(3600, request.idleSeconds || 120))); }
      });
    });
  });
  await new Promise<void>((resolveListen, reject) => { server.once("error", reject); server.listen(privacySocketPath(), () => { void chmod(privacySocketPath(), 0o600).then(resolveListen, reject); }); });
  armIdle();
  process.once("SIGTERM", () => { void close(); });
  process.once("SIGINT", () => { void close(); });
}
