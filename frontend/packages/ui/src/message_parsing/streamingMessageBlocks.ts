// frontend/packages/ui/src/message_parsing/streamingMessageBlocks.ts
// Defines the runtime contract for committed assistant blocks and mutable tails.
// The implementation is intentionally introduced after its red contract tests.
// Canonical Markdown remains authoritative across live and reopened messages.
// Spec: docs/specs/streaming-message-render-convergence/spec.yml

export type AssistantRenderPhase = "streaming" | "final";

export interface AssistantRenderBlock {
  id: string;
  markdown: string;
  document: Record<string, unknown>;
}

export interface AppSkillExecution {
  embedId: string;
  appId?: string;
  skillId?: string;
  sourceIndex: number;
}

export interface AppSkillGroupBlock {
  id: string;
  executions: AppSkillExecution[];
  document: Record<string, unknown>;
}

export type AssistantRenderOperation =
  | { kind: "append-blocks"; blockIds: string[] }
  | { kind: "replace-tail" }
  | { kind: "commit-tail" }
  | { kind: "update-app-skill-group" }
  | { kind: "replace-block"; index: number; blockId: string }
  | { kind: "convergence-failure"; reason: "non-local-divergence" };

export interface AssistantRenderPlan {
  sourceMarkdown: string;
  phase: AssistantRenderPhase;
  appSkillGroup: AppSkillGroupBlock | null;
  committed: AssistantRenderBlock[];
  tail: AssistantRenderBlock | null;
  authoredDocument: Record<string, unknown>;
  document: { type: "doc"; content: Array<Record<string, unknown>> };
  operations: AssistantRenderOperation[];
}

export interface CreateAssistantRenderPlanOptions {
  phase: AssistantRenderPhase;
  previous?: AssistantRenderPlan;
  chatId?: string;
}

export interface NormalizedAssistantRenderPlan {
  appSkillIds: string[];
  blocks: Array<{ id: string; nodeTypes: string[] }>;
}

export function createAssistantRenderPlan(
  _markdown: string,
  _options: CreateAssistantRenderPlanOptions,
): AssistantRenderPlan {
  throw new Error("Committed assistant block planning is not implemented");
}

export function normalizeAssistantRenderPlan(
  _plan: AssistantRenderPlan,
): NormalizedAssistantRenderPlan {
  throw new Error("Assistant render plan normalization is not implemented");
}
