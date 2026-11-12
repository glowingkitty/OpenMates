/**
 * frontend/packages/ui/src/components/embeds/embedProgress.ts
 *
 * Live progress of a running app skill embed. The server re-sends the
 * "processing" embed with a `progress` object; later frames (higher `seq`)
 * replace earlier ones. Skills that report nothing omit the field.
 */

export interface EmbedProgress {
  sources_total: number;
  sources_done: number;
  result_count: number;
  seq: number;
}

function isCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

/** Return a valid progress object from decoded embed content, else null. */
export function parseEmbedProgress(value: unknown): EmbedProgress | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  if (!isCount(raw.sources_total) || raw.sources_total < 1) return null;
  if (!isCount(raw.sources_done) || !isCount(raw.result_count) || !isCount(raw.seq)) return null;
  return {
    sources_total: raw.sources_total,
    sources_done: Math.min(raw.sources_done, raw.sources_total),
    result_count: raw.result_count,
    seq: raw.seq,
  };
}

/** Keep the frame with the higher seq; a lower or equal seq is ignored. */
export function nextEmbedProgress(
  current: EmbedProgress | null,
  incoming: EmbedProgress | null,
): EmbedProgress | null {
  if (!incoming) return current;
  if (current && incoming.seq <= current.seq) return current;
  return incoming;
}

/** Translated status line for a progress frame. `t` is the `$text` function. */
export function formatEmbedProgress(
  progress: EmbedProgress,
  t: (key: string, options?: { values: Record<string, string | number> }) => string,
): string {
  const results = progress.result_count === 0
    ? ''
    : progress.result_count === 1
      ? t('embeds.progress_result_one')
      : t('embeds.progress_results', { values: { count: progress.result_count } });
  if (progress.sources_total === 1) {
    return results || t('embeds.progress_searching');
  }
  if (!results) {
    return t('embeds.progress_searching_sources', {
      values: { total: progress.sources_total, done: progress.sources_done },
    });
  }
  return `${progress.sources_done}/${progress.sources_total} · ${results}`;
}
