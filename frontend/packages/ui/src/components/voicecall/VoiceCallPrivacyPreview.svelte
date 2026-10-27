<script lang="ts">
  import { onMount } from 'svelte';
  import NotificationStack from '../NotificationStack.svelte';
  import { ensureVoiceCallPrivacyAcknowledgement } from '../../services/voiceCallPrivacy';
  let { failFirst = false, holdSave = false }: { failFirst?: boolean; holdSave?: boolean } = $props();
  let result = $state('Pending');
  let reads = $state(0);
  let saves = $state(0);
  let gestures = $state(0);
  const abort = new AbortController();
  let releaseSave: (() => void) | undefined;
  onMount(() => {
    const originalFetch = window.fetch;
    const previewFetch: typeof fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (url.pathname !== '/v1/settings/voice-processing-ack') return originalFetch.call(window, input, init);
      const saving = String(init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase() === 'POST';
      if (saving) saves++; else reads++;
      if (saving && holdSave) await new Promise<void>(resolve => { releaseSave = resolve; });
      const failed = saving && failFirst && saves === 1;
      return new Response(JSON.stringify({ version: 2, acknowledged: saving && !failed, acknowledged_at: saving && !failed ? 1700000000 : null }), { status: failed ? 503 : 200, headers: { 'Content-Type': 'application/json' } });
    };
    window.fetch = previewFetch;
    void ensureVoiceCallPrivacyAcknowledgement(abort.signal, () => { gestures++; }).then(accepted => { result = accepted ? 'Saved' : 'Cancelled'; }).catch(() => { result = 'Unavailable'; });
    return () => { abort.abort(); releaseSave?.(); if (window.fetch === previewFetch) window.fetch = originalFetch; };
  });
</script>
<NotificationStack />
<div data-testid="privacy-preview-result">{result}</div>
<div data-testid="privacy-preview-reads">{reads}</div>
<div data-testid="privacy-preview-saves">{saves}</div>
<div data-testid="privacy-preview-gestures">{gestures}</div>
<button data-testid="privacy-preview-abort" onclick={() => abort.abort()}>Abort pending launch</button>
{#if holdSave}<button data-testid="privacy-preview-release" onclick={() => releaseSave?.()}>Complete profile save</button>{/if}
