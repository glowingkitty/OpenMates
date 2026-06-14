// frontend/packages/ui/src/demo_chats/exampleChatData.ts
//
// Pure example-chat data registry shared by the web app and OpenMates CLI.
// Keep this file free of Svelte stores and browser-only services so it can be
// bundled by non-Svelte consumers. UI-specific conversion and embed-store
// registration belongs in exampleChatStore.ts.

import type { ExampleChat } from "./types";

import { giganticAirplanesChat } from "./data/example_chats/gigantic-airplanes";
import { artemisIIMissionChat } from "./data/example_chats/artemis-ii-mission";
import { beautifulSinglePageHtmlChat } from "./data/example_chats/beautiful-single-page-html";
import { flightsBerlinBangkokChat } from "./data/example_chats/flights-berlin-to-bangkok";
import { euChatControlLawChat } from "./data/example_chats/eu-chat-control-law-criticisms";
import { creativityDrawingMeetupsBerlinChat } from "./data/example_chats/creativity-drawing-meetups-berlin";
import { germanyHistoricFilmIndustryChat } from "./data/example_chats/germany-historic-film-industry";
import { buildingMaintenanceEmailChat } from "./data/example_chats/building-maintenance-email";
import { aiWorkshopsMeetupsBerlinChat } from "./data/example_chats/ai-workshops-meetups-berlin";
import { rightToRepairLawsEuUsChat } from "./data/example_chats/right-to-repair-laws-eu-us";
import { berlinWeatherBikeCommuteChat } from "./data/example_chats/berlin-weather-bike-commute";
import { quietCafesTempelhoferFeldChat } from "./data/example_chats/quiet-cafes-tempelhofer-feld";
import { ragExplainedVideosChat } from "./data/example_chats/rag-explained-videos";
import { mortgagePaymentCalculationChat } from "./data/example_chats/mortgage-payment-calculation";
import { rustVectorDatabaseReposChat } from "./data/example_chats/rust-vector-database-repos";
import { svelteRunesDocsChat } from "./data/example_chats/svelte-runes-docs";
import { familyStaysKyotoChat } from "./data/example_chats/family-stays-kyoto";
import { tedTalkTranscriptSummaryChat } from "./data/example_chats/ted-talk-transcript-summary";
import { balconyPlantReminderChat } from "./data/example_chats/balcony-plant-reminder";
import { buckConverters24v5vChat } from "./data/example_chats/buck-converters-24v-5v";
import { organicGroceriesBerlinChat } from "./data/example_chats/organic-groceries-berlin";
import { furnishedApartmentsBerlinChat } from "./data/example_chats/furnished-apartments-berlin";
import { sqliteStrictTablesSummaryChat } from "./data/example_chats/sqlite-strict-tables-summary";
import { privacyWebsiteHeroBackgroundChat } from "./data/example_chats/privacy-website-hero-background";
import { northstarMetricsSvgLogoChat } from "./data/example_chats/northstar-metrics-svg-logo";
import { pythonSquaresCodeRunChat } from "./data/example_chats/python-squares-code-run";
import { habitTrackerOnboardingDraftChat } from "./data/example_chats/habit-tracker-onboarding-draft";
import { chickpeaSpinachProteinDinnersChat } from "./data/example_chats/chickpea-spinach-protein-dinners";
import { openmatesAppSkillsEmbedsDocsChat } from "./data/example_chats/openmates-app-skills-embeds-docs";
import { openmatesAddAppSkillDocChat } from "./data/example_chats/openmates-add-app-skill-doc";
import { nonprofitEventPlanningUseCaseChat } from "./data/example_chats/nonprofit-event-planning-use-case";
import { lh400FlightStatusCheckChat } from "./data/example_chats/lh400-flight-status-check";
import { berlinDermatologyAppointmentsChat } from "./data/example_chats/berlin-dermatology-appointments";
import { productLaunchSynthLoopChat } from "./data/example_chats/product-launch-synth-loop";
import { privateWorkspaceDemoVideoChat } from "./data/example_chats/private-workspace-demo-video";
import { upcomingRemindersListChat } from "./data/example_chats/upcoming-reminders-list";
import { cancelTestReminderChat } from "./data/example_chats/cancel-test-reminder";
import { fediverseActivitypubSocialSearchChat } from "./data/example_chats/fediverse-activitypub-social-search";
import { mastodonAccountRecentPostsChat } from "./data/example_chats/mastodon-account-recent-posts";
import { habitGardenViteAppChat } from "./data/example_chats/habit-garden-vite-app";
import { pdfReadSecretWordChat } from "./data/example_chats/pdf-read-secret-word";
import { pdfViewPageLayoutChat } from "./data/example_chats/pdf-view-page-layout";
import { pdfSearchEncryptionChat } from "./data/example_chats/pdf-search-encryption";
import { imageVectorizeOpenmatesHeaderChat } from "./data/example_chats/image-vectorize-openmates-header";
import { audioTranscribeVoiceNoteChat } from "./data/example_chats/audio-transcribe-voice-note";
import { usEggPricesDeepResearchChat } from "./data/example_chats/us-egg-prices-deep-research";
import { frameworkStoreReputationCheckChat } from "./data/example_chats/framework-store-reputation-check";
import { frontendDeveloperCareerPivotChat } from "./data/example_chats/frontend-developer-career-pivot";
import { memoryAiCommunicationStyleChat } from "./data/example_chats/memory-ai-communication-style";
import { memoryAiLearningPreferencesChat } from "./data/example_chats/memory-ai-learning-preferences";
import { memoryBooksFavoriteBooksChat } from "./data/example_chats/memory-books-favorite-books";
import { memoryBooksCurrentlyReadingChat } from "./data/example_chats/memory-books-currently-reading";
import { memoryBooksToReadListChat } from "./data/example_chats/memory-books-to-read-list";
import { memoryCodePreferredTechChat } from "./data/example_chats/memory-code-preferred-tech";
import { memoryCodeProjectsChat } from "./data/example_chats/memory-code-projects";
import { memoryCodeWantToLearnChat } from "./data/example_chats/memory-code-want-to-learn";
import { memoryCodeCodingSetupChat } from "./data/example_chats/memory-code-coding-setup";
import { memoryDocsWritingStyleChat } from "./data/example_chats/memory-docs-writing-style";
import { memoryEventsSavedEventsChat } from "./data/example_chats/memory-events-saved-events";
import { memoryHealthAppointmentsChat } from "./data/example_chats/memory-health-appointments";
import { memoryHealthMedicalHistoryChat } from "./data/example_chats/memory-health-medical-history";
import { memoryHomeSavedListingsChat } from "./data/example_chats/memory-home-saved-listings";
import { memoryImagesPreferredStylesChat } from "./data/example_chats/memory-images-preferred-styles";
import { memoryMailWritingStylesChat } from "./data/example_chats/memory-mail-writing-styles";
import { memoryReminderDefaultsChat } from "./data/example_chats/memory-reminder-defaults";
import { memoryStudyLearningGoalsChat } from "./data/example_chats/memory-study-learning-goals";
import { memoryTravelSavedConnectionsChat } from "./data/example_chats/memory-travel-saved-connections";
import { memoryTravelSavedStaysChat } from "./data/example_chats/memory-travel-saved-stays";
import { memoryTravelTripsChat } from "./data/example_chats/memory-travel-trips";
import { memoryTravelPreferredAirlinesChat } from "./data/example_chats/memory-travel-preferred-airlines";
import { memoryTravelPreferredTransportChat } from "./data/example_chats/memory-travel-preferred-transport";
import { memoryTravelPreferredActivitiesChat } from "./data/example_chats/memory-travel-preferred-activities";
import { memoryTvWatchedMoviesChat } from "./data/example_chats/memory-tv-watched-movies";
import { memoryTvWatchedShowsChat } from "./data/example_chats/memory-tv-watched-shows";
import { memoryTvToWatchListChat } from "./data/example_chats/memory-tv-to-watch-list";
import { memoryVideosToWatchListChat } from "./data/example_chats/memory-videos-to-watch-list";
import { memoryWebBookmarksChat } from "./data/example_chats/memory-web-bookmarks";
import { memoryWebReadLaterChat } from "./data/example_chats/memory-web-read-later";
import { productTeaserRemotionVideoChat } from "./data/example_chats/product-teaser-remotion-video";
import { dampedSineWavePlotChat } from "./data/example_chats/damped-sine-wave-plot";
import { berlinCentralStationMapLocationChat } from "./data/example_chats/berlin-central-station-map-location";
import { launchReadinessChecklistDocChat } from "./data/example_chats/launch-readiness-checklist-doc";
import { searchParentPreviewStressTestChat } from "./data/example_chats/search-parent-preview-stress-test";
import { berlinRainRadarNext10MinutesChat } from "./data/example_chats/berlin-rain-radar-next-10-minutes";

export const ALL_EXAMPLE_CHATS: ExampleChat[] = [
  giganticAirplanesChat,
  artemisIIMissionChat,
  beautifulSinglePageHtmlChat,
  flightsBerlinBangkokChat,
  euChatControlLawChat,
  creativityDrawingMeetupsBerlinChat,
  germanyHistoricFilmIndustryChat,
  buildingMaintenanceEmailChat,
  aiWorkshopsMeetupsBerlinChat,
  rightToRepairLawsEuUsChat,
  berlinWeatherBikeCommuteChat,
  quietCafesTempelhoferFeldChat,
  ragExplainedVideosChat,
  mortgagePaymentCalculationChat,
  rustVectorDatabaseReposChat,
  svelteRunesDocsChat,
  familyStaysKyotoChat,
  tedTalkTranscriptSummaryChat,
  balconyPlantReminderChat,
  buckConverters24v5vChat,
  organicGroceriesBerlinChat,
  furnishedApartmentsBerlinChat,
  sqliteStrictTablesSummaryChat,
  privacyWebsiteHeroBackgroundChat,
  northstarMetricsSvgLogoChat,
  pythonSquaresCodeRunChat,
  habitTrackerOnboardingDraftChat,
  chickpeaSpinachProteinDinnersChat,
  openmatesAppSkillsEmbedsDocsChat,
  openmatesAddAppSkillDocChat,
  nonprofitEventPlanningUseCaseChat,
  lh400FlightStatusCheckChat,
  berlinDermatologyAppointmentsChat,
  productLaunchSynthLoopChat,
  privateWorkspaceDemoVideoChat,
  upcomingRemindersListChat,
  cancelTestReminderChat,
  fediverseActivitypubSocialSearchChat,
  mastodonAccountRecentPostsChat,
  habitGardenViteAppChat,
  pdfReadSecretWordChat,
  pdfViewPageLayoutChat,
  pdfSearchEncryptionChat,
  imageVectorizeOpenmatesHeaderChat,
  audioTranscribeVoiceNoteChat,
  usEggPricesDeepResearchChat,
  frameworkStoreReputationCheckChat,
  frontendDeveloperCareerPivotChat,
  memoryAiCommunicationStyleChat,
  memoryAiLearningPreferencesChat,
  memoryBooksFavoriteBooksChat,
  memoryBooksCurrentlyReadingChat,
  memoryBooksToReadListChat,
  memoryCodePreferredTechChat,
  memoryCodeProjectsChat,
  memoryCodeWantToLearnChat,
  memoryCodeCodingSetupChat,
  memoryDocsWritingStyleChat,
  memoryEventsSavedEventsChat,
  memoryHealthAppointmentsChat,
  memoryHealthMedicalHistoryChat,
  memoryHomeSavedListingsChat,
  memoryImagesPreferredStylesChat,
  memoryMailWritingStylesChat,
  memoryReminderDefaultsChat,
  memoryStudyLearningGoalsChat,
  memoryTravelSavedConnectionsChat,
  memoryTravelSavedStaysChat,
  memoryTravelTripsChat,
  memoryTravelPreferredAirlinesChat,
  memoryTravelPreferredTransportChat,
  memoryTravelPreferredActivitiesChat,
  memoryTvWatchedMoviesChat,
  memoryTvWatchedShowsChat,
  memoryTvToWatchListChat,
  memoryVideosToWatchListChat,
  memoryWebBookmarksChat,
  memoryWebReadLaterChat,
  productTeaserRemotionVideoChat,
  dampedSineWavePlotChat,
  berlinCentralStationMapLocationChat,
  launchReadinessChecklistDocChat,
  berlinRainRadarNext10MinutesChat,
].sort((a, b) => a.metadata.order - b.metadata.order);

// Internal deterministic fixtures used by tests and direct hash navigation only.
// Keep these out of normal example listings and SEO pages.
export const INTERNAL_EXAMPLE_CHATS: ExampleChat[] = [
  searchParentPreviewStressTestChat,
];
