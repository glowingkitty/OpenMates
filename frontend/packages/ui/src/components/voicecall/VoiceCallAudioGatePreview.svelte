<script lang="ts">
  import { onDestroy } from 'svelte';
  import { VoiceCallAudioGate } from '../../services/voiceCallAudioGate';
  import { downsample, pcm16Base64 } from '../videocall/callAudio';

  // Account-free engineering fixture: a real local MediaStream feeds the same
  // production PCM conversion and gate. Only the public voice-note asset is used.
  let phase = $state('Not started');
  let inputIdle = $state(false);
  let speaking = $state(false);
  let muted = $state(false);
  let captured = $state(0);
  let capturedSamples = $state(0);
  let uploaded = $state(0);
  let uploadedSamples = $state(0);
  let ends = $state(0);
  let resumes = $state(0);
  let prefixMs = $state(0);
  let playing = $state(false);
  let speechReady = $state(false);
  let contextState = $state('none');
  let trackState = $state('none');
  let error = $state('');
  let context: AudioContext | null = null;
  let stream: MediaStream | null = null;
  let processor: ScriptProcessorNode | null = null;
  let streamSource: MediaStreamAudioSourceNode | null = null;
  let silence: ConstantSourceNode | null = null;
  let voice: AudioBufferSourceNode | null = null;
  let destination: MediaStreamAudioDestinationNode | null = null;
  let silentGain: GainNode | null = null;
  let speech: AudioBuffer | null = null;
  let gate: VoiceCallAudioGate | null = null;
  let generation = 0;
  let burst: { samples: number } | null = null;

  function start() {
    if (context) return;
    const currentGeneration = ++generation;
    const current = () => currentGeneration === generation;
    const audio = new AudioContext();
    context = audio;
    contextState = audio.state;
    audio.onstatechange = () => { contextState = audio.state; };
    void audio.resume();
    gate = new VoiceCallAudioGate({
      onAudio: (data) => {
        if (!current()) return;
        const samples = atob(data).length / 2;
        uploaded++;
        uploadedSamples += samples;
        if (burst) burst.samples += samples;
      },
      onAudioEnd: () => { if (current()) ends++; },
      onState: (state) => {
        if (!current()) return;
        if (inputIdle && !state.inputIdle && state.userSpeaking && phase === 'Live') {
          resumes++;
          const resumed = { samples: 0 };
          burst = resumed;
          // The production gate replays its bounded prefix synchronously after
          // announcing resumed speech. Count only that replay, before live PCM.
          queueMicrotask(() => { prefixMs = resumed.samples / 16; if (burst === resumed) burst = null; });
        }
        inputIdle = state.inputIdle;
        speaking = state.userSpeaking;
      },
      onError: () => { if (current()) { error = 'Capture buffer failed'; stop(); } },
    });
    destination = audio.createMediaStreamDestination();
    stream = destination.stream;
    trackState = stream.getAudioTracks()[0].readyState;
    silence = audio.createConstantSource();
    silence.offset.value = 0;
    silence.connect(destination);
    silence.start();
    streamSource = audio.createMediaStreamSource(stream);
    processor = audio.createScriptProcessor(2048, 1, 1);
    silentGain = audio.createGain();
    silentGain.gain.value = 0;
    streamSource.connect(processor);
    processor.connect(silentGain);
    silentGain.connect(audio.destination);
    processor.onaudioprocess = (event) => {
      if (!current()) return;
      const pcm = downsample(event.inputBuffer.getChannelData(0), event.inputBuffer.sampleRate);
      captured++;
      capturedSamples += pcm.length;
      gate?.push(pcm16Base64(pcm));
    };
    phase = 'Capturing before ready';
    void fetch('/store-examples/transcription-demo-voice-note.wav')
      .then((response) => { if (!response.ok) throw new Error('Fixture unavailable'); return response.arrayBuffer(); })
      .then((bytes) => audio.decodeAudioData(bytes))
      .then((buffer) => { if (current()) { speech = buffer; speechReady = true; } })
      .catch(() => { if (current()) error = 'Speech fixture unavailable'; });
  }

  function connect() {
    if (phase !== 'Capturing before ready') return;
    phase = 'Live';
    gate?.setLive(true);
    gate?.start();
  }

  function playSpeech(short: boolean) {
    if (!context || !destination || !speech || playing) return;
    const source = context.createBufferSource();
    source.buffer = speech;
    source.connect(destination);
    voice = source;
    playing = true;
    source.onended = () => { source.disconnect(); if (voice === source) { voice = null; playing = false; } };
    // The public fixture has 750 ms of leading quiet. Trim it for the short
    // case so a real 350 ms spoken fragment reaches the production detector.
    source.start(0, short ? 0.75 : 0, short ? 0.35 : speech.duration);
  }

  function toggleMute() {
    muted = !muted;
    gate?.setMuted(muted);
  }

  function stop() {
    ++generation;
    gate?.stop();
    gate = null;
    if (processor) processor.onaudioprocess = null;
    processor?.disconnect();
    streamSource?.disconnect();
    silence?.stop();
    silence?.disconnect();
    if (voice) { voice.onended = null; voice.stop(); voice.disconnect(); voice = null; }
    playing = false;
    silentGain?.disconnect();
    stream?.getTracks().forEach((track) => track.stop());
    trackState = stream?.getAudioTracks()[0].readyState ?? 'none';
    inputIdle = false;
    speaking = false;
    phase = 'Ended';
    if (context && context.state !== 'closed') void context.close().then(() => { contextState = 'closed'; });
  }
  onDestroy(stop);
</script>

<section aria-label="Local voice activity gate preview" data-testid="audio-gate-preview">
  <h2>Local voice activity gate</h2>
  <p data-testid="gate-phase">{phase}</p>
  <p role="status" data-testid="gate-status">{muted ? 'Microphone muted' : inputIdle ? 'Speak to resume call.' : speaking ? 'Listening to speech' : 'Listening'}</p>
  <p>Public speech fixture · Audio stays in this browser</p>
  <div class="actions">
    <button onclick={start} disabled={phase !== 'Not started'}>Start capture</button>
    <button onclick={connect} disabled={phase !== 'Capturing before ready'}>Server ready</button>
    <button onclick={() => playSpeech(false)} disabled={!speechReady || playing || phase !== 'Live'}>Play speech</button>
    <button onclick={() => playSpeech(true)} disabled={!speechReady || playing || phase !== 'Live'}>Play short speech</button>
    <button onclick={toggleMute} aria-pressed={muted} disabled={phase !== 'Live'}>Mute microphone</button>
    <button onclick={stop} disabled={phase === 'Not started' || phase === 'Ended'}>Hang up</button>
  </div>
  <dl>
    <dt>Captured frames</dt><dd data-testid="gate-captured">{captured}</dd>
    <dt>Captured samples</dt><dd data-testid="gate-captured-samples">{capturedSamples}</dd>
    <dt>Uploaded frames</dt><dd data-testid="gate-uploaded">{uploaded}</dd>
    <dt>Uploaded samples</dt><dd data-testid="gate-uploaded-samples">{uploadedSamples}</dd>
    <dt>End markers</dt><dd data-testid="gate-ends">{ends}</dd>
    <dt>Speech resumes</dt><dd data-testid="gate-resumes">{resumes}</dd>
    <dt>Replayed prefix (ms)</dt><dd data-testid="gate-prefix">{prefixMs}</dd>
    <dt>Public speech playing</dt><dd data-testid="gate-playing">{String(playing)}</dd>
    <dt>Local stream</dt><dd data-testid="gate-track">{trackState}</dd>
    <dt>Audio context</dt><dd data-testid="gate-context">{contextState}</dd>
  </dl>
  {#if error}<p role="alert">{error}</p>{/if}
</section>

<style>
  section { color:var(--color-font-primary); background:var(--color-grey-0); border-radius:var(--radius-4); padding:var(--spacing-6); max-width:52rem; box-sizing:border-box; }
  h2 { margin-block-start:0; font-size:var(--font-size-large); }
  .actions { display:flex; flex-wrap:wrap; gap:var(--spacing-3); }
  button { min-height:2.5rem; padding:var(--spacing-3); color:var(--color-font-primary); background:var(--color-grey-10); border:1px solid var(--color-grey-30); border-radius:var(--radius-2); cursor:pointer; }
  button:focus-visible { outline:2px solid var(--color-primary); outline-offset:2px; }
  button:disabled { opacity:.5; cursor:default; }
  dl { display:grid; grid-template-columns:1fr auto; gap:var(--spacing-2) var(--spacing-5); font-variant-numeric:tabular-nums; }
  dd { margin:0; }
</style>
