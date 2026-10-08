import { getAllOpenMatesEvents } from './openmatesEvents';
import type { LandingPublication } from '../components/landing/landingPageContent';

/** Public card projection of all unfinished OpenMates events, including paid ones. */
export function getUpcomingOpenMatesEventCards(now: Date, appBaseUrl: string): LandingPublication[] {
  return getAllOpenMatesEvents()
    .filter((event) => Date.parse(event.date_end) >= now.getTime())
    .sort((a, b) => Date.parse(a.date_start) - Date.parse(b.date_start))
    .map((event) => ({
      id: event.id,
      title: event.title,
      description: event.summary,
      href: `${appBaseUrl.replace(/\/$/, '')}/#embed-id=${encodeURIComponent(event.embed_id)}`,
      image: event.image_url,
      label: new Intl.DateTimeFormat('en', {dateStyle: 'medium', timeZone: 'Europe/Berlin'}).format(new Date(event.date_start))
    }));
}
