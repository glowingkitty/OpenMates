import publicApps from '../../generated/publicApps.generated.json';

/** The capability tour order is generated from currently available public apps. */
export const landingAppOrder = publicApps.map((app) => app.id);

/** Compatibility view for route and browser tests; IDs come from app metadata. */
export const landingAppExamples: Record<string, string> = Object.fromEntries(
  publicApps.map((app) => [app.id, app.exampleChatId])
);

/** A published event, news item, or blog post supplied by the landing route. */
export interface LandingPublication {
  id: string;
  title: string;
  description?: string;
  href: string;
  image?: string;
  label?: string;
}

/** Real example destinations shared by the screenshots and section action links. */
export const landingSectionExamples = {
  actionable: landingAppExamples.events,
  privacy: 'example-plumber-message-email-phone',
  'model-choice': landingAppExamples.events,
  workflows: undefined,
  devices: landingAppExamples.travel,
} as const;

/** Set only after a genuine native Watch capture has been supplied and reviewed. */
export const landingDeviceMedia: { devicesWatch?: string } = {};
