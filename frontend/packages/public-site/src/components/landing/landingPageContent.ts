import publicApps from '../../generated/publicApps.generated.json';

/** The capability tour order is generated from currently available public apps. */
export const landingAppOrder = publicApps.map((app) => app.id);

/** Existing share-imported chats whose opening naturally demonstrates this app. */
export const landingAppExamples: Record<string, string> = {
  events: 'example-ai-workshops-meetups-berlin',
  travel: 'example-family-stays-kyoto',
  code: 'example-habit-garden-web-application',
  home: 'example-furnished-apartments-berlin',
  health: 'example-berlin-english-speaking-gp',
  images: 'example-community-garden-sunflower-illustration',
  pdf: 'example-community-garden-budget-review',
  social_media: 'example-mastodon-public-post-themes',
  calendar: 'example-community-garden-calendar-invitation',
  jobs: 'example-adjacent-career-portfolio-experiments',
  life_coaching: 'example-calm-manager-follow-up',
  plants: 'example-autumn-basil-balcony-care',
  study: 'example-bayes-theorem-quick-quiz',
  finance: 'example-net-cash-from-supplied',
  audio: 'example-voice-note-transcription-action',
  music: 'example-community-garden-welcome-melody',
  ai: 'example-urban-heat-island-at',
  books: 'example-books-after-left-hand',
  docs: 'example-community-garden-volunteer-onboarding',
  models3d: 'example-printable-benchy-phone-stand',
  fitness: 'example-beginner-yoga-classes-berlin',
  mail: 'example-private-plumber-email',
  web: 'example-us-egg-prices-deep',
  maps: 'example-quiet-cafes-tempelhofer-feld',
  weather: 'example-berlin-weather-bike-commute',
  shopping: 'example-organic-groceries-berlin',
  nutrition: 'example-chickpea-spinach-protein-dinners',
  news: 'example-right-to-repair-laws',
  mindmaps: 'example-community-garden-planning-mindmap',
  math: 'example-damped-sine-decay-plot',
  videos: 'example-rag-explained-videos',
  business: 'example-vital-farms-sec-financials',
  design: 'example-dashboard-sidebar-svg-icons',
  electronics: 'example-buck-converters-24v-5v',
  hosting: 'example-social-app-name-domain',
  politics: 'example-housing-policy-dinner-discussion'
};

/** A published event, news item, or blog post supplied by the landing route. */
export interface LandingPublication {
  id: string;
  title: string;
  description?: string;
  href: string;
  image?: string;
  label?: string;
}
