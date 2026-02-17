/**
 * Preview mock data for ImageGenerateEmbedFullscreen.
 *
 * Note: This component normally decrypts images from S3.
 * In preview mode, the image won't load but the component layout/controls can be tested.
 * Access at: /dev/preview/embeds/images/ImageGenerateEmbedFullscreen
 */

/** Default props — shows a fullscreen image generation view (without actual image data) */
const defaultProps = {
	prompt: 'A serene mountain landscape at sunset with vibrant orange and purple skies',
	model: 'flux-schnell',
	aspectRatio: '16:9',
	status: 'finished',
	skillId: 'generate' as const,
	generatedAt: '2026-02-17T10:30:00Z',
	onClose: () => console.log('[Preview] Close clicked'),
	hasPreviousEmbed: false,
	hasNextEmbed: false
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** With navigation arrows */
	withNavigation: {
		...defaultProps,
		hasPreviousEmbed: true,
		hasNextEmbed: true,
		onNavigatePrevious: () => console.log('[Preview] Navigate previous'),
		onNavigateNext: () => console.log('[Preview] Navigate next')
	},

	/** Draft generation */
	draft: {
		...defaultProps,
		prompt: 'Quick sketch of a cat wearing a top hat',
		skillId: 'generate_draft' as const,
		model: 'flux-schnell'
	},

	/** Error state */
	error: {
		...defaultProps,
		status: 'error',
		error: 'Image generation failed: content policy violation'
	},

	/** Processing state */
	processing: {
		...defaultProps,
		status: 'processing'
	},

	/** Square aspect ratio */
	square: {
		...defaultProps,
		aspectRatio: '1:1',
		prompt: 'A detailed portrait of a robot reading a book in a cozy library'
	}
};
