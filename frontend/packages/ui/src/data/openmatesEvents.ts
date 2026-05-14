/**
 * frontend/packages/ui/src/data/openmatesEvents.ts
 *
 * Hardcoded public OpenMates event data used by the chat sidebar, event SEO
 * pages, sitemap generation, and hash-based event embed deep links.
 * Keep this data static and crawlable; external provider IDs stay in URLs only,
 * while internal ids use stable human-readable slugs.
 */

export interface OpenMatesEvent {
  embed_id: string;
  id: string;
  slug: string;
  provider: string;
  title: string;
  description: string;
  url: string;
  date_start: string;
  date_end: string;
  timezone: string;
  event_type: string;
  venue: {
    name: string;
    address: string;
    city: string;
    country: string;
    lat: number;
    lon: number;
  };
  organizer: {
    name: string;
    slug: string;
  };
  is_paid: boolean;
  image_url: string;
  keywords: string[];
  summary: string;
}

export const OPENMATES_EVENTS: OpenMatesEvent[] = [
  {
    embed_id: "openmates-meetup-2026-05-19",
    id: "openmates-meetup-2026-05-19",
    slug: "openmates-meetup-2026-05-19",
    provider: "luma",
    title: "OpenMates Meetup",
    summary:
      "Join the OpenMates community in Berlin to talk about privacy-first AI team mates, the next steps for OpenMates, and how to help build an alternative to big tech.",
    description: `A lot of exciting new changes have happened in the recent months regarding OpenMates.org. To make it not just a more privacy & safety focused open source alternative to ChatGPT, Claude, OpenClaw etc., but to build AI team mates that are also more useful and reliable for everyday tasks like finding doctor appointments, apartments, events, flights and train connection, as well as planning and building projects and so much more.

Effectively building the next generation operating system for a wide range of daily tasks & learning. All while ensuring that user interests are put first in every architecture and design decision, NOT advertisers.

Now, with the first 200 active users, many more visitors, and close to 8000 git commits, let’s come together to talk about the next steps of OpenMate and to move OpenMates from a single person project to a team effort.

If you are a user, developer, designer, storyteller / marketing enthusiast or community builder or just are curious about the project - feel free to join the meetup and contribute in building a real alternative to big tech :)`,
    url: "https://luma.com/2159uo8z",
    date_start: "2026-05-19T19:00:00+02:00",
    date_end: "2026-05-19T21:00:00+02:00",
    timezone: "Europe/Berlin",
    event_type: "IN_PERSON",
    venue: {
      name: "New xHain rooms (direct street access, huge glass windows)",
      address: "Grünberger Str. 18, 10243 Berlin",
      city: "Berlin",
      country: "Germany",
      lat: 52.512778392359216,
      lon: 13.449996888857694,
    },
    organizer: {
      name: "OpenMates Meetup Group",
      slug: "openmates",
    },
    is_paid: false,
    image_url:
      "https://images.lumacdn.com/uploads/xl/0c9da73e-8fd7-4a03-90ea-fa047af921f8.png",
    keywords: [
      "OpenMates meetup",
      "privacy-first AI",
      "open source AI",
      "AI team mates",
      "Berlin AI meetup",
    ],
  },
];

export function getAllOpenMatesEvents(): OpenMatesEvent[] {
  return OPENMATES_EVENTS;
}

export function getOpenMatesEventBySlug(slug: string): OpenMatesEvent | undefined {
  return OPENMATES_EVENTS.find((event) => event.slug === slug || event.embed_id === slug);
}
