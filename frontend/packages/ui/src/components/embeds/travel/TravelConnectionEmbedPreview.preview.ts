/**
 * Preview mock data for TravelConnectionEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/travel/TravelConnectionEmbedPreview
 */

/** Default props — shows a finished flight connection card */
const defaultProps = {
	id: 'preview-travel-connection-1',
	connection: { origin_country_code: 'DE', destination_country_code: 'GB', legs: [{ origin: 'Munich (MUC)', destination: 'London Heathrow (LHR)', departure: '2026-03-15T08:30:00', arrival: '2026-03-15T10:00:00', duration: '2h 30m', segments: [{ departure_is_daytime: true, arrival_is_daytime: true }] }], route_points: [{lat: 48.3537, lon: 11.775}, {lat: 51.47, lon: -0.4543}] },
	price: '189.00',
	currency: 'EUR',
	transportMethod: 'airplane',
	tripType: 'one_way',
	origin: 'Munich (MUC)',
	destination: 'London Heathrow (LHR)',
	departure: '2026-03-15T08:30:00',
	arrival: '2026-03-15T10:00:00',
	duration: '2h 30m',
	stops: 0,
	carriers: ['Lufthansa'],
	bookingProvider: 'Lufthansa',
	carrierCodes: ['LH'],
	bookableSeats: 4,
	isCheapest: true,
	status: 'finished' as const,
	isMobile: false,
	onFullscreen: () => console.info('[Preview] travel/event result expanded')
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  brokenCarrier: {
    ...defaultProps, transportMethod: 'train', bookingProvider: 'Rail provider', carriers: ['Rail provider'], carrierCodes: [],
    airlineLogo: '/missing-carrier-fixture.png',
  },
  roundTripItinerary: {
    ...defaultProps,
    tripType: 'round_trip',
    connection: { origin_country_code: 'DE', destination_country_code: 'GB', legs: [
      { origin: 'Munich (MUC)', destination: 'London Heathrow (LHR)', departure: '2026-03-15T08:30:00', arrival: '2026-03-15T10:00:00', duration: '2h 30m', segments: [{ departure_is_daytime: true, arrival_is_daytime: true }] },
      { origin: 'London Heathrow (LHR)', destination: 'Munich (MUC)', departure: '2026-03-22T18:00:00', arrival: '2026-03-22T20:30:00', duration: '1h 30m', segments: [{ departure_is_daytime: false, arrival_is_daytime: false }] },
    ], route_points: [{lat: 48.3537, lon: 11.775}, {lat: 51.47, lon: -0.4543}] },
  },
  trainRealtime: {
    ...defaultProps, transportMethod: 'train', bookingProvider: 'Example Rail', airlineLogo: '/icons/server.svg',
    origin: 'Berlin Central Station', destination: 'Hamburg Central Station',
    departure: '2026-03-15T09:04:00+01:00', arrival: '2026-03-15T10:46:00+01:00', duration: '1h 42m',
    connection: { legs: [{
      origin: 'Berlin Central Station', destination: 'Hamburg Central Station',
      departure: '2026-03-15T09:04:00+01:00', arrival: '2026-03-15T10:46:00+01:00',
      segments: [{ departure_latitude: 52.525, departure_longitude: 13.369, arrival_latitude: 53.553, arrival_longitude: 10.007 }],
    }] },
    carriers: ['Example Rail'], carrierCodes: [], arrivalDelayMinutes: 12,
    optimization: { optimized_by: 'openmates', badge: 'Optimized by OpenMates' },
  },
  baggageExcluded: { ...defaultProps, connection: { ...defaultProps.connection, baggage_included: false } },
  baggageIncluded: { ...defaultProps, connection: { ...defaultProps.connection, baggage_included: true } },
  baggageConflicting: { ...defaultProps, connection: { ...defaultProps.connection, baggage_included: true, checked_baggage_included: false } },
  baggageUnknown: { ...defaultProps },
  noRouteGeometry: { ...defaultProps, connection: {} },
  chat: { ...defaultProps, resultContext: 'chat' as const },
	/** Multi-stop connection */
	multiStop: {
		...defaultProps,
		connection: undefined,
		id: 'preview-travel-connection-multistop',
		price: '245.50',
		destination: 'London Gatwick (LGW)',
		departure: '2026-03-15T14:15:00',
		arrival: '2026-03-15T17:45:00',
		duration: '4h 30m',
		stops: 1,
		carriers: ['British Airways', 'Eurowings'],
		carrierCodes: ['BA', 'EW'],
		bookableSeats: 2,
		isCheapest: false
	},

	/** Round trip */
	roundTrip: {
		...defaultProps,
		id: 'preview-travel-connection-roundtrip',
		tripType: 'round_trip',
		price: '349.00'
	},

	/** Processing state */
	processing: {
		id: 'preview-travel-connection-processing',
		status: 'processing' as const,
		isMobile: false
	},

	/** Error state */
	error: {
		id: 'preview-travel-connection-error',
		status: 'error' as const,
		isMobile: false
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-travel-connection-mobile',
		isMobile: true
	},

	/** Train connection with stored source icon and explicit times */
	exampleRail: {
		...defaultProps,
		connection: undefined,
		id: 'preview-travel-connection-db',
		transportMethod: 'train',
		origin: 'Berlin Central Station',
		destination: 'Hamburg Central Station',
		departure: '2026-03-15T09:04:00+01:00',
		arrival: '2026-03-15T10:46:00+01:00',
		duration: '1h 42m',
		carriers: ['Example Rail'],
		bookingProvider: 'Example Rail',
		airlineLogo: '/icons/server.svg',
		carrierCodes: []
	},

	/** ExampleCoach connection with stored source icon and explicit times */
	ExampleCoach: {
		...defaultProps,
		connection: undefined,
		id: 'preview-travel-connection-ExampleCoach',
		transportMethod: 'train',
		origin: 'Berlin Central Station',
		destination: 'Stuttgart Flughafen/Messe',
		departure: '2026-03-15T07:37:00+01:00',
		arrival: '2026-03-15T14:22:00+01:00',
		duration: '6h 45m',
		stops: 1,
		carriers: ['ExampleCoach', 'ExampleCoach'],
		bookingProvider: 'ExampleCoach / ExampleCoach',
		carrierCodes: []
	}
};
