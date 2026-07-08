/**
 * Preview mock data for FitnessSearchEmbedPreview.
 *
 * Provides stable Urban Sports Club class/location payloads for the dev embed
 * showcase at /dev/preview/embeds/fitness.
 */

const sampleResults = [
  {
    id: "appointment-1",
    provider: "Urban Sports Club",
    appointment_id: "appointment-1",
    name: "Morning Yoga Flow",
    category: "Yoga",
    attendance_mode: "onsite",
    date: "2026-07-10",
    time_range: "07:30 - 08:30",
    venue_name: "Yoga Studio Kreuzberg",
    venue_address: "Oranienstr. 1, 10997 Berlin",
    distance_km: 0.9,
    spots_display: "5 spots left",
    plans_required: ["Classic", "Premium", "Max"],
    detail_url: "https://urbansportsclub.com/en/class-details/appointment-1",
  },
  {
    id: "appointment-2",
    provider: "Urban Sports Club",
    appointment_id: "appointment-2",
    name: "HIIT Strength",
    category: "HIIT",
    attendance_mode: "onsite",
    date: "2026-07-10",
    time_range: "18:00 - 19:00",
    venue_name: "BEAT81 - Paul-Lincke-Ufer",
    venue_address: "Paul-Lincke-Ufer 19, 10999 Berlin",
    distance_km: 0.7,
    spots_display: "3 spots left",
    plans_required: ["Premium", "Max"],
    detail_url: "https://urbansportsclub.com/en/class-details/appointment-2",
  },
];

const defaultProps = {
  id: "preview-fitness-search-classes",
  skillId: "search_classes" as const,
  query: "yoga near Sorauer Str. 12",
  provider: "Urban Sports Club",
  summary: "Found 2 Urban Sports classes in onsite mode. Searched all Urban Sports plans.",
  filters: {
    query: "yoga",
    address: "Sorauer Str. 12, Berlin",
    radius_km: 3,
    plan: "all",
    attendance_mode: "onsite",
  },
  status: "finished" as const,
  results: sampleResults,
  result_count: sampleResults.length,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  processing: {
    ...defaultProps,
    id: "preview-fitness-search-processing",
    status: "processing" as const,
    results: [],
    result_count: 0,
  },
  locations: {
    id: "preview-fitness-search-locations",
    skillId: "search_locations" as const,
    query: "HIIT near Sorauer Str. 12",
    provider: "Urban Sports Club",
    summary: "Found 1 Urban Sports locations. Searched all Urban Sports plans.",
    filters: {
      query: "HIIT",
      address: "Sorauer Str. 12, Berlin",
      radius_km: 2,
      plan: "all",
    },
    status: "finished" as const,
    results: [
      {
        id: "beat81-paul-lincke-ufer",
        provider: "Urban Sports Club",
        venue_id: "beat81-paul-lincke-ufer",
        name: "BEAT81 - Paul-Lincke-Ufer",
        address: "Paul-Lincke-Ufer 19, 10999 Berlin",
        distance_km: 0.7,
        disciplines: ["HIIT", "Strength"],
        plans_required: ["Premium", "Max"],
        url: "https://urbansportsclub.com/en/venues/beat81-paul-lincke-ufer",
      },
    ],
    result_count: 1,
    isMobile: false,
    onFullscreen: () => {},
  },
  mobile: {
    ...defaultProps,
    id: "preview-fitness-search-mobile",
    isMobile: true,
  },
};
