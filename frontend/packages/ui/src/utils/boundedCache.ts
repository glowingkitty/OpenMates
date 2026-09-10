// Byte-budgeted LRU for recoverable browser data.
// Budgets estimate retained payload, not the browser's total heap allocation.
// Values that exist only in memory stay pinned until persistence succeeds.
// Identity checks prevent an older transaction from unpinning a newer update.
// Active consumers keep their own references when a cache entry is evicted.
// Architecture: docs/architecture/web-memory-lifetimes.md

export function estimatePayloadBytes(value: unknown, limit = Infinity): number {
  const seen = new WeakSet<object>();
  let bytes = 0;
  function visit(item: unknown): void {
    if (bytes > limit || item == null) return;
    if (typeof item === 'string') { bytes += item.length * 2; return; }
    if (typeof item !== 'object') { bytes += 8; return; }
    if (seen.has(item)) return;
    seen.add(item);
    if (ArrayBuffer.isView(item)) { bytes += item.byteLength; return; }
    if (item instanceof ArrayBuffer) { bytes += item.byteLength; return; }
    bytes += 32;
    for (const key in item) {
      if (!Object.prototype.hasOwnProperty.call(item, key)) continue;
      bytes += key.length * 2;
      visit((item as Record<string, unknown>)[key]);
      if (bytes > limit) break;
    }
  }
  visit(value);
  return bytes;
}

export class BoundedCache<K, V> extends Map<K, V> {
  private weights = new Map<K, number>();
  private pinned = new Set<K>();
  private bytes = 0;

  constructor(private readonly maxBytes: number, private readonly maxEntries: number) { super(); }

  override get(key: K): V | undefined {
    const value = super.get(key);
    if (super.has(key)) { super.delete(key); super.set(key, value!); }
    return value;
  }

  override set(key: K, value: V): this {
    this.bytes -= this.weights.get(key) ?? 0;
    const weight = estimatePayloadBytes(value, this.maxBytes) + estimatePayloadBytes(key);
    this.weights.set(key, weight);
    this.bytes += weight;
    super.delete(key);
    super.set(key, value);
    this.trim();
    return this;
  }

  setPinned(key: K, value: V): this { this.pinned.add(key); return this.set(key, value); }

  markPersisted(key: K, value: V): void {
    if (super.get(key) !== value) return;
    this.pinned.delete(key);
    this.trim();
  }

  private trim(): void {
    for (const key of Array.from(this.keys())) {
      if (this.bytes <= this.maxBytes && this.size <= this.maxEntries) break;
      if (!this.pinned.has(key)) this.delete(key);
    }
  }

  override delete(key: K): boolean {
    this.bytes -= this.weights.get(key) ?? 0;
    this.weights.delete(key);
    this.pinned.delete(key);
    return super.delete(key);
  }

  override clear(): void {
    super.clear(); this.weights.clear(); this.pinned.clear(); this.bytes = 0;
  }
}
