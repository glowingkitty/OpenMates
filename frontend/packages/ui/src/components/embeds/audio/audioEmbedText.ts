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

/** app:audio:generate */
export function renderAudioGenerate(c: Record<string, unknown>): string {
	const prompt = str(c.prompt) ?? str(c.text_preview) ?? '';
	const provider = str(c.provider) ?? 'ElevenLabs';
	const model = str(c.model) ?? '';
	const duration = str(c.duration_seconds) ?? '';
	const lines: string[] = ['**Audio | Generate sound effect**'];
	if (prompt) lines.push(`Prompt: ${trunc(prompt, 200)}`);
	if (provider) lines.push(`Provider: ${provider}`);
	if (model) lines.push(`Model: ${model}`);
	if (duration) lines.push(`Duration: ${duration}s`);
	lines.push('[audio]');
	return lines.join('\n');
}

/** app:audio:speak */
export function renderAudioSpeak(c: Record<string, unknown>): string {
	const preview = str(c.text_preview) ?? '';
	const voice = str(c.voice) ?? '';
	const provider = str(c.provider) ?? 'ElevenLabs';
	const model = str(c.model) ?? '';
	const duration = str(c.duration_seconds) ?? '';
	const lines: string[] = ['**Audio | Speak**'];
	if (preview) lines.push(`Text: ${trunc(preview, 200)}`);
	if (voice) lines.push(`Voice: ${voice}`);
	if (provider) lines.push(`Provider: ${provider}`);
	if (model) lines.push(`Model: ${model}`);
	if (duration) lines.push(`Duration: ${duration}s`);
	lines.push('[audio]');
	return lines.join('\n');
}
