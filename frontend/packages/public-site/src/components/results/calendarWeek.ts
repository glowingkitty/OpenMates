/** Shared week geometry for assistant results, event previews and public demos. */
export interface CalendarWeekEntry {
  ref: string;
  title: string;
  dateOrdinal: number;
  startMinutes: number;
  endMinutes?: number;
  endKnown?: boolean;
  /** Exclusive all-day end, when supplied. */
  endDateOrdinal?: number;
  dateOnly: boolean;
  location?: string;
  category?: string;
  highlighted?: boolean;
  contextual?: boolean;
  /** Geometry for unknown ends is presentation only; never an asserted duration. */
  minimumDisplayMinutes?: number;
  column?: number;
  columnCount?: number;
}

export function weekStartOrdinal(ordinal: number): number {
  return ordinal - ((new Date(ordinal * 86_400_000).getUTCDay() + 6) % 7);
}

export function calendarEndMinutes(item: CalendarWeekEntry): number {
  return item.endMinutes != null && item.endMinutes > item.startMinutes
    ? item.endMinutes : item.startMinutes + (item.minimumDisplayMinutes ?? 45);
}

export function calendarWeeksWithEntries(items: CalendarWeekEntry[]): number[] {
  const weeks = new Set<number>();
  for (const item of items) {
    const lastDay = item.dateOnly ? Math.max(item.dateOrdinal, (item.endDateOrdinal ?? item.dateOrdinal + 1) - 1)
      : item.dateOrdinal + Math.ceil(calendarEndMinutes(item) / 1440) - 1;
    // Render bounded source data without allocating thousands of empty weeks.
    const finalWeek = Math.min(weekStartOrdinal(lastDay), weekStartOrdinal(item.dateOrdinal) + 7 * 520);
    for (let week = weekStartOrdinal(item.dateOrdinal); week <= finalWeek; week += 7) weeks.add(week);
  }
  return [...weeks].sort((a, b) => a - b);
}

export function layoutCalendarDay(items: CalendarWeekEntry[]): CalendarWeekEntry[] {
  const timed = items.filter(item => !item.dateOnly).map(item => ({ ...item })).sort((a, b) => a.startMinutes - b.startMinutes);
  let group: CalendarWeekEntry[] = [];
  let laneEnds: number[] = [];
  let groupEnd = -1;
  const finishGroup = () => { for (const item of group) item.columnCount = laneEnds.length; };
  for (const item of timed) {
    if (item.startMinutes >= groupEnd) { finishGroup(); group = []; laneEnds = []; }
    const freeLane = laneEnds.findIndex(end => end <= item.startMinutes);
    item.column = freeLane < 0 ? laneEnds.length : freeLane;
    laneEnds[item.column] = calendarEndMinutes(item);
    group.push(item);
    groupEnd = Math.max(...laneEnds);
  }
  finishGroup();
  return [...items.filter(item => item.dateOnly), ...timed];
}

export function buildCalendarWeekDays(weekStart: number, items: CalendarWeekEntry[], today = todayOrdinal()) {
  return Array.from({ length: 7 }, (_, index) => {
    const dateOrdinal = weekStart + index;
    return {
      dateOrdinal, isToday: dateOrdinal === today,
      entries: layoutCalendarDay(items.flatMap(item => {
        if (item.dateOnly) return dateOrdinal >= item.dateOrdinal && dateOrdinal < (item.endDateOrdinal ?? item.dateOrdinal + 1) ? [item] : [];
        const offset = (dateOrdinal - item.dateOrdinal) * 1440;
        const start = Math.max(0, item.startMinutes - offset);
        const end = Math.min(1440, calendarEndMinutes(item) - offset);
        return end > start && start < 1440 ? [{ ...item, dateOrdinal, startMinutes: start, endMinutes: end, endKnown: item.endKnown ?? item.endMinutes != null }] : [];
      })),
    };
  });
}

function todayOrdinal(): number {
  const now = new Date();
  return Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()) / 86_400_000;
}

export function calendarTime(minutes: number): string {
  return `${Math.floor(minutes / 60).toString().padStart(2, '0')}:${Math.round(minutes % 60).toString().padStart(2, '0')}`;
}

export function calendarWeekNumber(weekStart: number): { week: number; year: number } {
  const thursday = new Date((weekStart + 3) * 86_400_000);
  const year = thursday.getUTCFullYear();
  return { week: Math.ceil(((thursday.getTime() - Date.UTC(year, 0, 1)) / 86_400_000 + 1) / 7), year };
}
