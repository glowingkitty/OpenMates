/**
 * Preview mock data for TravelConnectionEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/travel/TravelConnectionEmbedPreview
 */

/** Default props — shows a finished flight connection card */
const defaultProps = {
	id: 'preview-travel-connection-1',
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
	onFullscreen: () => {}
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Multi-stop connection */
	multiStop: {
		...defaultProps,
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

	/** Train connection with provider favicon and explicit times */
	deutscheBahn: {
		...defaultProps,
		id: 'preview-travel-connection-db',
		transportMethod: 'train',
		origin: 'Berlin Central Station',
		destination: 'Hamburg Central Station',
		departure: '2026-03-15T09:04:00+01:00',
		arrival: '2026-03-15T10:46:00+01:00',
		duration: '1h 42m',
		carriers: ['Deutsche Bahn'],
		bookingProvider: 'Deutsche Bahn',
		carrierCodes: []
	},

	/** Flix connection with provider favicon and explicit times */
	flixTrain: {
		...defaultProps,
		id: 'preview-travel-connection-flix',
		transportMethod: 'train',
		origin: 'Berlin Central Station',
		destination: 'Stuttgart Flughafen/Messe',
		departure: '2026-03-15T07:37:00+01:00',
		arrival: '2026-03-15T14:22:00+01:00',
		duration: '6h 45m',
		stops: 1,
		carriers: ['FlixTrain', 'FlixBus'],
		bookingProvider: 'FlixBus / FlixTrain',
		carrierCodes: []
	}
};
