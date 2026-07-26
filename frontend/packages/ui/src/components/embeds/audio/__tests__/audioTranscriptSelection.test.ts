/**
 * Audio recording transcript selection regression tests.
 *
 * The fullscreen auto-correct toggle controls which transcript variant is shown
 * before send and which variant is stored as LLM-visible audio context.
 * Requests must use the original transcript whenever correction is disabled.
 */

import { describe, expect, it } from "vitest";
import {
	selectAudioTranscriptText,
	selectAudioTranscriptUseCorrected,
} from "../audioTranscriptSelection";

describe("audio transcript selection", () => {
	it("shows the original transcript when auto-correction is disabled", () => {
		expect(
			selectAudioTranscriptText(
				{
					transcript: "Corrected transcript should not be used",
					transcriptOriginal: "raw original transcript",
					transcriptCorrected: "polished corrected transcript",
				},
				false,
			),
		).toBe("raw original transcript");
	});

	it("uses the original transcript for request input even if transcript is stale", () => {
		expect(
			selectAudioTranscriptUseCorrected({
				transcript: "stale corrected transcript",
				transcriptOriginal: "unedited recording transcript",
				transcriptCorrected: "stale corrected transcript",
				useCorrected: false,
			}),
		).toEqual({
			transcript: "unedited recording transcript",
			useCorrected: false,
		});
	});

	it("keeps corrected transcript as the default when correction is enabled", () => {
		expect(
			selectAudioTranscriptUseCorrected({
				transcript: "polished corrected transcript",
				transcriptOriginal: "raw original transcript",
				transcriptCorrected: "polished corrected transcript",
				useCorrected: true,
			}),
		).toEqual({
			transcript: "polished corrected transcript",
			useCorrected: true,
		});
	});
});
