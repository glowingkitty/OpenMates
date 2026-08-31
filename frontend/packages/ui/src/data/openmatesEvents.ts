/**
 * frontend/packages/ui/src/data/openmatesEvents.ts
 *
 * Generated from shared/events/openmates_events.yml by scripts/generate_openmates_events.py.
 * Used by the chat sidebar, event SEO pages, sitemap generation, and
 * hash-based event embed deep links. Do not edit records manually.
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
  event_type: "ONLINE" | "PHYSICAL";
  venue: {
    name: string;
    address: string;
    city: string;
    country: string;
    lat?: number;
    lon?: number;
  };
  organizer: {
    name: string;
    slug: string;
  };
  is_paid: boolean;
  image_url: string;
  keywords: string[];
  summary: string;
  online_url?: string | null;
}

export const OPENMATES_EVENTS: OpenMatesEvent[] = [
  {
    "embed_id": "openmates-berlin-meetup-2026-09-26",
    "id": "openmates-berlin-meetup-2026-09-26",
    "slug": "openmates-berlin-meetup-2026-09-26",
    "provider": "luma",
    "title": "OpenMates Monthly Meetup Berlin",
    "description": "Join a relaxed monthly meetup for people seeking a European alternative to big-tech AI or already using OpenMates. Bring questions, issues, and feature wishes while meeting other people over a drink.",
    "url": "https://luma.com/dtz982h1",
    "date_start": "2026-09-26T16:00:00+02:00",
    "date_end": "2026-09-26T18:00:00+02:00",
    "timezone": "Europe/Berlin",
    "event_type": "PHYSICAL",
    "venue": {
      "name": "xHain Glitch",
      "address": "Grünberger Str. 20, 10243 Berlin",
      "city": "Berlin",
      "country": "Germany"
    },
    "organizer": {
      "name": "OpenMates Events",
      "slug": "openmates"
    },
    "is_paid": false,
    "image_url": "/event-assets/openmates/openmates-berlin-meetup-2026-09-26.jpg",
    "keywords": [
      "OpenMates",
      "OpenMates Events",
      "OpenMates Monthly Meetup Berlin",
      "In Person Meetup"
    ],
    "summary": "Meet OpenMates users and contributors in Berlin, learn how to use it better, and directly influence development.",
    "online_url": null
  },
  {
    "embed_id": "openmates-community-hour-2026-09-29",
    "id": "openmates-community-hour-2026-09-29",
    "slug": "openmates-community-hour-2026-09-29",
    "provider": "luma",
    "title": "OpenMates Monthly Community Hour",
    "description": "Tired of big-tech AI chatbots and agents, or already using OpenMates for everyday tasks and learning? Join the monthly community video call with questions, discovered issues, and wishes that can improve OpenMates for everyone.",
    "url": "https://luma.com/frepqvmi",
    "date_start": "2026-09-29T19:00:00+02:00",
    "date_end": "2026-09-29T20:00:00+02:00",
    "timezone": "Europe/Berlin",
    "event_type": "ONLINE",
    "venue": {
      "name": "OpenMates online event",
      "address": "https://meet.openmates.org",
      "city": "Online",
      "country": ""
    },
    "organizer": {
      "name": "OpenMates Events",
      "slug": "openmates"
    },
    "is_paid": false,
    "image_url": "/event-assets/openmates/openmates-community-hour-2026-09-29.jpg",
    "keywords": [
      "OpenMates",
      "OpenMates Events",
      "OpenMates Monthly Community Hour",
      "Online Community Hour"
    ],
    "summary": "Join the monthly OpenMates video call to learn, ask questions, report issues, and directly shape development.",
    "online_url": "https://meet.openmates.org"
  },
  {
    "embed_id": "everyday-workflows-webinar-2026-09-30",
    "id": "everyday-workflows-webinar-2026-09-30",
    "slug": "everyday-workflows-webinar-2026-09-30",
    "provider": "luma",
    "title": "Intro to automating everyday workflows - No coding experience needed",
    "description": "This presentation and Q&A shows how to set up OpenMates workflows within minutes without coding or automation experience, with practical tips and recommendations for improving personal workflows.",
    "url": "https://luma.com/fql7sc2a",
    "date_start": "2026-09-30T19:00:00+02:00",
    "date_end": "2026-09-30T19:50:00+02:00",
    "timezone": "Europe/Berlin",
    "event_type": "ONLINE",
    "venue": {
      "name": "OpenMates online event",
      "address": "https://meet.openmates.org",
      "city": "Online",
      "country": ""
    },
    "organizer": {
      "name": "OpenMates Events",
      "slug": "openmates"
    },
    "is_paid": false,
    "image_url": "/event-assets/openmates/everyday-workflows-webinar-2026-09-30.jpg",
    "keywords": [
      "OpenMates",
      "OpenMates Events",
      "Intro to automating everyday workflows - No coding experience needed",
      "Webinar"
    ],
    "summary": "Learn to automate recurring searches for events, apartments, appointments, news, and other personal or work tasks.",
    "online_url": "https://meet.openmates.org"
  },
  {
    "embed_id": "openmates-teams-webinar-2026-10-14",
    "id": "openmates-teams-webinar-2026-10-14",
    "slug": "openmates-teams-webinar-2026-10-14",
    "provider": "luma",
    "title": "OpenMates for teams - Collaborate on projects, AI chats and workflows",
    "description": "This presentation and Q&A introduces the OpenMates teams feature, separation of work and personal data, shared usage credits, and practical recommendations for setting up a small team's workspace.",
    "url": "https://luma.com/brp682ie",
    "date_start": "2026-10-14T19:00:00+02:00",
    "date_end": "2026-10-14T19:50:00+02:00",
    "timezone": "Europe/Berlin",
    "event_type": "ONLINE",
    "venue": {
      "name": "OpenMates online event",
      "address": "https://meet.openmates.org",
      "city": "Online",
      "country": ""
    },
    "organizer": {
      "name": "OpenMates Events",
      "slug": "openmates"
    },
    "is_paid": false,
    "image_url": "/event-assets/openmates/openmates-teams-webinar-2026-10-14.jpg",
    "keywords": [
      "OpenMates",
      "OpenMates Events",
      "OpenMates for teams - Collaborate on projects, AI chats and workflows",
      "Webinar"
    ],
    "summary": "Learn how freelancers and small teams can collaborate on projects, chats, workflows, and tasks with privacy-focused encryption.",
    "online_url": "https://meet.openmates.org"
  },
  {
    "embed_id": "cli-sdk-webinar-2026-10-28",
    "id": "cli-sdk-webinar-2026-10-28",
    "slug": "cli-sdk-webinar-2026-10-28",
    "provider": "luma",
    "title": "OpenMates CLI and SDK for developers - All chats and features included",
    "description": "This presentation and Q&A introduces the official OpenMates CLI plus npm and pip SDKs, cross-device access, broad feature parity, and practical recommendations for integrating OpenMates into software workflows.",
    "url": "https://luma.com/8kquidf1",
    "date_start": "2026-10-28T19:00:00+01:00",
    "date_end": "2026-10-28T19:50:00+01:00",
    "timezone": "Europe/Berlin",
    "event_type": "ONLINE",
    "venue": {
      "name": "OpenMates online event",
      "address": "https://meet.openmates.org",
      "city": "Online",
      "country": ""
    },
    "organizer": {
      "name": "OpenMates Events",
      "slug": "openmates"
    },
    "is_paid": false,
    "image_url": "/event-assets/openmates/cli-sdk-webinar-2026-10-28.jpg",
    "keywords": [
      "OpenMates",
      "OpenMates Events",
      "OpenMates CLI and SDK for developers - All chats and features included",
      "Webinar"
    ],
    "summary": "Learn to use OpenMates chats, app skills, projects, tasks, workflows, memories, teams, and settings through the CLI and SDKs.",
    "online_url": "https://meet.openmates.org"
  },
  {
    "embed_id": "spec-driven-development-webinar-2026-11-11",
    "id": "spec-driven-development-webinar-2026-11-11",
    "slug": "spec-driven-development-webinar-2026-11-11",
    "provider": "luma",
    "title": "Beyond vibe coding - Introduction to spec-driven development",
    "description": "This presentation and Q&A introduces OpenMates Projects, Plans, and Tasks for structured agentic coding beyond vibe coding, including enforced planning and recommendations for improving development workflows.",
    "url": "https://luma.com/vj8dq9qs",
    "date_start": "2026-11-11T19:00:00+01:00",
    "date_end": "2026-11-11T19:50:00+01:00",
    "timezone": "Europe/Berlin",
    "event_type": "ONLINE",
    "venue": {
      "name": "OpenMates online event",
      "address": "https://meet.openmates.org",
      "city": "Online",
      "country": ""
    },
    "organizer": {
      "name": "OpenMates Events",
      "slug": "openmates"
    },
    "is_paid": false,
    "image_url": "/event-assets/openmates/spec-driven-development-webinar-2026-11-11.jpg",
    "keywords": [
      "OpenMates",
      "OpenMates Events",
      "Beyond vibe coding - Introduction to spec-driven development",
      "Webinar"
    ],
    "summary": "Learn how plans, tasks, projects, and enforced rules can make agentic coding more reliable and secure.",
    "online_url": "https://meet.openmates.org"
  },
  {
    "embed_id": "self-hosting-webinar-2026-11-25",
    "id": "self-hosting-webinar-2026-11-25",
    "slug": "self-hosting-webinar-2026-11-25",
    "provider": "luma",
    "title": "Intro to self-hosting your AI agents - Options, tips and tricks",
    "description": "This presentation and Q&A introduces OpenMates self-hosting, external API and local-model options, infrastructure and provider requirements, and recommendations for a practical self-hosted setup.",
    "url": "https://luma.com/8gr6arot",
    "date_start": "2026-11-25T19:00:00+01:00",
    "date_end": "2026-11-25T19:50:00+01:00",
    "timezone": "Europe/Berlin",
    "event_type": "ONLINE",
    "venue": {
      "name": "OpenMates online event",
      "address": "https://meet.openmates.org",
      "city": "Online",
      "country": ""
    },
    "organizer": {
      "name": "OpenMates Events",
      "slug": "openmates"
    },
    "is_paid": false,
    "image_url": "/event-assets/openmates/self-hosting-webinar-2026-11-25.jpg",
    "keywords": [
      "OpenMates",
      "OpenMates Events",
      "Intro to self-hosting your AI agents - Options, tips and tricks",
      "Webinar"
    ],
    "summary": "Learn how to run the OpenMates Self-Hosting Edition with external inference APIs or local models for greater control and sovereignty.",
    "online_url": "https://meet.openmates.org"
  }
];

export function getAllOpenMatesEvents(): OpenMatesEvent[] {
  return OPENMATES_EVENTS;
}

export function getOpenMatesEventBySlug(slug: string): OpenMatesEvent | undefined {
  return OPENMATES_EVENTS.find((event) => event.slug === slug || event.embed_id === slug);
}
