/**
 * Preview mock data for TravelStayEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/travel/TravelStayEmbedFullscreen
 */

/** Default props — shows a fullscreen hotel stay detail view */
const defaultProps = {
	stay: {
		type: 'stay',
		name: 'Hotel Maximilian',
		description:
			'A charming 4-star hotel in the heart of Munich, just steps from Marienplatz. ' +
			'Featuring elegant rooms with modern amenities, a rooftop terrace with panoramic views, ' +
			'and an award-winning breakfast buffet.',
		property_type: 'Hotel',
		link: 'https://example.com/hotel-maximilian',
		hotel_class: 4,
		overall_rating: 4.3,
		reviews: 1248,
		rate_per_night: '€129',
		extracted_rate_per_night: 129,
		total_rate: '€387',
		extracted_total_rate: 387,
		currency: 'EUR',
		check_in_time: '15:00',
		check_out_time: '11:00',
		amenities: [
			'Free Wi-Fi',
			'Breakfast included',
			'Spa',
			'Fitness center',
			'Airport shuttle',
			'24-hour front desk',
			'Room service',
			'Laundry service'
		],
		images: [
			{ url: '', caption: 'Hotel exterior' },
			{ url: '', caption: 'Deluxe room' },
			{ url: '', caption: 'Rooftop terrace' }
		],
		thumbnail: '',
		nearby_places: [
			{ name: 'Marienplatz', distance: '200m' },
			{ name: 'Hofbräuhaus', distance: '350m' },
			{ name: 'Englischer Garten', distance: '1.2km' }
		],
		eco_certified: true,
		free_cancellation: true,
		gps_coordinates: { latitude: 48.1371, longitude: 11.5754 }
	},
	onClose: () => console.log('[Preview] Close clicked')
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Budget hostel */
	budget: {
		stay: {
			type: 'stay',
			name: 'City Hostel Central',
			description: 'A modern hostel in a prime location with shared and private room options.',
			property_type: 'Hostel',
			hotel_class: 2,
			overall_rating: 3.8,
			reviews: 523,
			rate_per_night: '€45',
			extracted_rate_per_night: 45,
			total_rate: '€135',
			extracted_total_rate: 135,
			currency: 'EUR',
			amenities: ['Free Wi-Fi', 'Shared kitchen', 'Luggage storage'],
			thumbnail: '',
			eco_certified: false,
			free_cancellation: false
		},
		onClose: () => console.log('[Preview] Close clicked')
	},

	/** Luxury resort */
	luxury: {
		stay: {
			type: 'stay',
			name: 'The Ritz-Carlton Berlin',
			description:
				'Experience unparalleled luxury at The Ritz-Carlton Berlin, featuring world-class dining, ' +
				'a stunning rooftop spa, and impeccable service in the heart of Potsdamer Platz.',
			property_type: 'Hotel',
			hotel_class: 5,
			overall_rating: 4.8,
			reviews: 3456,
			rate_per_night: '€450',
			extracted_rate_per_night: 450,
			total_rate: '€1350',
			extracted_total_rate: 1350,
			currency: 'EUR',
			amenities: [
				'Free Wi-Fi',
				'Spa',
				'Pool',
				'Concierge',
				'Michelin restaurant',
				'Valet parking',
				'Butler service'
			],
			thumbnail: '',
			eco_certified: true,
			free_cancellation: true
		},
		onClose: () => console.log('[Preview] Close clicked')
	}
};
