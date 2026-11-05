import type { CalendarDownloadInput } from '../../../utils/calendarDownload';
import { asText } from './fitnessEmbedData';

function timeFromRange(value: unknown, index: 0 | 1): string {
  const matches = Array.from(asText(value).matchAll(/\b(\d{1,2}):(\d{2})\b/g));
  const match = matches[index];
  if (!match) return '';
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (!Number.isFinite(hours) || !Number.isFinite(minutes) || hours > 23 || minutes > 59) return '';
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
}

/** Keep legacy parsing; authored classes never acquire an unsupplied duration. */
export function fitnessClassCalendarTiming(date: unknown, timeRange: unknown, authored = false): Pick<CalendarDownloadInput, 'start' | 'end' | 'preserveUnknownEnd'> {
  const classDate = asText(date);
  const startTime = timeFromRange(timeRange, 0);
  const endTime = timeFromRange(timeRange, 1);
  return {
    start: classDate && startTime ? `${classDate}T${startTime}:00` : classDate,
    end: classDate && endTime ? `${classDate}T${endTime}:00` : authored ? undefined : classDate,
    ...(authored ? {preserveUnknownEnd:true} : {}),
  };
}
