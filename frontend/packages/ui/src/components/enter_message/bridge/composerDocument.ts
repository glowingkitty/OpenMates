// Product-owned composer document contract shared by web and Apple adapters.
// Canonical markdown remains the durable format; this model is editor-session state.
// Parsing and serialization are deterministic across web and native Apple.
// Never add encryption material, raw files, or platform editor objects here.
// Invalid runtime documents fail explicitly rather than serializing partial content.

export interface ComposerDocumentV1 {
  version: 1;
  nodes: ComposerNodeV1[];
}

export interface TextNodeV1 {
  kind: "text";
  id: string;
  source: string;
}

export interface HardBreakNodeV1 {
  kind: "hardBreak";
  id: string;
}

export interface MentionNodeV1 {
  kind: "mention";
  id: string;
  mentionKind:
    | "mate"
    | "aiModel"
    | "bestModel"
    | "skill"
    | "focus"
    | "project"
    | "memory";
  targetId: string;
  canonicalSyntax: string;
  displayLabel: string;
}

export interface ComposerEmbedDisplayV1 {
  title: string;
  mediaKind: string;
}

export interface EmbedNodeV1 {
  kind: "embed";
  id: string;
  embedType: string;
  status:
    | "draft"
    | "uploading"
    | "processing"
    | "transcribing"
    | "finished"
    | "error"
    | "cancelled";
  contentRef?: string;
  referenceOnly: boolean;
  canonicalSource: string;
  display: ComposerEmbedDisplayV1;
}

export type ComposerNodeV1 =
  | TextNodeV1
  | HardBreakNodeV1
  | MentionNodeV1
  | EmbedNodeV1;

export type ComposerDocumentErrorCode =
  | "unsupported-version"
  | "unsupported-node"
  | "invalid-node"
  | "duplicate-node-id";

export class ComposerDocumentError extends Error {
  constructor(
    readonly code: ComposerDocumentErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "ComposerDocumentError";
  }
}

const EMBED_FENCE_PATTERN = /```(json_embed|json)\n([\s\S]*?)\n```/g;
const MENTION_PATTERN =
  /@(best-model|ai-model|mate|skill|focus|project|memory):([a-zA-Z0-9_.-]+(?::[a-zA-Z0-9_.-]+)*)/g;
const OPAQUE_MARKDOWN_PATTERN = /```[\s\S]*?```|:::[^\n]*\n[\s\S]*?\n:::/g;

interface NodeCounters {
  text: number;
  mention: number;
  embed: number;
}

export function parseCanonicalMarkdownToComposerDocument(
  markdown: string,
): ComposerDocumentV1 {
  const source = markdown.replace(/\r\n?/g, "\n");
  const nodes: ComposerNodeV1[] = [];
  const counters: NodeCounters = { text: 0, mention: 0, embed: 0 };
  let cursor = 0;

  EMBED_FENCE_PATTERN.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = EMBED_FENCE_PATTERN.exec(source)) !== null) {
    const index = match.index;

    const embed = parseEmbedNode(
      match[0],
      match[1],
      match[2],
      `composer:embed:${counters.embed}`,
    );
    if (!embed) continue;

    appendTextAndMentions(source.slice(cursor, index), nodes, counters);
    nodes.push(embed);
    counters.embed += 1;
    cursor = index + match[0].length;
  }

  appendTextAndMentions(source.slice(cursor), nodes, counters);
  return { version: 1, nodes };
}

export function serializeComposerDocumentToCanonicalMarkdown(
  document: ComposerDocumentV1,
): string {
  if (document.version !== 1) {
    throw new ComposerDocumentError(
      "unsupported-version",
      `Unsupported ComposerDocument version: ${document.version}`,
    );
  }

  const seenNodeIds = new Set<string>();
  return document.nodes
    .map((node: ComposerNodeV1) => {
      if (typeof node.id !== "string" || !node.id) {
        throw new ComposerDocumentError(
          "invalid-node",
          "ComposerDocument node is missing an id",
        );
      }
      if (seenNodeIds.has(node.id)) {
        throw new ComposerDocumentError(
          "duplicate-node-id",
          `Duplicate ComposerDocument node id: ${node.id}`,
        );
      }
      seenNodeIds.add(node.id);

      switch (node.kind) {
        case "text":
          if (typeof node.source !== "string") {
            throw invalidNode(node.kind, node.id, "source");
          }
          return node.source;
        case "hardBreak":
          return "\n";
        case "mention":
          if (typeof node.canonicalSyntax !== "string") {
            throw invalidNode(node.kind, node.id, "canonicalSyntax");
          }
          return node.canonicalSyntax;
        case "embed":
          if (typeof node.canonicalSource !== "string") {
            throw invalidNode(node.kind, node.id, "canonicalSource");
          }
          return node.canonicalSource;
        default:
          throw new ComposerDocumentError(
            "unsupported-node",
            `Unsupported ComposerDocument node kind: ${String((node as { kind?: unknown }).kind)}`,
          );
      }
    })
    .join("");
}

export function utf16Length(value: string): number {
  return value.length;
}

function appendTextAndMentions(
  source: string,
  nodes: ComposerNodeV1[],
  counters: NodeCounters,
): void {
  let cursor = 0;

  OPAQUE_MARKDOWN_PATTERN.lastIndex = 0;
  let opaqueMatch: RegExpExecArray | null;
  while ((opaqueMatch = OPAQUE_MARKDOWN_PATTERN.exec(source)) !== null) {
    appendMentionTokens(source.slice(cursor, opaqueMatch.index), nodes, counters);
    appendTextNode(opaqueMatch[0], nodes, counters);
    cursor = opaqueMatch.index + opaqueMatch[0].length;
  }
  appendMentionTokens(source.slice(cursor), nodes, counters);
}

function appendMentionTokens(
  source: string,
  nodes: ComposerNodeV1[],
  counters: NodeCounters,
): void {
  let cursor = 0;

  MENTION_PATTERN.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = MENTION_PATTERN.exec(source)) !== null) {
    const index = match.index;

    appendTextNode(source.slice(cursor, index), nodes, counters);
    const targetId = match[2];
    nodes.push({
      kind: "mention",
      id: `composer:mention:${counters.mention++}`,
      mentionKind: mentionKind(match[1]),
      targetId,
      canonicalSyntax: match[0],
      displayLabel: `@${displayName(targetId)}`,
    });
    cursor = index + match[0].length;
  }

  appendTextNode(source.slice(cursor), nodes, counters);
}

function appendTextNode(
  source: string,
  nodes: ComposerNodeV1[],
  counters: NodeCounters,
): void {
  if (!source) return;
  nodes.push({
    kind: "text",
    id: `composer:text:${counters.text++}`,
    source,
  });
}

function parseEmbedNode(
  canonicalSource: string,
  fence: string,
  jsonSource: string,
  nodeId: string,
): EmbedNodeV1 | null {
  try {
    const value = JSON.parse(jsonSource) as Record<string, unknown>;
    if (
      typeof value.embed_id === "string" &&
      typeof value.type === "string"
    ) {
      const embedType = value.type;
      return {
        kind: "embed",
        id: nodeId,
        embedType,
        status: "finished",
        contentRef: `embed:${value.embed_id}`,
        referenceOnly: value.reference_only === true,
        canonicalSource,
        display: {
          title:
            typeof value.title === "string"
              ? value.title
              : displayName(embedType),
          mediaKind: embedType,
        },
      };
    }

    if (
      fence === "json_embed" &&
      value.type === "website" &&
      typeof value.url === "string"
    ) {
      return {
        kind: "embed",
        id: nodeId,
        embedType: "web-website",
        status: "finished",
        referenceOnly: false,
        canonicalSource,
        display: {
          title: typeof value.title === "string" ? value.title : "Website",
          mediaKind: "web-website",
        },
      };
    }

    return null;
  } catch {
    return null;
  }
}

function mentionKind(value: string): MentionNodeV1["mentionKind"] {
  if (value === "ai-model") return "aiModel";
  if (value === "best-model") return "bestModel";
  return value as MentionNodeV1["mentionKind"];
}

function displayName(value: string): string {
  if (value === "pdf") return "PDF";
  return value
    .split(/[-_:]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function invalidNode(
  kind: string,
  id: string,
  missingField: string,
): ComposerDocumentError {
  return new ComposerDocumentError(
    "invalid-node",
    `ComposerDocument ${kind} node ${id} is missing ${missingField}`,
  );
}
