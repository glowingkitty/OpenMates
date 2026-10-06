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
import { APP_GRADIENTS } from '../../appGradientTheme.js';
import { normalizeFitnessSearchContent, getFitnessResultTitle, getFitnessResultAddress, getFitnessResultUrl, normalizePipedList, asText, asNumber, type FitnessResult } from '../../ui/src/components/embeds/fitness/fitnessEmbedData.js';
import { padCells, wrapCells, truncateCells, type TuiLine } from './tuiText.js';

export type TuiEmbedTarget = { embedId: string; appId: string; skillId: string; resultIndex?: number };
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
  const messages = state.screen === 'example' ? state.activeExample?.messages ?? [] : state.messages;
  const saved = {...exampleEmbedMap(state), ...state.chatEmbeds};
  const known = new Set(Object.values(state.embedAliases).filter(target => target.resultIndex === undefined).map(target => target.embedId));
  for (const message of messages) {
    const segments = parseMessageSegments(message.content).filter(segment => segment.type === 'embed');
    const refs = [...segments, ...(message.embedIds ?? []).filter(id => !segments.some(segment => segment.value === id)).map(id => ({value:id, meta:{} as Record<string,unknown>}))];
    for (const ref of refs) {
      if (known.has(ref.value)) continue;
      const embed = saved[ref.value], meta = ref.meta ?? {};
      const appId = embed?.appId || asText(meta.app_id) || asText(embed?.content.app_id) || 'embed';
      const skillId = embed?.skillId || asText(meta.skill_id) || asText(embed?.content.skill_id) || 'view';
      const prefix = embedAliasPrefix(appId, skillId);
      let count = 1;
      while (state.embedAliases[`${prefix}-${count}`]) count++;
      state.embedAliases[`${prefix}-${count}`] = {embedId:ref.value, appId, skillId};
      known.add(ref.value);
    }
  }
  for (const [alias, target] of Object.entries(state.embedAliases)) {
    if (target.resultIndex !== undefined) continue;
    const embed = saved[target.embedId];
    if (!embed || !isFitnessEmbed(embed) || embed.type === 'fitness-class') continue;
    normalizeFitnessSearchContent(embed.content).results.forEach((_result, index) => {
      state.embedAliases[`${alias}-${index + 1}`] = {...target, resultIndex:index};
    });
  }
}
export function aliasForEmbed(state: TuiState, id: string): string {
  return Object.entries(state.embedAliases).find(([,target]) => target.embedId === id && target.resultIndex === undefined)?.[0] ?? id;
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
  const ids = [...new Set(Object.values(aliases).filter(target => target.resultIndex === undefined).map(target => target.embedId))].filter(id => !state.chatEmbeds[id] && !loads.has(id)).slice(-20);
  let next = 0;
  await Promise.all(Array.from({length:Math.min(3, ids.length)}, async () => {
    while (next < ids.length) {
      const id = ids[next++]; loads.add(id);
      try {
        let embed = await client.getEmbed(id, {preferCache:true, chatId:chatId ?? undefined});
        const cachedClient=Object.create(client) as OpenMatesClient;
        cachedClient.getEmbed=(id,options)=>client.getEmbed(id,{...options,preferCache:true,chatId:chatId??undefined});
        embed=await hydrateFitnessResults(embed,cachedClient,2);
        if (aliases !== state.embedAliases || chatId !== state.activeChatId) return;
        state.chatEmbeds[id] = embed;
        registerChatEmbedAliases(state); render();
      } catch { /* Keep the reference card and let /embed retry explicitly. */ }
      finally { loads.delete(id); }
    }
  }));
}

function card(rows: string[], width: number): TuiLine[] {
  width = Math.max(1, Math.min(width, 62));
  if (width < 6) return rows.flatMap(row => wrapCells(row, width));
  const color = APP_GRADIENTS.fitness.start;
  return [
    {text:`╭${'─'.repeat(width-2)}╮`, color},
    ...rows.flatMap((row,index) => wrapCells(row, width-4).map(text => {
      const value=`│ ${padCells(text,width-4)} │`;
      return {text:value,...(index<2 ? {spans:[{text:value,background:color,bold:index===1}]} : {color:'#e6e6e6'})};
    })),
    {text:`╰${'─'.repeat(width-2)}╯`,color},
  ];
}
export function fitnessResultRows(result: FitnessResult): string[] {
  const distance = asNumber(result.distance_km);
  return [getFitnessResultTitle(result),
    [result.date, result.time_range, result.venue_name].filter(Boolean).join(' · '),
    [distance === undefined ? '' : `${distance.toFixed(2)} km`, result.spots_display, ...normalizePipedList(result.disciplines).slice(0,2)].filter(Boolean).join(' · '),
    normalizePipedList(result.plans_required).length ? `Plans: ${normalizePipedList(result.plans_required).join(', ')}` : '',
  ].filter(Boolean);
}
export function renderFitnessPreview(embed: DecryptedEmbed, width: number, alias: string): TuiLine[] {
  if (embed.type === 'fitness-class') return card(['Urban Sports Club',...fitnessResultRows(embed.content as FitnessResult),`/embed ${alias} · Open class`],width);
  const data = normalizeFitnessSearchContent(embed.content);
  const location = asText(data.filters.address || data.filters.city || data.query || 'Urban Sports');
  const state = data.status === 'processing' ? 'Searching for classes…' : data.status === 'error' ? 'Search failed. No verified results.' : data.status === 'cancelled' ? 'Search cancelled.' : `${data.resultCount} classes`;
  const chips = [data.filters.radius_km ? `${asText(data.filters.radius_km)} km` : '',data.filters.plan ? `Plan: ${asText(data.filters.plan)}` : '',asText(data.filters.attendance_mode)].filter(Boolean).join(' · ');
  return card([data.provider,'Search classes',location,state,...(data.status==='finished' ? [data.summary,...data.results.slice(0,2).map((result,index) => `${index+1}. ${getFitnessResultTitle(result)}${result.venue_name ? ` · ${result.venue_name}` : ''}`)] : []),chips,`/embed ${alias} · Open results`].filter(Boolean).map(row=>truncateCells(row,Math.max(1,width-4))),width);
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
