/* eslint-disable @typescript-eslint/no-explicit-any -- TipTap JSON documents are untyped trees, as in parse_message.ts. */
// Answer-body embed policy (assertion app-skills.answer.only-result-embeds-in-body).
//
// An app skill invocation (`app_skill_use`, including the generated-media parent
// card such as "Generate · 1 · Results") is shown only in the collapsible
// "Used the X app" container (assistantActivityRuns.ts), which is built from
// activity nodes: the fenced JSON block where the skill ran or, when a message
// has none for that invocation, a retained `[!](embed:ref)` to it. Authored
// body references never render a skill card:
// - `[!](embed:ref)` becomes an activity node unless the invocation already has
//   one (an echo, dropped), followed by its result children that the body does
//   not already show;
// - `[text](embed:ref)` and `> [quote](embed:ref)` keep only their text.
//
// Stored messages already contain such references, so this runs at render time:
// once while parsing (parse_message) and again in ChatMessage whenever the ref
// index learns a type or a parent's children were read (late resolution).
// A block reference whose type or children are not known yet stays as a hidden
// placeholder (`bodyHidden`), so its position is kept, it renders nothing and
// it is never counted in a carousel run.

import { resolveExampleChatEmbedRef, resolveExampleChatChildEmbedIds } from "../demo_chats/publicExampleEmbedRefs";
import { resolveEmbedRefIndexEntry } from "../services/embedRefIndex";

export interface BodyEmbedRefEntry {
  embedId: string | null;
  appId?: string | null;
  skillId?: string | null;
  type: string | null;
}
export type BodyEmbedRefResolver = (ref: string) => BodyEmbedRefEntry | null;
/** Result child ids of a skill invocation; null while they are unknown. */
export type BodyEmbedChildLookup = (parentEmbedId: string) => string[] | null;

const SKILL_USE_TYPES = new Set(["app-skill-use", "app_skill_use", "app-skill-use-group"]);
// Deterministic parent ref (backend generated_media_parent_ref). Recognising
// it before the ref index is warm keeps a streaming parent card from flashing.
const GENERATED_MEDIA_PARENT_REF_RE = /^generated-media-(?:images|audio|music|videos|models3d|design)-[0-9a-f]{12}$/i;

export function isSkillUseEmbedType(type: unknown): boolean {
  return typeof type === "string" && SKILL_USE_TYPES.has(type);
}

/**
 * The single body rule: may an authored answer-body reference render this embed?
 * A known type decides; with no type yet, a generated-media parent ref is
 * already recognisable as an invocation.
 */
export function bodyMayShowEmbed(embedRef: unknown, type: string | null | undefined): boolean {
  if (type) return !isSkillUseEmbedType(type);
  if (typeof embedRef !== "string") return true;
  return !GENERATED_MEDIA_PARENT_REF_RE.test(embedRef.replace(/^embed:/, "").trim());
}

/** Ref lookup used by both the parser and the late pass for one chat. */
export function bodyEmbedRefResolver(chatId: string | null | undefined): BodyEmbedRefResolver {
  return chatId?.startsWith("example-")
    ? (ref) => resolveExampleChatEmbedRef(ref, chatId)
    : (ref) => resolveEmbedRefIndexEntry(ref);
}

/** Children known without any read: public example chats carry their graph. */
export function bodyEmbedSyncChildLookup(chatId: string | null | undefined): BodyEmbedChildLookup {
  return chatId?.startsWith("example-")
    ? (parentId) => resolveExampleChatChildEmbedIds(parentId, chatId)
    : () => null;
}

// ─── Carousel runs ───────────────────────────────────────────────────────────

function isEmptyParagraph(node: any): boolean {
  return node?.type === "paragraph" && (!Array.isArray(node.content) || node.content.length === 0);
}

function isHiddenBodyEmbed(node: any): boolean {
  return node?.type === "embedPreviewLarge" && node.attrs?.bodyHidden === true;
}

/**
 * Assign carousel metadata to consecutive embedPreviewLarge runs. Empty
 * paragraphs inside a run are discarded; hidden placeholders stay in place but
 * are not counted. Recurses into container nodes.
 */
export function assignCarouselRuns(nodes: any[]): any[] {
  const finalContent: any[] = [];
  let currentRun: any[] = [];
  let pendingEmpties: any[] = [];

  function flushRun() {
    if (currentRun.length === 0) return;
    const visible = currentRun.filter((node) => !isHiddenBodyEmbed(node));
    const runRef = (visible[0]?.attrs.embedRef as string | undefined) ?? "";
    let index = 0;
    for (const node of currentRun) {
      if (isHiddenBodyEmbed(node)) {
        finalContent.push({ ...node, attrs: { ...node.attrs, carouselIndex: -1, carouselTotal: 0, runRef: "" } });
        continue;
      }
      finalContent.push({
        ...node,
        attrs: { ...node.attrs, carouselIndex: index++, carouselTotal: visible.length, runRef },
      });
    }
    currentRun = [];
    pendingEmpties = [];
  }

  for (const node of nodes) {
    if (node?.type === "embedPreviewLarge") {
      pendingEmpties = [];
      currentRun.push(node);
    } else if (isEmptyParagraph(node) && currentRun.length > 0) {
      pendingEmpties.push(node);
    } else {
      flushRun();
      finalContent.push(...pendingEmpties);
      pendingEmpties = [];
      if (node?.type !== "paragraph" && Array.isArray(node?.content) && node.content.length > 0) {
        finalContent.push({ ...node, content: assignCarouselRuns(node.content) });
      } else {
        finalContent.push(node);
      }
    }
  }
  flushRun();
  return finalContent;
}

// ─── Enforcement ─────────────────────────────────────────────────────────────

export interface BodyEmbedPolicyContext {
  resolve: BodyEmbedRefResolver;
  childIds: BodyEmbedChildLookup;
}

function refKey(value: unknown): string | null {
  return typeof value === "string" && value ? value.replace(/^embed:/, "").trim() : null;
}

function nodeRefType(attrs: any, resolve: BodyEmbedRefResolver): { entry: BodyEmbedRefEntry | null; ref: string | null } {
  const ref = refKey(attrs?.embedRef) ?? refKey(attrs?.embedId);
  const entry = (ref ? resolve(ref) : null) ?? (refKey(attrs?.embedId) ? resolve(refKey(attrs.embedId)!) : null);
  return { entry, ref };
}

function blockMayShow(node: any, resolve: BodyEmbedRefResolver): boolean {
  if (node?.type !== "embedPreviewLarge") return true;
  const { entry, ref } = nodeRefType(node.attrs, resolve);
  return bodyMayShowEmbed(ref, entry?.type);
}

function collectVisibleIds(nodes: any[], resolve: BodyEmbedRefResolver, out: Set<string>): void {
  for (const node of nodes) {
    if (node?.type === "embedPreviewLarge" && !node.attrs?.bodyHidden && blockMayShow(node, resolve)) {
      const { entry } = nodeRefType(node.attrs, resolve);
      for (const key of [refKey(node.attrs?.embedRef), refKey(node.attrs?.embedId), refKey(entry?.embedId)]) {
        if (key) out.add(key);
      }
    }
    if (Array.isArray(node?.content)) collectVisibleIds(node.content, resolve, out);
  }
}

function collectActivityIds(nodes: any[], out: Set<string>): void {
  for (const node of nodes) {
    if (node?.type === "embed") {
      const attrs = node.attrs ?? {};
      const items = attrs.type === "app-skill-use-group" && Array.isArray(attrs.groupedItems) ? attrs.groupedItems : [attrs];
      for (const item of items) {
        if (item?.type !== "app-skill-use") continue;
        const id = refKey(item.id) ?? refKey(item.contentRef);
        if (id) out.add(id);
      }
    }
    if (Array.isArray(node?.content)) collectActivityIds(node.content, out);
  }
}

// Activity nodes made from a body ref whose result children are not known yet
// carry `resultsPending`, so the late pass can place those results after them.
function activityEmbedItems(node: any): any[] {
  if (node?.type !== "paragraph" || !Array.isArray(node.content) || node.content.length !== 1) return [];
  const embed = node.content[0];
  if (embed?.type !== "embed") return [];
  const attrs = embed.attrs ?? {};
  return attrs.type === "app-skill-use-group" && Array.isArray(attrs.groupedItems) ? attrs.groupedItems : [attrs];
}

function pendingActivityIds(node: any): string[] {
  return activityEmbedItems(node).flatMap((item) =>
    item?.resultsPending === true && refKey(item.id) ? [refKey(item.id)!] : []);
}

function clearResultsPending(node: any): any {
  const embed = node.content[0];
  const strip = (item: any) => {
    if (item?.resultsPending !== true) return item;
    const { resultsPending: _pending, ...rest } = item;
    return rest;
  };
  const attrs = strip(embed.attrs);
  if (Array.isArray(attrs.groupedItems)) attrs.groupedItems = attrs.groupedItems.map(strip);
  return { ...node, content: [{ ...embed, attrs }] };
}

function compactActivityParagraph(embedId: string, entry: BodyEmbedRefEntry, fallbackAppId: unknown, resultsPending: boolean): any {
  const attrs: Record<string, unknown> = {
    id: embedId,
    type: "app-skill-use",
    status: "finished",
    contentRef: `embed:${embedId}`,
  };
  if (resultsPending) attrs.resultsPending = true;
  const appId = entry.appId ?? (typeof fallbackAppId === "string" ? fallbackAppId : null);
  if (appId) attrs.app_id = appId;
  if (entry.skillId) attrs.skill_id = entry.skillId;
  return { type: "paragraph", content: [{ type: "embed", attrs }] };
}

function textNode(text: string, marks: unknown): any | null {
  if (!text) return null;
  const kept = Array.isArray(marks) ? marks.filter((mark: any) => mark?.type !== "link") : [];
  return kept.length > 0 ? { type: "text", text, marks: kept } : { type: "text", text };
}

/**
 * Apply the body rule to a parsed read-mode document. Returns the input object
 * unchanged when nothing had to change, so reactive callers stay stable.
 */
export function enforceBodyEmbedPolicy<T>(doc: T, ctx: BodyEmbedPolicyContext): T {
  const root = doc as any;
  if (!root || !Array.isArray(root.content)) return doc;
  const shown = new Set<string>();
  collectVisibleIds(root.content, ctx.resolve, shown);
  const activity = new Set<string>();
  collectActivityIds(root.content, activity);
  let changed = false;

  const visit = (nodes: any[], inParagraph: boolean): any[] => {
    const out: any[] = [];
    // The blank-line paragraph before a card that no longer shows would
    // otherwise remain as an empty gap.
    const dropSeparatorBefore = () => { if (out.length > 0 && isEmptyParagraph(out[out.length - 1])) out.pop(); };
    for (const node of nodes) {
      if (!node || typeof node !== "object") { out.push(node); continue; }
      if (node.type === "embedPreviewLarge") {
        const { entry, ref } = nodeRefType(node.attrs, ctx.resolve);
        if (bodyMayShowEmbed(ref, entry?.type)) {
          if (node.attrs?.bodyHidden) { changed = true; out.push({ ...node, attrs: { ...node.attrs, bodyHidden: false } }); }
          else out.push(node);
          continue;
        }
        const parentId = refKey(entry?.embedId) ?? refKey(node.attrs?.embedId);
        const children = parentId ? ctx.childIds(parentId) : null;
        // A resolved invocation without an activity node marks where it ran.
        const activityNode = entry?.type && parentId && !activity.has(parentId)
          ? compactActivityParagraph(parentId, entry, node.attrs?.appId, children === null)
          : null;
        if (activityNode) activity.add(parentId!);
        if (children === null) {
          const embedId = parentId ?? node.attrs?.embedId ?? null;
          if (!activityNode && node.attrs?.bodyHidden === true && node.attrs?.embedId === embedId) { out.push(node); continue; }
          changed = true;
          dropSeparatorBefore();
          // The activity node (or else a hidden placeholder) keeps the spot
          // for children that are read later.
          out.push(activityNode ?? { ...node, attrs: { ...node.attrs, embedId, bodyHidden: true } });
          continue;
        }
        changed = true;
        const missing = children.map(refKey).filter((key): key is string => !!key && !shown.has(key));
        if (missing.length === 0) dropSeparatorBefore();
        if (activityNode) out.push(activityNode);
        for (const key of missing) {
          shown.add(key);
          out.push({
            type: "embedPreviewLarge",
            attrs: { embedRef: key, embedId: key, appId: entry?.appId ?? node.attrs?.appId ?? null, carouselIndex: 0, carouselTotal: 1 },
          });
        }
        continue;
      }
      if (node.type === "embedInline" || node.type === "sourceQuote") {
        const attrs = node.attrs ?? {};
        const ref = refKey(attrs.embedRef);
        const entry = ref ? ctx.resolve(ref) : null;
        if (bodyMayShowEmbed(ref, entry?.type)) { out.push(node); continue; }
        changed = true;
        const text = String((node.type === "sourceQuote" ? attrs.quoteText : attrs.displayText) ?? "");
        const plain = textNode(text, node.marks);
        if (node.type === "sourceQuote" && !inParagraph) {
          if (plain) out.push({ type: "paragraph", content: [plain] });
        } else if (plain) {
          out.push(plain);
        }
        continue;
      }
      const pendingIds = pendingActivityIds(node);
      if (pendingIds.length > 0) {
        const known = pendingIds.map((id) => ctx.childIds(id));
        if (known.some((ids) => ids === null)) { out.push(node); continue; }
        changed = true;
        out.push(clearResultsPending(node));
        for (const key of known.flat().map(refKey)) {
          if (!key || shown.has(key)) continue;
          shown.add(key);
          out.push({ type: "embedPreviewLarge", attrs: { embedRef: key, embedId: key, appId: null, carouselIndex: 0, carouselTotal: 1 } });
        }
        continue;
      }
      if (Array.isArray(node.content)) {
        const content = visit(node.content, node.type === "paragraph");
        const before = node.content;
        if (content.length === before.length && content.every((child, index) => child === before[index])) {
          out.push(node);
          continue;
        }
        // A paragraph left with only separators would render an empty gap.
        if (node.type === "paragraph" && content.every((child) =>
          child?.type === "hardBreak" || child?.type === "softBreak" || (child?.type === "text" && !String(child.text ?? "").trim()))) {
          continue;
        }
        out.push({ ...node, content });
        continue;
      }
      out.push(node);
    }
    return out;
  };

  const content = visit(root.content, false);
  if (!changed) return doc;
  return { ...root, content: assignCarouselRuns(content) } as T;
}

/** Invocations referenced in the body whose result children are still unknown. */
export function pendingBodySkillParents(doc: unknown, ctx: BodyEmbedPolicyContext): string[] {
  const ids = new Set<string>();
  const walk = (nodes: unknown): void => {
    if (!Array.isArray(nodes)) return;
    for (const node of nodes as any[]) {
      const candidates = isHiddenBodyEmbed(node) ? [refKey(node.attrs?.embedId)] : pendingActivityIds(node);
      for (const id of candidates) {
        if (id && ctx.childIds(id) === null) ids.add(id);
      }
      walk(node?.content);
    }
  };
  walk((doc as any)?.content);
  return [...ids];
}
