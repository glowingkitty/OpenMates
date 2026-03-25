/**
 * Preview mock data for HealthSearchEmbedPreview.
 *
 * Represents the preview card for a health appointment search (parent embed).
 * Access at: /dev/preview/embeds/health/HealthSearchEmbedPreview
 */

/** Default props — finished search with mixed Doctolib + Jameda results */
const defaultProps = {
  id: "preview-health-search-1",
  query: "Ophthalmologist in Munich",
  provider: "Doctolib, Jameda",
  status: "finished" as const,
  results: [
    {
      type: "appointment",
      slot_datetime: "2026-04-03T08:00:00",
      name: "Dr. Markus Reinholz",
      speciality: "Hautarzt / Dermatologe",
      address: "Frauenplatz 11, 80331 München",
      insurance: "",
      telehealth: false,
    },
    {
      type: "appointment",
      slot_datetime: "2026-04-03T10:30:00",
      name: "Dr. Sophie Müller",
      speciality: "Ophthalmologist",
      address: "Maximilianstraße 12, 80539 Munich",
      insurance: "public",
      telehealth: false,
    },
    {
      type: "appointment",
      slot_datetime: "2026-04-05T14:00:00",
      name: "Prof. Dr. Klaus Weber",
      speciality: "Ophthalmologist",
      address: "Leopoldstraße 45, 80802 Munich",
      insurance: "private",
      telehealth: true,
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

  /** Single result */
  singleResult: {
    ...defaultProps,
    id: "preview-health-search-single",
    query: "Neurologist in Hamburg",
    results: [
      {
        type: "appointment",
        slot_datetime: "2026-04-03T10:00:00",
        name: "Jan Philipp Buschmann",
        speciality: "Neurologe",
        address: "Hoheluftchaussee 2, 20253 Hamburg",
      },
    ],
  },
};
