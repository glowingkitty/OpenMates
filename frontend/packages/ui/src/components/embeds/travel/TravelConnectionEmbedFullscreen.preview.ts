/**
 * Preview mock data for TravelConnectionEmbedFullscreen.
 *
 * Note: This component expects a `connection` object with detailed flight data.
 * The Leaflet map may not render without network access to tile servers.
 * Access at: /dev/preview/embeds/travel/TravelConnectionEmbedFullscreen
 */

/** Default props — shows a fullscreen flight connection detail view */
const defaultProps = {
	connection: {
		embed_id: 'preview-connection-detail-1',
		type: 'connection',
		transport_method: 'airplane',
		trip_type: 'one_way',
		total_price: '189.00',
		currency: 'EUR',
		bookable_seats: 4,
		last_ticketing_date: '2026-03-10',
		booking_url: 'https://example.com/book/LH123',
		booking_provider: 'Lufthansa',
		origin: 'Munich (MUC)',
		destination: 'London Heathrow (LHR)',
		departure: '2026-03-15T08:30:00',
		arrival: '2026-03-15T10:00:00',
		duration: '2h 30m',
		stops: 0,
		carriers: ['Lufthansa'],
		carrier_codes: ['LH'],
		co2_kg: 85,
		co2_typical_kg: 120,
		co2_difference_percent: -29,
		legs: [
			{
				departure_airport: 'MUC',
				departure_city: 'Munich',
				departure_time: '2026-03-15T08:30:00',
				arrival_airport: 'LHR',
				arrival_city: 'London',
				arrival_time: '2026-03-15T10:00:00',
				duration: '2h 30m',
				flight_number: 'LH 2478',
				carrier: 'Lufthansa',
				carrier_code: 'LH',
				aircraft: 'Airbus A320neo'
			}
		]
	},
	onClose: () => console.log('[Preview] Close clicked')
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Multi-leg connection with stopover */
	multiLeg: {
		connection: {
			embed_id: 'preview-connection-detail-multi',
			type: 'connection',
			transport_method: 'airplane',
			trip_type: 'one_way',
			total_price: '245.50',
			currency: 'EUR',
			bookable_seats: 2,
			origin: 'Munich (MUC)',
			destination: 'London Gatwick (LGW)',
			departure: '2026-03-15T14:15:00',
			arrival: '2026-03-15T17:45:00',
			duration: '4h 30m',
			stops: 1,
			carriers: ['British Airways', 'Eurowings'],
			carrier_codes: ['BA', 'EW'],
			legs: [
				{
					departure_airport: 'MUC',
					departure_city: 'Munich',
					departure_time: '2026-03-15T14:15:00',
					arrival_airport: 'DUS',
					arrival_city: 'Düsseldorf',
					arrival_time: '2026-03-15T15:30:00',
					duration: '1h 15m',
					flight_number: 'EW 9542',
					carrier: 'Eurowings',
					carrier_code: 'EW',
					aircraft: 'Airbus A319'
				},
				{
					departure_airport: 'DUS',
					departure_city: 'Düsseldorf',
					departure_time: '2026-03-15T16:30:00',
					arrival_airport: 'LGW',
					arrival_city: 'London',
					arrival_time: '2026-03-15T17:45:00',
					duration: '1h 15m',
					flight_number: 'BA 2617',
					carrier: 'British Airways',
					carrier_code: 'BA',
					aircraft: 'Airbus A320'
				}
			]
		},
		onClose: () => console.log('[Preview] Close clicked')
	}
};
