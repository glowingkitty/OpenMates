/**
 * Preview mock data for HealthAppointmentEmbedFullscreen.
 *
 * Uses the data-driven shape (EmbedFullscreenRawData) — the appointment fields
 * are flattened into decodedContent, matching what the component extracts via
 * `data.decodedContent`. The old `{ appointment: {...} }` direct-prop format
 * was removed in OPE-413 after the OPE-276 migration to data-driven routing.
 *
 * Uses EntryWithMapTemplate — map requires network access to load tiles.
 * Access at: /dev/preview/embeds/health/HealthAppointmentEmbedFullscreen
 */

/** Default props — ExampleClinicA ophthalmologist appointment slot with GPS coordinates */
const defaultProps = {
  data: {
    decodedContent: {
      embed_id: "preview-health-appointment-fs-1",
      slot_datetime: "2026-04-03T10:30:00",
      name: "Dr. Sophie Müller",
      speciality: "Ophthalmologist",
      address: "Maximilianstraße 12\n80539 Munich",
      gps_coordinates: { latitude: 48.1397, longitude: 11.5784 },
      insurance: "private",
      rating: 4.8,
      rating_count: 46,
      price: 120,
      description: "Ophthalmology consultations and preventive eye care in a welcoming practice.",
      telehealth: false,
      practice_url: "https://example.com/fixture",
      provider: "ExampleClinicA",
      provider_platform: "ExampleClinicA",
    },
    embedData: { status: "finished" },
    attrs: { app_id: "health" },
  },
  onClose: () => {},
  hasPreviousEmbed: false,
  hasNextEmbed: false,
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  unknownInsurance: { data: { ...defaultProps.data, decodedContent: {...defaultProps.data.decodedContent, insurance: "unknown"} } },
  /** Telehealth cardiologist with private insurance (ExampleClinicA) */
  telehealth: {
    data: {
      decodedContent: {
        embed_id: "preview-health-appointment-fs-telehealth",
        slot_datetime: "2026-04-05T14:00:00",
        name: "Prof. Dr. Klaus Weber",
        speciality: "Cardiologist",
        address: "Leopoldstraße 45\n80802 Munich",
        gps_coordinates: { latitude: 48.1584, longitude: 11.5798 },
        insurance: "private",
        telehealth: true,
        practice_url: "https://example.com/fixture",
        provider: "ExampleClinicA",
        provider_platform: "ExampleClinicA",
      },
      embedData: { status: "finished" },
      attrs: { app_id: "health" },
    },
    onClose: () => {},
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => {},
    onNavigateNext: () => {},
  },

  /** ExampleClinicB appointment — with rating, price, service, and direct booking URL */
  ExampleClinicB: {
    data: {
      decodedContent: {
        embed_id: "preview-health-appointment-fs-ExampleClinicB",
        slot_datetime: "2026-04-03T08:00:00",
        name: "Dr. Markus Reinholz",
        speciality: "Hautarzt / Dermatologe",
        address: "Frauenplatz 11\n80331 München",
        gps_coordinates: { latitude: 48.1374, longitude: 11.5733 },
        insurance: "",
        telehealth: false,
        provider: "ExampleClinicB",
        provider_platform: "ExampleClinicB",
        booking_url: "https://example.com/fixture",
        rating: 5.0,
        rating_count: 125,
        price: 120,
        service_name: "Erstuntersuchung (Neupatient/in)",
      },
      embedData: { status: "finished" },
      attrs: { app_id: "health" },
    },
    onClose: () => {},
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => {},
    onNavigateNext: () => {},
  },

  /** ExampleClinicB appointment — no GPS (map hidden), with service + price */
  ExampleClinicBNoMap: {
    data: {
      decodedContent: {
        embed_id: "preview-health-appointment-fs-ExampleClinicB-nomap",
        slot_datetime: "2026-04-04T09:30:00",
        name: "Konrad Witkowski",
        speciality: "Zahnarzt",
        address: "Hoheluftchaussee 2, 20253 Hamburg",
        provider: "ExampleClinicB",
        provider_platform: "ExampleClinicB",
        booking_url: "https://example.com/fixture",
        rating: 4.8,
        rating_count: 46,
        service_name: "Allgemeine Sprechstunde",
      },
      embedData: { status: "finished" },
      attrs: { app_id: "health" },
    },
    onClose: () => {},
  },

  /** Appointment without GPS coordinates (map hidden, ExampleClinicA) */
  noMap: {
    data: {
      decodedContent: {
        embed_id: "preview-health-appointment-fs-nomap",
        slot_datetime: "2026-04-04T08:30:00",
        name: "Dr. Anna Schmidt",
        speciality: "General Practitioner",
        address: "Sendlinger Straße 8, 80331 Munich",
        insurance: "public",
        telehealth: false,
        practice_url:
          "https://example.com/fixture",
        provider: "ExampleClinicA",
        provider_platform: "ExampleClinicA",
      },
      embedData: { status: "finished" },
      attrs: { app_id: "health" },
    },
    onClose: () => {},
  },

};
