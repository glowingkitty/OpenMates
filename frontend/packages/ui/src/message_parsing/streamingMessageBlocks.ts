// frontend/packages/ui/src/message_parsing/streamingMessageBlocks.ts
// Defines the runtime contract for committed assistant blocks and mutable tails.
// The implementation is intentionally introduced after its red contract tests.
// Canonical Markdown remains authoritative across live and reopened messages.
// Spec: docs/specs/streaming-message-render-convergence/spec.yml

import { compileAssistantDisplayMessage } from "./streamingMessageCompiler";

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
  attributes?: Record<string, unknown>;
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
  | { kind: "delete-block"; index: number; blockId: string }
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

const APP_SKILL_GROUP_ID = "assistant-app-skill-executions";
const APP_SKILL_FENCE = /```json\s*\n([\s\S]*?)```/g;

interface ExtractedExecutions {
  authoredMarkdown: string;
  executions: AppSkillExecution[];
  fencesByEmbedId: Map<string, string>;
}

function hashText(value: string): string {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

function compileBlock(markdown: string, options: CreateAssistantRenderPlanOptions) {
  return compileAssistantDisplayMessage(markdown, {
    phase: options.phase,
    role: "assistant",
    chatId: options.chatId,
  }) as Record<string, unknown>;
}

function extractAppSkillExecutions(markdown: string): ExtractedExecutions {
  const executions: AppSkillExecution[] = [];
  const fencesByEmbedId = new Map<string, string>();
  const authoredMarkdown = markdown.replace(
    APP_SKILL_FENCE,
    (fence, jsonText: string, sourceIndex: number) => {
      try {
        const parsed = JSON.parse(jsonText.trim()) as Record<string, unknown>;
        const type = String(parsed.type || "").replace(/_/g, "-");
        const embedId = typeof parsed.embed_id === "string" ? parsed.embed_id : "";
        if (type !== "app-skill-use" || !embedId) return fence;

        executions.push({
          embedId,
          appId: typeof parsed.app_id === "string" ? parsed.app_id : undefined,
          skillId: typeof parsed.skill_id === "string" ? parsed.skill_id : undefined,
          sourceIndex,
          attributes: parsed,
        });
        fencesByEmbedId.set(embedId, fence);
        return "";
      } catch {
        return fence;
      }
    },
  );

  return {
    authoredMarkdown: authoredMarkdown.replace(/\n{3,}/g, "\n\n").trim(),
    executions,
    fencesByEmbedId,
  };
}

function findSafeParagraphEnds(markdown: string): number[] {
  const ends: number[] = [];
  let inFence = false;
  let index = 0;

  while (index < markdown.length) {
    if (markdown.startsWith("```", index)) {
      inFence = !inFence;
      index += 3;
      continue;
    }
    if (!inFence && markdown.startsWith("\n\n", index)) {
      ends.push(index);
      index += 2;
      continue;
    }
    index += 1;
  }
  return ends;
}

function hasBalancedInlineSyntax(markdown: string): boolean {
  let squareDepth = 0;
  let roundDepth = 0;
  let escaped = false;
  for (const character of markdown) {
    if (escaped) {
      escaped = false;
      continue;
    }
    if (character === "\\") {
      escaped = true;
      continue;
    }
    if (character === "[") squareDepth += 1;
    if (character === "]") squareDepth = Math.max(0, squareDepth - 1);
    if (character === "(" && squareDepth === 0) roundDepth += 1;
    if (character === ")" && squareDepth === 0) roundDepth = Math.max(0, roundDepth - 1);
  }
  return squareDepth === 0 && roundDepth === 0;
}

function isStandaloneLargePreview(markdown: string): boolean {
  return /^\s*\[!\]\(embed:[^)]+\)\s*$/.test(markdown);
}

function isSafeCompletedBlock(markdown: string, remaining: string): boolean {
  const trimmed = markdown.trim();
  if (!trimmed || !hasBalancedInlineSyntax(trimmed)) return false;
  if ((trimmed.match(/```/g) || []).length % 2 !== 0) return false;

  const lines = trimmed.split("\n");
  const isList = lines.some((line) => /^\s*(?:[-*+] |\d+\. )/.test(line));
  const isTable = lines.some((line) => /^\s*\|?.*\|.*\|?\s*$/.test(line)) &&
    lines.some((line) => /^\s*\|?\s*:?-{3,}/.test(line));
  const isCompleteSourceQuote = /^>\s*\[[^\]]+\]\(embed:[^)]+\)\s*$/.test(trimmed);
  const hasOtherQuote = lines.some((line) => /^\s*>/.test(line)) && !isCompleteSourceQuote;
  if (isList || isTable || hasOtherQuote) return false;

  if (isStandaloneLargePreview(trimmed)) {
    const nextBlock = remaining.split("\n\n", 1)[0] || "";
    return !isStandaloneLargePreview(nextBlock);
  }
  return true;
}

function isClosedStandaloneFence(markdown: string): boolean {
  const trimmed = markdown.trim();
  if (!trimmed.startsWith("```")) return false;
  return (trimmed.match(/```/g) || []).length >= 2 && trimmed.endsWith("```");
}

function partitionAuthoredMarkdown(
  markdown: string,
  phase: AssistantRenderPhase,
): { committedMarkdown: string[]; tailMarkdown: string | null } {
  const committedMarkdown: string[] = [];
  let start = 0;

  for (const end of findSafeParagraphEnds(markdown)) {
    if (end < start) continue;
    const block = markdown.slice(start, end).trim();
    const remaining = markdown.slice(end + 2).trimStart();
    if (block && isSafeCompletedBlock(block, remaining)) {
      committedMarkdown.push(block);
      start = end + 2;
    }
  }

  const remainder = markdown.slice(start).trim();
  if (!remainder) return { committedMarkdown, tailMarkdown: null };
  if (phase === "final" || isClosedStandaloneFence(remainder)) {
    committedMarkdown.push(remainder);
    return { committedMarkdown, tailMarkdown: null };
  }
  return { committedMarkdown, tailMarkdown: remainder };
}

function createBlock(
  markdown: string,
  occurrence: number,
  options: CreateAssistantRenderPlanOptions,
  previousByKey: Map<string, AssistantRenderBlock>,
): AssistantRenderBlock {
  const previous = previousByKey.get(`${markdown}\u0000${occurrence}`);
  if (previous) return previous;
  return {
    id: `assistant-block:${hashText(markdown)}:${occurrence}`,
    markdown,
    document: compileBlock(markdown, options),
  };
}

function documentContent(document: Record<string, unknown>): Array<Record<string, unknown>> {
  return Array.isArray(document.content)
    ? document.content as Array<Record<string, unknown>>
    : [];
}

function findEmbedAttrs(
  node: Record<string, unknown>,
  embedId: string,
): Record<string, unknown> | null {
  const attrs = node.attrs as Record<string, unknown> | undefined;
  if (node.type === "embed" && attrs?.id === embedId) return attrs;
  const groupedItems = Array.isArray(attrs?.groupedItems)
    ? attrs.groupedItems as Array<Record<string, unknown>>
    : [];
  const groupedMatch = groupedItems.find((item) => item.id === embedId);
  if (groupedMatch) return groupedMatch;
  const children = Array.isArray(node.content)
    ? node.content as Array<Record<string, unknown>>
    : [];
  for (const child of children) {
    const match = findEmbedAttrs(child, embedId);
    if (match) return match;
  }
  return null;
}

function createAppSkillGroup(
  extracted: ExtractedExecutions,
  options: CreateAssistantRenderPlanOptions,
  previous: AppSkillGroupBlock | null | undefined,
): AppSkillGroupBlock | null {
  if (extracted.executions.length === 0) return null;

  const executions = [...extracted.executions].sort(
    (left, right) => right.sourceIndex - left.sourceIndex,
  );
  if (JSON.stringify(previous?.executions || []) === JSON.stringify(executions)) {
    return previous || null;
  }
  const groupMarkdown = executions
    .map((execution) => extracted.fencesByEmbedId.get(execution.embedId) || "")
    .filter(Boolean)
    .join("\n\n");
  const parsed = compileBlock(groupMarkdown, options);
  const groupedItems = executions.map((execution) => {
    const attrs = findEmbedAttrs(parsed, execution.embedId);
    return attrs || {
      ...execution.attributes,
      id: execution.embedId,
      type: "app-skill-use",
      status: "processing",
      contentRef: `embed:${execution.embedId}`,
      app_id: execution.appId,
      skill_id: execution.skillId,
    };
  });
  const node = {
    type: "embed",
    attrs: {
      id: APP_SKILL_GROUP_ID,
      type: "app-skill-use-group",
      status: "finished",
      contentRef: null,
      groupedItems,
      groupCount: groupedItems.length,
    },
  };

  return {
    id: APP_SKILL_GROUP_ID,
    executions,
    document: { type: "doc", content: [{ type: "paragraph", content: [node] }] },
  };
}

function sameExecutions(
  previous: AppSkillGroupBlock | null,
  next: AppSkillGroupBlock | null,
): boolean {
  return JSON.stringify(previous?.executions || []) === JSON.stringify(next?.executions || []);
}

function reuseStableBlocks(
  blocks: AssistantRenderBlock[],
  previous: AssistantRenderPlan | undefined,
): void {
  if (!previous) return;
  const sharedLength = Math.min(blocks.length, previous.committed.length);
  for (let index = 0; index < sharedLength; index += 1) {
    if (blocks[index].markdown === previous.committed[index].markdown) {
      blocks[index] = previous.committed[index];
    }
  }
}

function deriveOperations(
  plan: AssistantRenderPlan,
  previous: AssistantRenderPlan | undefined,
): AssistantRenderOperation[] {
  if (!previous) return [];
  const operations: AssistantRenderOperation[] = [];

  if (!sameExecutions(previous.appSkillGroup, plan.appSkillGroup)) {
    operations.push({ kind: "update-app-skill-group" });
  }

  const previousBlocks = previous.committed;
  const nextBlocks = plan.committed;
  const sharedLength = Math.min(previousBlocks.length, nextBlocks.length);
  const changedIndexes: number[] = [];
  for (let index = 0; index < sharedLength; index += 1) {
    if (previousBlocks[index].markdown !== nextBlocks[index].markdown) {
      changedIndexes.push(index);
    }
  }

  if (changedIndexes.length > 1) {
    return [{ kind: "convergence-failure", reason: "non-local-divergence" }];
  }
  if (changedIndexes.length === 1) {
    const index = changedIndexes[0];
    plan.committed[index].id = previousBlocks[index].id;
    operations.push({ kind: "replace-block", index, blockId: previousBlocks[index].id });
  }

  if (previousBlocks.length === nextBlocks.length + 1) {
    const nextMarkdown = nextBlocks.map((block) => block.markdown);
    const removedIndex = previousBlocks.findIndex((_, candidateIndex) => {
      const remaining = previousBlocks
        .filter((__, index) => index !== candidateIndex)
        .map((block) => block.markdown);
      return JSON.stringify(remaining) === JSON.stringify(nextMarkdown);
    });
    if (removedIndex < 0) {
      return [{ kind: "convergence-failure", reason: "non-local-divergence" }];
    }
    operations.push({
      kind: "delete-block",
      index: removedIndex,
      blockId: previousBlocks[removedIndex].id,
    });
  } else if (previousBlocks.length > nextBlocks.length) {
    return [{ kind: "convergence-failure", reason: "non-local-divergence" }];
  }

  if (nextBlocks.length > previousBlocks.length) {
    const appended = nextBlocks.slice(previousBlocks.length);
    const commitsPreviousTail = previous.tail && appended[0]?.markdown === previous.tail.markdown;
    if (commitsPreviousTail) {
      appended[0].id = previous.tail!.id;
      operations.push({ kind: "commit-tail" });
      if (appended.length > 1) {
        operations.push({ kind: "append-blocks", blockIds: appended.slice(1).map((block) => block.id) });
      }
    } else {
      operations.push({ kind: "append-blocks", blockIds: appended.map((block) => block.id) });
    }
  }

  if (plan.tail?.markdown !== previous.tail?.markdown) {
    operations.push({ kind: "replace-tail" });
  }
  return operations;
}

function collectNodeTypes(node: Record<string, unknown>): string[] {
  const types = typeof node.type === "string" ? [node.type] : [];
  const children = Array.isArray(node.content)
    ? node.content as Array<Record<string, unknown>>
    : [];
  for (const child of children) types.push(...collectNodeTypes(child));
  return types;
}

export function createAssistantRenderPlan(
  markdown: string,
  options: CreateAssistantRenderPlanOptions,
): AssistantRenderPlan {
  const extracted = extractAppSkillExecutions(markdown);
  const partition = partitionAuthoredMarkdown(extracted.authoredMarkdown, options.phase);
  const occurrences = new Map<string, number>();
  const previousOccurrences = new Map<string, number>();
  const previousByKey = new Map<string, AssistantRenderBlock>();
  for (const block of options.previous?.committed || []) {
    const occurrence = previousOccurrences.get(block.markdown) || 0;
    previousOccurrences.set(block.markdown, occurrence + 1);
    previousByKey.set(`${block.markdown}\u0000${occurrence}`, block);
  }
  const committed = partition.committedMarkdown.map((blockMarkdown) => {
    const occurrence = occurrences.get(blockMarkdown) || 0;
    occurrences.set(blockMarkdown, occurrence + 1);
    return createBlock(blockMarkdown, occurrence, options, previousByKey);
  });
  reuseStableBlocks(committed, options.previous);
  const tail = partition.tailMarkdown
    ? {
        id: "assistant-tail",
        markdown: partition.tailMarkdown,
        document: compileBlock(partition.tailMarkdown, options),
      }
    : null;
  const appSkillGroup = createAppSkillGroup(
    extracted,
    options,
    options.previous?.appSkillGroup,
  );
  const authoredContent = [
    ...committed.flatMap((block) => documentContent(block.document)),
    ...(tail ? documentContent(tail.document) : []),
  ];
  const authoredDocument = { type: "doc", content: authoredContent };
  const content = [
    ...(appSkillGroup ? documentContent(appSkillGroup.document) : []),
    ...authoredContent,
  ];
  const plan: AssistantRenderPlan = {
    sourceMarkdown: markdown,
    phase: options.phase,
    appSkillGroup,
    committed,
    tail,
    authoredDocument,
    document: { type: "doc", content },
    operations: [],
  };
  plan.operations = deriveOperations(plan, options.previous);

  if (plan.operations[0]?.kind === "convergence-failure" && options.previous) {
    const failureContent = [
      ...options.previous.document.content,
      {
        type: "paragraph",
        content: [{ type: "text", text: "Message update could not be applied safely." }],
      },
    ];
    return {
      ...options.previous,
      sourceMarkdown: markdown,
      phase: options.phase,
      document: { type: "doc", content: failureContent },
      operations: plan.operations,
    };
  }
  return plan;
}

export function normalizeAssistantRenderPlan(
  plan: AssistantRenderPlan,
): NormalizedAssistantRenderPlan {
  return {
    appSkillIds: plan.appSkillGroup?.executions.map((execution) => execution.embedId) || [],
    blocks: [
      ...plan.committed.map((block) => ({
        id: `semantic:${hashText(block.markdown)}`,
        nodeTypes: collectNodeTypes(block.document),
      })),
      ...(plan.tail
        ? [{
            id: `semantic:${hashText(plan.tail.markdown)}`,
            nodeTypes: collectNodeTypes(plan.tail.document),
          }]
        : []),
    ],
  };
}
