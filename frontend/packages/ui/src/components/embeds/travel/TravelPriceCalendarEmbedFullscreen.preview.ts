/**
 * Preview mock data for TravelPriceCalendarEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/travel/TravelPriceCalendarEmbedFullscreen
 */

// results is PriceCalendarResult[] — each item wraps entries[] (calendar days).
// The component reads results[0] as the calendar result containing route info + entries.
const sampleResults = [
  {
    type: "price_calendar",
    origin: "MUC",
    origin_name: "Munich",
    destination: "BCN",
    destination_name: "Barcelona",
    month: "2026-03",
    currency: "EUR",
    cheapest_price: 62,
    most_expensive_price: 155,
    days_with_data: 12,
    entries: [
      { date: "2026-03-01", price: 89 },
      { date: "2026-03-02", price: 95 },
      { date: "2026-03-05", price: 72 },
      { date: "2026-03-08", price: 110 },
      { date: "2026-03-10", price: 65 },
      { date: "2026-03-12", price: 78 },
      { date: "2026-03-15", price: 145 },
      { date: "2026-03-18", price: 62 },
      { date: "2026-03-20", price: 99 },
      { date: "2026-03-22", price: 68 },
      { date: "2026-03-25", price: 120 },
      { date: "2026-03-28", price: 155 },
    ],
  },
];

/** Default props — shows a fullscreen price calendar view */
const defaultProps = {
  query: "Munich -> Barcelona, March 2026",
  status: "finished" as const,
  results: sampleResults,
  onClose: () => console.log("[Preview] Close clicked"),
  hasPreviousEmbed: false,
  hasNextEmbed: false,
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** With navigation arrows */
  withNavigation: {
    ...defaultProps,
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => console.log("[Preview] Navigate previous"),
    onNavigateNext: () => console.log("[Preview] Navigate next"),
  },

  /** Processing state */
  processing: {
    query: "Berlin -> Rome, April 2026",
    status: "processing" as const,
    onClose: () => console.log("[Preview] Close clicked"),
  },

  /** Error state */
  error: {
    query: "Invalid route",
    status: "error" as const,
    errorMessage: "Could not retrieve price calendar for the selected route.",
    results: [],
    onClose: () => console.log("[Preview] Close clicked"),
  },
};
