<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { get } from 'svelte/store';
  import Header from '../Header.svelte';
  import Settings from '../Settings.svelte';
  import { demoMode } from '../../stores/demoModeStore';
  import { showSignupFooter } from '../../stores/signupState';
  import { voiceCallController, initialVoiceCallState, type VoiceCallState } from '../../services/voiceCall';


  const originalDemoMode = demoMode.get();
  const originalSignupFooter = get(showSignupFooter);
  demoMode.set(true);
  showSignupFooter.set(false);
  onDestroy(() => {
    demoMode.set(originalDemoMode);
    showSignupFooter.set(originalSignupFooter);
  });

  let { state = {} }: { state?:Partial<VoiceCallState> } = $props();
  const originalCall = get(voiceCallController);
  const fixture = voiceCallController as unknown as { update: (state:Partial<VoiceCallState>) => void };
  onMount(() => fixture.update({ ...initialVoiceCallState, status:'live',chatId:'preview-chat',callId:'preview-call',activeElapsedSeconds:15,
    billingActivity:{inputListening:true,processing:false}, ...state }));
  onDestroy(() => fixture.update(originalCall));
  const onReturn = () => window.dispatchEvent(new CustomEvent('voice-call-preview-return'));
</script>

<div class="global-call-preview">
  <Header context="webapp" isLoggedIn={true} voiceCallPill={{ onReturn }} />
  <main aria-label="Chat workspace"></main>
  <Settings isLoggedIn={false} />
</div>

<style>
  /* The production header and detached bar both use the viewport as origin.
     Escape the preview canvas's 32px capture padding for the same geometry. */
  .global-call-preview { position:fixed; inset:0; display:flex; flex-direction:column; }
  .global-call-preview :global(header.webapp) { flex:none; }
  main { flex:1; }
</style>
