/**
 * Preview mock data for HealthSearchEmbedFullscreen.
 *
 * Represents the fullscreen grid of doctor appointment results.
 * Child embeds (appointment cards) are provided inline via `results` prop.
 * Access at: /dev/preview/embeds/health/HealthSearchEmbedFullscreen
 */

/** Default props — finished search with mixed Doctolib + Jameda results */
const defaultProps = {
  query: "Ophthalmologist in Munich",
  provider: "Doctolib, Jameda",
  status: "finished" as const,
  results: [
    {
      embed_id: "preview-health-fs-result-1",
      type: "appointment",
      slot_datetime: "2026-04-03T08:00:00",
      name: "Dr. Markus Reinholz",
      speciality: "Hautarzt / Dermatologe",
      address: "Frauenplatz 11, 80331 München",
      gps_coordinates: { latitude: 48.1374, longitude: 11.5733 },
      insurance: "",
      telehealth: false,
      provider_platform: "Jameda",
      booking_url: "https://www.jameda.de/booking/datum-auswaehlen/12345/67890/2026-04-03T08:00:00+01:00",
      rating: 5.0,
      rating_count: 125,
      price: 120,
      service_name: "Erstuntersuchung (Neupatient/in)",
    },
    {
      embed_id: "preview-health-fs-result-2",
      type: "appointment",
      slot_datetime: "2026-04-03T10:30:00",
      name: "Dr. Sophie Müller",
      speciality: "Ophthalmologist",
      address: "Maximilianstraße 12, 80539 Munich",
      gps_coordinates: { latitude: 48.1397, longitude: 11.5784 },
      slots_count: 3,
      next_slot: "2026-04-03T10:30:00",
      insurance: "public",
      telehealth: false,
      practice_url: "https://www.doctolib.de/ophtalmologe/munich/sophie-mueller",
      provider_platform: "Doctolib",
    },
    {
      embed_id: "preview-health-fs-result-3",
      type: "appointment",
      slot_datetime: "2026-04-03T14:00:00",
      name: "Prof. Dr. Klaus Weber",
      speciality: "Ophthalmologist",
      address: "Leopoldstraße 45, 80802 Munich",
      slots_count: 5,
      next_slot: "2026-04-05T14:00:00",
      insurance: "private",
      telehealth: true,
      practice_url: "https://www.doctolib.de/cardiologue/munich/klaus-weber",
      provider_platform: "Doctolib",
    },
    {
      embed_id: "preview-health-fs-result-4",
      type: "appointment",
      slot_datetime: "2026-04-04T09:30:00",
      name: "Konrad Witkowski",
      speciality: "Zahnarzt",
      address: "Hoheluftchaussee 2, 20253 Hamburg",
      provider_platform: "Jameda",
      booking_url: "https://www.jameda.de/booking/datum-auswaehlen/44444/55555/2026-04-04T09:30:00+01:00",
      rating: 4.8,
      rating_count: 46,
      service_name: "Allgemeine Sprechstunde",
    },
    {
      embed_id: "preview-health-fs-result-5",
      type: "appointment",
      name: "Dr. Anna Schmidt",
      speciality: "Ophthalmologist",
      address: "Sendlinger Straße 8, 80331 Munich",
      slots_count: 0,
      insurance: "public",
      telehealth: false,
      practice_url: "https://www.doctolib.de/ophtalmologe/munich/anna-schmidt",
      provider_platform: "Doctolib",
    },
  ],
  onClose: () => {},
  hasPreviousEmbed: false,
  hasNextEmbed: false,
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Processing state */
  processing: {
    ...defaultProps,
    query: "Cardiologist near me",
    status: "processing" as const,
    results: [],
  },

  /** Error state */
  error: {
    ...defaultProps,
    query: "Specialist search failed",
    status: "error" as const,
    errorMessage: "Could not connect to Doctolib. Please try again.",
    results: [],
  },

  /** Jameda only results */
  jamedaOnly: {
    ...defaultProps,
    query: "Hausarzt in Berlin",
    provider: "Jameda",
    results: [
      {
        embed_id: "preview-health-fs-jam-1",
        type: "appointment",
        slot_datetime: "2026-04-03T09:00:00",
        name: "Ingmar Frank",
        speciality: "Allgemeinmediziner",
        address: "Potsdamer Chaussee 80, Berlin",
        provider_platform: "Jameda",
        booking_url: "https://www.jameda.de/booking/datum-auswaehlen/270886/508647/2026-04-03T09:00:00+01:00",
        rating: 5.0,
        rating_count: 10,
        service_name: "Erstuntersuchung (Neupatient/in)",
      },
      {
        embed_id: "preview-health-fs-jam-2",
        type: "appointment",
        slot_datetime: "2026-04-03T09:10:00",
        name: "Nikolaus Peter Höllen",
        speciality: "Allgemeinmediziner",
        address: "Kyffhäuserstr. 11, Berlin",
        provider_platform: "Jameda",
        booking_url: "https://www.jameda.de/booking/datum-auswaehlen/89012/396782/2026-04-03T09:10:00+01:00",
        rating: 5.0,
        rating_count: 165,
        price: 30,
        service_name: "Allgemeine Sprechstunde",
      },
    ],
  },
};
