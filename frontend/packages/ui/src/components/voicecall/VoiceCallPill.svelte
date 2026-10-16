<script lang="ts">
  import { text } from '../../i18n/translations';
  let { activeElapsedSeconds, activityActive, onReturn }: { activeElapsedSeconds:number; activityActive:boolean; onReturn:()=>void } = $props();
  const duration = $derived(`${String(Math.floor(activeElapsedSeconds / 60)).padStart(2,'0')}:${String(activeElapsedSeconds % 60).padStart(2,'0')}`);
</script>
<button class="call-pill" data-testid="voice-call-pill" aria-label={$text('voicecall.return_to_chat')} onclick={onReturn}>
  <span class="clickable-icon icon_call" aria-hidden="true"></span><strong class:inactive={!activityActive} data-testid="voice-call-pill-timer">{duration}</strong>
</button>
<style>
  .call-pill { display:inline-flex; align-items:center; gap:var(--spacing-2); margin:0; margin-right:0; padding:var(--spacing-4) var(--spacing-5); min-width:0; min-height:2.5rem; box-sizing:border-box; filter:none; height:auto; border:0; border-radius:var(--radius-full); background:var(--gradient-primary); color:var(--color-font-button); cursor:pointer; font:inherit; font-size:var(--font-size-small); animation:voice-call-pulse 3s ease-in-out infinite; }
  .clickable-icon { width:.875rem; height:.875rem; margin:0; background:currentColor; }
  strong { font-variant-numeric:tabular-nums; transition:opacity 200ms ease; }
  strong.inactive { opacity:.48; }
  button:focus-visible { outline:2px solid var(--color-primary-start); outline-offset:3px; }
  @keyframes voice-call-pulse { 0%,100% { opacity:1; } 50% { opacity:.82; } }
  @media(prefers-reduced-motion:reduce) { .call-pill { animation:none; } strong { transition:none; } }
</style>
