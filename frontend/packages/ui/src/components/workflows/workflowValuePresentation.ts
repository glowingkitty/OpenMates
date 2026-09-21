import type { Schema } from './workflowBuilder';

const internalFields = new Set(['id', 'type', 'hash', 'source_id', 'embed_id', 'embed_ids', 'delivery_id', 'message_id', 'run_id', 'workflow_id', 'node_id', 'task_id', 'app_id', 'skill_id', 'canonical_url', 'dispatches', 'output_schema', 'input_schema', 'usage', 'raw', 'debug', 'metadata', 'provider_metadata', 'error', 'errors', 'error_summary', 'query_id', 'request_id']);
const resultAliases = new Set(['articles', 'events', 'listings']);
export const valueLabel = (key: string): string => key.replace(/_/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase());

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
  return Object.entries(data).filter(([key]) => !internalFields.has(key) && !key.startsWith('_') && !key.startsWith('encrypted_') && !key.startsWith('hashed_') && !(Array.isArray(data.results) && resultAliases.has(key)));
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
