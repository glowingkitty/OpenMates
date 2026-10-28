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
import { rightToRepairLawsEuUsChat } from "./data/example_chats/right-to-repair-laws-eu-us";
import { berlinWeatherBikeCommuteChat } from "./data/example_chats/berlin-weather-bike-commute";
import { ragExplainedVideosChat } from "./data/example_chats/rag-explained-videos";
import { rustVectorDatabaseReposChat } from "./data/example_chats/rust-vector-database-repos";
import { svelteRunesDocsChat } from "./data/example_chats/svelte-runes-docs";
import { balconyPlantReminderChat } from "./data/example_chats/balcony-plant-reminder";
import { vegetarianRecipesFromFridgeVegetablesChat } from "./data/example_chats/vegetarian-recipes-from-fridge-vegetables";
import { searchParentPreviewStressTestChat } from "./data/example_chats/search-parent-preview-stress-test";
import { housingPolicyDinnerDiscussionChat } from "./data/example_chats/housing-policy-dinner-discussion";
import { habitGardenWebApplicationChat } from "./data/example_chats/habit-garden-web-application";
import { dashboardSidebarSvgIconsChat } from "./data/example_chats/dashboard-sidebar-svg-icons";
import { vitalFarmsSecFinancialsChat } from "./data/example_chats/vital-farms-sec-financials";
import { financeCashFlowOverviewChat } from "./data/example_chats/finance-cash-flow-overview";
import { screenshotToHtmlPricingCardChat } from "./data/example_chats/screenshot-to-html-pricing-card";
import { berlinMitteWorkFriendlyRestaurantsChat } from "./data/example_chats/berlin-mitte-work-friendly-restaurants";
import { privatePlumberEmailChat } from "./data/example_chats/private-plumber-email";
import { dampedSineDecayPlotChat } from "./data/example_chats/damped-sine-decay-plot";
import { communityGardenPlanningMindmapChat } from "./data/example_chats/community-garden-planning-mindmap";
import { communityGardenVolunteerOnboardingChat } from "./data/example_chats/community-garden-volunteer-onboarding";
import { booksAfterLeftHandOfDarknessChat } from "./data/example_chats/books-after-left-hand-of-darkness";
import { mastodonPublicPostThemesChat } from "./data/example_chats/mastodon-public-post-themes";
import { adjacentCareerPortfolioExperimentsChat } from "./data/example_chats/adjacent-career-portfolio-experiments";
import { netCashFromSuppliedBalancesChat } from "./data/example_chats/net-cash-from-supplied-balances";
import { communityGardenWelcomeMelodyChat } from "./data/example_chats/community-garden-welcome-melody";
import { communityGardenSunflowerIllustrationChat } from "./data/example_chats/community-garden-sunflower-illustration";
import { communityGardenBudgetReviewChat } from "./data/example_chats/community-garden-budget-review";
import { communityGardenVolunteerChimeChat } from "./data/example_chats/community-garden-volunteer-chime";
import { onlineShopCheckoutFlowDiagramChat } from "./data/example_chats/online-shop-checkout-flow-diagram";
import { browseExampleDomainChat } from "./data/example_chats/browse-example-domain";
import { browseHeadingJsonChat } from "./data/example_chats/browse-heading-json";

export const ALL_EXAMPLE_CHATS: ExampleChat[] = [
  giganticAirplanesChat,
  buildingMaintenanceEmailChat,
  rightToRepairLawsEuUsChat,
  berlinWeatherBikeCommuteChat,
  ragExplainedVideosChat,
  rustVectorDatabaseReposChat,
  svelteRunesDocsChat,
  balconyPlantReminderChat,
  vegetarianRecipesFromFridgeVegetablesChat,
  housingPolicyDinnerDiscussionChat,
  habitGardenWebApplicationChat,
  dashboardSidebarSvgIconsChat,
  vitalFarmsSecFinancialsChat,
  financeCashFlowOverviewChat,
  screenshotToHtmlPricingCardChat,
  berlinMitteWorkFriendlyRestaurantsChat,
  privatePlumberEmailChat,
  dampedSineDecayPlotChat,
  communityGardenPlanningMindmapChat,
  communityGardenVolunteerOnboardingChat,
  booksAfterLeftHandOfDarknessChat,
  mastodonPublicPostThemesChat,
  adjacentCareerPortfolioExperimentsChat,
  netCashFromSuppliedBalancesChat,
  communityGardenWelcomeMelodyChat,
  communityGardenSunflowerIllustrationChat,
  communityGardenBudgetReviewChat,
  communityGardenVolunteerChimeChat,
  onlineShopCheckoutFlowDiagramChat,
  browseExampleDomainChat,
  browseHeadingJsonChat,
].sort((a, b) => a.metadata.order - b.metadata.order);

// Internal deterministic fixtures used by tests and direct hash navigation only.
// Keep these out of normal example listings and SEO pages.
export const INTERNAL_EXAMPLE_CHATS: ExampleChat[] = [
  searchParentPreviewStressTestChat,
  compressionHistoryFixtureChat,
];
