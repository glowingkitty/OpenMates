/**
 * Preview mock data for HealthAppointmentEmbedFullscreen.
 *
 * Represents the fullscreen detail view for a single appointment slot.
 * Uses EntryWithMapTemplate — map requires network access to load tiles.
 * Access at: /dev/preview/embeds/health/HealthAppointmentEmbedFullscreen
 */

/** Default props — Doctolib ophthalmologist appointment slot with GPS coordinates */
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
    provider_platform: "Doctolib",
  },
  onClose: () => {},
  hasPreviousEmbed: false,
  hasNextEmbed: false,
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Telehealth cardiologist with private insurance (Doctolib) */
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
      provider_platform: "Doctolib",
    },
    onClose: () => {},
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => {},
    onNavigateNext: () => {},
  },

  /** Jameda appointment — with rating, price, service, and direct booking URL */
  jameda: {
    appointment: {
      embed_id: "preview-health-appointment-fs-jameda",
      slot_datetime: "2026-04-03T08:00:00",
      name: "Dr. Markus Reinholz",
      speciality: "Hautarzt / Dermatologe",
      address: "Frauenplatz 11\n80331 München",
      gps_coordinates: { latitude: 48.1374, longitude: 11.5733 },
      insurance: "",
      telehealth: false,
      provider: "Jameda",
      provider_platform: "Jameda",
      booking_url: "https://www.jameda.de/booking/datum-auswaehlen/12345/67890/2026-04-03T08:00:00+01:00",
      rating: 5.0,
      rating_count: 125,
      price: 120,
      service_name: "Erstuntersuchung (Neupatient/in)",
    },
    onClose: () => {},
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => {},
    onNavigateNext: () => {},
  },

  /** Jameda appointment — no GPS (map hidden), with service + price */
  jamedaNoMap: {
    appointment: {
      embed_id: "preview-health-appointment-fs-jameda-nomap",
      slot_datetime: "2026-04-04T09:30:00",
      name: "Konrad Witkowski",
      speciality: "Zahnarzt",
      address: "Hoheluftchaussee 2, 20253 Hamburg",
      provider: "Jameda",
      provider_platform: "Jameda",
      booking_url: "https://www.jameda.de/booking/datum-auswaehlen/44444/55555/2026-04-04T09:30:00+01:00",
      rating: 4.8,
      rating_count: 46,
      service_name: "Allgemeine Sprechstunde",
    },
    onClose: () => {},
  },

  /** Appointment without GPS coordinates (map hidden, Doctolib) */
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
      provider_platform: "Doctolib",
    },
    onClose: () => {},
  },

};
