/**
 * Preview mock data for TravelStayEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/travel/TravelStayEmbedPreview
 */

/** Default props — shows a finished hotel stay card */
const defaultProps = {
	id: 'preview-travel-stay-1',
	name: 'Hotel Maximilian',
	thumbnail: '',
	hotelClass: 4,
	overallRating: 4.3,
	reviews: 1248,
	currency: 'EUR',
	ratePerNight: 129,
	totalRate: 387,
	amenities: ['Free Wi-Fi', 'Breakfast included', 'Spa', 'Fitness center', 'Airport shuttle'],
	isCheapest: false,
	ecoCertified: true,
	freeCancellation: true,
	status: 'finished' as const,
	isMobile: false,
	onFullscreen: () => console.log('[Preview] Fullscreen clicked')
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Budget option — cheapest */
	budget: {
		...defaultProps,
		id: 'preview-travel-stay-budget',
		name: 'City Hostel Central',
		hotelClass: 2,
		overallRating: 3.8,
		reviews: 523,
		ratePerNight: 45,
		totalRate: 135,
		amenities: ['Free Wi-Fi', 'Shared kitchen'],
		isCheapest: true,
		ecoCertified: false,
		freeCancellation: false
	},

	/** Luxury option */
	luxury: {
		...defaultProps,
		id: 'preview-travel-stay-luxury',
		name: 'The Ritz-Carlton Berlin',
		hotelClass: 5,
		overallRating: 4.8,
		reviews: 3456,
		ratePerNight: 450,
		totalRate: 1350,
		amenities: ['Free Wi-Fi', 'Spa', 'Pool', 'Concierge', 'Michelin restaurant', 'Valet parking'],
		ecoCertified: true,
		freeCancellation: true
	},

	/** Processing state */
	processing: {
		id: 'preview-travel-stay-processing',
		status: 'processing' as const,
		isMobile: false
	},

	/** Error state */
	error: {
		id: 'preview-travel-stay-error',
		status: 'error' as const,
		isMobile: false
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-travel-stay-mobile',
		isMobile: true
	}
};
