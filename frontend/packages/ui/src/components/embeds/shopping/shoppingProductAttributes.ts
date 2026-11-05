/** Combine admitted named specifications with legacy attribute dictionaries. */
export function shoppingProductAttributes(attributes: unknown, specifications: unknown): Record<string, unknown> | undefined {
  const legacy = attributes && typeof attributes === 'object' && !Array.isArray(attributes) ? attributes as Record<string, unknown> : {};
  const pairs: [string, unknown][] = [];
  if (Array.isArray(specifications)) for (const item of specifications) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue;
    const {name, value} = item as Record<string, unknown>;
    if (typeof name !== 'string' || !name.trim() || value == null || value === '') continue;
    if (!['string', 'number', 'boolean'].includes(typeof value)) continue;
    pairs.push([name.trim(), value]);
  }
  const result = {...Object.fromEntries(pairs), ...legacy};
  return Object.keys(result).length ? result : undefined;
}
