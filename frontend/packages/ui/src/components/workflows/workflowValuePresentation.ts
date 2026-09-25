import type { Schema } from './workflowBuilder';

const internalFields = new Set(['id', 'type', 'hash', 'source_id', 'embed_id', 'embed_ids', 'delivery_id', 'message_id', 'run_id', 'workflow_id', 'node_id', 'task_id', 'app_id', 'skill_id', 'canonical_url', 'dispatches', 'output_schema', 'input_schema', 'usage', 'raw', 'debug', 'metadata', 'provider_metadata', 'error', 'errors', 'error_summary', 'query_id', 'request_id']);
const diagnosticFields = new Set(['summary', 'warning', 'warnings', 'partial', 'is_partial', 'status']);
const resultAliases = new Set(['articles', 'events', 'listings']);
const preferredFields = /^(results?|answer|text|content|result_count|count|title|name|date_start|start(?:_time|_date)?|location|address|url|link|value|matched|forecast|forecast_day|forecast_days|temperature|rain_probability|rain_expected|rain_periods|rain_summary|max_temperature_c|min_temperature_c|condition)$/;
export const valueLabel = (key: string): string => key.replace(/_/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase());

export type PresentedFields = { basic: [string, Schema][]; advanced: [string, Schema][] };

export function hiddenWorkflowField(key: string, schema?: Schema): boolean {
  return schema?.['x-ui']?.hidden === true || internalFields.has(key) || diagnosticFields.has(key)
    || key.startsWith('_') || key.startsWith('encrypted_') || key.startsWith('hashed_')
    || key.endsWith('_id') || key.endsWith('_ids');
}

function hiddenReadableValueField(key: string): boolean {
  return internalFields.has(key) || key.startsWith('_') || key.startsWith('encrypted_') || key.startsWith('hashed_');
}

/** Keep workflow authoring focused while letting schemas explicitly override the fallback. */
export function presentedFields(properties: Record<string, Schema>, maxBasic = 4): PresentedFields {
  const eligible = Object.entries(properties).filter(([key, schema]) => !hiddenWorkflowField(key, schema) && !(properties.results && resultAliases.has(key)));
  const explicitBasic = eligible.filter(([, schema]) => schema['x-ui']?.basic === true);
  const hasExplicitSelection = eligible.some(([, schema]) => schema['x-ui']?.basic !== undefined);
  const unspecified = eligible.filter(([, schema]) => schema['x-ui']?.basic === undefined);
  const preferred = unspecified.filter(([key]) => preferredFields.test(key));
  const fallback = unspecified.filter(([key]) => !preferredFields.test(key));
  const prioritized = [...explicitBasic, ...preferred];
  const basic = hasExplicitSelection ? explicitBasic : (prioritized.length ? prioritized : fallback).slice(0, maxBasic);
  const basicKeys = new Set(basic.map(([key]) => key));
  return { basic, advanced: eligible.filter(([key]) => !basicKeys.has(key)) };
}

export function presentedItems<T extends { reference: string; schema: Schema }>(items: T[]): { basic: T[]; advanced: T[] } {
  const pathFor = (item: T): string[] => (item.reference.split('.output.')[1] ?? item.reference).split('.').filter(Boolean);
  const last = (parts: string[]): string | undefined => parts[parts.length - 1];
  const eligible = items.filter(item => {
    const key = last(pathFor(item)) ?? item.reference;
    return !hiddenWorkflowField(key, item.schema);
  });
  const byNode = new Map<string, T[]>();
  for (const item of eligible) {
    const path = pathFor(item);
    const group = `${item.reference.split('.output.')[0]}.${path.slice(0, -1).join('.')}`;
    byNode.set(group, [...(byNode.get(group) ?? []), item]);
  }
  const basic: T[] = [];
  const advanced: T[] = [];
  for (const group of Array.from(byNode.values())) {
    const properties = Object.fromEntries(group.map(item => [last(pathFor(item)) ?? item.reference, item.schema]));
    const shown = new Set(presentedFields(properties).basic.map(([key]) => key));
    for (const item of group) (shown.has(last(pathFor(item)) ?? item.reference) ? basic : advanced).push(item);
  }
  return { basic, advanced };
}

export function workflowValue(value: unknown): unknown {
  if (value && typeof value === 'object' && !Array.isArray(value) && '$date' in value) return valueLabel(String((value as Record<string, unknown>).$date));
  if (typeof value !== 'string') return value;
  const trimmed = value.trim();
  const candidate = trimmed.replace(/^```(?:json)?\s*\n?/i, '').replace(/\n?```$/, '');
  if (candidate.startsWith('[') || candidate.startsWith('{')) {
    try { return JSON.parse(candidate); } catch { /* Ordinary authored text stays text. */ }
  }
  return value.replace(/```json\s*([\s\S]*?)```/gi, (_, json: string) => {
    try {
      const parsed = JSON.parse(json);
      if (parsed && typeof parsed === 'object' && 'embed_id' in parsed) return '';
      return readableValue(parsed);
    } catch { return ''; }
  }).trim();
}

function readableValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(readableValue).join('\n');
  if (value && typeof value === 'object') return valueEntries(value).map(([key, item]) => `${valueLabel(key)}: ${readableValue(item)}`).join('\n');
  return value == null ? '' : String(value);
}

export function valueEntries(value: unknown): [string, unknown][] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
  const data = value as Record<string, unknown>;
  return Object.entries(data).filter(([key]) => !hiddenReadableValueField(key) && !(Array.isArray(data.results) && resultAliases.has(key)));
}

export function outputFields(properties: Record<string, Schema>): [string, Schema][] {
  return Object.entries(properties).filter(([key]) => !internalFields.has(key) && !(properties.results && resultAliases.has(key)));
}

export function valueType(schema?: Schema, value?: unknown): string {
  const type = schema?.type;
  if (schema?.format === 'date' || schema?.format === 'date-time') return 'date';
  if (type === 'array' || Array.isArray(value)) return 'list';
  if (type === 'object' || (value !== null && typeof value === 'object')) return 'object';
  if (type === 'boolean' || typeof value === 'boolean') return 'boolean';
  if (type === 'number' || type === 'integer' || typeof value === 'number') return 'number';
  return 'text';
}

export function readableScalar(value: unknown, key = ''): string {
  if (typeof value === 'number') return new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(value);
  if (typeof value !== 'string') return '';
  if (/^\$nodes\.[^.]+\.output\./.test(value)) return value.replace(/^\$nodes\.([^.]+)\.output\.(.*)$/, (_, node: string, field: string) => `${valueLabel(node)} · ${valueLabel(field.replace(/\./g, ' '))}`);
  if (/^\d{4}-\d{2}-\d{2}(T.*)?$/.test(value) && /date|time|start|end|published|available/i.test(key)) {
    const date = new Date(value);
    if (!Number.isNaN(date.getTime())) return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', ...(value.includes('T') ? { timeStyle: 'short' as const } : {}) }).format(date);
  }
  return value.replace(/\{\{\s*steps\.([^.]+)\.([^{}]+?)\s*\}\}/g, (_, node: string, field: string) => `${valueLabel(node)} · ${valueLabel(field.replace(/\./g, ' '))}`);
}

/** Build a readable example from declared field examples without inventing values. */
export function exampleValue(schema: Schema, depth = 0): unknown {
  if (schema.example !== undefined) return schema.example;
  if (schema.examples?.length) return schema.examples[0];
  if (schema.default !== undefined) return schema.default;
  if (depth >= 8) return undefined;
  if (schema.type === 'object' && schema.properties) {
    const entries = Object.entries(schema.properties).map(([key, child]) => [key, exampleValue(child, depth + 1)] as const).filter(([, value]) => value !== undefined);
    return entries.length ? Object.fromEntries(entries) : undefined;
  }
  if (schema.type === 'array' && schema.items) {
    const item = exampleValue(schema.items, depth + 1);
    return item === undefined ? undefined : [item];
  }
  return undefined;
}
