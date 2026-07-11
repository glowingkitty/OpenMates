/**
 * Preview fixtures for a single Urban Sports fitness result card.
 *
 * These direct component props cover both location and class registry aliases
 * used by the generated embed registry and generic component preview route.
 */

const defaultProps = {
  id: "fitness-result-preview",
  result: {
    id: "appointment-1",
    name: "Morning Yoga Flow",
    date: "2026-07-10",
    time_range: "07:30 - 08:30",
    venue_name: "Yoga Studio Kreuzberg",
    venue_address: "Oranienstr. 1, 10997 Berlin",
    distance_km: 0.9,
    spots_display: "5 spots left",
    plans_required: ["Classic", "Premium", "Max"],
  },
  skillId: "search_classes" as const,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  location: {
    ...defaultProps,
    result: {
      id: "location-1",
      name: "Yoga Studio Kreuzberg",
      address: "Oranienstr. 1, 10997 Berlin",
      distance_km: 0.9,
      disciplines: ["Yoga", "Pilates"],
    },
    skillId: "search_locations" as const,
  },
};
