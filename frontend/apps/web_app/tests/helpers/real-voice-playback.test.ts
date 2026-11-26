import assert from 'node:assert/strict';
import { test } from 'node:test';
import { qualifiedVoiceTiming, voicePcmProgress, type RealVoicePlayback } from './real-voice-playback';

const identity = { callId: 'call', chatId: 'chat', messageId: 'assistant', trackId: 'speech' };
const cue = '/audio/assistant-acknowledgements/mate/answering.mp3';
const speech = 'blob:http://localhost:5173/speech';
const owner = { ...identity, userMessageId: 'utterance' };
const emptyMilestones = {
  lastVoicedToFinalTranscriptMs: null,
  lastVoicedToAdmissionMs: null,
  lastVoicedToAdmissionAckMs: null,
  lastVoicedToProseStartMs: null,
  lastVoicedToMatchingAudioBytesMs: null,
  lastVoicedToPlaybackMs: 1000,
};

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
    { cueMs: 500, substantiveMs: 1000, sampleRate: 48000, milestones: emptyMilestones });
});

// contract-test: supporting surface=gui.web assertions=video-call.audio.spoken-rich-response,video-call.audio.complete-turn-admission

test('records no cue when audio is silent, unrelated, or happened before speech ended', () => {
  for (const replace of [{ samples: 0 }, { source: 'call-start-chime' }, { first: 12000 }]) {
    const proof = recorded();
    Object.assign(proof.output[0], replace);
    assert.deepEqual(qualifiedVoiceTiming(proof, identity),
      { cueMs: null, substantiveMs: 1000, sampleRate: 48000, milestones: emptyMilestones });
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

// contract-test: supporting surface=gui.web assertions=video-call.audio.spoken-rich-response,video-call.audio.complete-turn-admission
test('attributes every relative milestone to the owned utterance and audible track using the same sample clock', () => {
  const proof = recorded();
  const scope = { callId: owner.callId, chatId: owner.chatId, userMessageId: owner.userMessageId };
  proof.transcriptFrames = [
    { ...scope, callId: 'foreign-call', frame: 48001 },
    { ...scope, chatId: 'foreign-chat', frame: 48100 },
    { ...scope, userMessageId: 'another-utterance', frame: 48200 },
    { ...scope, frame: 47000 },
    { ...scope, frame: 52800 },
  ];
  proof.admissionFrames = [
    { ...scope, chatId: 'foreign-chat', sentFrame: 48100, ackFrame: 48200 },
    { ...scope, userMessageId: 'another-utterance', sentFrame: 48200, ackFrame: 48300 },
    { ...scope, sentFrame: 57600, ackFrame: 62400 },
  ];
  proof.proseSources[0] = { source: speech, identity, startFrame: 72000, bytesFrame: 76800 };
  proof.proseSources.push({ source: 'silent-other-track', identity: { ...identity, trackId: 'foreign-track' },
    startFrame: 48400, bytesFrame: 48500 });
  const timing = qualifiedVoiceTiming(proof, owner);
  assert.deepEqual(timing?.milestones, {
    lastVoicedToFinalTranscriptMs: 100, lastVoicedToAdmissionMs: 200,
    lastVoicedToAdmissionAckMs: 300, lastVoicedToProseStartMs: 500,
    lastVoicedToMatchingAudioBytesMs: 600, lastVoicedToPlaybackMs: 1000,
  });
  assert.ok(Object.values(timing!.milestones).every(value => value === null || typeof value === 'number'));
});

// contract-test: supporting surface=gui.web assertions=video-call.audio.spoken-rich-response,video-call.audio.complete-turn-admission
test('missing, stale and ambiguous optional milestones leave a qualified browser playback intact', () => {
  const proof = recorded();
  proof.admissionFrames = [{ callId: owner.callId, chatId: owner.chatId,
    userMessageId: owner.userMessageId, sentFrame: 47000, ackFrame: 49000 }];
  proof.proseSources.push({ source: speech, identity: { ...identity, trackId: 'ambiguous-track' },
    startFrame: 50200, bytesFrame: 50800 });
  assert.deepEqual(qualifiedVoiceTiming(proof, owner),
    { cueMs: 500, substantiveMs: 1000, sampleRate: 48000, milestones: emptyMilestones });
});


// contract-test: supporting surface=gui.web assertions=video-call.audio.spoken-rich-response
test('the finite PCM progress follows only the owned reply and exact MediaSource attribution', () => {
  const proof = recorded();
  proof.proseWire = [
    { identity, started: true, chunked: true },
    { identity: { ...identity, callId: 'foreign-call' }, failed: true },
    { identity: { ...identity, chatId: 'foreign-chat' }, failed: true },
    { identity: { ...identity, messageId: 'foreign-reply' }, failed: true },
  ];
  assert.deepEqual(voicePcmProgress(proof, owner), [
    'pcm_input_measured', 'pcm_owned_prose_start', 'pcm_owned_prose_chunk',
    'pcm_owned_media_append', 'pcm_owned_non_silent_playback',
  ]);
  proof.proseSources[0].identity = { ...identity, messageId: 'foreign-reply' };
  assert.deepEqual(voicePcmProgress(proof, owner), [
    'pcm_input_measured', 'pcm_owned_prose_start', 'pcm_owned_prose_chunk',
  ]);
});

// contract-test: supporting surface=gui.web assertions=video-call.audio.spoken-rich-response
test('owned speech and observer errors remain separate from missing or silent output', () => {
  const proof = recorded();
  proof.proseWire = [{ identity, failed: true }];
  proof.observerErrorCount = 1;
  proof.output[1].samples = 0;
  assert.deepEqual(voicePcmProgress(proof, owner), [
    'pcm_input_measured', 'pcm_owned_media_append', 'pcm_observer_error', 'pcm_owned_prose_error',
  ]);
  assert.equal(qualifiedVoiceTiming(proof, owner), null);
});
