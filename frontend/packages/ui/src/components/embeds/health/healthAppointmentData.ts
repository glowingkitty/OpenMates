import { eventCalendarBadge, formatEventResultDate, formatEventResultTime } from '../events/eventResult';

/** Supplied identity fields are aliases, never a reason to invent a clinician. */
export function healthAppointmentName(content: Record<string, unknown>): string | undefined {
  for (const key of ['name', 'doctor_name', 'practice_name', 'clinician_or_practice']) {
    if (typeof content[key] === 'string' && content[key].trim()) return content[key];
  }
  return undefined;
}

/** Share the event adapter's source timezone/offset behavior with appointment cards. */
export function healthAppointmentSlot(value: string | undefined, timezone?: string, locale?: string) {
  const badge = eventCalendarBadge(value, timezone);
  const dateLabel = formatEventResultDate(value, timezone, locale);
  const timeLabel = formatEventResultTime(value, timezone, locale);
  return {
    ...badge,
    timeLabel,
    label: [dateLabel, timeLabel, timezone].filter(Boolean).join(' · ') || value || '',
  };
}
