/**
 * Preview mock data for HealthAppointmentEmbedFullscreen.
 *
 * Represents the fullscreen detail view for a single appointment slot.
 * Uses EntryWithMapTemplate — map requires network access to load tiles.
 * Access at: /dev/preview/embeds/health/HealthAppointmentEmbedFullscreen
 */

/** Default props — ophthalmologist appointment slot with GPS coordinates */
const defaultProps = {
  appointment: {
    embed_id: "preview-health-appointment-fs-1",
    slot_datetime: "2026-04-03T10:30:00",
    name: "Dr. Sophie Müller",
    speciality: "Ophthalmologist",
    address: "Maximilianstraße 12\n80539 Munich",
    gps_coordinates: { latitude: 48.1397, longitude: 11.5784 },
    insurance: "public",
    telehealth: false,
    practice_url: "https://www.doctolib.de/ophtalmologe/munich/sophie-mueller",
    provider: "Doctolib",
  },
  onClose: () => {},
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
      slot_datetime: "2026-04-05T14:00:00",
      name: "Prof. Dr. Klaus Weber",
      speciality: "Cardiologist",
      address: "Leopoldstraße 45\n80802 Munich",
      gps_coordinates: { latitude: 48.1584, longitude: 11.5798 },
      insurance: "private",
      telehealth: true,
      practice_url: "https://www.doctolib.de/cardiologue/munich/klaus-weber",
      provider: "Doctolib",
    },
    onClose: () => {},
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => {},
    onNavigateNext: () => {},
  },

  /** Appointment without GPS coordinates (map hidden) */
  noMap: {
    appointment: {
      embed_id: "preview-health-appointment-fs-nomap",
      slot_datetime: "2026-04-04T08:30:00",
      name: "Dr. Anna Schmidt",
      speciality: "General Practitioner",
      address: "Sendlinger Straße 8, 80331 Munich",
      insurance: "public",
      telehealth: false,
      practice_url:
        "https://www.doctolib.de/medecin-generaliste/munich/anna-schmidt",
      provider: "Doctolib",
    },
    onClose: () => {},
  },

  /** Legacy per-doctor format with multiple slots (backward compat) */
  legacyMultiSlot: {
    appointment: {
      embed_id: "preview-health-appointment-fs-legacy",
      name: "Dr. Hans Braun",
      speciality: "Dermatologist",
      address: "Sendlinger Straße 8\n80331 Munich",
      gps_coordinates: { latitude: 48.1351, longitude: 11.5820 },
      slots_count: 3,
      next_slot: "2026-04-03T10:30:00",
      slots: [
        { datetime: "2026-04-03T10:30:00" },
        { datetime: "2026-04-03T14:00:00" },
        { datetime: "2026-04-07T09:15:00" },
      ],
      insurance: "public",
      telehealth: false,
      practice_url: "https://www.doctolib.de/dermatologe/munich/hans-braun",
      provider: "Doctolib",
    },
    onClose: () => {},
  },
};
