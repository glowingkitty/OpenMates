/** Text equivalents of the web embed details and its bottom basic-info bar. */
import type { DecryptedEmbed } from './client.js';
import { APP_GRADIENTS, PRIMARY_GRADIENT } from '../../appGradientTheme.js';
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
import { padCells, terminalText, truncateCells, wrapCells, type TuiLine } from './tuiText.js';

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

/** Use a single web app color, with readable text even for bright app colors. */
function appColors(appId: string): { background: string; foreground: string } {
  const background = APP_GRADIENTS[appId]?.start ?? PRIMARY_GRADIENT.start;
  const [r, g, b] = [1, 3, 5].map(index => {
    const channel = parseInt(background.slice(index, index + 2), 16) / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  // Fixed black/white on brand colors keeps at least 4.5:1 contrast for every app.
  return { background, foreground: 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.179 ? '#000000' : '#ffffff' };
}

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
function card(details: string[], width: number, appName: string, skillName: string, alias: string,
  appId: string, emphasizeSecond = true): TuiLine[] {
  const cardWidth = Math.max(1, Math.min(62, Math.floor(width) || 1));
  const shortcut = `/embed ${readable(alias)}`;
  if (cardWidth < 6) return [truncateCells(shortcut, cardWidth)];
  const inner = cardWidth - 4;
  const colors = appColors(appId);
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
    lines.push(row(truncateCells(detail, inner), index === 0 ? SECONDARY : DETAIL, undefined, emphasizeSecond && index === 1));
  }
  // A full-width separator keeps the web preview's details above the basic-info bar.
  lines.push({ text: `├${'─'.repeat(cardWidth - 2)}┤`, color: BORDER });
  lines.push(row(truncateCells(`${appName} · ${skillName}`, inner), colors.foreground, colors.background, true));
  lines.push(row(truncateCells(shortcut, inner), colors.foreground, colors.background));
  lines.push({ text: `╰${'─'.repeat(cardWidth - 2)}╯`, color: BORDER });
  return lines;
}

/** Recording payloads store flat transcript fields, exactly as the web preview does. */
function recordingDetails(content: Record<string, unknown>, title: string, width: number, status: string): string[] {
  if (status === 'error' || status === 'cancelled') {
    return [title, status === 'error' ? 'Recording failed.' : 'Recording cancelled.'];
  }
  const original = typeof content.transcript_original === 'string' ? content.transcript_original : undefined;
  const corrected = typeof content.transcript_corrected === 'string' ? content.transcript_corrected : undefined;
  const transcript = typeof content.transcript === 'string' ? content.transcript : undefined;
  const active = original && corrected ? content.use_corrected === false ? original : corrected
    : transcript ?? corrected ?? original ?? (typeof content.text === 'string' ? content.text : '');
  const clean = readable(active);
  const characters = [...clean];
  const shortened = characters.length > 120 ? characters.slice(0, 119).join('') + '…' : clean;
  const inner = Math.max(1, Math.min(62, Math.floor(width) || 1) - 4);
  const statusText = status && status !== 'finished' ? prettyName(status) + '…' : '';
  return [title || 'Audio recording', ...(shortened ? wrapCells(shortened, inner) :
    [statusText || 'No transcript available.']), ...(shortened && statusText ? [statusText] : [])];
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
  const recording = embed.type === 'audio-recording' || embed.type === 'recording' || content.type === 'audio-recording';
  const appId = readable(options.appId || embed.appId || content.app_id ||
    (embed.type==='fitness-class'?'fitness':recording?'audio':'')).toLowerCase();
  const skillId = readable(options.skillId || embed.skillId || content.skill_id || (recording ? 'transcribe' : ''));
  if (appId === 'fitness' && (skillId === 'search_classes' || skillId === 'search_locations' || embed.type === 'fitness-class')) {
    const fitnessSkill = normalizeFitnessSkillId(skillId || content.skill_id);
    if (embed.type === 'fitness-class') {
      const result = content as FitnessResult;
      const title = readable(getFitnessResultTitle(result));
      return card(fitnessResultDetails(result, fitnessSkill, Boolean(options.unavailable)), width,
        'Fitness', options.unavailable || result._tuiUnavailable ? fitnessSkillName(fitnessSkill) : title, alias, appId);
    }
    return card(fitnessSearchDetails(embed, fitnessSkill, options.status), width,
      'Fitness', fitnessSkillName(fitnessSkill), alias, appId);
  }

  const appName = prettyName(appId || 'Embed');
  const skillName = prettyName(skillId || embed.type || 'View');
  const title = readable(content.title || content.name || content.query || embed.textPreview);
  const summary = readable(content.summary || content.description);
  const status = readable(options.status || content.status);
  if (recording || (appId === 'audio' && skillId === 'transcribe')) {
    return card(recordingDetails(content, title, width, status), width, appName, skillName, alias, appId, false);
  }
  const details = [title, summary && summary !== title ? summary : '', status && status !== 'finished' ? prettyName(status) : ''].filter(Boolean);
  return card(details, width, appName, skillName, alias, appId);
}
