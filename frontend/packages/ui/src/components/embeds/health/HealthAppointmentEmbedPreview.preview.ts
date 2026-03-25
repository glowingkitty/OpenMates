/**
 * Preview mock data for HealthAppointmentEmbedPreview.
 *
 * Represents a single appointment slot card (child embed rendered inside HealthSearchEmbedFullscreen grid).
 * Access at: /dev/preview/embeds/health/HealthAppointmentEmbedPreview
 */

/** Default props — Doctolib ophthalmologist appointment slot */
const defaultProps = {
  id: "preview-health-appointment-1",
  slotDatetime: "2026-04-03T10:30:00",
  name: "Dr. Sophie Müller",
  speciality: "Ophthalmologist",
  address: "Maximilianstraße 12\n80539 Munich",
  insurance: "public",
  telehealth: false,
  status: "finished" as const,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Telehealth appointment slot (Doctolib) */
  telehealth: {
    ...defaultProps,
    id: "preview-health-appointment-telehealth",
    slotDatetime: "2026-04-05T14:00:00",
    name: "Prof. Dr. Klaus Weber",
    speciality: "Cardiologist",
    address: "Leopoldstraße 45\n80802 Munich",
    insurance: "private",
    telehealth: true,
    providerPlatform: "Doctolib",
  },

  /** Jameda appointment with rating + price */
  jameda: {
    ...defaultProps,
    id: "preview-health-appointment-jameda",
    slotDatetime: "2026-04-03T08:00:00",
    name: "Dr. Markus Reinholz",
    speciality: "Hautarzt / Dermatologe",
    address: "Frauenplatz 11, 80331 München",
    insurance: "",
    telehealth: false,
    rating: 5.0,
    price: 120,
    providerPlatform: "Jameda",
  },

  /** Jameda appointment without price */
  jamedaNoPrice: {
    ...defaultProps,
    id: "preview-health-appointment-jameda-no-price",
    slotDatetime: "2026-04-03T09:30:00",
    name: "Konrad Witkowski",
    speciality: "Zahnarzt",
    address: "Hoheluftchaussee 2, 20253 Hamburg",
    rating: 4.8,
    providerPlatform: "Jameda",
  },

  /** Mobile layout */
  mobile: {
    ...defaultProps,
    id: "preview-health-appointment-mobile",
    isMobile: true,
  },

  /** Mobile Jameda */
  mobileJameda: {
    ...defaultProps,
    id: "preview-health-appointment-mobile-jameda",
    isMobile: true,
    name: "Beatrice Kochanek",
    speciality: "Frauenärztin / Gynäkologin",
    address: "Aachener Str. 56, 50674 Köln",
    rating: 5.0,
    price: 80,
    providerPlatform: "Jameda",
  },
};
