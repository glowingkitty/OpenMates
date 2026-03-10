/**
 * Preview mock data for HealthAppointmentEmbedFullscreen.
 *
 * Represents the fullscreen detail view for a single doctor appointment result.
 * Uses EntryWithMapTemplate — map requires network access to load tiles.
 * Access at: /dev/preview/embeds/health/HealthAppointmentEmbedFullscreen
 */

/** Default props — ophthalmologist with GPS coordinates and multiple slots */
const defaultProps = {
  appointment: {
    embed_id: "preview-health-appointment-fs-1",
    name: "Dr. Sophie Müller",
    speciality: "Ophthalmologist",
    address: "Maximilianstraße 12\n80539 Munich",
    gps_coordinates: { latitude: 48.1397, longitude: 11.5784 },
    slots_count: 3,
    next_slot: "2026-04-03T10:30:00",
    slots: [
      { datetime: "2026-04-03T10:30:00" },
      { datetime: "2026-04-03T14:00:00" },
      { datetime: "2026-04-07T09:15:00" },
    ],
    insurance: "public",
    telehealth: false,
    practice_url: "https://www.doctolib.de/ophtalmologe/munich/sophie-mueller",
    provider: "Doctolib",
  },
  onClose: () => console.log("[Preview] Close clicked"),
  hasPreviousEmbed: false,
  hasNextEmbed: false,
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Telehealth cardiologist with private insurance */
  telehealth: {
    appointment: {
      embed_id: "preview-health-appointment-fs-telehealth",
      name: "Prof. Dr. Klaus Weber",
      speciality: "Cardiologist",
      address: "Leopoldstraße 45\n80802 Munich",
      gps_coordinates: { latitude: 48.1584, longitude: 11.5798 },
      slots_count: 5,
      next_slot: "2026-04-05T14:00:00",
      slots: [
        { datetime: "2026-04-05T14:00:00" },
        { datetime: "2026-04-06T11:30:00" },
        { datetime: "2026-04-08T09:00:00" },
        { datetime: "2026-04-09T15:30:00" },
        { datetime: "2026-04-10T10:00:00" },
      ],
      insurance: "private",
      telehealth: true,
      practice_url: "https://www.doctolib.de/cardiologue/munich/klaus-weber",
      provider: "Doctolib",
    },
    onClose: () => console.log("[Preview] Close clicked"),
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => console.log("[Preview] Navigate previous"),
    onNavigateNext: () => console.log("[Preview] Navigate next"),
  },

  /** Doctor without GPS coordinates (map hidden) */
  noMap: {
    appointment: {
      embed_id: "preview-health-appointment-fs-nomap",
      name: "Dr. Anna Schmidt",
      speciality: "General Practitioner",
      address: "Sendlinger Straße 8, 80331 Munich",
      slots_count: 2,
      next_slot: "2026-04-04T08:30:00",
      slots: [
        { datetime: "2026-04-04T08:30:00" },
        { datetime: "2026-04-04T09:00:00" },
      ],
      insurance: "public",
      telehealth: false,
      practice_url:
        "https://www.doctolib.de/medecin-generaliste/munich/anna-schmidt",
      provider: "Doctolib",
    },
    onClose: () => console.log("[Preview] Close clicked"),
  },
};
