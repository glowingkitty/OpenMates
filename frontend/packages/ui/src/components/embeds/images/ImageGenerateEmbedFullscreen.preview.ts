/**
 * Preview mock data for ImageGenerateEmbedFullscreen.
 *
 * Note: This component normally decrypts images from S3.
 * In preview mode, the image won't load but the component layout/controls can be tested.
 * Access at: /dev/preview/embeds/images/ImageGenerateEmbedFullscreen
 */

import { MODIFY_PROMPT, MODIFY_UNMET, SAMPLE_MODIFY_DRAFT, SAMPLE_MODIFY_RESULT_URL } from './imageModifyFixtures';

/** Default props — shows a fullscreen image generation view (without actual image data) */
const defaultProps = {
	prompt: 'A serene mountain landscape at sunset with vibrant orange and purple skies',
	embedId: '22222222-2222-4222-8222-222222222222',
	filename: 'mountain_landscape.png',
	model: 'flux-schnell',
	previewImageUrl: '/images/examples/group1.jpg',
	aspect_ratio: '16:9',
	status: 'finished',
	skillId: 'generate' as const,
	generatedAt: '2026-02-17T10:30:00Z',
	onClose: () => {},
	hasPreviousEmbed: false,
	hasNextEmbed: false
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	completePrompt: {
		...defaultProps,
		prompt: 'An observatory on a windswept coast, blue-hour fog, copper telescope, and three bright stars above the horizon',
		model: 'google/gemini-3-pro-image-preview',
		provider: 'Google',
		filename: 'observatory_coast.png'
	},
	/** With navigation arrows */
	withNavigation: {
		...defaultProps,
		hasPreviousEmbed: true,
		hasNextEmbed: true,
		onNavigatePrevious: () => {},
		onNavigateNext: () => {}
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

	/** Enhance round button states (embed-user-edits.enhance.button) */
	enhanceIdle: { ...defaultProps, onEnhance: () => {} },
	enhanceRunning: { ...defaultProps, onEnhance: () => {}, enhanceState: 'running' },
	enhanceFailed: {
		...defaultProps,
		onEnhance: () => {},
		enhanceState: 'failed',
		enhanceError: 'Enhance failed. Please try again.'
	},
	enhanceNotAllowed: { ...defaultProps, onEnhance: () => {}, canEnhance: false },

	/** Processing state */
	processing: {
		...defaultProps,
		status: 'processing'
	},

	/** Version 2 of 3 with badge (the timeline needs stored versions and stays empty in the preview) */
	versionTwoOfThree: {
		...defaultProps,
		version: 2,
		versionCount: 3
	},

	/** Square aspect ratio */
	square: {
		...defaultProps,
		aspect_ratio: '1:1',
		prompt: 'A detailed portrait of a robot reading a book in a cozy library'
	},

	/** images.modify variants: content fields use the wire names of the backend. */
	modifyWriting: {
		...defaultProps,
		previewImageUrl: undefined,
		prompt: MODIFY_PROMPT,
		skill_id: 'modify',
		model: 'gpt-6.1-sol',
		status: 'processing',
		draft_stage: 'writing',
		draft_attempt: 1
	},
	modifyCheckingWithDraft: {
		...defaultProps,
		previewImageUrl: undefined,
		prompt: MODIFY_PROMPT,
		skill_id: 'modify',
		model: 'gpt-6.1-sol',
		status: 'processing',
		draft_stage: 'checking',
		draft_attempt: 1,
		image_draft: SAMPLE_MODIFY_DRAFT
	},
	modifyCorrecting: {
		...defaultProps,
		previewImageUrl: undefined,
		prompt: MODIFY_PROMPT,
		skill_id: 'modify',
		model: 'gpt-6.1-sol',
		status: 'processing',
		draft_stage: 'correcting',
		draft_attempt: 2,
		image_draft: SAMPLE_MODIFY_DRAFT
	},
	modifyFinished: {
		...defaultProps,
		prompt: MODIFY_PROMPT,
		skill_id: 'modify',
		model: 'gpt-6.1-sol',
		filename: 'edited_image.png',
		previewImageUrl: SAMPLE_MODIFY_RESULT_URL,
		review_status: 'accepted',
		attempts: 1
	},
	modifyUnmet: {
		...defaultProps,
		prompt: MODIFY_PROMPT,
		skill_id: 'modify',
		model: 'gpt-6.1-sol',
		filename: 'edited_image.png',
		previewImageUrl: SAMPLE_MODIFY_RESULT_URL,
		review_status: 'unmet_delivered',
		unmet_requirements: MODIFY_UNMET,
		attempts: 3
	},
	modifyFailed: {
		...defaultProps,
		prompt: MODIFY_PROMPT,
		skill_id: 'modify',
		model: 'gpt-6.1-sol',
		status: 'error',
		error: 'The edit could not be completed'
	}
};
