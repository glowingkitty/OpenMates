// Ordered Worker-side queue of server socket frames that arrived while the Client was busy
// (send, read, initial sync). Frames are applied in arrival order before any later Worker op.
import { withAuthRefreshLock } from "./browserAdapters";
import { SOCKET_FRAME_MAX_BYTES, SOCKET_FRAME_MAX_COUNT, validSocketFrameSummary } from "./socketFramesProtocol";
import type { SocketFrameSummary } from "./socketFramesProtocol";
import type { WorkerRuntimeState } from "./workerRuntimeState";
import { project, retireOriginalClient } from "./workerRuntimeState";

/** Hard caps of the queue; an overflow clears it and the page must re-admit its chat window. */
export const SOCKET_QUEUE_MAX_FRAMES = 2048;
export const SOCKET_QUEUE_MAX_BYTES = 8 * 1024 * 1024;

/** Queue state held on the runtime (identity travels with each frame; a stale identity fails at drain). */
export interface PendingSocketQueue {
  frames: { handle: string; generation: number; frame: Record<string, unknown>; bytes: number }[];
  bytes: number;
  /** Changes applied by drains since the last ingest reply; merged into that reply. */
  drainedChats: Map<string, number>;
  drainedIgnored: number;
}

export const newSocketQueue = (): PendingSocketQueue => ({ frames: [], bytes: 0, drainedChats: new Map(), drainedIgnored: 0 });

export const clearSocketQueue = (rt: WorkerRuntimeState): void => { rt.socketQueue = newSocketQueue(); };

/** Appends frames in order; false (queue cleared, fixed log code) when a cap would be exceeded. */
export function enqueueSocketFrames(rt: WorkerRuntimeState, handle: string, generation: number, frames: Record<string, unknown>[]): boolean {
  const queue = rt.socketQueue;
  const rows = frames.map(frame => ({ handle, generation, frame, bytes: JSON.stringify(frame).length }));
  const added = rows.reduce((sum, row) => sum + row.bytes, 0);
  if (queue.frames.length + rows.length > SOCKET_QUEUE_MAX_FRAMES || queue.bytes + added > SOCKET_QUEUE_MAX_BYTES) {
    clearSocketQueue(rt);
    console.warn("[RustCore] socket frame queue failed:", "socket_queue_overflow");
    return false;
  }
  queue.frames.push(...rows);
  queue.bytes += added;
  return true;
}

/** Folds drained changes into a reply summary (later messagesV per chat wins) and resets the accumulator. */
export function mergeDrainedSummary(rt: WorkerRuntimeState, own: SocketFrameSummary): SocketFrameSummary {
  const queue = rt.socketQueue;
  const chats = new Map(queue.drainedChats);
  for (const row of own.changedChats) chats.set(row.chatId, row.messagesV);
  const merged = { ...own, changedChats: [...chats].map(([chatId, messagesV]) => ({ chatId, messagesV })), ignored: own.ignored + queue.drainedIgnored };
  queue.drainedChats = new Map();
  queue.drainedIgnored = 0;
  return merged;
}

/**
 * Ordering contract: every Worker op starts with the socket frames received before it applied;
 * borrowers of the Client outside this dispatch (e.g. the voice unit's coreClientBorrow) must call
 * drainPendingSocketFrames first. A drain failure logs a fixed code and clears the queue; it never
 * fails the calling op. Applied changes accumulate and are returned by the next ingest reply.
 */
export async function drainPendingSocketFrames(rt: WorkerRuntimeState): Promise<void> {
  const owned = rt.client;
  if (rt.socketQueue.frames.length === 0) return;
  if (!owned || rt.disposed || typeof owned.ingest_socket_frames !== "function") { clearSocketQueue(rt); return; }
  const queue = rt.socketQueue;
  const alreadyReading = rt.reading === owned;
  if (!alreadyReading) rt.reading = owned;
  try {
    while (queue.frames.length > 0 && rt.client === owned && !rt.disposed && rt.socketQueue === queue) {
      const { handle, generation } = queue.frames[0];
      let count = 0, bytes = 0;
      while (count < queue.frames.length && count < SOCKET_FRAME_MAX_COUNT && queue.frames[count].handle === handle
        && queue.frames[count].generation === generation && (count === 0 || bytes + queue.frames[count].bytes <= SOCKET_FRAME_MAX_BYTES / 2)) {
        bytes += queue.frames[count].bytes; count++;
      }
      const batch = queue.frames.splice(0, count);
      queue.bytes -= bytes;
      const authority = project(rt, owned.status(handle, generation));
      if (authority.localReadOnly === true) throw new Error("local_profile_read_only");
      const encoded = await withAuthRefreshLock(rt.locks, rt.lifetime.signal,
        () => owned.ingest_socket_frames!(handle, generation, JSON.stringify(batch.map(row => row.frame))));
      const summary: unknown = typeof encoded === "string" && encoded.length <= 64 * 1024 ? JSON.parse(encoded) : null;
      if (!validSocketFrameSummary(summary)) throw new Error("unavailable");
      for (const row of summary.changedChats) queue.drainedChats.set(row.chatId, row.messagesV);
      queue.drainedIgnored += summary.ignored;
    }
  } catch (error) {
    const code = typeof error === "string" ? error : error instanceof Error ? error.message : "";
    console.warn("[RustCore] socket frame drain failed:", /^[a-z_]{3,40}$/.test(code) ? code : "unavailable");
    if (rt.socketQueue === queue) { queue.frames = []; queue.bytes = 0; }
  } finally {
    if (!alreadyReading && rt.reading === owned) rt.reading = null;
    if (!alreadyReading) retireOriginalClient(rt, owned);
  }
}
