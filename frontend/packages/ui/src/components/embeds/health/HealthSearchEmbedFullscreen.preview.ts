/**
 * Preview mock data for HealthSearchEmbedFullscreen.
 *
 * Represents the fullscreen grid of doctor appointment results.
 * Child embeds (appointment cards) are provided inline via `results` prop.
 * Access at: /dev/preview/embeds/health/HealthSearchEmbedFullscreen
 */

/** Default props — finished search showing 3 doctor results */
const defaultProps = {
  query: "Ophthalmologist in Munich",
  provider: "Doctolib",
  status: "finished" as const,
  results: [
    {
      embed_id: "preview-health-fs-result-1",
      type: "appointment",
      name: "Dr. Sophie Müller",
      speciality: "Ophthalmologist",
      address: "Maximilianstraße 12, 80539 Munich",
      slots_count: 3,
      next_slot: "2026-04-03T10:30:00",
      slots: [
        { datetime: "2026-04-03T10:30:00" },
        { datetime: "2026-04-03T14:00:00" },
        { datetime: "2026-04-07T09:15:00" },
      ],
      insurance: "public",
      telehealth: false,
      practice_url:
        "https://www.doctolib.de/ophtalmologe/munich/sophie-mueller",
      provider: "Doctolib",
    },
    {
      embed_id: "preview-health-fs-result-2",
      type: "appointment",
      name: "Prof. Dr. Klaus Weber",
      speciality: "Ophthalmologist",
      address: "Leopoldstraße 45, 80802 Munich",
      slots_count: 5,
      next_slot: "2026-04-05T14:00:00",
      slots: [
        { datetime: "2026-04-05T14:00:00" },
        { datetime: "2026-04-06T11:30:00" },
        { datetime: "2026-04-08T09:00:00" },
      ],
      insurance: "private",
      telehealth: true,
      practice_url: "https://www.doctolib.de/cardiologue/munich/klaus-weber",
      provider: "Doctolib",
    },
    {
      embed_id: "preview-health-fs-result-3",
      type: "appointment",
      name: "Dr. Anna Schmidt",
      speciality: "Ophthalmologist",
      address: "Sendlinger Straße 8, 80331 Munich",
      slots_count: 0,
      insurance: "public",
      telehealth: false,
      practice_url: "https://www.doctolib.de/ophtalmologe/munich/anna-schmidt",
      provider: "Doctolib",
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
};
