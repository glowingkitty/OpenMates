import { validBrowserRetainedRead } from './browserCacheProtocol';
import type { BrowserRetainedRead } from './browserCacheProtocol';
import { projectSavedRendererMessages } from './savedChatRendererProjection';
import type { SavedChatRendererMessage } from './savedChatRendererProjection';
type ReadonlyTree<T> = T extends readonly (infer U)[] ? readonly ReadonlyTree<U>[] : T extends object ? {readonly [K in keyof T]:ReadonlyTree<T[K]>} : T;
export interface BrowserRetainedRendererProjection {
  readonly source:'browser_retained_message_cache';
  readonly chatId:string; readonly title:string; readonly category:string;
  readonly messages:readonly SavedChatRendererMessage[];
  /** Entire original retained envelope: no range/checkpoint/durable-ACK upgrade. */
  readonly page:ReadonlyTree<BrowserRetainedRead>;
}
function snapshot<T>(value:T):ReadonlyTree<T> {
  if(Array.isArray(value))return Object.freeze(value.map(item=>snapshot(item))) as ReadonlyTree<T>;
  if(value!==null&&typeof value==='object')return Object.freeze(Object.fromEntries(Object.entries(value).map(([k,v])=>[k,snapshot(v)]))) as ReadonlyTree<T>;
  return value as ReadonlyTree<T>;
}
/** Distinct inactive UI adapter. Caller owns original frame handle/generation/
 * principal admission and lifetime; source tags alone grant no authority.
 * Never manufacture an intermediate canonical/local-profile DTO. */
export function projectBrowserRetainedChatForRenderer(input:unknown,expectedChatId:string):BrowserRetainedRendererProjection {
  try {
    if(!validBrowserRetainedRead(input)||input.chat.id!==expectedChatId)throw Error();
    return Object.freeze({source:input.source,chatId:input.chat.id,title:input.chat.title,category:input.chat.category,
      messages:projectSavedRendererMessages(input.chat,input.messageMetadata),page:snapshot(input)});
  } catch { throw new Error('invalid_retained_renderer_page'); }
}
