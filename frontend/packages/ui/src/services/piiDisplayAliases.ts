/** Presentation only: aliases never replace canonical message/mapping tokens. */
import type { PIIMapping } from '../types/chat';

// Enhanced browser detections use a 16-hex nonce, with an optional send-collision
// counter/UUID. Existing regex suffixes and user labels keep their exact spelling.
const enhancedToken = /^\[([A-Z][A-Z0-9_]*?)_[1-9][0-9]*_[0-9a-f]{16}(?:_[1-9][0-9]*_[0-9a-f]{32})*\]$/;

function sourceStrings(value: unknown): string[] {
  if (typeof value === 'string') return [value];
  if (Array.isArray(value)) return value.flatMap(sourceStrings);
  if (value && typeof value === 'object') return Object.values(value).flatMap(sourceStrings);
  return [];
}

export function createPIIDisplayAliases(
  sourceContent: string | Record<string, unknown> | null,
  mappings: readonly PIIMapping[],
  configuredReplacements: readonly string[] = [],
): ReadonlyMap<string, string> {
  // Preserve actual text-node strings: JSON serialization escapes quotes/newlines
  // in restored originals and would miss those values in structured messages.
  const source = sourceStrings(sourceContent).join('\n');
  const aliases = new Map<string, string>();
  const reserved = new Set(Array.from(source.matchAll(/\[[^[\]\r\n]+\]/g), match => match[0]));
  for (const value of configuredReplacements) {
    if (value) reserved.add(value.startsWith('[') ? value : `[${value}]`);
  }
  for (const mapping of mappings) reserved.add(mapping.placeholder);
  const configured = new Set(configuredReplacements.map(value => value.startsWith('[') ? value : `[${value}]`));
  const candidates = mappings.flatMap(mapping => {
    const match = enhancedToken.exec(mapping.placeholder);
    if (!match || match[1] !== mapping.type || configured.has(mapping.placeholder)) return [];
    const tokenIndex = source.indexOf(mapping.placeholder);
    const originalIndex = mapping.original ? source.indexOf(mapping.original) : -1;
    const index = tokenIndex >= 0 ? tokenIndex : originalIndex;
    return index < 0 ? [] : [{ placeholder: mapping.placeholder, type: match[1], index }];
  }).sort((a, b) => a.index - b.index);
  const counters = new Map<string, number>();
  for (const { placeholder, type } of candidates) {
    if (aliases.has(placeholder)) continue;
    let counter = counters.get(type) ?? 0;
    let alias: string;
    do { alias = `[${type}_${++counter}]`; } while (reserved.has(alias));
    counters.set(type, counter);
    reserved.add(alias);
    aliases.set(placeholder, alias);
  }
  return aliases;
}
