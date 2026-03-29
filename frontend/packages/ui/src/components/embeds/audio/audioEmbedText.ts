/**
 * Text-only renderers for audio embed types.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str, trunc } from '../../../data/embedTextRenderers';

/** recording — audio recording embed */
export function renderRecording(c: Record<string, unknown>): string {
	const duration = str(c.duration) ?? '';
	const lines: string[] = ['**Recording**'];
	if (duration) lines.push(`Duration: ${duration}`);
	lines.push('[audio recording]');
	return lines.join('\n');
}

/** app:audio:transcribe */
export function renderAudioTranscribe(c: Record<string, unknown>): string {
	const duration = str(c.duration) ?? str(c.length) ?? '';
	const language = str(c.language) ?? '';
	const text = str(c.text) ?? str(c.transcript) ?? '';
	const lines: string[] = ['**Audio Transcription**'];
	if (duration) lines.push(`Duration: ${duration}`);
	if (language) lines.push(`Language: ${language}`);
	if (text) lines.push(trunc(text, 200));
	return lines.join('\n');
}
