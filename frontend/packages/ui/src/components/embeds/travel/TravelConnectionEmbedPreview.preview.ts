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
	carrierCodes: ['LH'],
	bookableSeats: 4,
	isCheapest: true,
	status: 'finished' as const,
	isMobile: false,
	onFullscreen: () => console.log('[Preview] Fullscreen clicked')
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
	}
};
