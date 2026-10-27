/**
 * Preview mock data for TravelSearchEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/travel/TravelSearchEmbedFullscreen
 */

const sampleResults = [
	{
		price: '189.00',
		currency: 'EUR',
		transport_method: 'airplane',
		origin: 'Munich (MUC)',
		destination: 'London Heathrow (LHR)',
		departure: '2026-03-15T08:30:00',
		arrival: '2026-03-15T10:00:00',
		duration: '2h 30m',
		stops: 0,
		carriers: ['Lufthansa']
	},
	{
		price: '245.50',
		currency: 'EUR',
		transport_method: 'airplane',
		origin: 'Munich (MUC)',
		destination: 'London Gatwick (LGW)',
		departure: '2026-03-15T14:15:00',
		arrival: '2026-03-15T17:45:00',
		duration: '4h 30m',
		stops: 1,
		carriers: ['British Airways', 'Eurowings']
	}
];

/** Explicit raw data keeps route geometry intact through the preview adapter. */
const overviewResults = [
  { destination: 'Hamburg Central Station', carrier: 'Example Rail', price: '29.90',
    end: { lat: 53.5526, lon: 10.0067 }, via: { lat: 53.14, lon: 12.45 }, arrival: '2026-10-25T10:46:00+01:00', duration: '1h 42m' },
  { destination: 'Leipzig Central Station', carrier: 'ExampleCoach', price: '19.90',
    end: { lat: 51.3455, lon: 12.3818 }, via: { lat: 52.0, lon: 12.6 }, arrival: '2026-10-25T10:18:00+01:00', duration: '1h 14m' },
].map((item) => ({
  type: 'connection', transport_method: 'train', trip_type: 'one_way',
  total_price: item.price, currency: 'EUR', origin: 'Berlin Central Station', destination: item.destination,
  departure: '2026-10-25T09:04:00+01:00', arrival: item.arrival, duration: item.duration,
  stops: 0, carriers: [item.carrier], booking_provider: item.carrier, source_provider: item.carrier,
  booking_url: 'https://example.com/train-booking',
  route_points: [{lat: 52.5251, lon: 13.3694, label: 'Berlin Central Station'}, item.via, { ...item.end, label: item.destination }],
  legs: [{ leg_index: 0, origin: 'Berlin Central Station', destination: item.destination,
    departure: '2026-10-25T09:04:00+01:00', arrival: item.arrival, duration: item.duration, stops: 0,
    segments: [{ mode: 'train', carrier: item.carrier, number: item.carrier === 'Example Rail' ? 'REG 700' : 'REG 123',
      departure_station: 'Berlin Central Station', arrival_station: item.destination,
      departure_time: '2026-10-25T09:04:00+01:00', arrival_time: item.arrival, duration: item.duration,
      departure_latitude: 52.5251, departure_longitude: 13.3694,
      arrival_latitude: item.end.lat, arrival_longitude: item.end.lon,
    }],
  }],
}));

/** Default props — shows a fullscreen travel search results view */
const defaultProps = {
	query: 'Munich -> London, 2026-03-15',
	provider: 'Google',
	status: 'finished' as const,
	results: sampleResults,
	onClose: () => {},
	hasPreviousEmbed: false,
	hasNextEmbed: false
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  routeOverview: {
    data: {
      decodedContent: { query: 'Trains from Berlin', provider: 'Rail providers', transport_method: 'train', results: overviewResults },
      embedData: { status: 'finished' }, attrs: { app_id: 'travel' },
    },
    onClose: () => {},
  },
	/** With navigation arrows */
	withNavigation: {
		...defaultProps,
		hasPreviousEmbed: true,
		hasNextEmbed: true,
		onNavigatePrevious: () => {},
		onNavigateNext: () => {}
	},

	/** Processing state */
	processing: {
		provider: 'Google Flights',
		providers: [{ id: 'google_flights', name: 'Google Flights', icon_url: 'https://www.google.com/favicon.ico' }],
		legs: [{ origin: 'Berlin', destination: 'Paris', date: '2026-04-01' }],
		status: 'processing' as const,
		results: [],
		onClose: () => {}
	},

	/** Finished empty state — header still shows route/date/providers */
	empty: {
		provider: 'Google Flights',
		providers: [{ id: 'google_flights', name: 'Google Flights', icon_url: 'https://www.google.com/favicon.ico' }],
		legs: [{ origin: 'Hamburg', destination: 'Vienna', date: '2026-04-03' }],
		status: 'finished' as const,
		result_count: 0,
		results: [],
		onClose: () => {}
	},

	/** Error state */
	error: {
		query: 'Invalid -> Route',
		provider: 'Google',
		status: 'error' as const,
		errorMessage: 'No connections found for the selected route.',
		results: [],
		onClose: () => {}
	}
};
