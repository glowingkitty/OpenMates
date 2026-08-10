/**
 * frontend/packages/ui/src/utils/audioWaveform.ts
 *
 * Compact audio waveform metadata helpers for recording embeds.
 * Waveforms are derived RMS envelopes, not raw audio, and are stored inside
 * encrypted embed content so previews can render without loading audio blobs.
 */

export const AUDIO_WAVEFORM_SAMPLE_COUNT = 128;
export const AUDIO_WAVEFORM_MAX_VALUE = 100;

export interface AudioWaveformData {
	version: 1;
	kind: 'rms-envelope';
	samples: number[];
	duration_seconds?: number;
}

function clampWaveformLevel(value: unknown): number | null {
	if (typeof value !== 'number' || !Number.isFinite(value)) return null;
	return Math.max(0, Math.min(AUDIO_WAVEFORM_MAX_VALUE, Math.round(value)));
}

export function normalizeWaveformData(value: unknown): AudioWaveformData | undefined {
	if (!value || typeof value !== 'object') return undefined;
	const record = value as Record<string, unknown>;
	const rawSamples = Array.isArray(record.samples) ? record.samples : [];
	const samples = rawSamples
		.map(clampWaveformLevel)
		.filter((sample): sample is number => sample !== null);

	if (samples.length === 0) return undefined;

	const durationSeconds =
		typeof record.duration_seconds === 'number' &&
		Number.isFinite(record.duration_seconds) &&
		record.duration_seconds > 0
			? record.duration_seconds
			: undefined;

	return {
		version: 1,
		kind: 'rms-envelope',
		samples,
		...(durationSeconds ? { duration_seconds: durationSeconds } : {}),
	};
}

export function buildWaveformFromLevels(
	levels: number[],
	durationSeconds?: number,
	sampleCount: number = AUDIO_WAVEFORM_SAMPLE_COUNT,
): AudioWaveformData | undefined {
	const validLevels = levels.filter((level) => Number.isFinite(level));
	if (validLevels.length === 0 || sampleCount <= 0) return undefined;

	const samples = Array.from({ length: sampleCount }, (_, index) => {
		const start = Math.min(validLevels.length - 1, Math.floor((index * validLevels.length) / sampleCount));
		const end = Math.min(
			validLevels.length,
			Math.max(start + 1, Math.floor(((index + 1) * validLevels.length) / sampleCount)),
		);
		let sumOfSquares = 0;
		for (let levelIndex = start; levelIndex < end; levelIndex += 1) {
			const level = Math.max(0, Math.min(1, validLevels[levelIndex] ?? 0));
			sumOfSquares += level * level;
		}
		const rms = Math.sqrt(sumOfSquares / Math.max(1, end - start));
		return Math.round(rms * AUDIO_WAVEFORM_MAX_VALUE);
	});

	return {
		version: 1,
		kind: 'rms-envelope',
		samples,
		...(durationSeconds && durationSeconds > 0 ? { duration_seconds: durationSeconds } : {}),
	};
}
