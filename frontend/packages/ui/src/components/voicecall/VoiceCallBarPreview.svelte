<script lang="ts">
  import { onMount } from 'svelte';
  import { writable } from 'svelte/store';
  import VoiceCallBar from './VoiceCallBar.svelte';
  import NotificationStack from '../NotificationStack.svelte';
  import { initialVoiceCallState, type VoiceCallState, type VoiceCallControllerLike } from '../../services/voiceCall';
  import { downsample, pcm16Base64 } from '../videocall/callAudio';
  import { voicePcmEnvelope } from '../../services/voiceCall';
  let { state:initialState = {}, fixed = false, realAudio = true }: { state?:Partial<VoiceCallState>; fixed?:boolean; realAudio?:boolean } = $props();
  const store = writable<VoiceCallState>({ ...initialVoiceCallState, status:'live' as const, chatId:'preview-chat', callId:'preview-call', activeElapsedSeconds:15, billingActivity:{inputListening:true,processing:false} });
  let closed = $state(false);
  const controller: VoiceCallControllerLike = {
    subscribe:store.subscribe,
    async start() { store.update(current => ({ ...current,status:'connecting',error:null,activeElapsedSeconds:0 })); },
    async submitText() { return true; },
    setMuted(muted) { store.update(current => ({ ...current, muted, audioLevels:muted && !current.assistantSpeaking ? Array(16).fill(0) : current.audioLevels, billingActivity:{inputListening:!muted,processing:current.billingActivity?.processing ?? false} })); },
    setMinimized(minimized) { store.update(current => ({ ...current,minimized })); },
    hangup() { store.update(current => ({ ...current,status:'ended',audioLevels:Array(16).fill(0) })); },
  };
  onMount(() => {
    store.update(current => ({...current,...initialState}));
    if (!realAudio) return;
    const context = new AudioContext();
    let disposed = false;
    // One public voice-note window supplies genuine RMS fixture values. No
    // microphone, random bars, detector substitute or continuous preview timer.
    void fetch('/store-examples/transcription-demo-voice-note.wav').then(response => response.arrayBuffer())
      .then(bytes => context.decodeAudioData(bytes)).then(buffer => {
        if (disposed) return;
        const start = Math.floor(buffer.sampleRate * .85);
        const samples = buffer.getChannelData(0).slice(start,start+2048);
        const levels = voicePcmEnvelope(pcm16Base64(downsample(samples,buffer.sampleRate)));
        store.update(current => ({...current,audioLevels:levels}));
      }).catch(() => { /* A missing public asset leaves a truthful flat envelope. */ }).finally(() => { if(context.state !== 'closed') void context.close(); });
    return () => { disposed=true; if(context.state !== 'closed') void context.close(); };
  });
</script>
{#snippet moreActions()}
  <details class="fixture-menu" data-testid="voice-call-menu">
    <summary aria-label="More chat actions" data-testid="voice-call-more"><span class="clickable-icon icon_more" aria-hidden="true"></span></summary>
    <div role="menu">
      <button role="menuitem" onclick={() => controller.setMuted(!$store.muted)}>{$store.muted ? 'Unmute' : 'Mute'}</button>
      <button role="menuitem" onclick={() => { closed=true; }}>Close chat</button>
    </div>
  </details>
{/snippet}
<div class="fixture-stack">
  <VoiceCallBar {controller} {fixed} {moreActions} onReturn={() => {}} onCloseChat={() => { closed=true; }} />
  {#if closed}<span data-testid="preview-chat-closed">Chat closed; call retained</span>{/if}
</div>
<NotificationStack />
<style>
  .fixture-stack { display:flex; flex-direction:column; width:100%; min-width:0; }
  .fixture-menu { position:relative; color:var(--color-font-button); }
  summary { display:flex; align-items:center; justify-content:center; width:2.75rem; height:2.75rem; border-radius:var(--radius-full); background:color-mix(in srgb,currentColor 20%,transparent); box-shadow:var(--shadow-md); cursor:pointer; list-style:none; }
  summary::-webkit-details-marker { display:none; }
  summary:focus-visible { outline:2px solid currentColor; outline-offset:3px; }
  .icon_more { mask-image:url("@openmates/ui/static/icons/more.svg"); -webkit-mask-image:url("@openmates/ui/static/icons/more.svg"); }
  .clickable-icon { width:1.5rem; height:1.5rem; margin:0; background:currentColor; }
  [role='menu'] { position:absolute; inset-inline-start:0; top:calc(100% + var(--spacing-4)); min-width:10rem; padding:var(--spacing-4); border-radius:var(--radius-4); color:var(--color-font-primary); background:var(--color-grey-0); box-shadow:var(--shadow-md); z-index:var(--z-index-dropdown-2); }
  [role='menuitem'] { display:block; width:100%; text-align:start; padding:var(--spacing-4); border:0; background:transparent; color:inherit; cursor:pointer; }
  @media(max-width:700px) { summary { width:2.25rem; height:2.25rem; } }
</style>
