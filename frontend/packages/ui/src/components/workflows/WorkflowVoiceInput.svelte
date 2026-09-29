<script lang="ts">
  import { onMount } from 'svelte';
  import { startAudioRealtimeTranscription, type AudioRealtimeTranscriptionHandle } from '../../services/audioRealtimeTranscription';
  import { text } from '../../i18n/translations';

  let { onSubmit, onReview, onClose, previewOnly = false, previewText = '' }: {
    onSubmit: (text: string) => void | Promise<void>;
    onReview: (text: string) => void;
    onClose: () => void;
    previewOnly?: boolean;
    previewText?: string;
  } = $props();
  let status = $state('connecting');
  let preview = $state('');
  let error = $state('');
  let finishing = $state(false);
  let stream: MediaStream | null = null;
  let handle = $state<AudioRealtimeTranscriptionHandle | null>(null);
  let closed = false;

  function release(): void {
    stream?.getTracks().forEach(track => track.stop());
    stream = null;
  }

  onMount(() => {
    if (previewOnly) {
      status = 'listening';
      preview = previewText;
      return;
    }
    void (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (closed) { release(); return; }
        handle = startAudioRealtimeTranscription(stream, {
          onTranscript: value => preview = value,
          onStatus: value => status = value
        });
      } catch (cause) {
        error = cause instanceof Error ? cause.message : $text('workflows.builder.voice_microphone_unavailable');
        release();
      }
    })();
    return () => { closed = true; handle?.cancel(); release(); };
  });

  async function finish(): Promise<void> {
    if (!handle || finishing) return;
    finishing = true;
    handle.finish();
    release();
    try {
      const raw = await handle.transcription;
      preview = raw.transcript;
      status = 'correcting';
      try {
        const corrected = await handle.correction;
        if (!corrected.useCorrected) {
          onReview(raw.transcript);
          onClose();
          return;
        }
        const instruction = corrected.transcriptCorrected || '';
        if (!instruction.trim()) throw new Error($text('workflows.builder.voice_no_speech'));
        await onSubmit(instruction.trim());
        onClose();
      } catch {
        onReview(raw.transcript);
        onClose();
      }
    } catch (cause) {
      error = cause instanceof Error ? cause.message : $text('workflows.builder.voice_transcription_failed');
      finishing = false;
    }
  }

  function cancel(): void { handle?.cancel(); release(); onClose(); }
</script>

<div class="voice-input" data-testid="workflow-voice-input" role="dialog" aria-label={$text('workflows.builder.voice_dialog')}>
  <p role="status">{$text(`workflows.builder.voice_${status === 'listening' ? 'listening' : status === 'correcting' ? 'correcting' : 'connecting'}`)}</p>
  <p class="preview" data-testid="workflow-voice-preview">{preview || $text('workflows.builder.voice_preview')}</p>
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  <div class="actions">
    <button type="button" onclick={cancel} data-testid="workflow-voice-cancel">{$text('workflows.builder.voice_cancel')}</button>
    <button type="button" onclick={() => void finish()} disabled={!handle || finishing} data-testid="workflow-voice-finish">{$text('workflows.builder.voice_finish')}</button>
  </div>
</div>

<style>
  .voice-input{box-sizing:border-box;width:min(629px,100%);margin:0 auto;padding:1rem 1.25rem;border-radius:1.25rem;background:var(--color-grey-blue);color:var(--color-font-primary);box-shadow:var(--shadow-md)}
  p{margin:.3rem 0}.preview{min-height:2.5rem;white-space:pre-wrap;overflow-wrap:anywhere}.error{color:var(--color-error)}
  .actions{display:flex;justify-content:flex-end;gap:.75rem}.actions button{border:0;border-radius:.7rem;padding:.55rem 1rem;background:var(--color-button-primary);color:var(--color-font-button);font:inherit;cursor:pointer}.actions button:disabled{opacity:.5}
</style>
