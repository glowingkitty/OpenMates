/** Local privacy through Rust: 1 MiB UTF-8 text, 4 MiB canonical Rust JSON input (16 MiB wire ceiling) and 1024
 * combined memory/mapping entries. Prepared and restored UTF-8 output is capped
 * at 1 MiB, with growth checked before replacement copies. Values must be plain JSON data, with safe
 * integer-valued numbers, valid Unicode and at most 64 levels of nesting.
 */
import { createRequire } from "node:module";
import { SessionClientError } from "./sdkSession.js";

export interface PreparedPrivacy { text: string; mappings: Record<string, unknown>[] }
export interface PrivacyOptions {
  memories?: readonly unknown[];
  existingMappings?: readonly unknown[];
  enhanced?: boolean;
}
const invalid = (): never => { throw new SessionClientError("invalid_argument", "Invalid typed privacy input."); };
function validate(value: unknown, depth = 0): void {
  if (depth>64) invalid();
  if(value===null || typeof value==="boolean") return;
  if(typeof value==="number") { if(!Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value))) invalid(); return; }
  if(typeof value==="string") {
    for(let i=0;i<value.length;i++) {
      const c=value.charCodeAt(i);
      if(c>=0xd800 && c<=0xdbff) { const next=value.charCodeAt(++i); if(!(next>=0xdc00 && next<=0xdfff)) invalid(); }
      else if(c>=0xdc00 && c<=0xdfff) invalid();
    }
    return;
  }
  if(typeof value!=="object") return invalid();
  if(!Array.isArray(value) && Object.getPrototypeOf(value)!==Object.prototype && Object.getPrototypeOf(value)!==null) invalid();
  for(const key of Reflect.ownKeys(value)) {
    if(Array.isArray(value) && key==="length") continue;
    if(typeof key!=="string") return invalid();
    if(Array.isArray(value) && (!/^(0|[1-9][0-9]*)$/.test(key) || Number(key)>=value.length)) return invalid();
    validate(key,depth+1);
    const descriptor=Object.getOwnPropertyDescriptor(value,key);
    if(!descriptor || !Object.hasOwn(descriptor,"value")) return invalid();
    validate(descriptor.value,depth+1);
  }
  if(Array.isArray(value) && Object.keys(value).length!==value.length) invalid();
}
function call(input: Record<string, unknown>): Record<string, unknown> {
  let encoded: string;
  try {
    validate(input);
    encoded = JSON.stringify(input);
    if (Buffer.byteLength(encoded,"utf8")>16*1024*1024) invalid();
  } catch { return invalid(); }
  const platform = `${process.platform}-${process.arch}`;
  let native: {privacy(input:string):string};
  try { native=createRequire(import.meta.url)(`../native/${platform}.node`); }
  catch { throw new SessionClientError("native_binding_unavailable", "Install a native SDK build containing privacy operations."); }
  if (typeof native.privacy!=="function") throw new SessionClientError("native_binding_unavailable", "Install a native SDK build containing privacy operations.");
  try {
    const result: unknown=JSON.parse(native.privacy(encoded));
    if (!result || typeof result!=="object" || Array.isArray(result) || typeof (result as {text?:unknown}).text!=="string") throw new SessionClientError("protocol", "The native privacy result is invalid.");
    return result as Record<string,unknown>;
  } catch(error) {
    if (error instanceof SessionClientError) throw error;
    try {
      const value=JSON.parse(error instanceof Error ? error.message : "");
      if (typeof value.code==="string" && typeof value.message==="string") throw new SessionClientError(value.code,value.message);
    } catch(mapped) { if(mapped instanceof SessionClientError) throw mapped; }
    throw new SessionClientError("native_failure", "The native privacy operation failed.");
  }
}

function prepareChecked(text: string, options: PrivacyOptions): PreparedPrivacy {
  validate(options);
  if (typeof text!=="string" || !options || typeof options!=="object" || Array.isArray(options) || Reflect.ownKeys(options).some(key=>key!=="memories" && key!=="existingMappings" && key!=="enhanced")) invalid();
  const memories=Object.hasOwn(options,"memories")?options.memories:[];
  const existing=Object.hasOwn(options,"existingMappings")?options.existingMappings:[];
  const enhanced=Object.hasOwn(options,"enhanced")?options.enhanced:false;
  if (!Array.isArray(memories) || !Array.isArray(existing) || typeof enhanced!=="boolean" || memories.length+existing.length>1024 || Buffer.byteLength(text,"utf8")>1024*1024) invalid();
  const result=call({operation:"prepare",text,memories,existing_mappings:existing,enhanced});
  if (!Array.isArray(result.mappings) || result.mappings.some(m=>!m || typeof m!=="object" || Array.isArray(m) || typeof m.original!=="string" || typeof m.placeholder!=="string")) throw new SessionClientError("protocol", "The native privacy result is invalid.");
  return result as unknown as PreparedPrivacy;
}

function restoreChecked(text: string, mappings: readonly unknown[]): string {
  if (typeof text!=="string" || !Array.isArray(mappings) || mappings.length>1024 || Buffer.byteLength(text,"utf8")>1024*1024) invalid();
  return call({operation:"restore",text,mappings}).text as string;
}

/** Anonymize locally; retain returned mappings privately for restoration. */
export function preparePrivacy(text: string, options: PrivacyOptions = {}): PreparedPrivacy {
  try { return prepareChecked(text,options); }
  catch(error) { if(error instanceof SessionClientError) throw error; return invalid(); }
}

/** Restore in one pass, refusing unavailable or conflicting mappings. */
export function restorePrivacy(text: string, mappings: readonly unknown[]): string {
  try { return restoreChecked(text,mappings); }
  catch(error) { if(error instanceof SessionClientError) throw error; return invalid(); }
}
