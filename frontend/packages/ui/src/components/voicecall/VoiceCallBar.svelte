<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '../../i18n/translations';
  import { voiceCallController, initialVoiceCallState, type VoiceCallControllerLike, type VoiceCallState } from '../../services/voiceCall';

  let { controller = voiceCallController, onReturn, boundChatVisible = true, underFloatingHeader = false }: {
    controller?: VoiceCallControllerLike;
    onReturn: (chatId: string) => void;
    boundChatVisible?: boolean;
    underFloatingHeader?: boolean;
  } = $props();
  let state = $state<VoiceCallState>({ ...initialVoiceCallState });
  onMount(() => controller.subscribe((next) => { state = next; }));

  function clock(seconds: number): string {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const rest = Math.floor(seconds % 60);
    return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`
      : `${minutes}:${String(rest).padStart(2, '0')}`;
  }
  const active = $derived(state.status === 'connecting' || state.status === 'live');
  const credits = $derived(state.usage?.credits_charged ?? 0);
  const rate = $derived(state.usage?.audio_credits_per_minute ?? 27.6);
  const compact = $derived(state.minimized || !boundChatVisible);
  const errorKey = $derived(state.error === 'transcript_limit' ? 'transcript_limit' :
    state.error && ['microphone_denied', 'microphone_missing', 'microphone_failed', 'session_expired',
      'connection_failed', 'connection_lost', 'invalid_response', 'transcript_save_failed'].includes(state.error)
      ? state.error : 'call_unavailable');
</script>

{#if active || state.status === 'error'}
  <aside class="voice-call-bar" class:compact class:under-floating-header={underFloatingHeader && !compact} data-testid="voice-call-bar" aria-label={$text('voicecall.title')}>
    <div class="identity">
      <span class="call-dot" class:pulse={state.status === 'connecting' || state.assistantSpeaking || state.userSpeaking} data-testid="voice-call-indicator" aria-hidden="true"></span>
      <div class="identity-text">
        <strong>{$text('voicecall.title')}</strong>
        <span>{$text('voicecall.provider')}</span>
      </div>
    </div>
    {#if !compact}
      <div class="call-status" role="status" data-testid="voice-call-status">
        {#if state.status === 'connecting'}{$text('voicecall.connecting')}
        {:else if state.status === 'error'}{$text(`voicecall.${errorKey}`)}
        {:else if state.muted}{$text('voicecall.muted')}
        {:else if state.assistantSpeaking}{$text('voicecall.assistant_speaking')}
        {:else}{$text('voicecall.live')}{/if}
      </div>
      <div class="call-meter">
        <span data-testid="voice-call-timer">{clock(state.elapsedSeconds)}</span>
        <span data-testid="voice-call-usage">{credits} {$text('voicecall.credits')} · {Math.round(rate)} {$text('voicecall.credits_per_minute')}</span>
      </div>
    {:else}
      <div class="compact-details" role="status" data-testid="voice-call-status">
        <span>{state.status === 'connecting' ? $text('voicecall.connecting') :
          state.status === 'error' ? $text(`voicecall.${errorKey}`) :
          state.muted ? $text('voicecall.muted') : $text('voicecall.live')}</span>
        <span><span data-testid="voice-call-timer">{clock(state.elapsedSeconds)}</span> · <span data-testid="voice-call-usage">{credits} {$text('voicecall.credits')} · {Math.round(rate)} {$text('voicecall.credits_per_minute')}</span></span>
      </div>
    {/if}
    <div class="call-actions">
      {#if state.chatId}
        <button type="button" data-testid="voice-call-return" onclick={() => onReturn(state.chatId!)}>{$text('voicecall.return_to_chat')}</button>
      {/if}
      {#if state.status === 'live'}
        <button type="button" data-testid="voice-call-mute" aria-pressed={state.muted} onclick={() => controller.setMuted(!state.muted)}>{state.muted ? $text('voicecall.unmute') : $text('voicecall.mute')}</button>
      {/if}
      {#if active && boundChatVisible}
        <button type="button" data-testid="voice-call-minimize" aria-expanded={!compact} onclick={() => controller.setMinimized(!state.minimized)}>{compact ? $text('voicecall.expand') : $text('voicecall.minimize')}</button>
      {/if}
      <button class="hangup" type="button" data-testid="voice-call-hangup" onclick={() => controller.hangup()}>{state.status === 'error' ? $text('voicecall.close') : $text('voicecall.hangup')}</button>
    </div>
  </aside>
{/if}

<style>
  .voice-call-bar {
    --call-foreground: var(--color-font-button);
    position: relative;
    z-index: var(--z-index-dropdown-2);
    align-self: center;
    flex: 0 0 auto;
    height: max-content;
    margin: var(--spacing-3) auto var(--spacing-4);
    width: min(900px, calc(100% - var(--spacing-8)));
    box-sizing: border-box;
    display: flex;
    align-items: center;
    gap: var(--spacing-5);
    padding: var(--spacing-6) var(--spacing-8);
    border-radius: var(--radius-6);
    background: var(--gradient-primary);
    color: var(--call-foreground);
    box-shadow: var(--shadow-lg);
    font-size: var(--font-size-small);
  }
  .voice-call-bar.compact { position:fixed; z-index:var(--z-index-popover); inset-inline-end:var(--spacing-4); inset-block-start:var(--spacing-4); margin:0; width:min(500px,calc(100vw - var(--spacing-8))); flex-wrap:wrap; gap:var(--spacing-2) var(--spacing-4); }
  .voice-call-bar.under-floating-header { margin-block-start:64px; }
  .identity,.call-actions { display:flex; align-items:center; gap:var(--spacing-3); }
  .identity { min-width:max-content; }
  .identity-text { display:flex; flex-direction:column; line-height:1.25; }
  .identity-text span { opacity:.86; font-size:var(--font-size-xs); }
  .call-dot { width:12px; height:12px; flex:none; border-radius:50%; background:var(--call-foreground); }
  .call-dot.pulse { animation:pulse 1.5s ease-in-out infinite; }
  @keyframes pulse { 50% { transform:scale(1.35); opacity:.55; } }
  .call-status { flex:1; min-width:90px; overflow-wrap:anywhere; }
  .call-meter { display:flex; flex-direction:column; align-items:flex-end; min-width:max-content; font-variant-numeric:tabular-nums; }
  .call-meter span:last-child { opacity:.86; font-size:var(--font-size-xs); }
  .compact-details { flex:1; min-width:160px; display:flex; flex-direction:column; line-height:1.25; }
  .compact-details span:last-child { font-size:var(--font-size-xs); opacity:.86; font-variant-numeric:tabular-nums; }
  .call-actions { flex-wrap:wrap; justify-content:flex-end; }
  button {
    min-width: 0;
    min-height: 40px;
    height: auto;
    margin: 0;
    padding: var(--spacing-4) var(--spacing-6);
    border: 1px solid color-mix(in srgb, var(--call-foreground) 45%, transparent);
    border-radius: var(--radius-full);
    background: color-mix(in srgb, var(--call-foreground) 18%, transparent);
    color: var(--call-foreground);
    filter: none;
    font: inherit;
    line-height: 1.2;
    cursor: pointer;
  }
  button:hover { background:color-mix(in srgb,var(--call-foreground) 30%,transparent); }
  button:focus-visible { outline:3px solid var(--call-foreground); outline-offset:2px; }
  button.hangup { background:var(--color-button-primary); color:var(--call-foreground); border-color:var(--color-button-primary); }
  button.hangup:hover { background:var(--color-button-primary-hover); }
  @media (max-width:700px) {
    .voice-call-bar:not(.compact) { flex-wrap:wrap; gap:var(--spacing-3); }
    .call-meter { order:1; margin-inline-start:auto; }
    .call-status { order:2; width:100%; flex:auto; }
    .call-actions { order:3; width:100%; justify-content:flex-start; }
    .compact .identity-text span { display:none; }
    .compact .compact-details { min-width:0; }
    .compact .call-actions { width:100%; }
    .compact .call-actions button { min-height:36px; }
  }
</style>
