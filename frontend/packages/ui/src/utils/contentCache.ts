/**
 * Content Cache Utility
 * Caches processed TipTap JSON content to avoid redundant markdown parsing
 * Uses a simple LRU (Least Recently Used) strategy with a max size limit
 */

interface CacheEntry {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- TipTap JSON is intentionally schema-extensible at this cache boundary.
  content: any;
  timestamp: number;
}

interface ContentCacheOptions {
  maxSize?: number;
  maxAgeMs?: number;
}

function cloneContent<T>(content: T): T {
  if (typeof structuredClone === 'function') return structuredClone(content);
  return JSON.parse(JSON.stringify(content)) as T;
}

export class ContentCache {
  private cache: Map<string, CacheEntry> = new Map();
  private readonly maxSize: number;
  private readonly maxAgeMs: number;

  constructor({ maxSize = 100, maxAgeMs = 1000 * 60 * 5 }: ContentCacheOptions = {}) {
    this.maxSize = maxSize;
    this.maxAgeMs = maxAgeMs;
  }

  /**
   * Generate a cache key from content
   * Uses the exact semantic content to prevent shared-prefix collisions.
   */
  private generateKey(content: string): string {
    return content;
  }

  /**
   * Get cached content if available and not expired
   */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing dynamic TipTap cache API for heterogeneous node attributes.
  get(content: string): any | null {
    const key = this.generateKey(content);
    const entry = this.cache.get(key);

    if (!entry) {
      return null;
    }

    // Check if cache entry has expired
    if (Date.now() - entry.timestamp > this.maxAgeMs) {
      this.cache.delete(key);
      return null;
    }

    this.cache.delete(key);
    this.cache.set(key, entry);
    return cloneContent(entry.content);
  }

  /**
   * Store processed content in cache
   */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing dynamic TipTap cache API for heterogeneous node attributes.
  set(content: string, processedContent: any): void {
    const key = this.generateKey(content);

    // If cache is full, remove oldest entry
    if (this.cache.has(key)) this.cache.delete(key);
    if (this.cache.size >= this.maxSize) {
      const oldestKey = this.cache.keys().next().value;
      this.cache.delete(oldestKey);
    }

    this.cache.set(key, {
      content: cloneContent(processedContent),
      timestamp: Date.now()
    });
  }

  /**
   * Clear all cached content
   */
  clear(): void {
    this.cache.clear();
  }

  /**
   * Get cache statistics for debugging
   */
  getStats(): { size: number; maxSize: number } {
    return {
      size: this.cache.size,
      maxSize: this.maxSize
    };
  }
}

// Export singleton instance
export const contentCache = new ContentCache();
