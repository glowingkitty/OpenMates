/** Single fitness location/class details; no account or live provider needed. */
const result = {
  id: 'fitness-class-design', name: 'Morning Yoga Flow', skill_id: 'search_classes',
  date: '2026-10-26', time_range: '07:30 - 08:30', venue_name: 'Yoga Studio Kreuzberg',
  venue_address: 'Oranienstr. 1, 10997 Berlin', venue_lat: 52.502, venue_lon: 13.421,
  image_url: '/preview-fixtures/fitness-yoga-studio.svg', distance_km: 0.9, spots_display: '5 spots left',
  plans_required: ['Classic', 'Premium'], disciplines: ['Yoga', 'Pilates'], attendance_mode: 'In person',
  detail_url: 'https://example.com/fixture',
};
const defaultProps = { data: { decodedContent: result }, embedId: 'fitness-class-design', onClose: () => {} };
export default defaultProps;
export const variants = {
  classImage: { data: { decodedContent: { ...result, image_url: null, class_image_url: '/preview-fixtures/fitness-yoga-studio.svg', venue_image_url: '/preview-fixtures/fitness-hiit-studio.svg' } } },
  venueImage: { data: { decodedContent: { ...result, image_url: null, venue_image_url: '/preview-fixtures/fitness-hiit-studio.svg' } } },
  zero: { data: { decodedContent: { ...result, distance_km: 0, spots_display: '0 spots left' } } },
  noImage: { data: { decodedContent: { ...result, image_url: null } } },
  minimal: { data: { decodedContent: { id: 'fitness-minimal', name: 'Local studio', skill_id: 'search_locations' } } },
  location: { data: { decodedContent: { ...result, skill_id: 'search_locations', name: result.venue_name, date: undefined, time_range: undefined } } },
};
