import { describe, expect, it } from 'vitest';
import { publicRecordingAudioUrl } from './publicRecordingAudio';

describe('publicRecordingAudioUrl', () => {
  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it('accepts reviewed same-origin example audio paths', () => {
    expect(publicRecordingAudioUrl('/store-examples/transcription-demo-voice-note.wav'))
      .toBe('/store-examples/transcription-demo-voice-note.wav');
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it.each([
    'https://example.org/voice.wav',
    '//example.org/voice.wav',
    '/store-examples/../private.wav',
    '/store-examples/%2e%2e/private.wav',
    '/store-examples/voice.wav?url=https://example.org',
    '/other/voice.wav',
    'javascript:alert(1)',
  ])('rejects unreviewed audio URL %s', (value) => {
    expect(publicRecordingAudioUrl(value)).toBeUndefined();
  });
});
