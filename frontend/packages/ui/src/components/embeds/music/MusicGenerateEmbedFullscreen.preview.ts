/**
 * Preview mock data for MusicGenerateEmbedFullscreen.
 *
 * Fullscreen components receive decoded embed content through the shared
 * data-driven wrapper used by the embed preview showcase.
 * Access at: /dev/preview/embeds/music
 */

const decodedContent = {
	prompt: 'A 30 second ambient synth background loop with soft pads and no drums',
	mode: 'background',
	model: 'lyria-3-clip-preview',
	duration_seconds: 30,
	generated_at: '2026-05-21T23:30:00Z',
	watermarking: 'SynthID'
};

const defaultProps = {
	data: {
		decodedContent,
		embedData: { status: 'finished' },
		attrs: { app_id: 'music', skill_id: 'generate' }
	},
	embedId: 'preview-music-generate-1',
	onClose: () => {}
};

export default defaultProps;

export const variants = {
	jingle: {
		...defaultProps,
		data: {
			...defaultProps.data,
			decodedContent: {
				...decodedContent,
				prompt: 'An upbeat electronic product jingle with warm synth bass',
				mode: 'jingle',
				model: 'lyria-3-pro-preview',
				duration_seconds: 45
			}
		}
	},
	error: {
		...defaultProps,
		data: {
			...defaultProps.data,
			embedData: { status: 'error' },
			decodedContent: {
				...decodedContent,
				error: 'Music generation failed: provider returned no audio output'
			}
		}
	}
};
