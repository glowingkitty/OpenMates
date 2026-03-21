/**
 * Preview mock data for HealthAppointmentEmbedPreview.
 *
 * Represents a single appointment slot card (child embed rendered inside HealthSearchEmbedFullscreen grid).
 * Access at: /dev/preview/embeds/health/HealthAppointmentEmbedPreview
 */

/** Default props — ophthalmologist appointment slot */
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
  /** Telehealth appointment slot */
  telehealth: {
    ...defaultProps,
    id: "preview-health-appointment-telehealth",
    slotDatetime: "2026-04-05T14:00:00",
    name: "Prof. Dr. Klaus Weber",
    speciality: "Cardiologist",
    address: "Leopoldstraße 45\n80802 Munich",
    insurance: "private",
    telehealth: true,
  },

  /** Mobile layout */
  mobile: {
    ...defaultProps,
    id: "preview-health-appointment-mobile",
    isMobile: true,
  },
};
