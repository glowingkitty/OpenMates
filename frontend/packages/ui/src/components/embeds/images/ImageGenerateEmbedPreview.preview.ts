/**
 * Preview mock data for ImageGenerateEmbedPreview.
 *
 * Note: This component normally decrypts images from S3.
 * In preview mode, the image won't load but the component states can still be tested.
 * Access at: /dev/preview/embeds/images/ImageGenerateEmbedPreview
 */

import { MODIFY_PROMPT, SAMPLE_MODIFY_DRAFT, SAMPLE_MODIFY_RESULT_URL } from './imageModifyFixtures';

/** Default props — shows a finished image generation (without actual image data) */
const defaultProps = {
	id: 'preview-image-gen-1',
	skillId: 'generate' as const,
	prompt: 'A serene mountain landscape at sunset with vibrant orange and purple skies',
	model: 'flux-schnell',
	previewImageUrl: '/images/examples/group1.jpg',
	status: 'finished' as const,
	isMobile: false,
	onFullscreen: () => {}
};

const sampleSvg =
	'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 120"><rect width="200" height="120" fill="#bfe3ff"/><circle cx="150" cy="30" r="16" fill="#fcd34d"/><path d="M0 120 L0 80 Q 50 40 100 80 T 200 80 L200 120 Z" fill="#4ade80"/></svg>';

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Public child media remains visible without private S3 decryption metadata. */
	publicChild: {
		...defaultProps,
		id: 'preview-image-gen-public-child',
		model: 'google/gemini-3-pro-image-preview',
		provider: 'Google',
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

	/** Vector author mid-drawing: partial SVG cut off inside a path. */
	svgDrafting: {
		id: 'preview-image-gen-svg-drafting',
		skillId: 'generate' as const,
		prompt: 'A flat illustration of a sun over two hills',
		model: 'vector-author',
		status: 'processing' as const,
		svgDraft: sampleSvg.slice(0, sampleSvg.indexOf('Q 50 40') + 4),
		draftStage: 'drawing' as const,
		isMobile: false
	},

	/** Complete drawing while the automatic check runs. */
	svgChecking: {
		id: 'preview-image-gen-svg-checking',
		skillId: 'generate' as const,
		prompt: 'A flat illustration of a sun over two hills',
		model: 'vector-author',
		status: 'processing' as const,
		svgDraft: sampleSvg,
		draftStage: 'checking' as const,
		isMobile: false
	},

	/** Generator script being written and run: no picture yet, only the stage label. */
	svgScripting: {
		id: 'preview-image-gen-svg-scripting',
		skillId: 'generate' as const,
		prompt: 'A precise geometric pattern of concentric circles',
		model: 'vector-author',
		status: 'processing' as const,
		svgDraft: '',
		draftStage: 'scripting' as const,
		isMobile: false
	},

	/** images.modify: author is writing the editing steps. */
	modifyWriting: {
		id: 'preview-image-modify-writing',
		skillId: 'modify' as const,
		model: 'gpt-6.1-sol',
		prompt: MODIFY_PROMPT,
		status: 'processing' as const,
		modifyProgress: { stage: 'writing' as const, attempt: 1, draft: '' },
		isMobile: false
	},

	/** images.modify: first computed picture shown as draft while it is checked. */
	modifyCheckingWithDraft: {
		id: 'preview-image-modify-checking',
		skillId: 'modify' as const,
		model: 'gpt-6.1-sol',
		prompt: MODIFY_PROMPT,
		status: 'processing' as const,
		modifyProgress: { stage: 'checking' as const, attempt: 1, draft: SAMPLE_MODIFY_DRAFT },
		isMobile: false
	},

	/** images.modify: second attempt, correcting after an unmet requirement. */
	modifyCorrecting: {
		id: 'preview-image-modify-correcting',
		skillId: 'modify' as const,
		model: 'gpt-6.1-sol',
		prompt: MODIFY_PROMPT,
		status: 'processing' as const,
		modifyProgress: { stage: 'correcting' as const, attempt: 2, draft: SAMPLE_MODIFY_DRAFT },
		isMobile: false
	},

	/** images.modify: finished result is a normal image. */
	modifyFinished: {
		id: 'preview-image-modify-finished',
		skillId: 'modify' as const,
		model: 'gpt-6.1-sol',
		prompt: MODIFY_PROMPT,
		previewImageUrl: SAMPLE_MODIFY_RESULT_URL,
		status: 'finished' as const,
		isMobile: false
	},

	/** images.modify: failed without a picture. */
	modifyFailed: {
		id: 'preview-image-modify-failed',
		skillId: 'modify' as const,
		model: 'gpt-6.1-sol',
		prompt: MODIFY_PROMPT,
		status: 'error' as const,
		error: 'The edit could not be completed',
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

	/** Version 2 of 3 with badge: the card of the message that made version 2 */
	versionTwoOfThree: {
		...defaultProps,
		id: 'preview-image-gen-version-2-of-3',
		version: 2,
		versionCount: 3
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-image-gen-mobile',
		isMobile: true
	}
};
