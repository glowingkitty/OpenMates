/**
 * Mention result scoring and ranking (pure, import-free so the parity-vector
 * generator can load it directly under Node type stripping).
 *
 * The shared Rust core Worker `composer` unit mirrors `rankMentionResults`
 * (packages/openmates-rust/src/web_composer/mentions.rs); suggestionVectors.test.ts
 * keeps the committed TS-generated vectors in sync with this file.
 */

/** Score boost for settings/memory categories and entries when the query matches. */
const SETTINGS_MEMORY_SCORE_BOOST = 30;
const PROJECT_MENTION_SCORE_BOOST = 40;

export interface RankableMention {
  searchTerms: string[];
  type?: string;
  score?: number;
}

/**
 * Calculate match score for a search query against terms.
 * Higher score = better match.
 * Settings/memory results get a small boost when they match so they can compete with models/skills.
 */
export function calculateMatchScore(query: string, terms: string[], type?: string): number {
  if (!query) return 1; // No query = all results are equal

  const queryLower = query.toLowerCase();
  let score = 0;

  for (const term of terms) {
    if (term === queryLower) {
      score += 100; // Exact match
    } else if (term.startsWith(queryLower)) {
      score += 50; // Prefix match
    } else if (term.includes(queryLower)) {
      score += 25; // Contains match
    }
  }

  // Boost settings/memory types when they match so they can appear and be selected
  if (score > 0 && (type === "settings_memory" || type === "settings_memory_entry")) {
    score += SETTINGS_MEMORY_SCORE_BOOST;
  }

  if (score > 0 && (type === "project" || type === "project_folder" || type === "project_file")) {
    score += PROJECT_MENTION_SCORE_BOOST;
  }

  return score;
}

/** Score, drop non-matches, sort best first (stable) and keep `limit` results. */
export function rankMentionResults<T extends RankableMention>(results: T[], query: string, limit: number): T[] {
  return results
    .map((result) => ({
      ...result,
      score: calculateMatchScore(query, result.searchTerms, result.type),
    }))
    .filter((result) => result.score > 0)
    .sort((a, b) => (b.score || 0) - (a.score || 0))
    .slice(0, limit);
}
