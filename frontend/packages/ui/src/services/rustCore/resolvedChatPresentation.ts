import type { SavedChatRendererMessage, SavedChatRendererProjection } from "./savedChatRendererProjection";
export type ResolvedChatBlock =
  | { readonly kind: "markdown"; readonly content: string }
  | { readonly kind: "code"; readonly code: string; readonly language: string | null; readonly filename: string | null }
  | { readonly kind: "embed"; readonly id: string; readonly state: "loading" | "unavailable" | "error"; readonly message: string | null }
  | { readonly kind: "embed"; readonly id: string; readonly state: "resolved"; readonly value: Readonly<Record<string, unknown>> }
  | { readonly kind: "subchat"; readonly id: string; readonly title: string; readonly description: string | null };
export interface ResolvedChatMessagePresentation {
  readonly messageId: string;
  readonly sourceContent: string;
  readonly blocks: readonly ResolvedChatBlock[];
}
export interface ResolvedChatPresentation {
  readonly message: SavedChatRendererMessage;
  readonly blocks: readonly ResolvedChatBlock[];
}
function fail(): never { throw new Error("invalid_resolved_chat_presentation"); }
function record(v: unknown): v is Record<string, unknown> { return !!v && typeof v === "object" && Object.getPrototypeOf(v) === Object.prototype; }
function exact(v: Record<string, unknown>, keys: string[]): boolean { const own = Object.keys(v); return own.length === keys.length && own.every(k => keys.includes(k)); }
function text(v: unknown): v is string { return typeof v === "string"; }
function nullableText(v: unknown): boolean { return v === null || text(v); }
// Presentation structure only, not a second transport/authority validator.
// No getters/native resources; the generous local bound avoids serializing a
// duplicate source string or inheriting saved-chat wire limits for embed bodies.
function plainPresentation(value: unknown): boolean {
  let nodes = 0, units = 0;
  const walk = (v: unknown, depth: number): boolean => {
    if (++nodes > 131072 || depth > 64) return false;
    if (typeof v === "string") { units += v.length; return units <= 32 * 1024 * 1024; }
    if (v === null || typeof v === "boolean") return true;
    if (typeof v === "number") return Number.isFinite(v);
    if (!record(v) && !Array.isArray(v)) return false;
    if (Array.isArray(v) && (Object.getPrototypeOf(v) !== Array.prototype || Object.keys(v).length !== v.length)) return false;
    return Object.entries(Object.getOwnPropertyDescriptors(v)).every(([key,item]) => {
      if (Array.isArray(v) && key === "length") return true;
      units += key.length;
      return units <= 32 * 1024 * 1024 && "value" in item && !item.get && !item.set && walk(item.value,depth+1);
    });
  };
  try { return walk(value,0); } catch { return false; }
}
function block(v: unknown): v is ResolvedChatBlock {
  if (!record(v)) return false;
  if (v.kind === "markdown") return exact(v,["kind","content"]) && text(v.content);
  if (v.kind === "code") return exact(v,["kind","code","language","filename"]) && text(v.code) && nullableText(v.language) && nullableText(v.filename);
  if (v.kind === "subchat") return exact(v,["kind","id","title","description"]) && text(v.id) && !!v.id && text(v.title) && nullableText(v.description);
  if (v.kind !== "embed" || !text(v.id) || !v.id) return false;
  return v.state === "resolved" ? exact(v,["kind","id","state","value"]) && record(v.value)
    : ["loading","unavailable","error"].includes(String(v.state)) && exact(v,["kind","id","state","message"]) && nullableText(v.message);
}
function copy<T>(v: T): T {
  if (Array.isArray(v)) return Object.freeze(v.map(copy)) as T;
  if (record(v)) return Object.freeze(Object.fromEntries(Object.entries(v).map(([k,x]) => [k,copy(x)]))) as T;
  return v;
}
/** UI-only mapping of an explicitly resolved Rust presentation. Source identity
 * and exact plaintext are consistency guards, not authentication or authority.
 * Never parse/decrypt/restore PII/select a key/read a store/merge or sort here.
 */
export function projectResolvedChatPresentation(projection: Pick<SavedChatRendererProjection, "messages">,
  input: readonly ResolvedChatMessagePresentation[]): readonly ResolvedChatPresentation[] {
  if (!Array.isArray(input) || !plainPresentation(input) || input.length !== projection.messages.length) fail();
  const seen = new Set<string>();
  const result = input.map((part,index) => {
    const message = projection.messages[index];
    if (!record(part) || !exact(part,["messageId","sourceContent","blocks"]) || part.messageId !== message.id
      || part.sourceContent !== message.content || seen.has(part.messageId) || !Array.isArray(part.blocks)
      || part.blocks.length > 1024 || !part.blocks.every(block)) fail();
    seen.add(part.messageId);
    return Object.freeze({message,blocks:copy(part.blocks)});
  });
  return Object.freeze(result);
}
/** Text-only presentation keeps every Rust-decoded byte; it never resolves an
 * embed or interprets a status. Rich blocks must be supplied by the Rust caller. */
export function plainResolvedChatPresentation(projection: Pick<SavedChatRendererProjection, "messages">): readonly ResolvedChatMessagePresentation[] {
  return Object.freeze(projection.messages.map(message => Object.freeze({messageId:message.id,
    sourceContent:message.content,blocks:Object.freeze([{kind:"markdown" as const,content:message.content}])})));
}
