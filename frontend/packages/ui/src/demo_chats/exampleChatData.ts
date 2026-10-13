// frontend/packages/ui/src/demo_chats/exampleChatData.ts
//
// Pure example-chat data registry shared by the web app and OpenMates CLI.
// Keep this file free of Svelte stores and browser-only services so it can be
// bundled by non-Svelte consumers. UI-specific conversion and embed-store
// registration belongs in exampleChatStore.ts.

import type { ExampleChat } from "./types";
import { privacyFirstLocalAiWorkspaceChat as compressionHistoryFixtureChat } from "./data/example_chats/privacy-first-local-ai-workspace";

import { giganticAirplanesChat } from "./data/example_chats/gigantic-airplanes";
import { buildingMaintenanceEmailChat } from "./data/example_chats/building-maintenance-email";
import { aiWorkshopsMeetupsBerlinChat } from "./data/example_chats/ai-workshops-meetups-berlin";
import { rightToRepairLawsEuUsChat } from "./data/example_chats/right-to-repair-laws-eu-us";
import { berlinWeatherBikeCommuteChat } from "./data/example_chats/berlin-weather-bike-commute";
import { ragExplainedVideosChat } from "./data/example_chats/rag-explained-videos";
import { rustVectorDatabaseReposChat } from "./data/example_chats/rust-vector-database-repos";
import { svelteRunesDocsChat } from "./data/example_chats/svelte-runes-docs";
import { familyStaysKyotoChat } from "./data/example_chats/family-stays-kyoto";
import { tedTalkTranscriptSummaryChat } from "./data/example_chats/ted-talk-transcript-summary";
import { balconyPlantReminderChat } from "./data/example_chats/balcony-plant-reminder";
import { buckConverters24v5vChat } from "./data/example_chats/buck-converters-24v-5v";
import { organicGroceriesBerlinChat } from "./data/example_chats/organic-groceries-berlin";
import { furnishedApartmentsBerlinChat } from "./data/example_chats/furnished-apartments-berlin";
import { sqliteStrictTablesSummaryChat } from "./data/example_chats/sqlite-strict-tables-summary";
import { pythonSquaresCodeRunChat } from "./data/example_chats/python-squares-code-run";
import { habitTrackerOnboardingDraftChat } from "./data/example_chats/habit-tracker-onboarding-draft";
import { chickpeaSpinachProteinDinnersChat } from "./data/example_chats/chickpea-spinach-protein-dinners";
import { nonprofitEventPlanningUseCaseChat } from "./data/example_chats/nonprofit-event-planning-use-case";
import { lh400FlightStatusCheckChat } from "./data/example_chats/lh400-flight-status-check";
import { referenceImage3DModelChat } from "./data/example_chats/reference-image-3d-model";
import { upcomingRemindersListChat } from "./data/example_chats/upcoming-reminders-list";
import { cancelTestReminderChat } from "./data/example_chats/cancel-test-reminder";
import { fediverseActivitypubSocialSearchChat } from "./data/example_chats/fediverse-activitypub-social-search";
import { pdfViewPageLayoutChat } from "./data/example_chats/pdf-view-page-layout";
import { imageVectorizeOpenmatesHeaderChat } from "./data/example_chats/image-vectorize-openmates-header";
import { audioTranscribeVoiceNoteChat } from "./data/example_chats/audio-transcribe-voice-note";
import { usEggPricesDeepResearchChat } from "./data/example_chats/us-egg-prices-deep-research";
import { frameworkStoreReputationCheckChat } from "./data/example_chats/framework-store-reputation-check";
import { productTeaserRemotionVideoChat } from "./data/example_chats/product-teaser-remotion-video";
import { searchParentPreviewStressTestChat } from "./data/example_chats/search-parent-preview-stress-test";
import { rostockHeavyRainRadarChat } from "./data/example_chats/rostock-heavy-rain-radar";
import { housingPolicyDinnerDiscussionChat } from "./data/example_chats/housing-policy-dinner-discussion";
import { habitGardenWebApplicationChat } from "./data/example_chats/habit-garden-web-application";
import { printableBenchyPhoneStandModelsChat } from "./data/example_chats/printable-benchy-phone-stand-models";
import { exampleChatTaskPlanningChecklistChat } from "./data/example_chats/example-chat-task-planning-checklist";
import { libraryBookReturnWorkflowChat } from "./data/example_chats/library-book-return-workflow";
import { dashboardSidebarSvgIconsChat } from "./data/example_chats/dashboard-sidebar-svg-icons";
import { vitalFarmsSecFinancialsChat } from "./data/example_chats/vital-farms-sec-financials";
import { financeCashFlowOverviewChat } from "./data/example_chats/finance-cash-flow-overview";
import { screenshotToHtmlPricingCardChat } from "./data/example_chats/screenshot-to-html-pricing-card";
import { deutschlandticketTrainFareBreakdownChat } from "./data/example_chats/deutschlandticket-train-fare-breakdown";
import { berlinMitteWorkFriendlyRestaurantsChat } from "./data/example_chats/berlin-mitte-work-friendly-restaurants";
import { audioSpeakOpenmatesWelcomeMessageChat } from "./data/example_chats/audio-speak-openmates-welcome-message";
import { plumberMessageEmailPhonePrivacyChat } from "./data/example_chats/plumber-message-email-phone-privacy";
import { privatePlumberEmailChat } from "./data/example_chats/private-plumber-email";
import { socialAppNameDomainSearchChat } from "./data/example_chats/social-app-name-domain-search";
import { dampedSineDecayPlotChat } from "./data/example_chats/damped-sine-decay-plot";
import { communityGardenPlanningMindmapChat } from "./data/example_chats/community-garden-planning-mindmap";
import { beginnerYogaClassesBerlinChat } from "./data/example_chats/beginner-yoga-classes-berlin";
import { communityGardenVolunteerOnboardingChat } from "./data/example_chats/community-garden-volunteer-onboarding";
import { booksAfterLeftHandOfDarknessChat } from "./data/example_chats/books-after-left-hand-of-darkness";
import { mastodonPublicPostThemesChat } from "./data/example_chats/mastodon-public-post-themes";
import { adjacentCareerPortfolioExperimentsChat } from "./data/example_chats/adjacent-career-portfolio-experiments";
import { netCashFromSuppliedBalancesChat } from "./data/example_chats/net-cash-from-supplied-balances";
import { communityGardenWelcomeMelodyChat } from "./data/example_chats/community-garden-welcome-melody";
import { berlinEnglishSpeakingGpAppointmentsChat } from "./data/example_chats/berlin-english-speaking-gp-appointments";
import { communityGardenSunflowerIllustrationChat } from "./data/example_chats/community-garden-sunflower-illustration";
import { communityGardenBudgetReviewChat } from "./data/example_chats/community-garden-budget-review";
import { communityGardenVolunteerChimeChat } from "./data/example_chats/community-garden-volunteer-chime";
import { onlineShopCheckoutFlowDiagramChat } from "./data/example_chats/online-shop-checkout-flow-diagram";
import { findBrandNameAndDomainChat } from "./data/example_chats/find-brand-name-and-domain";
import { jobsInSwedenChat } from "./data/example_chats/jobs-in-sweden";

export const ALL_EXAMPLE_CHATS: ExampleChat[] = [
  giganticAirplanesChat,
  buildingMaintenanceEmailChat,
  aiWorkshopsMeetupsBerlinChat,
  rightToRepairLawsEuUsChat,
  berlinWeatherBikeCommuteChat,
  ragExplainedVideosChat,
  rustVectorDatabaseReposChat,
  svelteRunesDocsChat,
  familyStaysKyotoChat,
  tedTalkTranscriptSummaryChat,
  balconyPlantReminderChat,
  buckConverters24v5vChat,
  organicGroceriesBerlinChat,
  furnishedApartmentsBerlinChat,
  sqliteStrictTablesSummaryChat,
  pythonSquaresCodeRunChat,
  habitTrackerOnboardingDraftChat,
  chickpeaSpinachProteinDinnersChat,
  nonprofitEventPlanningUseCaseChat,
  lh400FlightStatusCheckChat,
  referenceImage3DModelChat,
  upcomingRemindersListChat,
  cancelTestReminderChat,
  fediverseActivitypubSocialSearchChat,
  pdfViewPageLayoutChat,
  imageVectorizeOpenmatesHeaderChat,
  audioTranscribeVoiceNoteChat,
  usEggPricesDeepResearchChat,
  frameworkStoreReputationCheckChat,
  productTeaserRemotionVideoChat,
  rostockHeavyRainRadarChat,
  housingPolicyDinnerDiscussionChat,
  habitGardenWebApplicationChat,
  printableBenchyPhoneStandModelsChat,
  exampleChatTaskPlanningChecklistChat,
  libraryBookReturnWorkflowChat,
  dashboardSidebarSvgIconsChat,
  vitalFarmsSecFinancialsChat,
  financeCashFlowOverviewChat,
  screenshotToHtmlPricingCardChat,
  deutschlandticketTrainFareBreakdownChat,
  berlinMitteWorkFriendlyRestaurantsChat,
  audioSpeakOpenmatesWelcomeMessageChat,
  plumberMessageEmailPhonePrivacyChat,
  privatePlumberEmailChat,
  socialAppNameDomainSearchChat,
  dampedSineDecayPlotChat,
  communityGardenPlanningMindmapChat,
  beginnerYogaClassesBerlinChat,
  communityGardenVolunteerOnboardingChat,
  booksAfterLeftHandOfDarknessChat,
  mastodonPublicPostThemesChat,
  adjacentCareerPortfolioExperimentsChat,
  netCashFromSuppliedBalancesChat,
  communityGardenWelcomeMelodyChat,
  berlinEnglishSpeakingGpAppointmentsChat,
  communityGardenSunflowerIllustrationChat,
  communityGardenBudgetReviewChat,
  communityGardenVolunteerChimeChat,
  onlineShopCheckoutFlowDiagramChat,
  findBrandNameAndDomainChat,
  jobsInSwedenChat,
].sort((a, b) => a.metadata.order - b.metadata.order);

// Internal deterministic fixtures used by tests and direct hash navigation only.
// Keep these out of normal example listings and SEO pages.
export const INTERNAL_EXAMPLE_CHATS: ExampleChat[] = [
  searchParentPreviewStressTestChat,
  compressionHistoryFixtureChat,
];
