// frontend/packages/ui/src/message_parsing/streamingMessageBlocks.ts
// Defines the runtime contract for committed assistant blocks and mutable tails.
// Canonical Markdown remains authoritative across live and reopened messages.
// Adjacent app-skill calls retain their source positions beside authored text.
// Spec: docs/specs/streaming-message-render-convergence/spec.yml

import { compileAssistantDisplayMessage } from "./streamingMessageCompiler";

export type AssistantRenderPhase = "streaming" | "final";

export interface AssistantRenderBlock {
  id: string;
  markdown: string;
  document: Record<string, unknown>;
}

export type AssistantRenderOperation =
  | { kind: "append-blocks"; blockIds: string[] }
  | { kind: "replace-tail" }
  | { kind: "commit-tail" }
  | { kind: "replace-block"; index: number; blockId: string }
  | { kind: "delete-block"; index: number; blockId: string }
  | { kind: "convergence-failure"; reason: "non-local-divergence" };

export interface AssistantRenderPlan {
  sourceMarkdown: string;
  phase: AssistantRenderPhase;
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

  const previousBlocks = previous.committed;
  const nextBlocks = plan.committed;
  let committedPreviousTail = false;
  const sharedLength = Math.min(previousBlocks.length, nextBlocks.length);
  const changedIndexes: number[] = [];
  for (let index = 0; index < sharedLength; index += 1) {
    if (previousBlocks[index].markdown !== nextBlocks[index].markdown) {
      changedIndexes.push(index);
    }
  }

  for (const index of changedIndexes) {
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
      committedPreviousTail = true;
      appended[0].id = previous.tail!.id;
      operations.push({ kind: "commit-tail" });
      if (appended.length > 1) {
        operations.push({ kind: "append-blocks", blockIds: appended.slice(1).map((block) => block.id) });
      }
    } else {
      operations.push({ kind: "append-blocks", blockIds: appended.map((block) => block.id) });
    }
  }

  if (!committedPreviousTail && plan.tail?.markdown !== previous.tail?.markdown) {
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
  const partition = partitionAuthoredMarkdown(markdown, options.phase);
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
  // Compile the complete canonical source once. The parser groups only adjacent
  // cards, so prose and result references stay between the calls that produced them.
  // Stable committed/tail IDs above still describe incremental text updates.
  const document = compileBlock(markdown, options) as AssistantRenderPlan["document"];
  const authoredDocument = document;
  const plan: AssistantRenderPlan = {
    sourceMarkdown: markdown,
    phase: options.phase,
    committed,
    tail,
    authoredDocument,
    document,
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

function collectAppSkillIds(document: Record<string, unknown>): string[] {
  const ids: string[] = [];
  function visit(node: Record<string, unknown>): void {
    const attrs = node.attrs as Record<string, unknown> | undefined;
    if (node.type === "embed" && attrs) {
      if (attrs.type === "app-skill-use" && typeof attrs.id === "string") ids.push(attrs.id);
      if (attrs.type === "app-skill-use-group" && Array.isArray(attrs.groupedItems)) {
        for (const item of attrs.groupedItems as Array<Record<string, unknown>>) {
          if (typeof item.id === "string") ids.push(item.id);
        }
      }
    }
    for (const child of (Array.isArray(node.content) ? node.content : []) as Array<Record<string, unknown>>) visit(child);
  }
  visit(document);
  return ids;
}

export function normalizeAssistantRenderPlan(
  plan: AssistantRenderPlan,
): NormalizedAssistantRenderPlan {
  return {
    appSkillIds: collectAppSkillIds(plan.document),
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
