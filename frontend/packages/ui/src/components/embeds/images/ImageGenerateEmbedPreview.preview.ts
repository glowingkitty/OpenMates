/**
 * Preview mock data for ImageGenerateEmbedPreview.
 *
 * Note: This component normally decrypts images from S3.
 * In preview mode, the image won't load but the component states can still be tested.
 * Access at: /dev/preview/embeds/images/ImageGenerateEmbedPreview
 */

/** Default props — shows a finished image generation (without actual image data) */
const defaultProps = {
	id: 'preview-image-gen-1',
	skillId: 'generate' as const,
	prompt: 'A serene mountain landscape at sunset with vibrant orange and purple skies',
	model: 'flux-schnell',
	status: 'finished' as const,
	isMobile: false,
	onFullscreen: () => {}
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Public child media remains visible without private S3 decryption metadata. */
	publicChild: {
		...defaultProps,
		id: 'preview-image-gen-public-child',
		model: 'google/gemini-3-pro-image-preview',
		previewImageUrl: 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="128" height="96"%3E%3Crect width="128" height="96" fill="%23ad64e0"/%3E%3C/svg%3E'
	},
	/** Processing state — shows generation progress */
	processing: {
		id: 'preview-image-gen-processing',
		skillId: 'generate' as const,
		prompt: 'A futuristic cityscape with flying cars and neon lights',
		model: 'flux-schnell',
		status: 'processing' as const,
		isMobile: false
	},

	/** Draft generation variant */
	draft: {
		id: 'preview-image-gen-draft',
		skillId: 'generate_draft' as const,
		prompt: 'Quick sketch of a cat wearing a top hat',
		model: 'flux-schnell',
		status: 'finished' as const,
		isMobile: false
	},

	/** Error state */
	error: {
		id: 'preview-image-gen-error',
		skillId: 'generate' as const,
		prompt: 'Something that caused an error',
		model: 'flux-schnell',
		status: 'error' as const,
		error: 'Image generation failed: content policy violation',
		isMobile: false
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-image-gen-mobile',
		isMobile: true
	}
};
