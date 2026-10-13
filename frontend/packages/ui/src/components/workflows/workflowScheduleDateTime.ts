/** Convert schedule instants to and from the wall time in the chosen IANA timezone. */
function parts(date: Date, timezone: string): Record<string, string> {
  const formatter = new Intl.DateTimeFormat('en-GB', {
    timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  });
  return Object.fromEntries(formatter.formatToParts(date).map(part => [part.type, part.value]));
}

function wallTime(date: Date, timezone: string): string {
  const value = parts(date, timezone);
  return `${value.year}-${value.month}-${value.day}T${value.hour}:${value.minute}`;
}

export function scheduleDateTimeInput(value: unknown, timezone: string): string {
  if (typeof value !== 'string' || !value) return '';
  // Legacy values without an offset already describe a wall time in the schedule timezone.
  if (!/(?:Z|[+-]\d\d:\d\d)$/i.test(value)) return value.slice(0, 16);
  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) return '';
  try { return wallTime(instant, timezone); } catch { return ''; }
}

export function scheduleDateTimeInstant(value: string, timezone: string): string | null {
  if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(value)) return null;
  const wallUtc = Date.parse(`${value}:00Z`);
  if (Number.isNaN(wallUtc)) return null;
  try {
    // Offsets on either side of a DST transition can differ. Try both and
    // accept only an instant that formats back to the selected wall time.
    const candidates = new Set<number>();
    for (const sample of [wallUtc - 86400000, wallUtc, wallUtc + 86400000]) {
      const local = wallTime(new Date(sample), timezone);
      const localUtc = Date.parse(`${local}:00Z`);
      candidates.add(wallUtc - (localUtc - sample));
    }
    const matching = [...candidates].filter(instant => wallTime(new Date(instant), timezone) === value);
    return matching.length ? new Date(Math.min(...matching)).toISOString() : null;
  } catch { return null; }
}

/** Attach the old timezone's offset without rounding authored seconds or fractions. */
export function scheduleDateTimeWithOffset(value: string, timezone: string): string | null {
  if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d+)?)?$/.test(value)) return null;
  const minute = value.slice(0, 16);
  const instant = scheduleDateTimeInstant(minute, timezone);
  if (!instant) return null;
  const offsetMinutes = (Date.parse(`${minute}:00Z`) - Date.parse(instant)) / 60000;
  const sign = offsetMinutes < 0 ? '-' : '+';
  const absolute = Math.abs(offsetMinutes);
  return `${value}${sign}${String(Math.floor(absolute / 60)).padStart(2, '0')}:${String(absolute % 60).padStart(2, '0')}`;
}
