/** Chat-local virtual result views. Uses cached embeds and never fetches in a renderer. */
import type { TuiState } from './tuiRenderer.js';
import { parseMessageSegments } from './messageSegments.js';
import { parseTuiMarkdown } from './tuiMarkdown.js';
import { buildTuiResultsViewData, renderTuiResultsViewLines, type TuiResultsViewDescriptor, type TuiResultsViewMode } from './tuiResultsViews.js';
import { aliasForEmbed, exampleEmbedMap } from './tuiEmbeds.js';
import { wrapCells, type TuiLine } from './tuiText.js';

export function messageResultsViews(content: string): TuiResultsViewDescriptor[] {
  return parseMessageSegments(content, {preserveCodeFences:true}).flatMap(segment => segment.type === 'text'
    ? parseTuiMarkdown(segment.value, 160).filter(block => block.type === 'results-view') : []);
}

/** Inline links and virtual sources need aliases/hydration, but are not preview cards. */
export function messageSupplementalEmbedIds(content: string): string[] {
  const ids = new Set<string>();
  for (const segment of parseMessageSegments(content, {preserveCodeFences:true})) {
    if (segment.type !== 'text') continue;
    for (const block of parseTuiMarkdown(segment.value, 160, {resolveEmbedAlias:id => {ids.add(id); return id;}})) {
      if (block.type === 'results-view') [...block.embeds, ...block.sources].forEach(id => ids.add(id.replace(/^embed:/, '')));
    }
  }
  return [...ids];
}

export function chatResultsViews(state: TuiState): TuiResultsViewDescriptor[] {
  const messages = state.activeExample && (state.screen === 'example' || state.embedOrigin?.screen === 'example' || state.resultsViewOrigin?.screen === 'example')
    ? state.activeExample.messages : state.messages;
  return messages.flatMap(message => messageResultsViews(message.content));
}

export function renderChatResultsView(state: TuiState, descriptor: TuiResultsViewDescriptor, key: number, width: number, mode?: TuiResultsViewMode): TuiLine[] {
  const data = buildTuiResultsViewData(descriptor, {...exampleEmbedMap(state), ...state.chatEmbeds});
  return renderTuiResultsViewLines(data, {viewKey:key, mode:mode ?? state.resultsViewModes[key], aliasForEmbed:id=>aliasForEmbed(state,id)})
    .flatMap((row,index) => wrapCells(row,width).map(text => index === 0 ? {text,bold:true,color:'#80caff'} : index === 1 && row.includes('/view') ? {text,color:'#85c9e8'} : text));
}
