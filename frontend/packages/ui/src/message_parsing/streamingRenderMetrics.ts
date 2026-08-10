// frontend/packages/ui/src/message_parsing/streamingRenderMetrics.ts
// Sanitized counters for bounded streaming-render diagnostics and E2E evidence.
// Counters contain no message text, embed refs, decrypted content, or identifiers.
// They are intentionally lightweight and shared across compiler/render components.
// Spec: docs/specs/streaming-message-render-convergence/spec.yml

export interface StreamingRenderMetrics {
  chunks: number;
  flushes: number;
  fullReplacements: number;
  nodeViewMounts: number;
  mapHydrations: number;
}

declare global {
  interface Window {
    __openmatesStreamingRenderMetrics?: StreamingRenderMetrics;
  }
}

export function getStreamingRenderMetrics(): StreamingRenderMetrics | null {
  if (typeof window === "undefined") return null;
  window.__openmatesStreamingRenderMetrics ??= {
    chunks: 0,
    flushes: 0,
    fullReplacements: 0,
    nodeViewMounts: 0,
    mapHydrations: 0,
  };
  return window.__openmatesStreamingRenderMetrics;
}

export function incrementStreamingRenderMetric(
  key: keyof StreamingRenderMetrics,
): void {
  const metrics = getStreamingRenderMetrics();
  if (metrics) metrics[key] += 1;
}
