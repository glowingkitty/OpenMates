/** DOM-only field projection of the existing Rust selected Cookie read DTO.
 * Provenance/ID checks are consistency only, never an auth or key capability.
 * No content parsing, wrapper selection, metadata lookup or PII restoration. */
export type ResolvedSavedEmbedBody = {
  readonly id: string; readonly status: 'finished' | 'error';
} & (
  | { readonly kind: 'code'; readonly code: string; readonly language: string | null; readonly filename: string | null }
  | { readonly kind: 'markdown'; readonly content: string }
  | { readonly kind: 'text'; readonly content: string }
  | { readonly kind: 'unsupported'; readonly preview: string }
);
function fail(): never { throw new Error('invalid_resolved_saved_embed_body'); }
function record(value: unknown): value is Record<string, unknown> {
  try { return !!value && typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype
    && Object.values(Object.getOwnPropertyDescriptors(value)).every(item => 'value' in item && !item.get && !item.set); } catch { return false; }
}
function optionalText(value: unknown): string | null { if (value === undefined || value === null) return null; return typeof value === 'string' ? value : fail(); }
export function projectResolvedSavedEmbedBody(id: string, input: Readonly<Record<string, unknown>>): ResolvedSavedEmbedBody {
  if (!record(input) || !id || input.embed_id !== id || input.schema_version !== 1 || input.source !== 'selected_cookie_ws'
    || input.read_only !== true || input.cached !== false || typeof input.type !== 'string' || typeof input.text_preview !== 'string'
    || (input.status !== 'finished' && input.status !== 'error')) fail();
  const shared: {id:string;status:'finished'|'error'} = {id,status:input.status};
  if (input.type === 'code') {
    if (typeof input.content === 'string') return Object.freeze({...shared,kind:'code',code:input.content,language:null,filename:null});
    if (record(input.content) && typeof input.content.code === 'string') return Object.freeze({...shared,kind:'code',code:input.content.code,
      language:optionalText(input.content.language),filename:optionalText(input.content.filename)});
    // A generic text field in a code-labeled record is not reclassified as code.
  }
  if ((input.type === 'markdown' || input.type === 'text') && typeof input.content === 'string') {
    return Object.freeze({...shared,kind:input.type,content:input.content});
  }
  return Object.freeze({...shared,kind:'unsupported',preview:input.text_preview});
}
