import { getLucideIcon } from '../../utils/categoryUtils';
import type { Schema } from './workflowBuilder';

/** Pick a familiar field icon from schema semantics before falling back to its data type. */
export function workflowFieldIcon(name: string, schema: Schema) {
  const key = `${name} ${schema.title ?? ''}`.toLowerCase();

  if (schema.format?.includes('date') || /(^|[_\s-])date|day/.test(key)) return getLucideIcon('calendar-days');
  if (/timezone|time zone/.test(key)) return getLucideIcon('globe-2');
  if (schema.format === 'time' || /(^|[_\s-])time|duration|timezone/.test(key)) return getLucideIcon('clock');
  if (/repeat|frequency|schedule/.test(key)) return getLucideIcon('repeat-2');
  if (/location|city|country|address|origin|destination|departure|arrival|station|airport|latitude|longitude|\blat\b|\blon\b/.test(key)) return getLucideIcon('map-pin');
  if (/price|cost|fee|amount|currency|budget/.test(key)) return getLucideIcon('coins');
  if (/url|link|website/.test(key)) return getLucideIcon('link');
  if (/email/.test(key)) return getLucideIcon('mail');
  if (/warning|error/.test(key)) return getLucideIcon('triangle-alert');
  if (/provider|source/.test(key)) return getLucideIcon('building-2');
  if (/query|search|keyword/.test(key)) return getLucideIcon('search');
  if (/message|instruction|prompt|question/.test(key)) return getLucideIcon('message-square-text');
  if (/title|heading/.test(key)) return getLucideIcon('heading');
  if (/distance|route|connection|journey|trip/.test(key)) return getLucideIcon('route');
  if (/weather|temperature|forecast/.test(key)) return getLucideIcon('cloud-sun');
  if (/count|total|number|quantity/.test(key)) return getLucideIcon('hash');

  if (schema.type === 'boolean') return getLucideIcon('toggle-left');
  if (schema.type === 'array') return getLucideIcon('list');
  if (schema.type === 'object' || schema.properties) return getLucideIcon('braces');
  if (['integer', 'number'].includes(schema.type ?? '')) return getLucideIcon('hash');
  return getLucideIcon('type');
}
