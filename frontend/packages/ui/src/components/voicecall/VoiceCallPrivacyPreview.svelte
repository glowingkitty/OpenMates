<script lang="ts">
  import VoiceCallPrivacyDialog from './VoiceCallPrivacyDialog.svelte';
  let { failFirst = false }: { failFirst?: boolean } = $props();
  let visible = $state(true);
  let result = $state('Pending');
  let saves = $state(0);
  async function save() {
    saves++;
    if (failFirst && saves === 1) throw new Error('Preview save failure');
    result = 'Saved'; visible = false;
  }
</script>
<div data-testid="privacy-preview-result">{result}</div>
<div data-testid="privacy-preview-saves">{saves}</div>
{#if visible}<VoiceCallPrivacyDialog onContinue={save} onCancel={() => { result = 'Cancelled'; visible = false; }} />{/if}
