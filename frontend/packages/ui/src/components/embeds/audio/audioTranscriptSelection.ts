/**
 * Audio recording transcript variant selection helpers.
 *
 * Recording embeds can carry the raw transcription, the auto-corrected text,
 * and a user-controlled flag choosing which variant should be visible and
 * LLM-visible. Keep this logic shared between fullscreen UI and send-time
 * serialization so request context matches what the user selected.
 */

export interface AudioTranscriptSelectionInput {
	transcript?: string | null;
	transcriptOriginal?: string | null;
	transcriptCorrected?: string | null;
	useCorrected?: boolean | null;
}

function normalizeTranscript(value: string | null | undefined): string | undefined {
	return typeof value === "string" ? value : undefined;
}

export function selectAudioTranscriptText(
	input: AudioTranscriptSelectionInput,
	useCorrected = input.useCorrected ?? true,
): string {
	const transcript = normalizeTranscript(input.transcript);
	const transcriptOriginal = normalizeTranscript(input.transcriptOriginal);
	const transcriptCorrected = normalizeTranscript(input.transcriptCorrected);

	if (useCorrected === false && transcriptOriginal !== undefined) {
		return transcriptOriginal;
	}
	if (useCorrected !== false && transcriptCorrected !== undefined) {
		return transcriptCorrected;
	}
	return transcript ?? transcriptCorrected ?? transcriptOriginal ?? "";
}

export function selectAudioTranscriptUseCorrected(
	input: AudioTranscriptSelectionInput,
): { transcript: string; useCorrected: boolean } {
	const useCorrected = input.useCorrected ?? true;
	return {
		transcript: selectAudioTranscriptText(input, useCorrected),
		useCorrected,
	};
}
