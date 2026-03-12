/**
 * Preview mock data for HealthAppointmentEmbedPreview.
 *
 * Represents a single doctor card (child embed rendered inside HealthSearchEmbedFullscreen grid).
 * Access at: /dev/preview/embeds/health/HealthAppointmentEmbedPreview
 */

/** Default props — ophthalmologist with available slots */
const defaultProps = {
  id: "preview-health-appointment-1",
  name: "Dr. Sophie Müller",
  speciality: "Ophthalmologist",
  address: "Maximilianstraße 12\n80539 Munich",
  slotsCount: 3,
  nextSlot: "2026-04-03T10:30:00",
  insurance: "public",
  telehealth: false,
  status: "finished" as const,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Doctor with telehealth option */
  telehealth: {
    ...defaultProps,
    id: "preview-health-appointment-telehealth",
    name: "Prof. Dr. Klaus Weber",
    speciality: "Cardiologist",
    address: "Leopoldstraße 45\n80802 Munich",
    slotsCount: 5,
    nextSlot: "2026-04-05T14:00:00",
    insurance: "private",
    telehealth: true,
  },

  /** No slots available */
  noSlots: {
    ...defaultProps,
    id: "preview-health-appointment-noslots",
    name: "Dr. Hans Braun",
    speciality: "Dermatologist",
    address: "Sendlinger Straße 8\n80331 Munich",
    slotsCount: 0,
    nextSlot: undefined,
    insurance: "public",
    telehealth: false,
  },

  /** Mobile layout */
  mobile: {
    ...defaultProps,
    id: "preview-health-appointment-mobile",
    isMobile: true,
  },
};
