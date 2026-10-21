import { describe, expect, it } from 'vitest';
import { audioTranscriptionResultContent } from '../audioTranscriptionResult';
describe('native transcription recording presentation', () => {
  // contract-test: direct surface=gui.web assertions=apps.results.shared-fullscreen
  it('normalizes the existing exact native input and nested paid transcript for the recording renderer', () => {
    const result = audioTranscriptionResultContent({ app_id: 'audio', skill_id: 'transcribe', input: { requests: [{ filename: 'meeting.webm', s3_key: 'key', s3_base_url: 'https://s3.test', aes_key: 'aes', aes_nonce: 'nonce' }] }, results: [{ id: 'request', results: [{ s3_key: 'key', transcript: 'Meeting at nine.', title: 'Meeting', duration_seconds: 12 }] }] });
    expect(result).toMatchObject({ filename: 'meeting.webm', transcript: 'Meeting at nine.', title: 'Meeting', duration: '0:12', s3_files: { original: { s3_key: 'key' } }, aes_key: 'aes', aes_nonce: 'nonce' });
  });
  // contract-test: direct surface=gui.web assertions=apps.results.shared-fullscreen
  it('preserves every transcript in a multi-audio native batch', () => {
    const result = audioTranscriptionResultContent({ app_id: 'audio', skill_id: 'transcribe', results: [{ results: [{ transcript: 'First' }, { transcript: 'Second' }] }] });
    expect(result.transcript).toBe('First\n\nSecond');
  });
  // contract-test: direct surface=gui.web assertions=apps.results.shared-fullscreen
  it('leaves existing recording leaves unchanged', () => {
    const content = { transcript: 'Existing voice note', filename: 'voice.webm' };
    expect(audioTranscriptionResultContent(content)).toBe(content);
  });
});
