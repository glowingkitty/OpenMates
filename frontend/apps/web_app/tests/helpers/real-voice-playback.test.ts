import assert from 'node:assert/strict';
import { test } from 'node:test';
import { qualifiedVoiceTiming, type RealVoicePlayback } from './real-voice-playback';

const identity = { callId: 'call', chatId: 'chat', messageId: 'assistant', trackId: 'speech' };
const cue = '/audio/assistant-acknowledgements/mate/answering.mp3';
const speech = 'blob:http://localhost:5173/speech';

function recorded(): ReturnType<RealVoicePlayback['snapshot']> {
  return {
    sampleRate: 48000,
    input: { first: 500, last: 48000, samples: 12000 },
    output: [
      { source: cue, since: 69000, first: 72000, last: 75000, samples: 2944, currentTime: 0.09 },
      { source: speech, since: 95000, first: 96000, last: 99000, samples: 2944, currentTime: 0.12 },
    ],
    turns: [], stt: [], cueSources: [{ callId: 'call', source: cue }],
    proseSources: [{ source: speech, identity }],
    observerErrorCount: 0,
  };
}

// contract-test: supporting surface=gui.web assertions=video-call.audio.spoken-rich-response,video-call.audio.complete-turn-admission

test('uses the last voiced input sample and separates cue and substantive PCM', () => {
  assert.deepEqual(qualifiedVoiceTiming(recorded(), identity),
    { cueMs: 500, substantiveMs: 1000, sampleRate: 48000 });
});

// contract-test: supporting surface=gui.web assertions=video-call.audio.spoken-rich-response,video-call.audio.complete-turn-admission

test('records no cue when audio is silent, unrelated, or happened before speech ended', () => {
  for (const replace of [{ samples: 0 }, { source: 'call-start-chime' }, { first: 12000 }]) {
    const proof = recorded();
    Object.assign(proof.output[0], replace);
    assert.deepEqual(qualifiedVoiceTiming(proof, identity),
      { cueMs: null, substantiveMs: 1000, sampleRate: 48000 });
  }
});

// contract-test: supporting surface=gui.web assertions=video-call.audio.spoken-rich-response,video-call.audio.complete-turn-admission

test('does not certify speech with a disconnected stream, wrong turn, or no PCM', () => {
  for (const discard of [
    (proof: ReturnType<RealVoicePlayback['snapshot']>) => { proof.proseSources = []; },
    (proof: ReturnType<RealVoicePlayback['snapshot']>) => { proof.output[1].samples = 0; },
    (proof: ReturnType<RealVoicePlayback['snapshot']>) => { proof.output[1].currentTime = 0; },
    (proof: ReturnType<RealVoicePlayback['snapshot']>) => { proof.observerErrorCount = 1; },
    (proof: ReturnType<RealVoicePlayback['snapshot']>) => {
      proof.proseSources[0].identity = { ...identity, messageId: 'another-response' };
    },
  ]) {
    const proof = recorded();
    discard(proof);
    assert.equal(qualifiedVoiceTiming(proof, identity), null);
  }
});
