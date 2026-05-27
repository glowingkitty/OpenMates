/**
 * Preview mock data for MusicGenerateEmbedPreview.
 *
 * Generated music normally decrypts an audio file from S3 before playback.
 * These fixtures keep preview rendering deterministic without network audio.
 * Access at: /dev/preview/embeds/music
 */

const defaultProps = {
	id: 'preview-music-generate-1',
	prompt: 'A 30 second ambient synth background loop with soft pads and no drums',
	mode: 'background',
	model: 'lyria-3-clip-preview',
	durationSeconds: 30,
	status: 'finished' as const,
	isMobile: false,
	onFullscreen: () => {}
};

export default defaultProps;

export const variants = {
	processing: {
		...defaultProps,
		id: 'preview-music-generate-processing',
		prompt: 'A cinematic intro sting with gentle strings and warm piano',
		status: 'processing' as const
	},
	jingle: {
		...defaultProps,
		id: 'preview-music-generate-jingle',
		prompt: 'An upbeat electronic product jingle with warm synth bass',
		mode: 'jingle',
		model: 'lyria-3-pro-preview',
		durationSeconds: 45
	},
	error: {
		...defaultProps,
		id: 'preview-music-generate-error',
		status: 'error' as const,
		error: 'Music generation failed: provider returned no audio output'
	},
	mobile: {
		...defaultProps,
		id: 'preview-music-generate-mobile',
		isMobile: true
	}
};
