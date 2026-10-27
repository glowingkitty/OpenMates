/**
 * Preview mock data for HealthAppointmentEmbedPreview.
 *
 * Represents a single appointment slot card (child embed rendered inside HealthSearchEmbedFullscreen grid).
 * Access at: /dev/preview/embeds/health/HealthAppointmentEmbedPreview
 */

/** Default props — ExampleClinicA ophthalmologist appointment slot */
const defaultProps = {
  id: "preview-health-appointment-1",
  slotDatetime: "2026-04-03T10:30:00",
  name: "Dr. Sophie Müller",
  speciality: "Ophthalmologist",
  address: "Maximilianstraße 12\n80539 Munich",
  insurance: "private",
  rating: 4.8,
  price: 120,
  providerPlatform: "ExampleClinicA",
  bookingUrl: "https://example.com/fixture",
  gpsCoordinates: {latitude: 48.1397, longitude: 11.5784},
  telehealth: false,
  status: "finished" as const,
  isMobile: false,
  onFullscreen: () => console.log('[Preview] result expanded'),
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  chat: {...defaultProps, resultContext: "chat" as const},
  /** Telehealth appointment slot (ExampleClinicA) */
  telehealth: {
    ...defaultProps,
    id: "preview-health-appointment-telehealth",
    slotDatetime: "2026-04-05T14:00:00",
    name: "Prof. Dr. Klaus Weber",
    speciality: "Cardiologist",
    address: "Leopoldstraße 45\n80802 Munich",
    insurance: "private",
    telehealth: true,
    providerPlatform: "ExampleClinicA",
  },

  /** ExampleClinicB appointment with rating + price */
  ExampleClinicB: {
    ...defaultProps,
    id: "preview-health-appointment-ExampleClinicB",
    slotDatetime: "2026-04-03T08:00:00",
    name: "Dr. Markus Reinholz",
    speciality: "Hautarzt / Dermatologe",
    address: "Frauenplatz 11, 80331 München",
    insurance: "",
    telehealth: false,
    rating: 5.0,
    price: 120,
    providerPlatform: "ExampleClinicB",
  },

  /** ExampleClinicB appointment without price */
  ExampleClinicBNoPrice: {
    ...defaultProps,
    id: "preview-health-appointment-ExampleClinicB-no-price",
    slotDatetime: "2026-04-03T09:30:00",
    name: "Konrad Witkowski",
    speciality: "Zahnarzt",
    address: "Hoheluftchaussee 2, 20253 Hamburg",
    rating: 4.8,
    providerPlatform: "ExampleClinicB",
  },

  /** Mobile layout */
  mobile: {
    ...defaultProps,
    id: "preview-health-appointment-mobile",
    isMobile: true,
  },

  /** Mobile ExampleClinicB */
  mobileExampleClinicB: {
    ...defaultProps,
    id: "preview-health-appointment-mobile-ExampleClinicB",
    isMobile: true,
    name: "Beatrice Kochanek",
    speciality: "Frauenärztin / Gynäkologin",
    address: "Aachener Str. 56, 50674 Köln",
    rating: 5.0,
    price: 80,
    providerPlatform: "ExampleClinicB",
  },
};
