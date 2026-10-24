/**
 * Preview mock data for FitnessSearchEmbedFullscreen.
 *
 * The fullscreen renderer consumes the app-skill grouped result shape through
 * data.decodedContent, matching production embed payloads.
 */

const classResults = [
  {
    id: "appointment-1",
    provider: "ExampleFitness",
    appointment_id: "appointment-1",
    name: "Morning Yoga Flow",
    // Synthetic studio illustrations exercise real provider image fields locally.
    class_image_url: "/preview-fixtures/fitness-yoga-studio.svg",
    venue_image_url: "/preview-fixtures/fitness-hiit-studio.svg",
    category: "Yoga",
    attendance_mode: "onsite",
    date: "2026-07-10",
    time_range: "07:30 - 08:30",
    venue_name: "Yoga Studio Kreuzberg",
    venue_address: "Oranienstr. 1, 10997 Berlin",
    distance_km: 0.9,
    spots_display: "5 spots left",
    plans_required: ["Classic", "Premium", "Max"],
    detail_url: "https://example.com/fixture",
  },
  {
    id: "appointment-2",
    provider: "ExampleFitness",
    appointment_id: "appointment-2",
    name: "HIIT Strength",
    // A class without its own photo uses the organizing venue image.
    venue_image_url: "/preview-fixtures/fitness-hiit-studio.svg",
    category: "HIIT",
    attendance_mode: "onsite",
    date: "2026-07-10",
    time_range: "18:00 - 19:00",
    venue_name: "BEAT81 - Paul-Lincke-Ufer",
    venue_address: "Paul-Lincke-Ufer 19, 10999 Berlin",
    distance_km: 0.7,
    spots_display: "3 spots left",
    plans_required: ["Premium", "Max"],
    detail_url: "https://example.com/fixture",
  },
];

const decodedContent = {
  app_id: "fitness",
  skill_id: "search_classes",
  provider: "ExampleFitness",
  results: [
    {
      id: "classes",
      provider: "ExampleFitness",
      result_count: classResults.length,
      filters: {
        query: "yoga",
        address: "Sorauer Str. 12, Berlin",
        radius_km: 3,
        plan: "all",
        attendance_mode: "onsite",
      },
      summary: "Found 2 fitness source classes in onsite mode. Searched all fitness source plans.",
      results: classResults,
    },
  ],
};

const defaultProps = {
  data: {
    decodedContent,
    embedData: {
      status: "finished",
      skill_id: "search_classes",
    },
    attrs: {
      app_id: "fitness",
    },
  },
  onClose: () => {},
};

export default defaultProps;

export const variants = {
  noImage: {
    data: {
      ...defaultProps.data,
      decodedContent: {
        ...decodedContent,
        results: [{ ...decodedContent.results[0], results: classResults.map(result => ({
          ...result, class_image_url: null, venue_image_url: null,
        })) }],
      },
    },
  },
  empty: {
    data: {
      decodedContent: {
        ...decodedContent,
        results: [
          {
            id: "empty",
            provider: "ExampleFitness",
            result_count: 0,
            filters: decodedContent.results[0].filters,
            summary: "No fitness source classes found.",
            results: [],
          },
        ],
      },
      embedData: {
        status: "finished",
        skill_id: "search_classes",
      },
      attrs: {
        app_id: "fitness",
      },
    },
  },
};
