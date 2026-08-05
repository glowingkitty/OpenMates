// frontend/packages/ui/src/message_parsing/streamingRenderScheduler.ts
// Monotonic leading/trailing scheduler for one streamed assistant message.
// It renders the first revision immediately, coalesces later revisions to a
// bounded cadence, and prevents stale work after completion or cancellation.
// Spec: docs/specs/streaming-message-render-convergence/spec.yml

import { incrementStreamingRenderMetric } from "./streamingRenderMetrics";

export type StreamingFlushReason = "stream" | "complete";

export interface StreamingRenderSchedulerOptions<T> {
  intervalMs?: number;
  onFlush: (value: T, revision: number, reason: StreamingFlushReason) => void;
}

export class StreamingRenderScheduler<T> {
  private readonly intervalMs: number;
  private readonly onFlush: StreamingRenderSchedulerOptions<T>["onFlush"];
  private timer: ReturnType<typeof setTimeout> | null = null;
  private pending: { value: T; revision: number } | null = null;
  private latestRevision = -1;
  private renderedRevision = -1;
  private lastFlushAt: number | null = null;
  private active = true;

  constructor({ intervalMs = 80, onFlush }: StreamingRenderSchedulerOptions<T>) {
    this.intervalMs = intervalMs;
    this.onFlush = onFlush;
  }

  seedRenderedRevision(revision: number): void {
    if (!this.active || this.latestRevision >= 0) return;
    this.latestRevision = revision;
    this.renderedRevision = revision;
    this.lastFlushAt = Date.now();
  }

  update(value: T, revision: number): void {
    if (!this.active || revision <= this.latestRevision) return;
    incrementStreamingRenderMetric("chunks");
    this.latestRevision = revision;
    this.pending = { value, revision };

    if (this.lastFlushAt === null) {
      this.flush("stream");
      return;
    }

    if (this.timer) return;
    const elapsed = Date.now() - this.lastFlushAt;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.flush("stream");
    }, Math.max(0, this.intervalMs - elapsed));
  }

  complete(value: T, revision: number): void {
    if (!this.active || revision < this.latestRevision) return;
    this.clearTimer();
    if (revision > this.latestRevision) {
      this.latestRevision = revision;
      this.pending = { value, revision };
    } else if (revision > this.renderedRevision) {
      this.pending = { value, revision };
    }

    if (this.pending && this.pending.revision > this.renderedRevision) {
      this.flush("complete");
    } else {
      this.pending = null;
    }
  }

  flushSemanticBoundary(): void {
    if (!this.active || !this.pending) return;
    this.clearTimer();
    this.flush("stream");
  }

  cancel(): void {
    this.active = false;
    this.pending = null;
    this.clearTimer();
  }

  destroy(): void {
    this.cancel();
  }

  private flush(reason: StreamingFlushReason): void {
    if (!this.active || !this.pending) return;
    const current = this.pending;
    this.pending = null;
    this.renderedRevision = current.revision;
    this.lastFlushAt = Date.now();
    incrementStreamingRenderMetric("flushes");
    this.onFlush(current.value, current.revision, reason);
  }

  private clearTimer(): void {
    if (!this.timer) return;
    clearTimeout(this.timer);
    this.timer = null;
  }
}
