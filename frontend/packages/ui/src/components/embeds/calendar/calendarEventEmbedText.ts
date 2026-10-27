import { str } from '../../../data/embedTextRenderers';
import { formatCalendarEventDate, normalizeCalendarEventContent } from '../../../utils/calendarEvent';

export function renderCalendarEvent(content: Record<string, unknown>): string {
  const document = normalizeCalendarEventContent(content);
  if (!document || (content.status && content.status !== 'finished')) return str(content.title) ?? 'Calendar event unavailable';
  const event = document.primary_event;
  return [event.title, formatCalendarEventDate(event), event.timezone, event.location, event.description, event.source_url,
    ...document.context_events.map(item => `Context: ${item.title} · ${formatCalendarEventDate(item)}`),
  ].filter(Boolean).join('\n');
}
