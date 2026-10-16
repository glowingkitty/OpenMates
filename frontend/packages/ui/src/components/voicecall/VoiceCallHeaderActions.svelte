<script lang="ts">
  import { text } from '@repo/ui';
  import { tooltip } from '../../actions/tooltip';
  import type { Readable } from 'svelte/store';
  import type { VoiceCallStatus } from '../../services/voiceCall';

  let { callState, showCall, showClose, closingChat = false, onToggleCall, onClose }: {
    callState: Readable<{ status: VoiceCallStatus }>;
    showCall: boolean;
    showClose: boolean;
    closingChat?: boolean;
    onToggleCall: () => void;
    onClose: () => void;
  } = $props();
  const active = $derived($callState.status === 'connecting' || $callState.status === 'live');
</script>

<!-- Physical ordering matches the handset/Close pair in every pane and locale. -->
<div class="voice-call-header-actions" data-testid="voice-call-header-actions">
  {#if showCall}
    <div class="new-chat-button-wrapper">
      <button class="header-action" type="button" data-testid="voice-call-start"
        data-call-state={$callState.status} aria-pressed={active}
        aria-label={$text(active ? 'voicecall.hangup' : 'voicecall.start')}
        aria-describedby={active ? undefined : 'voice-call-start-hint'}
        title={active ? undefined : $text('voicecall.start_hint')}
        onclick={onToggleCall} use:tooltip>
        <span class="clickable-icon icon_call top-button" data-testid="voice-call-handset"
          data-icon="audiocall" class:hangup={active} aria-hidden="true"
          style:background={active ? 'var(--color-error)' : undefined}
          style:filter={active ? 'none' : undefined}></span>
      </button>
      <span class="sr-only" id="voice-call-start-hint">{$text('voicecall.start_hint')}</span>
    </div>
  {/if}
  {#if showClose}
    <div class="new-chat-button-wrapper">
      <button class="header-action" type="button" data-testid="chat-close-button"
        aria-label={$text('common.close')} disabled={closingChat} onclick={onClose} use:tooltip>
        <span class="clickable-icon icon_close top-button" aria-hidden="true"></span>
      </button>
    </div>
  {/if}
</div>

<style>
  .voice-call-header-actions {
    display: flex;
    flex-direction: row;
    flex-wrap: nowrap;
    align-items: center;
    gap: var(--spacing-4);
    direction: ltr;
    width: max-content;
  }
  .new-chat-button-wrapper {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--spacing-4);
    background-color: var(--color-grey-10);
    border-radius: var(--radius-full);
    box-shadow: var(--shadow-md);
    pointer-events: auto;
    transition: background-color var(--duration-normal), transform var(--duration-fast), box-shadow var(--duration-fast);
  }
  .new-chat-button-wrapper:hover { transform: scale(1.08); box-shadow: var(--shadow-lg); }
  .new-chat-button-wrapper:active { transform: scale(.95); box-shadow: var(--shadow-xs); }
  button {
    all: unset;
    display: flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    min-width: 25px;
    min-height: 25px;
    cursor: pointer;
    pointer-events: auto;
  }
  /* --color-primary is a gradient. Use the solid focus token and outrank the
     parent header menu's generic button reset/outline when embedded there. */
  .voice-call-header-actions button.header-action:focus-visible {
    outline: 2px solid var(--color-button-primary);
    outline-offset: 4px;
    border-radius: var(--radius-full);
  }
  button:disabled { opacity: .5; cursor: default; }
  .clickable-icon { display: block; flex: none; width: 25px; height: 25px; margin: 0; }
  .sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
  .icon_call { transform: rotate(0deg); transition: transform var(--duration-normal); }
  .icon_call.hangup { transform: rotate(135deg); }
  @media (prefers-reduced-motion: reduce) {
    .new-chat-button-wrapper, .icon_call { transition: none; }
  }
</style>
