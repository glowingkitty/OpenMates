// frontend/packages/ui/src/message_parsing/streamingMessageCompiler.ts
// Canonical compiler for assistant message display documents.
// Streaming and final snapshots intentionally share the same read semantics;
// phase metadata exists only to describe lifecycle, never parser behavior.
// Spec: docs/specs/streaming-message-render-convergence/spec.yml

import { preprocessTiptapJsonForEmbeds } from "../components/enter_message/utils/tiptapContentProcessor";
import { parse_message } from "./parse_message";
import { getStreamingRenderMetrics } from "./streamingRenderMetrics";

getStreamingRenderMetrics();

export interface AssistantDisplayCompileOptions {
  phase: "streaming" | "final";
  role?: "assistant";
  chatId?: string;
}

function recordCompileMetric(startedAt: number): void {
  if (typeof performance === "undefined") return;
  const endedAt = performance.now();
  performance.measure("openmates.streaming.compile", {
    start: startedAt,
    end: endedAt,
  });
}

export function compileAssistantDisplayMessage(
  markdown: string,
  options: AssistantDisplayCompileOptions,
) {
  const startedAt = typeof performance === "undefined" ? 0 : performance.now();
  const parsed = parse_message(markdown, "read", {
    unifiedParsingEnabled: true,
    role: options.role ?? "assistant",
    chatId: options.chatId,
  });
  const compiled = preprocessTiptapJsonForEmbeds(parsed) ?? parsed;
  recordCompileMetric(startedAt);
  return compiled;
}
