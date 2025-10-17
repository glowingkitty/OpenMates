/**
 * Content Cache Utility
 * Caches processed TipTap JSON content to avoid redundant markdown parsing
 * Uses a simple LRU (Least Recently Used) strategy with a max size limit
 */

interface CacheEntry {
  content: any;
  timestamp: number;
}

class ContentCache {
  private cache: Map<string, CacheEntry> = new Map();
  private readonly MAX_SIZE = 100; // Maximum number of cached items
  private readonly MAX_AGE = 1000 * 60 * 5; // 5 minutes

  /**
   * Generate a cache key from content
   * Uses first 200 characters as key to balance uniqueness and performance
   */
  private generateKey(content: string): string {
    return content.substring(0, 200);
  }

  /**
   * Get cached content if available and not expired
   */
  get(content: string): any | null {
    const key = this.generateKey(content);
    const entry = this.cache.get(key);

    if (!entry) {
      return null;
    }

    // Check if cache entry has expired
    if (Date.now() - entry.timestamp > this.MAX_AGE) {
      this.cache.delete(key);
      return null;
    }

    return entry.content;
  }

  /**
   * Store processed content in cache
   */
  set(content: string, processedContent: any): void {
    const key = this.generateKey(content);

    // If cache is full, remove oldest entry
    if (this.cache.size >= this.MAX_SIZE) {
      const oldestKey = this.cache.keys().next().value;
      this.cache.delete(oldestKey);
    }

    this.cache.set(key, {
      content: processedContent,
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
      maxSize: this.MAX_SIZE
    };
  }
}

// Export singleton instance
export const contentCache = new ContentCache();
