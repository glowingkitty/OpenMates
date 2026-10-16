/**
 * Chat-local embed shortcuts and terminal Fitness cards.
 * Uses the web Fitness normalizer for the same fields and status semantics.
 * Only canonical IDs reach the encrypted SDK; shortcuts stay in session memory.
 * Cached hydration runs separately from opening chat text and keeps owner fences.
 */
import type { DecryptedEmbed, OpenMatesClient } from './client.js';
import { parseEmbedContentObject } from './client.js';
import type { TuiState } from './tuiRenderer.js';
import { parseMessageSegments } from './messageSegments.js';
import { messageSupplementalEmbedIds } from './tuiChatResults.js';
import { tuiResultsSourceChildren } from './tuiResultsViews.js';
import { renderTuiEmbedPreview } from './tuiEmbedPreviews.js';
import { normalizeFitnessSearchContent, getFitnessResultTitle, getFitnessResultAddress, getFitnessResultUrl, normalizePipedList, asText, asNumber, type FitnessResult } from '../../ui/src/components/embeds/fitness/fitnessEmbedData.js';
import { type TuiLine } from './tuiText.js';

export type TuiEmbedTarget = { embedId: string; appId: string; skillId: string; resultIndex?: number; legacy?: boolean };
/** Tool metadata can point to the originating request. It is not user-message content. */
export function messageEmbedReferences(message: {role:string;content:string;embedIds?:string[]}) {
  const inline=parseMessageSegments(message.content).filter(segment=>segment.type==='embed');
  const metadataIds=message.role==='assistant'?message.embedIds??[]:[];
  const extra=metadataIds.filter(id=>!inline.some(ref=>ref.value===id)).map(id=>({value:id,meta:{} as Record<string,unknown>}));
  return [...inline,...extra];
}
export function chatEmbedReferences(state:TuiState) {
  const messages=state.screen==='example'?state.activeExample?.messages??[]:state.messages;
  const seen=new Set<string>();
  return messages.flatMap(message=>messageEmbedReferences(message)).filter(ref=>{
    if(seen.has(ref.value))return false;seen.add(ref.value);return true;
  });
}
const shortPart = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
export function embedAliasPrefix(app: string, skill: string): string {
  return `${shortPart(app).slice(0, 3) || 'emb'}-${shortPart(skill).split('_').filter(Boolean).map(word => word[0]).join('_') || 'v'}`;
}
export function isFitnessEmbed(embed: DecryptedEmbed): boolean {
  return embed.type === 'fitness-class' || (embed.appId ?? embed.content.app_id) === 'fitness' && (embed.skillId ?? embed.content.skill_id) === 'search_classes';
}
export function exampleEmbedMap(state: TuiState): Record<string, DecryptedEmbed> {
  return Object.fromEntries((state.activeExample?.embeds ?? []).map(value => {
    const content = parseEmbedContentObject(value.content);
    return [value.embed_id, {id:value.embed_id, embedId:value.embed_id, type:value.type, content, textPreview:null,
      appId:asText(content.app_id) || null, skillId:asText(content.skill_id) || null, createdAt:null}];
  }));
}

/** Allocation is stable while an open chat gains older messages or synced content. */
export function registerChatEmbedAliases(state: TuiState): void {
  const messages = state.activeExample && (state.screen === 'example' || state.embedOrigin?.screen === 'example' || state.resultsViewOrigin?.screen === 'example') ? state.activeExample.messages : state.messages;
  const saved = {...exampleEmbedMap(state), ...state.chatEmbeds};
  const metadata=new Map(messages.flatMap(message=>parseMessageSegments(message.content).filter(segment=>segment.type==='embed')).map(ref=>[ref.value,ref.meta??{}]));
  for (const message of messages) {
    const refs = [...messageEmbedReferences(message),...messageSupplementalEmbedIds(message.content).map(value=>({value,meta:{}}))];
    for (const ref of refs) {
      const embed = saved[ref.value], meta = metadata.get(ref.value) ?? ref.meta ?? {};
      const appId = embed?.appId || asText(meta.app_id) || asText(embed?.content.app_id) || (embed?.type==='fitness-class'?'fitness':'embed');
      const skillId = embed?.skillId || asText(meta.skill_id) || asText(embed?.content.skill_id) || (embed?.type==='fitness-class'?'search_classes':'view');
      const prefix = embedAliasPrefix(appId, skillId);
      // Source child aliases already allocated under their parent remain actionable.
      if(Object.values(saved).some(parent=>isFitnessEmbed(parent)&&normalizeFitnessSearchContent(parent.content).results.some(result=>result.embed_id===ref.value)))continue;
      const current=Object.entries(state.embedAliases).find(([,target])=>target.embedId===ref.value&&target.resultIndex===undefined&&!target.legacy);
      if(current){
        const placeholder=current[1].appId==='embed'||current[1].skillId==='view';
        if(!placeholder||current[1].appId===appId&&current[1].skillId===skillId)continue;
        // Replace a placeholder once metadata arrives, while accepting its old command.
        current[1].legacy=true;
        for(const [alias,target] of Object.entries(state.embedAliases))if(alias.startsWith(current[0]+'-'))target.legacy=true;
      }
      let count = 1;
      while (state.embedAliases[`${prefix}-${count}`]) count++;
      state.embedAliases[`${prefix}-${count}`] = {embedId:ref.value, appId, skillId};
    }
  }
  for (const [alias, target] of Object.entries(state.embedAliases)) {
    if (target.resultIndex !== undefined || target.legacy) continue;
    const embed = saved[target.embedId];
    if (!embed || !isFitnessEmbed(embed) || embed.type === 'fitness-class') continue;
    normalizeFitnessSearchContent(embed.content).results.forEach((_result, index) => {
      state.embedAliases[`${alias}-${index + 1}`] = {...target, resultIndex:index};
    });
  }
}
export function aliasForEmbed(state: TuiState, id: string): string {
  const direct=Object.entries(state.embedAliases).find(([,target]) => target.embedId === id && target.resultIndex === undefined&&!target.legacy)?.[0];
  if(direct)return direct;
  const saved={...exampleEmbedMap(state),...state.chatEmbeds};
  return Object.entries(state.embedAliases).find(([,target])=>!target.legacy&&target.resultIndex!==undefined&&saved[target.embedId]&&normalizeFitnessSearchContent(saved[target.embedId].content).results[target.resultIndex]?.embed_id===id)?.[0]??id;
}

export async function hydrateFitnessResults(embed: DecryptedEmbed, client: OpenMatesClient, limit = 50): Promise<DecryptedEmbed> {
  if (!isFitnessEmbed(embed) || embed.type === 'fitness-class') return embed;
  const data = normalizeFitnessSearchContent(embed.content);
  let ids: string[] = [];
  if (Array.isArray(data.embedIds)) ids = data.embedIds.filter(value=>typeof value==='string');
  else if (typeof data.embedIds === 'string') {
    try { const parsed:unknown=JSON.parse(data.embedIds);if(Array.isArray(parsed))ids=parsed.filter(value=>typeof value==='string'); } catch { ids=data.embedIds.split(/[,|]/).map(value=>value.trim()).filter(Boolean); }
  }
  if (!ids.length || data.status !== 'finished') return embed;
  const results = ids.map((id,index) => ({...data.results[index],embed_id:id}));
  let next = 0;
  const count=Math.min(limit,results.length);
  await Promise.all(Array.from({length:Math.min(3,count)},async()=>{
    while(next<count){const index=next++;if(results[index].name&&!results[index]._tuiUnavailable)continue;
      try { const child=await client.getEmbed(ids[index],{preferCache:true});results[index]={...child.content,embed_id:ids[index]}; }
      catch { results[index]={...results[index],name:results[index].name||'Class details unavailable',_tuiUnavailable:true}; }
    }
  }));
  // Normalize only in transient presentation state; retain the encrypted cache untouched.
  return {...embed,content:{...embed.content,results,result_count:data.resultCount||ids.length,provider:data.provider,filters:data.filters,summary:data.summary}};
}

/** Metadata references are enough to draw an immediate card; hydrate without blocking chat opening. */
export async function hydrateChatEmbedPreviews(state: TuiState, client: OpenMatesClient, render: () => void): Promise<void> {
  registerChatEmbedAliases(state);
  const chatId = state.activeChatId, loads = state.chatEmbedLoads, aliases = state.embedAliases;
  const ids = [...new Set(Object.values(aliases).filter(target => target.resultIndex === undefined).map(target => target.embedId))].slice(-40);
  let next = 0;
  const queued = new Set(ids);
  const current = () => aliases === state.embedAliases && chatId === state.activeChatId;
  await Promise.all(Array.from({length:Math.min(3, ids.length)}, async () => {
    while (next < ids.length) {
      const id = ids[next++];
      if(!current())return;
      if(loads.has(id))continue;
      loads.add(id);
      try {
        let embed=state.chatEmbeds[id]??await client.getEmbed(id, {preferCache:true, chatId:chatId ?? undefined});
        if(!current())return;
        // Keep every cached child available to map/calendar as well as parent previews.
        const cachedClient=Object.create(client) as OpenMatesClient;
        cachedClient.getEmbed=async(childId,options)=>{
          const child=state.chatEmbeds[childId]??await client.getEmbed(childId,{...options,preferCache:true,chatId:chatId??undefined});
          if(current())state.chatEmbeds[childId]=child;
          return child;
        };
        embed=await hydrateFitnessResults(embed,cachedClient,2);
        if(!current())return;
        state.chatEmbeds[id]=embed;
        for(const child of tuiResultsSourceChildren(embed))if(!queued.has(child)&&ids.length<80){queued.add(child);ids.push(child);}
        registerChatEmbedAliases(state);render();
      } catch { /* Keep the reference card and let /embed retry explicitly. */ }
      finally { loads.delete(id); }
    }
  }));
}

export function fitnessResultRows(result: FitnessResult): string[] {
  const distance = asNumber(result.distance_km);
  return [getFitnessResultTitle(result),
    [result.date, result.time_range, result.venue_name].filter(Boolean).join(' · '),
    [distance === undefined ? '' : `${distance.toFixed(2)} km`, result.spots_display, ...normalizePipedList(result.disciplines).slice(0,2)].filter(Boolean).join(' · '),
    normalizePipedList(result.plans_required).length ? `Plans: ${normalizePipedList(result.plans_required).join(', ')}` : '',
  ].filter(Boolean);
}
/** Compatibility export; the shared renderer owns every preview's bottom info bar. */
export function renderFitnessPreview(embed: DecryptedEmbed, width: number, alias: string): TuiLine[] {
  return renderTuiEmbedPreview(embed,width,alias);
}
export function fitnessResultDetail(result: FitnessResult): string[] {
  return [...fitnessResultRows(result),'',getFitnessResultAddress(result),
    result.attendance_mode ? `Attendance: ${asText(result.attendance_mode)}` : '',
    asText(result.description),getFitnessResultUrl(result)].filter(Boolean);
}
export function fitnessSearchDetail(embed: DecryptedEmbed, alias: string): string[] {
  const data=normalizeFitnessSearchContent(embed.content);
  if(data.status!=='finished')return [data.status==='processing'?'Searching for classes…':data.status==='error'?'Search failed. No verified results.':'Search cancelled.'];
  return [data.provider,asText(data.filters.address||data.filters.city||data.query),`${data.resultCount} classes`,data.summary,'',
    ...(data.results.length ? data.results.flatMap((result,index)=>[...fitnessResultRows(result),`/embed ${alias}-${index+1} · Open class`,'']) : ['No classes found.'])].filter(row=>row!==undefined);
}
