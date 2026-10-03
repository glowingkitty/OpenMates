/** Shared local-calendar buckets for web and terminal chat navigation. */
export function chatTimeGroupKey(timestamp: number | null | undefined, now = new Date()): string {
  const value = timestamp ? timestamp < 10_000_000_000 ? timestamp * 1000 : timestamp : now.getTime();
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return 'today';
  // Compare calendar dates, not elapsed local-midnight hours across DST changes.
  const days = (Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
    - Date.UTC(date.getFullYear(), date.getMonth(), date.getDate())) / 86_400_000;
  if (days === 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 7) return 'previous_7_days';
  if (days < 30) return 'previous_30_days';
  return `month_${date.getFullYear()}_${date.getMonth() + 1}`;
}

export const CHAT_TIME_GROUPS = ['today', 'yesterday', 'previous_7_days', 'previous_30_days'] as const;
