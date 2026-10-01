import type { Schema } from '../workflows/workflowBuilder';

export type SkillSchema = Schema & {
  $ref?: string;
  $defs?: Record<string, SkillSchema>;
  definitions?: Record<string, SkillSchema>;
  oneOf?: SkillSchema[];
  anyOf?: SkillSchema[];
  minLength?: number;
  maxLength?: number;
  minItems?: number;
  maxItems?: number;
  pattern?: string;
};

const object = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const own = (value: object, key: string) => Object.prototype.hasOwnProperty.call(value, key);
const pathParts = (path: string) => path.split('.').filter(Boolean).map(part => part.endsWith('[]') ? part.slice(0, -2) : part);

export function resolveSkillSchema(schema: SkillSchema, root: SkillSchema, seen = new Set<string>()): SkillSchema {
  if (schema.$ref) {
    const reference = schema.$ref;
    if (!reference.startsWith('#/') || seen.has(reference)) return schema;
    const resolved = reference.slice(2).split('/').reduce<unknown>((value, part) => object(value)[part.replace(/~1/g, '/').replace(/~0/g, '~')], root);
    if (!resolved || typeof resolved !== 'object') return schema;
    return resolveSkillSchema({ ...(resolved as SkillSchema), ...schema, $ref: undefined }, root, new Set([...Array.from(seen), reference]));
  }
  const variants = schema.anyOf ?? schema.oneOf;
  if (variants?.length) {
    const nonNull = variants.filter(part => part.type !== 'null');
    if (nonNull.length === 1) return { ...resolveSkillSchema(nonNull[0], root, seen), ...schema, anyOf: undefined, oneOf: undefined };
  }
  return schema;
}

/** Metadata paths use [] for request-array items. The first item is edited by default. */
export function getSkillPath(input: Record<string, unknown>, path: string): unknown {
  let cursor: unknown = input;
  for (const part of path.split('.').filter(Boolean)) {
    cursor = object(cursor)[part.replace(/\[\]$/, '')];
    if (part.endsWith('[]')) cursor = Array.isArray(cursor) ? cursor[0] : undefined;
  }
  return cursor;
}

export function setSkillPath(input: Record<string, unknown>, path: string, value: unknown): Record<string, unknown> {
  const parts = path.split('.').filter(Boolean);
  function update(current: unknown, index: number): unknown {
    if (index === parts.length) return value;
    const part = parts[index];
    const key = part.replace(/\[\]$/, '');
    const parent = { ...object(current) };
    if (part.endsWith('[]')) {
      const entries = Array.isArray(parent[key]) ? [...parent[key] as unknown[]] : [];
      entries[0] = update(entries[0], index + 1);
      parent[key] = entries;
    } else parent[key] = update(parent[key], index + 1);
    return parent;
  }
  return update(input, 0) as Record<string, unknown>;
}

/** Project a JSON schema to exactly the selected paths while keeping its structure. */
export function selectSkillSchema(schema: SkillSchema, paths: string[], root: SkillSchema = schema, prefix = ''): SkillSchema | null {
  const selected = paths.some(path => path === prefix && Boolean(prefix));
  if (selected) return resolveSkillSchema(schema, root);
  const resolved = resolveSkillSchema(schema, root);
  if (resolved.type === 'array') {
    const items = selectSkillSchema(resolved.items as SkillSchema ?? {}, paths, root, `${prefix}[]`);
    return items ? { ...resolved, items } : null;
  }
  if (resolved.type === 'object' || resolved.properties) {
    const properties = Object.fromEntries(Object.entries(resolved.properties ?? {}).flatMap(([key, child]) => {
      const next = selectSkillSchema(child as SkillSchema, paths, root, prefix ? `${prefix}.${key}` : key);
      return next ? [[key, next]] : [];
    }));
    return Object.keys(properties).length ? { ...resolved, properties, required: (resolved.required ?? []).filter(key => own(properties, key)) } : null;
  }
  return null;
}

export function skillLeafPaths(schema: SkillSchema, root: SkillSchema = schema, prefix = ''): string[] {
  const resolved = resolveSkillSchema(schema, root);
  if (resolved.type === 'array' && resolved.items) return skillLeafPaths(resolved.items as SkillSchema, root, `${prefix}[]`);
  if (resolved.properties) return Object.entries(resolved.properties).flatMap(([key, child]) => skillLeafPaths(child as SkillSchema, root, prefix ? `${prefix}.${key}` : key));
  return prefix ? [prefix] : [];
}

export function remainingSkillPaths(schema: SkillSchema, primary: string[]): string[] {
  return skillLeafPaths(schema).filter(path => !primary.some(parent => path === parent || path.startsWith(`${parent}.`) || path.startsWith(`${parent}[].`)));
}

/** A declared date range consumes two schema paths but renders as one control. */
export function expandCompositeSkillPaths(schema: SkillSchema, primary: string[]): string[] {
  const expanded = new Set(primary);
  for (const path of primary) {
    const parentPath = path.includes('.') ? path.slice(0, path.lastIndexOf('.')) : '';
    const fieldName = path.slice(path.lastIndexOf('.') + 1);
    const parent = parentPath ? schemaForPath(schema, parentPath) : schema;
    const ui = parent?.['x-ui'];
    if (ui?.control !== 'date-range') continue;
    const start = ui.start_field ?? 'start_date';
    const end = ui.end_field ?? 'end_date';
    if (fieldName !== start && fieldName !== end) continue;
    const partner = fieldName === start ? end : start;
    if (parent?.properties?.[partner]) expanded.add(parentPath ? `${parentPath}.${partner}` : partner);
  }
  return Array.from(expanded);
}

/** Convert existing workflow date-picker tokens to literal direct REST input. */
export function prepareSkillInput(schema: SkillSchema, input: Record<string, unknown>, timezone: string, now = new Date()): Record<string, unknown> {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
  const part = (name: 'year' | 'month' | 'day') => Number(parts.find(item => item.type === name)?.value);
  const today = Math.floor(Date.UTC(part('year'), part('month') - 1, part('day')) / 86_400_000);
  const isoDate = (ordinal: number) => new Date(ordinal * 86_400_000).toISOString().slice(0, 10);

  function walk(node: SkillSchema, value: unknown): unknown {
    const resolved = resolveSkillSchema(node, schema);
    const token = object(value).$date;
    if (typeof token === 'string') {
      const weekday = (new Date(today * 86_400_000).getUTCDay() + 6) % 7;
      const ordinal = token === 'today' || token === 'today_end' || token === 'next_seven_days_start' ? today
        : token === 'next_seven_days_end' ? today + 6
          : token === 'next_week_start' ? today + 7 - weekday
            : token === 'next_week_end' ? today + 13 - weekday : null;
      if (ordinal === null) return value;
      const date = isoDate(ordinal);
      return object(value).format === 'datetime' || resolved.format === 'date-time'
        ? `${date}T${token.endsWith('_end') ? '23:59:59' : '00:00:00'}[${timezone}]`
        : date;
    }
    if (resolved.type === 'array' && Array.isArray(value)) return value.map(item => walk(resolved.items as SkillSchema ?? {}, item));
    if ((resolved.type === 'object' || resolved.properties) && value && typeof value === 'object' && !Array.isArray(value)) {
      const prepared = { ...object(value) };
      for (const [name, child] of Object.entries(resolved.properties ?? {})) {
        if (own(prepared, name)) prepared[name] = walk(child as SkillSchema, prepared[name]);
      }
      const ui = resolved['x-ui'];
      const start = ui?.start_field ?? 'start_date';
      const end = ui?.end_field ?? 'end_date';
      if (ui?.control === 'date-range' && prepared[start] && prepared[end] && resolved.properties?.days?.['x-ui']?.hidden) delete prepared.days;
      return prepared;
    }
    return value;
  }
  return walk(schema, input) as Record<string, unknown>;
}

export type SkillValidationIssue = { path: string; code: 'required' | 'type' | 'minimum' | 'maximum' | 'minLength' | 'maxLength' | 'minItems' | 'maxItems' | 'enum' | 'pattern' };

/** Validate user edits before dispatch; backend remains the authoritative validator. */
export function validateSkillInput(schema: SkillSchema, input: unknown): SkillValidationIssue[] {
  const issues: SkillValidationIssue[] = [];
  function walk(node: SkillSchema, value: unknown, path: string, required: boolean): void {
    const field = resolveSkillSchema(node, schema);
    if (value === null) {
      const nullable = node.type === 'null' || (node.anyOf ?? node.oneOf)?.some(part => part.type === 'null');
      if (!nullable) issues.push({ path, code: required ? 'required' : 'type' });
      return;
    }
    if (value === undefined || value === '') {
      if (required) issues.push({ path, code: 'required' });
      return;
    }
    if (field.enum && !field.enum.some(item => item === value)) issues.push({ path, code: 'enum' });
    if (field.type === 'object' || field.properties) {
      if (!value || typeof value !== 'object' || Array.isArray(value)) { issues.push({ path, code: 'type' }); return; }
      for (const [name, child] of Object.entries(field.properties ?? {})) walk(child as SkillSchema, object(value)[name], path ? `${path}.${name}` : name, (field.required ?? []).includes(name));
    } else if (field.type === 'array') {
      if (!Array.isArray(value)) { issues.push({ path, code: 'type' }); return; }
      if (field.minItems !== undefined && value.length < field.minItems) issues.push({ path, code: 'minItems' });
      if (field.maxItems !== undefined && value.length > field.maxItems) issues.push({ path, code: 'maxItems' });
      value.forEach((item, index) => walk(field.items as SkillSchema ?? {}, item, `${path}[${index}]`, true));
    } else if (field.type === 'integer' || field.type === 'number') {
      if (typeof value !== 'number' || !Number.isFinite(value) || (field.type === 'integer' && !Number.isInteger(value))) { issues.push({ path, code: 'type' }); return; }
      if (field.minimum !== undefined && value < field.minimum) issues.push({ path, code: 'minimum' });
      if (field.maximum !== undefined && value > field.maximum) issues.push({ path, code: 'maximum' });
    } else if (field.type === 'boolean') {
      if (typeof value !== 'boolean') issues.push({ path, code: 'type' });
    } else if (field.type === 'string' || !field.type) {
      if (typeof value !== 'string') { issues.push({ path, code: 'type' }); return; }
      if (field.minLength !== undefined && value.length < field.minLength) issues.push({ path, code: 'minLength' });
      if (field.maxLength !== undefined && value.length > field.maxLength) issues.push({ path, code: 'maxLength' });
      if (field.pattern) {
        try { if (!new RegExp(field.pattern).test(value)) issues.push({ path, code: 'pattern' }); } catch { /* malformed metadata is rejected server-side */ }
      }
    }
  }
  walk(schema, input, '', true);
  return issues;
}

export function schemaForPath(schema: SkillSchema, path: string): SkillSchema | null {
  let current = schema;
  for (const part of pathParts(path)) {
    const resolved = resolveSkillSchema(current, schema);
    current = resolved.properties?.[part] as SkillSchema;
    if (!current) return null;
    if (path.includes(`${part}[]`)) current = resolveSkillSchema(current, schema).items as SkillSchema ?? current;
  }
  return resolveSkillSchema(current, schema);
}

/** Suppress workflow-specific per-object basic/advanced toggles; Apps owns one settings toggle. */
export function showAllSkillSchema(schema: SkillSchema, root: SkillSchema = schema, depth = 0): SkillSchema {
  // Runtime schemas use local references for reusable request objects. Bound
  // recursive references so a circular definition cannot recurse during render.
  const resolved = depth < 12 ? resolveSkillSchema(schema, root) : { type: 'string', title: schema.title } as SkillSchema;
  return {
    ...resolved,
    'x-ui': { ...resolved['x-ui'], basic: true },
    ...(resolved.properties ? { properties: Object.fromEntries(Object.entries(resolved.properties).map(([key, child]) => [key, showAllSkillSchema(child as SkillSchema, root, depth + 1)])) } : {}),
    ...(resolved.items ? { items: showAllSkillSchema(resolved.items as SkillSchema, root, depth + 1) } : {}),
  };
}
