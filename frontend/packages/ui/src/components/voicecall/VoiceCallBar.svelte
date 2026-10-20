<script lang="ts">
  import { onMount, type Snippet } from 'svelte';
  import { text } from '../../i18n/translations';
  import { voiceCallController, initialVoiceCallState, type VoiceCallControllerLike, type VoiceCallState } from '../../services/voiceCall';
  import VoiceCallWaveform from './VoiceCallWaveform.svelte';
  import VoiceCallMedia from './VoiceCallMedia.svelte';

  let { controller = voiceCallController, onReturn: _onReturn, boundChatVisible: _boundChatVisible = true,
    underFloatingHeader: _underFloatingHeader = false, underGlobalHeader: _underGlobalHeader = false,
    fixed = false, moreActions, onMore, onCloseChat }: {
    controller?: VoiceCallControllerLike;
    onReturn: (chatId: string) => void;
    boundChatVisible?: boolean;
    underFloatingHeader?: boolean;
    underGlobalHeader?: boolean;
    fixed?: boolean;
    moreActions?: Snippet;
    onMore?: () => void;
    onCloseChat?: () => void;
  } = $props();
  let state = $state<VoiceCallState>({ ...initialVoiceCallState });
  onMount(() => controller.subscribe(next => { state = next; }));
  const active = $derived(state.status === 'connecting' || state.status === 'live');
  const activityActive = $derived(state.billingActivity === null || state.billingActivity.inputListening || state.billingActivity.processing);
  const duration = $derived(`${String(Math.floor(state.activeElapsedSeconds / 60)).padStart(2, '0')}:${String(state.activeElapsedSeconds % 60).padStart(2, '0')}`);
  const errorKey = $derived(state.error && ['microphone_denied', 'microphone_missing', 'microphone_failed', 'session_expired',
    'connection_failed', 'connection_lost', 'invalid_response', 'transcript_save_failed', 'transcript_limit',
    'context_too_large', 'context_unavailable'].includes(state.error) ? state.error : 'call_unavailable');
  const statusKey = $derived(state.status === 'connecting' ? 'connecting' : state.status === 'error' ? errorKey :
    state.userSpeaking ? 'live' : state.assistantSpeaking ? 'assistant_speaking' : state.billingActivity?.processing ? 'working' :
    state.muted ? 'muted' : state.inputIdle && state.billingActivity?.inputListening === false &&
      state.billingActivity.processing === false ? 'input_idle' : 'live');
</script>

{#if active || state.status === 'error'}
  <aside class="voice-call-bar" class:fixed data-testid="voice-call-bar" aria-label={$text('voicecall.title')} aria-busy={state.status === 'connecting'}>
    <div class="edge left">
      {#if fixed && moreActions}{@render moreActions()}
      {:else if fixed && onMore}<button class="round" data-testid="voice-call-more" aria-label={$text('voicecall.more_actions')} onclick={onMore}><span class="clickable-icon icon_more" aria-hidden="true"></span></button>{/if}
      <button class="round" class:camera-active={state.cameraEnabled} data-testid="voice-call-video"
        aria-label={$text(state.cameraEnabled ? 'voicecall.camera_off' : 'voicecall.video_call')}
        aria-pressed={state.cameraEnabled} aria-busy={state.cameraPending}
        disabled={state.status !== 'live' || !state.cameraAvailable}
        onclick={() => controller.setCameraEnabled(!state.cameraEnabled && !state.cameraPending)}>
        <span class="clickable-icon icon_video_call" aria-hidden="true"></span>
      </button>
    </div>
    <div class="call-center" class:inactive={!activityActive}>
      {#if state.status === 'connecting'}<span class="connecting-spinner" data-testid="voice-call-connecting" aria-hidden="true"></span>{/if}
      <strong data-testid="voice-call-timer">{duration}</strong>
      <div class="wave">
        <VoiceCallWaveform levels={state.audioLevels} />
        <button class="round microphone" class:muted={state.muted} data-testid="voice-call-mute" data-activity-active={activityActive}
          aria-label={state.status === 'error' ? $text(`voicecall.${errorKey}`) : $text(state.muted ? 'voicecall.unmute' : 'voicecall.mute')}
          aria-pressed={state.muted} aria-describedby="voice-call-accessible-status" disabled={state.status !== 'live'} onclick={() => controller.setMuted(!state.muted)}>
          <span class="clickable-icon icon_recordaudio" aria-hidden="true"></span>
          {#if state.muted}<span class="microphone-slash" aria-hidden="true"></span>{/if}
        </button>
      </div>
    </div>
    <div class="edge right">
      <button class="round hangup" data-testid="voice-call-hangup" aria-label={$text(state.status === 'error' ? 'voicecall.close' : 'voicecall.hangup')} onclick={() => controller.hangup()}>
        <span class="clickable-icon icon_call" aria-hidden="true"></span>
      </button>
      {#if fixed && onCloseChat}<button class="round" data-testid="voice-call-close-chat" aria-label={$text('voicecall.close_chat')} onclick={onCloseChat}><span class="clickable-icon icon_close" aria-hidden="true"></span></button>{/if}
    </div>
    <span class="sr-only" id="voice-call-accessible-status" role={state.status === 'error' ? 'alert' : 'status'} data-testid="voice-call-status"><span data-testid="voice-call-status-text">{$text(`voicecall.${statusKey}`)}</span></span>
    {#if active && (state.cameraEnabled || state.displayedMedia || state.cameraError)}
      <div class="media-stage">
        <VoiceCallMedia cameraStream={state.cameraStream} cameraEnabled={state.cameraEnabled}
          cameraFacing={state.cameraFacing} expanded={state.mediaExpanded} displayedMedia={state.displayedMedia}
          mediaCount={state.mediaItems.length} mediaIndex={state.mediaIndex}
          error={state.cameraError ? $text(`voicecall.${state.cameraError}`) : null}
          onExpandedChange={expanded => controller.setMediaExpanded(expanded)} onShowCamera={() => controller.showCamera()}
          onFlipCamera={() => controller.flipCamera()} onPrevious={() => controller.selectMedia(state.mediaIndex - 1)}
          onNext={() => controller.selectMedia(state.mediaIndex + 1)} />
      </div>
    {/if}
  </aside>
  {#if state.status === 'error'}
    <div class="call-error" role="alert" data-testid="voice-call-error">
      <span>{$text(`voicecall.${errorKey}`)}</span>
      {#if state.error !== 'context_too_large'}<button onclick={() => controller.start(state.chatId ?? undefined)}>{$text('voicecall.retry')}</button>{/if}
    </div>
  {/if}
{/if}

<style>
  .voice-call-bar { position:relative; display:grid; grid-template-columns:1fr auto 1fr; align-items:center; gap:var(--spacing-4); width:100%; box-sizing:border-box; min-height:4.25rem; padding:var(--spacing-6); border-radius:var(--radius-6); background:var(--gradient-primary); color:var(--color-font-button); }
  .edge { direction:ltr; display:flex; align-items:center; gap:var(--spacing-4); min-width:0; }
  .media-stage { grid-column:1 / -1; min-width:0; }
  .right { justify-content:flex-end; }
  .voice-call-bar button { margin:0; border:0; height:auto; min-width:0; font:inherit; color:inherit; cursor:pointer; filter:none; }
  .voice-call-bar button:focus-visible { outline:2px solid var(--color-font-button); outline-offset:3px; }
  .voice-call-bar .round { display:flex; align-items:center; justify-content:center; flex:none; width:2.75rem; height:2.75rem; padding:var(--spacing-4); border-radius:var(--radius-full); background:color-mix(in srgb,var(--color-font-button) 20%,transparent); box-shadow:var(--shadow-md); }
  .voice-call-bar .round:hover { background:color-mix(in srgb,var(--color-font-button) 30%,transparent); }
  .voice-call-bar .camera-active { background:color-mix(in srgb,var(--color-font-button) 40%,transparent); }
  .voice-call-bar .round:disabled { cursor:default; opacity:.5; }
  .icon_more { mask-image:url("@openmates/ui/static/icons/more.svg"); -webkit-mask-image:url("@openmates/ui/static/icons/more.svg"); }
  .clickable-icon { display:block; width:1.75rem; height:1.75rem; margin:0; background:currentColor; }
  .hangup .icon_call { color:var(--color-button-primary); transform:rotate(135deg); }
  .call-center { direction:ltr; display:flex; align-items:center; justify-content:center; gap:var(--spacing-4); padding:var(--spacing-2); opacity:1; }
  .call-center.inactive strong { opacity:.48; }
  .call-center strong { font-size:var(--font-size-h4); font-weight:var(--font-weight-bold); font-variant-numeric:tabular-nums; white-space:nowrap; transition:opacity 200ms ease; }
  .wave { position:relative; width:clamp(4rem,28vw,24rem); max-width:100%; }
  .fixed .wave { width:clamp(2.5rem,20vw,22rem); }
  .voice-call-bar .microphone { position:absolute; inset-block-start:50%; inset-inline-start:50%; transform:translate(-50%,-50%); z-index:1; }
  .voice-call-bar .microphone.muted { color:var(--color-button-primary); }
  .microphone-slash { position:absolute; width:1.5rem; height:.19rem; border-radius:var(--radius-full); background:currentColor; transform:rotate(-45deg); }
  .microphone:disabled { cursor:default; }
  .connecting-spinner { width:1rem; height:1rem; flex:none; border:2px solid color-mix(in srgb,currentColor 35%,transparent); border-top-color:currentColor; border-radius:var(--radius-full); animation:spin 1s linear infinite; }
  @keyframes spin { to { transform:rotate(360deg); } }
  .call-error { display:flex; align-items:center; justify-content:space-between; gap:var(--spacing-4); padding:var(--spacing-6); color:var(--color-error); background:var(--color-error-light); border-radius:var(--radius-4); font-size:var(--font-size-small); }
  .call-error button { flex:none; color:var(--color-font-primary); background:var(--color-grey-10); border:1px solid var(--color-grey-30); border-radius:var(--radius-full); padding:var(--spacing-4); cursor:pointer; }
  .sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
  @media(max-width:700px) { .voice-call-bar { padding:var(--spacing-4); gap:var(--spacing-2); } .edge { gap:var(--spacing-2); } .fixed .round { width:2.25rem; height:2.25rem; padding:var(--spacing-3); } .fixed .wave { width:clamp(2.5rem,16vw,4rem); } }
  @media(prefers-reduced-motion:reduce) { .call-center strong { transition:none; } .connecting-spinner { animation:none; } }
</style>
