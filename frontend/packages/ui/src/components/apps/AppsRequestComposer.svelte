<script lang="ts">
  import { onDestroy } from 'svelte';
  import WorkspacePromptComposer from '../workspace/WorkspacePromptComposer.svelte';
  import { text } from '../../i18n/translations';

  let { appId, value = $bindable(''), files = $bindable<File[]>([]), disabled = false, submitting = false, placeholder, presentation = 'workspace',
    onSubmit }: { appId: string; value?: string; files?: File[]; disabled?: boolean; submitting?: boolean; placeholder?: string; presentation?: 'workspace' | 'embed';
      onSubmit: (text: string, attachments: File[]) => void | boolean | Promise<void | boolean> } = $props();
  let input = $state<HTMLInputElement>();
  let cameraInput = $state<HTMLInputElement>();
  function addPicked(picker: HTMLInputElement | undefined) {
    files = [...files, ...Array.from(picker?.files ?? [])];
    if (picker) picker.value = '';
  }
  let recording = $state(false);
  let error = $state(false);
  let alive = true;
  onDestroy(() => { alive = false; });
  function closeRecording() { recording = false; }
  async function submit(request: string): Promise<boolean> {
    const accepted = await onSubmit(request, [...files]);
    if (!alive || accepted === false) return false;
    files = []; value = ''; return true;
  }
  // Dictation streams into the shared composer; audio without any transcript is kept as an attachment.
  function keepUntranscribedAudio(audio: { blob: Blob; mimeType: string; failed: boolean }) {
    if (!alive) return;
    files = [...files, new File([audio.blob], 'recording.webm', { type: audio.mimeType })];
    error = audio.failed;
  }
</script>

<div class="apps-request-composer" data-app-id={appId}>
  <input bind:this={input} type="file" multiple accept="image/*,audio/*,.pdf,.txt,.md,.csv,.tsv,.json,.jsonl,.yml,.yaml,.docx,.xlsx,.eml,.py,.js,.ts,.html,.css,.svelte,.jsx,.tsx,.xml,.sql,.sh,.toml,.ini,.log,.rs,.go,.java,.swift,.kt,.cpp,.h" hidden
    data-testid="apps-request-file-input" onchange={() => addPicked(input)} />
  <input bind:this={cameraInput} type="file" accept="image/*" capture="environment" hidden
    data-testid="apps-request-camera-input" onchange={() => addPicked(cameraInput)} />
  {#if files.length}
    <ul class="attachments" data-testid="apps-request-attachments">
      {#each files as file, index (index)}<li><span>{file.name}</span><button type="button" aria-label={`${$text('apps_workspace.remove_file')} ${file.name}`} disabled={submitting} onclick={() => files = files.filter((_, i) => i !== index)}>×</button></li>{/each}
    </ul>
  {/if}
  <WorkspacePromptComposer surface="projects" {presentation} bind:value
    placeholder={placeholder ?? $text('apps_workspace.request_placeholder')}
    submitLabel={$text(presentation === 'embed' ? 'enter_message.send' : 'apps_workspace.submit_request')} submittingLabel={$text('apps_workspace.interpreting_request')}
    {disabled} {submitting}
    testId="apps-request-composer" inputTestId="apps-request-textarea" submitTestId="apps-request-submit" micTestId="apps-request-mic"
    onSubmit={submit} onMicClick={() => { recording = true; }}
    fileImport={{ label: $text('apps_workspace.add_files'), testId: 'apps-request-add-files', onClick: () => input?.click(), onCamera: () => cameraInput?.click() }}
    {recording} onUntranscribedAudio={keepUntranscribedAudio} onRecordingClose={closeRecording} />
  {#if error}<p role="status">{$text('apps_workspace.audio_attached')}</p>{/if}
</div>
<style>
  .apps-request-composer { width:100%; }
  .attachments { display:flex; flex-wrap:wrap; gap:8px; padding:0 12px; list-style:none; }
  .attachments li { display:flex; align-items:center; gap:8px; padding:4px 10px; border-radius:12px; background:var(--color-grey-20); max-width:100%; }
  .attachments span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .attachments button { border:0; background:transparent; color:var(--color-font-primary); cursor:pointer; }
</style>
