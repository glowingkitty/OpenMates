/**
 * Preview mock data for FitnessSearchEmbedFullscreen.
 *
 * The fullscreen renderer consumes the app-skill grouped result shape through
 * data.decodedContent, matching production embed payloads.
 */

const classResults = [
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

const decodedContent = {
  app_id: "fitness",
  skill_id: "search_classes",
  provider: "Urban Sports Club",
  results: [
    {
      id: "classes",
      provider: "Urban Sports Club",
      result_count: classResults.length,
      filters: {
        query: "yoga",
        address: "Sorauer Str. 12, Berlin",
        radius_km: 3,
        plan: "all",
        attendance_mode: "onsite",
      },
      summary: "Found 2 Urban Sports classes in onsite mode. Searched all Urban Sports plans.",
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
  empty: {
    data: {
      decodedContent: {
        ...decodedContent,
        results: [
          {
            id: "empty",
            provider: "Urban Sports Club",
            result_count: 0,
            filters: decodedContent.results[0].filters,
            summary: "No Urban Sports classes found.",
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
