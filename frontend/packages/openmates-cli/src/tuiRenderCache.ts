/** Bounded, owner-local cache for private chat layout plans. */
export const CHAT_RENDER_CACHE_MAX_MESSAGES = 512;
export const CHAT_RENDER_CACHE_MAX_CHARS = 2_000_000;

type Entry<T> = {content:string; variant:string; value:T; size:number};
type Store<T> = {owner:string; width:number; aliases:string; embeds:Map<string,unknown>;
  frame:object;entries:Map<object,Entry<T>>; chars:number};
const stores = new WeakMap<object,Store<unknown>>();

function sameEmbeds(previous:Map<string,unknown>, current:Map<string,unknown>):boolean {
  if(previous.size!==current.size)return false;
  for(const [id,value] of current)if(previous.get(id)!==value)return false;
  return true;
}

/** The caller supplies a stable message object and its current content. Streaming edits are checked by value. */
export function cachedChatLayout<T>(state:object,message:object,content:string,
  context:{owner:string;width:number;aliases:string;embeds:Map<string,unknown>;frame:object;variant:string;cacheable:boolean},
  create:()=>T):T {
  let store=stores.get(state) as Store<T>|undefined;
  if(!store||store.frame!==context.frame&&(store.owner!==context.owner||store.width!==context.width||
    store.aliases!==context.aliases||!sameEmbeds(store.embeds,context.embeds))){
    store={owner:context.owner,width:context.width,aliases:context.aliases,embeds:new Map(context.embeds),
      frame:context.frame,entries:new Map(),chars:0};
    stores.set(state,store);
  }
  store.frame=context.frame;
  const hit=store.entries.get(message);
  if(hit&&hit.content===content&&hit.variant===context.variant){
    // Refresh recency without keeping old chat objects after their owner changes.
    store.entries.delete(message);store.entries.set(message,hit);
    return hit.value;
  }
  if(hit){store.entries.delete(message);store.chars-=hit.size;}
  const value=create();
  // A single huge streamed response must not evict every stable message.
  // Wrapped rows and span objects usually outweigh the source text itself.
  const size=chatLayoutWeight(content);
  if(!context.cacheable||size>CHAT_RENDER_CACHE_MAX_CHARS/4)return value;
  while(store.entries.size>=CHAT_RENDER_CACHE_MAX_MESSAGES||store.chars+size>CHAT_RENDER_CACHE_MAX_CHARS){
    const oldest=store.entries.keys().next().value;
    if(!oldest)break;
    const removed=store.entries.get(oldest)!;
    store.entries.delete(oldest);store.chars-=removed.size;
  }
  store.entries.set(message,{content,variant:context.variant,value,size});store.chars+=size;
  return value;
}

export function chatLayoutWeight(content:string):number {return content.length*4+128;}
export function clearChatRenderCache(state:object):void {stores.delete(state);}

/** Diagnostics expose only counts, never cached content. */
export function chatRenderCacheStats(state:object):{entries:number;chars:number} {
  const store=stores.get(state);
  return {entries:store?.entries.size??0,chars:store?.chars??0};
}
