/**
 * Preview mock data for HealthSearchEmbedPreview.
 *
 * Represents the preview card for a health appointment search (parent embed).
 * Access at: /dev/preview/embeds/health/HealthSearchEmbedPreview
 */

/** Default props — finished search with multiple results */
const defaultProps = {
  id: "preview-health-search-1",
  query: "Ophthalmologist in Munich",
  provider: "Doctolib",
  status: "finished" as const,
  results: [
    {
      type: "appointment",
      name: "Dr. Sophie Müller",
      speciality: "Ophthalmologist",
      address: "Maximilianstraße 12, 80539 Munich",
      slots_count: 3,
      next_slot: "2026-04-03T10:30:00",
      insurance: "public",
      telehealth: false,
    },
    {
      type: "appointment",
      name: "Prof. Dr. Klaus Weber",
      speciality: "Ophthalmologist",
      address: "Leopoldstraße 45, 80802 Munich",
      slots_count: 5,
      next_slot: "2026-04-05T14:00:00",
      insurance: "private",
      telehealth: true,
    },
    {
      type: "appointment",
      name: "Dr. Anna Schmidt",
      speciality: "Ophthalmologist",
      address: "Sendlinger Straße 8, 80331 Munich",
      slots_count: 0,
      insurance: "public",
      telehealth: false,
    },
  ],
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Processing state */
  processing: {
    ...defaultProps,
    id: "preview-health-search-processing",
    status: "processing" as const,
    results: [],
  },

  /** Error state */
  error: {
    ...defaultProps,
    id: "preview-health-search-error",
    status: "error" as const,
    results: [],
  },

  /** Mobile layout */
  mobile: {
    ...defaultProps,
    id: "preview-health-search-mobile",
    isMobile: true,
  },
};
