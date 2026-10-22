/** Synthetic persisted track: this fixture never requests flight/provider data. */
const flight = {
  flight_number: 'OM123', departure_date: '2026-10-20', origin_iata: 'MUC', destination_iata: 'LHR',
  actual_takeoff: '2026-10-20T08:15:00Z', actual_landing: '2026-10-20T09:45:00Z',
  runway_takeoff: '26R', runway_landing: '27L', actual_distance_km: 940, flight_time_minutes: 90,
  fr24_id: 'synthetic-preview', diverted: false,
  tracks: [
    { timestamp: 1792484100, lat: 48.35, lon: 11.77, alt: 0, gspeed: 120 },
    { timestamp: 1792485900, lat: 49.4, lon: 8.5, alt: 35000, gspeed: 450 },
    { timestamp: 1792487700, lat: 50.5, lon: 4.5, alt: 35000, gspeed: 450 },
    { timestamp: 1792489500, lat: 51.47, lon: -0.45, alt: 0, gspeed: 120 },
  ],
};
const defaultProps = { data: { decodedContent: flight }, onClose: () => {} };
export default defaultProps;
export const variants = {
  noTrack: { data: { decodedContent: { ...flight, tracks: [], actual_takeoff: undefined, actual_landing: undefined } }, onClose: () => {} },
  diverted: { data: { decodedContent: { ...flight, diverted: true, actual_destination_iata: 'LGW' } }, onClose: () => {} },
};
