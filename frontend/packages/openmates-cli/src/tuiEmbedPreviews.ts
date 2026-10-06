/** Text equivalents of the web embed details and its bottom basic-info bar. */
import type { DecryptedEmbed } from './client.js';
import {
  asNumber,
  asText,
  getFitnessResultAddress,
  getFitnessResultTitle,
  normalizeFitnessSearchContent,
  normalizeFitnessSkillId,
  normalizePipedList,
  type FitnessResult,
  type FitnessSkillId,
} from '../../ui/src/components/embeds/fitness/fitnessEmbedData.js';
import { padCells, terminalText, truncateCells, type TuiLine } from './tuiText.js';

export interface TuiEmbedPreviewOptions {
  /** Metadata from the reference may be available before the embed is hydrated. */
  appId?: string;
  skillId?: string;
  status?: string;
  /** A failed child fetch must not render its placeholder as a verified result. */
  unavailable?: boolean;
}

const BORDER = '#77717b';
const DETAIL = '#e6e6e6';
const SECONDARY = '#b5aeb8';
const BAR = '#302b34';

function readable(value: unknown): string {
  return terminalText(asText(value)).replace(/\s+/g, ' ').trim();
}

function prettyName(value: string): string {
  return value.replace(/[_-]+/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase());
}

function fitnessSkillName(skillId: FitnessSkillId): string {
  return skillId === 'search_locations' ? 'Search locations' : 'Search classes';
}

/** The final two inner rows form the shared basic-info bar for every embed. */
function card(details: string[], width: number, appName: string, skillName: string, alias: string): TuiLine[] {
  const cardWidth = Math.max(1, Math.min(62, Math.floor(width) || 1));
  const shortcut = `/embed ${readable(alias)}`;
  if (cardWidth < 6) return [truncateCells(shortcut, cardWidth)];
  const inner = cardWidth - 4;
  const row = (value: string, color = DETAIL, background?: string, bold = false): TuiLine => {
    const text = `│ ${padCells(value, inner)} │`;
    return { text, spans: [
      { text: '│ ', color: BORDER, background },
      { text: padCells(value, inner), color, background, bold },
      { text: ' │', color: BORDER, background },
    ] };
  };
  const lines: TuiLine[] = [{ text: `╭${'─'.repeat(cardWidth - 2)}╮`, color: BORDER }];
  for (const [index, detail] of details.filter(Boolean).entries()) {
    lines.push(row(truncateCells(detail, inner), index === 0 ? SECONDARY : DETAIL, undefined, index === 1));
  }
  // A full-width separator keeps the web preview's details above the basic-info bar.
  lines.push({ text: `├${'─'.repeat(cardWidth - 2)}┤`, color: BORDER });
  lines.push(row(truncateCells(`${appName} · ${skillName}`, inner), DETAIL, BAR, true));
  lines.push(row(truncateCells(shortcut, inner), SECONDARY, BAR));
  lines.push({ text: `╰${'─'.repeat(cardWidth - 2)}╯`, color: BORDER });
  return lines;
}

function fitnessSearchDetails(embed: DecryptedEmbed, skillId: FitnessSkillId, statusOverride?: string): string[] {
  const content = embed.content ?? {};
  const data = normalizeFitnessSearchContent({ ...content, skill_id: skillId,
    ...(statusOverride ? { status: statusOverride } : {}) }, skillId);
  const location = readable(data.filters.address || data.filters.city || data.query || 'Urban Sports');
  const details = [readable(data.provider), fitnessSkillName(skillId), location];
  if (data.status === 'finished') {
    details.push(`${data.resultCount} ${skillId === 'search_locations' ? 'locations' : 'classes'}`);
    if (data.summary) details.push(readable(data.summary));
    for (const result of data.results.slice(0, 2)) {
      if (!result || typeof result !== 'object' || result._tuiUnavailable) continue;
      details.push(readable(getFitnessResultTitle(result)));
      if (result.venue_name) details.push(readable(result.venue_name));
    }
  } else {
    details.push(data.status === 'error' ? 'Search failed.' :
      data.status === 'cancelled' ? 'Search cancelled.' : 'Searching Urban Sports Club...');
  }
  const chips = [
    data.filters.radius_km ? `${readable(data.filters.radius_km)} km` : '',
    data.filters.plan ? `Plan: ${readable(data.filters.plan)}` : '',
    readable(data.filters.attendance_mode),
  ].filter(Boolean);
  if (chips.length) details.push(chips.join(' · '));
  return details;
}

function fitnessResultDetails(result: FitnessResult, skillId: FitnessSkillId, unavailable: boolean): string[] {
  if (unavailable || result._tuiUnavailable) return ['Class details unavailable'];
  const subtitle = skillId === 'search_classes'
    ? [result.date, result.time_range, result.venue_name].map(readable).filter(Boolean).join(' · ')
    : readable(getFitnessResultAddress(result));
  const distance = asNumber(result.distance_km);
  const meta = [
    distance === undefined ? '' : `${distance.toFixed(2)} km`,
    readable(result.spots_display),
    normalizePipedList(result.disciplines).slice(0, 2).map(readable).join(', '),
    normalizePipedList(result.plans_required).map(readable).join(', '),
  ].filter(Boolean);
  return [subtitle, meta.join(' · ')].filter(Boolean);
}

/** Render a single compact card; carousel selection and height alignment live with the caller. */
export function renderTuiEmbedPreview(
  embed: DecryptedEmbed, width: number, alias: string, options: TuiEmbedPreviewOptions = {},
): TuiLine[] {
  const content = embed.content ?? {};
  const appId = readable(options.appId || embed.appId || content.app_id || (embed.type==='fitness-class'?'fitness':''));
  const skillId = readable(options.skillId || embed.skillId || content.skill_id);
  if (appId === 'fitness' && (skillId === 'search_classes' || skillId === 'search_locations' || embed.type === 'fitness-class')) {
    const fitnessSkill = normalizeFitnessSkillId(skillId || content.skill_id);
    if (embed.type === 'fitness-class') {
      const result = content as FitnessResult;
      const title = readable(getFitnessResultTitle(result));
      return card(fitnessResultDetails(result, fitnessSkill, Boolean(options.unavailable)), width,
        'Fitness', options.unavailable || result._tuiUnavailable ? fitnessSkillName(fitnessSkill) : title, alias);
    }
    return card(fitnessSearchDetails(embed, fitnessSkill, options.status), width,
      'Fitness', fitnessSkillName(fitnessSkill), alias);
  }

  const appName = prettyName(appId || 'Embed');
  const skillName = prettyName(skillId || embed.type || 'View');
  const title = readable(content.title || content.name || content.query || embed.textPreview);
  const summary = readable(content.summary || content.description);
  const status = readable(options.status || content.status);
  const details = [title, summary && summary !== title ? summary : '', status && status !== 'finished' ? prettyName(status) : ''].filter(Boolean);
  return card(details, width, appName, skillName, alias);
}
