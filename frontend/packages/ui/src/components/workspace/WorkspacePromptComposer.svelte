<!--
  WorkspacePromptComposer.svelte
  Neutral workspace prompt field for non-chat home surfaces.
  Mirrors the empty chat composer affordance without importing chat sync,
  drafts, embeddings, PII, or credit state. Owning surfaces provide submit
  behavior and start/stop recording; dictation itself matches the canonical
  composer: live words stream into the field at the caret, the field expands
  above the compact recording controls, dictated text shimmers while the
  correction runs, and Send submits once the corrected text is in place.
  Controls follow the chat composer: an attachment shortcut on the left
  (camera on touch devices when the host takes photos, files otherwise),
  the microphone left of Send on the right, a labeled Send while focused and
  the shared round Send for a blurred draft.
-->

<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { text } from '../../i18n/translations';
  import RecordAudio from '../enter_message/RecordAudio.svelte';
  import CompactSendButton from '../enter_message/CompactSendButton.svelte';
  import { isDesktop } from '../../utils/platform';
  import type { AudioRealtimeTranscriptionHandle } from '../../services/audioRealtimeTranscription';
  import { createTextLiveTranscript, type TextLiveTranscriptController } from '../enter_message/services/textLiveTranscript';

  type WorkspaceSurface = 'projects' | 'workflows' | 'tasks' | 'plans';

  type SubmitCallback = (value: string) => void | boolean | Promise<void | boolean>;
  type MicCallback = () => void | Promise<void>;
  type RecordedAudio = { blob: Blob; mimeType: string; realtime?: AudioRealtimeTranscriptionHandle };
  /** Audio that produced no transcript; hosts may keep it, e.g. as an attachment. */
  type UntranscribedAudio = { blob: Blob; mimeType: string; failed: boolean };

  let {
    surface,
    presentation = 'workspace',
    value = $bindable(''),
    focusActive = $bindable(false),
    placeholder,
    submitLabel,
    submittingLabel,
    disabled,
    submitting,
    testId = `${surface}-input-composer`,
    inputTestId = `${surface}-input-textarea`,
    submitTestId = `${surface}-input-submit`,
    micTestId = `${surface}-input-mic`,
    onSubmit,
    onMicClick,
    fileImport,
    recording = false,
    onUntranscribedAudio,
    onRecordingClose,
    submitDictationOnFinish = false,
  }: {
    surface: WorkspaceSurface;
    presentation?: 'workspace' | 'embed';
    value?: string;
    focusActive?: boolean;
    placeholder: string;
    submitLabel: string;
    submittingLabel: string;
    disabled: boolean;
    submitting: boolean;
    testId?: string;
    inputTestId?: string;
    submitTestId?: string;
    micTestId?: string;
    onSubmit: SubmitCallback;
    onMicClick: MicCallback;
    /** Attachment shortcut; `onCamera` makes it take a photo on touch devices while blurred, like the chat composer. */
    fileImport?: { label: string; testId: string; onClick: () => void; onCamera?: () => void };
    recording?: boolean;
    onUntranscribedAudio?: (audio: UntranscribedAudio) => void;
    onRecordingClose?: () => void;
    /** Finish submits a cleanly transcribed recording (Send always does). */
    submitDictationOnFinish?: boolean;
  } = $props();

  let textareaElement = $state<HTMLTextAreaElement | null>(null);
  let recordAudioComponent = $state<RecordAudio>();
  // One dictation per recording. The recorder can close before its correction
  // arrives, so a dictation stays valid until it is cancelled or a newer
  // recording supersedes it; only then are its late callbacks ignored.
  type Dictation = { live: TextLiveTranscriptController; sendRequested: boolean; superseded: boolean };
  let dictation = $state.raw<Dictation | null>(null);
  let latestDictation: Dictation | null = null;
  let recordingHasText = $state(false);
  let dictationProcessing = $state(false);
  let focused = $derived(focusActive);
  let expanded = $state(false);
  const hasText = $derived(value.trim().length > 0);
  // Resolved after mount so server rendering never guesses the device.
  let touchDevice = $state(false);
  onMount(() => { touchDevice = !isDesktop(); });
  const quickCamera = $derived(!!fileImport?.onCamera && touchDevice && !focused);
  const collapsible = $derived(surface === 'workflows' || surface === 'tasks' || presentation === 'embed');
  const collapsed = $derived(collapsible && !focused && !recording);
  // The visible preview never replaces the bound draft or its line breaks.
  const firstLine = $derived(value.split(/\r?\n/)[0] + (/[\r\n]/.test(value) ? '…' : ''));

  async function syncTextareaHeight(): Promise<void> {
    await tick();
    if (!textareaElement) return;
    if (!collapsible) textareaElement.style.height = 'auto';
    const style = getComputedStyle(textareaElement);
    const lineHeight = Number.parseFloat(style.lineHeight) || 22;
    const maximum = collapsible ? (expanded && !recording ? Number.parseFloat(style.maxHeight) : lineHeight * 4) : 160;
    const recordingLines = recording && recordingHasText ? lineHeight * 4 : lineHeight;
    const height = collapsed ? lineHeight : recording ? recordingLines : expanded ? maximum : collapsible && focused ? lineHeight * 4 : Math.min(textareaElement.scrollHeight, maximum);
    textareaElement.style.height = `${height}px`;
    if (collapsed) textareaElement.scrollTop = 0;
    else if (recording) textareaElement.scrollTop = textareaElement.scrollHeight;
  }

  function startDictation(): TextLiveTranscriptController | null {
    const field = textareaElement;
    if (!field) return null;
    // An unfocused field's DOM selection is unreliable (it can reset to 0 once the
    // recorder takes focus), so dictation continues at the caret it last wrote.
    let caret = { start: field.value.length, end: field.value.length };
    if (document.activeElement === field) caret = { start: field.selectionStart, end: field.selectionEnd };
    else field.setSelectionRange(caret.start, caret.end);
    return createTextLiveTranscript({
      read: () => {
        if (document.activeElement === field) caret = { start: field.selectionStart, end: field.selectionEnd };
        const end = Math.min(caret.end, field.value.length);
        return { value: field.value, selectionStart: Math.min(caret.start, end), selectionEnd: end };
      },
      write: (next, at) => {
        field.value = next;
        value = next;
        caret = { start: at, end: at };
        field.setSelectionRange(at, at);
      },
    });
  }

  function handleLiveTranscript(event: CustomEvent<{ transcript: string }>): void {
    if (!dictation?.live.apply(event.detail.transcript)) return;
    recordingHasText = dictation.live.hasText();
  }

  function handleRecordingCancelled(): void {
    if (dictation) {
      dictation.superseded = true;
      dictation.live.discard();
    }
    dictation = null;
    dictationProcessing = false;
    onRecordingClose?.();
  }

  // contract-test: direct surface=gui.web assertions=message-input.audio.workspace-dictation
  async function handleAudioRecorded(event: CustomEvent<RecordedAudio>): Promise<void> {
    const current = dictation;
    const overlay = recordAudioComponent;
    const { blob, mimeType, realtime } = event.detail;
    if (!current) { realtime?.cancel(); return; }
    let failed = false;
    let clean = false;
    if (realtime) {
      dictationProcessing = true;
      try {
        const { transcript, useCorrected, correctionSkipped } = await realtime.correction;
        if (current.superseded) return;
        clean = useCorrected || !!correctionSkipped;
        // One untouched dictation segment becomes the corrected text; text
        // edited while speaking stays as arranged.
        current.live.applyCorrection(transcript);
      } catch (error) {
        if (current.superseded) return;
        console.error('[WorkspacePromptComposer] Transcript correction failed:', error);
        failed = true;
      } finally {
        if (!current.superseded) dictationProcessing = false;
      }
    }
    if (current.superseded) return;
    const transcribed = current.live.hasText();
    if (!transcribed) onUntranscribedAudio?.({ blob, mimeType, failed: failed || !realtime });
    if (!realtime || !transcribed) {
      // Without corrected text there is nothing for the retained overlay to wait for.
      await overlay?.completeSend();
      return;
    }
    const submit = current.sendRequested || (submitDictationOnFinish && clean);
    if (submit && value.trim()) {
      try { await submitComposer(); } finally { await overlay?.completeSend(); }
      return;
    }
    if (current.sendRequested) await overlay?.completeSend();
  }

  $effect(() => {
    if (!recording) {
      // A pending correction of the closed recording still finishes; it
      // clears the processing state itself.
      dictation = null;
      recordingHasText = false;
      return;
    }
    if (dictation || !textareaElement) return;
    const live = startDictation();
    if (!live) return;
    if (latestDictation) latestDictation.superseded = true;
    dictationProcessing = false;
    latestDictation = dictation = { live, sendRequested: false, superseded: false };
  });

  function handleFocusIn(event: FocusEvent): void {
    if (event.target === textareaElement) {
      focusActive = true;
    }
  }

  function handleFocusOut(event: FocusEvent): void {
    if (event.relatedTarget instanceof HTMLElement && event.relatedTarget.matches('.workspace-prompt-cancel')) return;
    if (event.relatedTarget instanceof HTMLElement && event.relatedTarget.closest('.workspace-prompt-composer') === event.currentTarget) return;
    focusActive = false;
    expanded = false;
  }

  async function toggleExpanded(): Promise<void> {
    expanded = !expanded;
    await tick();
    textareaElement?.focus();
  }

  async function submitComposer(): Promise<void> {
    const trimmedValue = value.trim();
    if (!trimmedValue || disabled || submitting) return;
    try {
      const accepted = await onSubmit(trimmedValue);
      if (accepted === false) { textareaElement?.focus(); return; }
    } catch (error) {
      console.error('[WorkspacePromptComposer] Submit failed:', error);
      textareaElement?.focus();
      return;
    }
    focusActive = false;
    expanded = false;
    textareaElement?.blur();
    await syncTextareaHeight();
  }

  function handleKeydown(event: KeyboardEvent): void {
    // The recorder owns Enter (finish) and Escape (cancel) while dictating.
    if (event.isComposing || recording) return;
    if (event.key === 'Escape' && collapsible) {
      event.preventDefault();
      focusActive = false;
      textareaElement?.blur();
      return;
    }
    if (event.key !== 'Enter' || event.shiftKey) return;
    event.preventDefault();
    void submitComposer();
  }

  $effect(() => {
    void value;
    void focused;
    void expanded;
    void recording;
    void syncTextareaHeight();
  });

  $effect(() => {
    if (!focusActive && textareaElement === document.activeElement) textareaElement?.blur();
  });

  $effect(() => {
    if (focusActive && !recording && !disabled && textareaElement && !textareaElement.closest('form')?.contains(document.activeElement)) {
      textareaElement.focus();
    }
  });
</script>

<svelte:window onresize={() => void syncTextareaHeight()} />

<div class="workspace-prompt-shell" class:focused={collapsible && focused}>
<form
  class="workspace-prompt-composer"
  class:canonical-composer={presentation === 'embed'}
  class:embed-presentation={presentation === 'embed'}
  class:focused
  class:has-text={hasText}
  class:hasFileImport={!!fileImport}
  class:recording
  class:recording-with-text={recording && recordingHasText}
  class:collapsible
  class:collapsed
  class:expanded
  data-testid={testId}
  data-surface={surface}
  onpointerdown={(event) => {
    if (presentation === 'embed' && event.target instanceof Element && !event.target.closest('button, textarea, input')) {
      event.preventDefault();
      textareaElement?.focus();
    }
  }}
  onfocusin={handleFocusIn}
  onfocusout={handleFocusOut}
  onsubmit={(event) => {
    event.preventDefault();
    void submitComposer();
  }}
>
  {#if fileImport}
    {@const label = quickCamera ? $text('enter_message.attachments.take_photo') : fileImport.label}
    <button
      class="workspace-prompt-file"
      type="button"
      data-testid={fileImport.testId}
      data-attachment-kind={quickCamera ? 'camera' : 'files'}
      aria-label={label}
      title={label}
      disabled={disabled || submitting}
      onmousedown={(event) => { if (collapsible) event.preventDefault(); }}
      onclick={() => (quickCamera && fileImport.onCamera ? fileImport.onCamera() : fileImport.onClick())}
    ><span class="clickable-icon" class:icon_camera={quickCamera} class:icon_files={!quickCamera} aria-hidden="true"></span></button>
  {/if}
  <div class="workspace-prompt-text">
    {#if collapsed && hasText}
      <span class="workspace-prompt-preview" aria-hidden="true" data-testid={`${inputTestId}-preview`}>{firstLine}</span>
    {/if}
    <textarea
    wrap={surface === 'workflows' && !fileImport && !hasText ? 'off' : 'soft'}
    bind:this={textareaElement}
    bind:value
    rows="1"
    data-testid={inputTestId}
    {placeholder}
    {disabled}
    readOnly={submitting}
    aria-label={placeholder}
    class:dictation-processing={dictationProcessing}
    data-dictation-processing={dictationProcessing ? 'true' : 'false'}
    oninput={() => { if (textareaElement) dictation?.live.observe(textareaElement.value); void syncTextareaHeight(); }}
    onkeydown={handleKeydown}
  ></textarea>
  </div>
  {#if collapsible && focused && !recording}
    <button
      type="button"
      class="workspace-prompt-expand"
      data-testid={`${inputTestId}-expand`}
      aria-label={$text(expanded ? 'enter_message.fullscreen.exit_fullscreen' : 'enter_message.fullscreen.enter_fullscreen')}
      title={$text(expanded ? 'enter_message.fullscreen.exit_fullscreen' : 'enter_message.fullscreen.enter_fullscreen')}
      aria-expanded={expanded}
      disabled={disabled || submitting}
      onmousedown={(event) => event.preventDefault()}
      onclick={() => void toggleExpanded()}
    ><span class="clickable-icon" class:icon_minimize={expanded} class:icon_fullscreen={!expanded} aria-hidden="true"></span></button>
  {/if}
  <div class="workspace-prompt-actions" data-testid={`${inputTestId}-actions`}>
    <button
      class="clickable-icon icon_recordaudio workspace-prompt-mic"
      type="button"
      data-testid={micTestId}
      aria-label="Voice input"
      disabled={disabled || submitting}
      onmousedown={(event) => { if (collapsible) event.preventDefault(); }}
      onclick={() => void onMicClick()}
    ></button>
    {#if hasText && focused}
      <button
        class="workspace-prompt-submit"
        type="submit"
        data-testid={submitTestId}
        disabled={disabled || submitting}
        onmousedown={(event) => { if (collapsible) event.preventDefault(); }}
      >{submitting ? submittingLabel : submitLabel}</button>
    {:else if hasText}
      <CompactSendButton testId={submitTestId} disabled={disabled || submitting} busy={submitting} onclick={() => void submitComposer()} />
    {/if}
  </div>
  {#if recording}
    <div class="workspace-recording-controls" data-testid={`${inputTestId}-recording-controls`}>
      <RecordAudio bind:this={recordAudioComponent} initialPosition={{ x: 0, y: 0 }} enableRealtime={true}
        compact={true}
        transcriptInEditor={true}
        retainUntilCorrection={true}
        retainUntilSend={true}
        allowSend={true}
        correctionContext={surface === 'workflows' ? 'workflow' : undefined}
        on:livetranscript={handleLiveTranscript}
        on:sendrequested={() => { if (dictation) dictation.sendRequested = true; }}
        on:audiorecorded={(event) => void handleAudioRecorded(event)}
        on:close={() => onRecordingClose?.()}
        on:cancel={handleRecordingCancelled} />
    </div>
  {/if}
</form>
{#if collapsible}
  <button class="workspace-prompt-cancel" class:visible={focused && !recording} type="button" data-testid={`${inputTestId}-cancel`}
    tabindex={focused && !recording ? 0 : -1} aria-hidden={!(focused && !recording)}
    onpointerdown={(event) => event.preventDefault()}
    onfocusout={(event) => { if (!(event.relatedTarget instanceof HTMLElement && event.relatedTarget.closest('.workspace-prompt-composer'))) focusActive = false; }}
    onclick={(event) => { focusActive = false; expanded = false; textareaElement?.blur(); event.currentTarget.blur(); }}>{$text('common.cancel')}</button>
{/if}
</div>

<style>
  @import '../enter_message/composerPresentation.css';
  .workspace-prompt-shell {
    width: min(629px, 100%);
    margin: 0 auto;
  }

  .workspace-prompt-composer {
    position: relative;
    display: flex;
    width: 100%;
    min-height: 64px;
    align-items: center;
    gap: var(--spacing-4);
    margin: 0 auto;
    padding: 0 64px;
    border: 0;
    border-radius: var(--radius-full, 9999px);
    background: var(--color-grey-blue);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
    box-sizing: border-box;
    transition: min-height .18s ease, border-radius .18s ease, padding .18s ease;
  }

  .workspace-prompt-composer.has-text,
  .workspace-prompt-composer.focused {
    border-radius: 24px;
    padding-left: 56px;
    padding-right: var(--spacing-5);
  }

  /* Dictation: empty capture keeps the compact height; once words arrive the
     field expands above the compact recording controls, like the chat composer. */
  form.workspace-prompt-composer.recording {
    --recording-controls-height: var(--composer-compact-height, 60px);
    min-height: var(--recording-controls-height);
    padding: 0;
    border-radius: 24px;
    overflow: hidden;
  }

  form.workspace-prompt-composer.recording.recording-with-text {
    display: block;
    min-height: var(--composer-focused-height, 180px);
    padding: var(--spacing-8) var(--spacing-8) calc(var(--recording-controls-height) + var(--spacing-4));
  }

  .workspace-prompt-composer.recording:not(.recording-with-text) .workspace-prompt-text,
  .workspace-prompt-composer.recording .workspace-prompt-file,
  .workspace-prompt-composer.recording .workspace-prompt-actions {
    display: none;
  }

  .workspace-prompt-composer.recording textarea { text-align: left; }

  .workspace-recording-controls {
    position: absolute;
    inset: auto 0 0;
    height: var(--recording-controls-height);
  }

  /* Same sweep as the chat composer's dictated text while correction runs. */
  textarea.dictation-processing {
    background: linear-gradient(90deg,
      var(--color-font-primary) 0%,
      var(--color-font-primary) 35%,
      #667eea 45%,
      #a78bfa 50%,
      #764ba2 55%,
      var(--color-font-primary) 65%,
      var(--color-font-primary) 100%);
    background-size: 200% 100%;
    background-clip: text;
    -webkit-background-clip: text;
    color: transparent;
    animation: processing-text-shimmer 1.5s infinite linear;
  }

  .workspace-prompt-composer.collapsible.focused:not(.recording) {
    display: block;
    padding: 42px 16px 68px;
  }

  .workspace-prompt-text {
    position: relative;
    flex: 1;
    min-width: 0;
  }

  .workspace-prompt-composer.collapsible.focused .workspace-prompt-text {
    padding-right: 28px;
  }

  /* Right action group, like the chat composer: the microphone sits left of
     Send. Empty and resting it holds only the centered-row microphone; a
     draft adds Send in the row; focus moves the group to the bottom row. */
  .workspace-prompt-actions {
    display: flex;
    flex-shrink: 0;
    align-items: center;
    gap: var(--spacing-5);
  }

  .workspace-prompt-composer:not(.has-text):not(.focused) .workspace-prompt-actions {
    position: absolute;
    top: 50%;
    right: 24px;
    transform: translateY(-50%);
  }

  .workspace-prompt-composer.collapsible.focused .workspace-prompt-actions {
    position: absolute;
    right: 16px;
    bottom: 16px;
  }

  .workspace-prompt-composer.collapsible.focused .workspace-prompt-file {
    top: auto;
    bottom: 16px;
    transform: none;
  }

  .workspace-prompt-cancel {
    display: block;
    width: 100%;
    box-sizing: border-box;
    height: auto;
    min-height: 0;
    max-height: 0;
    margin: 0;
    border: 0 solid var(--color-grey-30);
    border-radius: var(--radius-full);
    padding: 0 var(--spacing-8);
    overflow: hidden;
    background: var(--color-grey-10);
    color: var(--color-font-secondary);
    font-family: inherit;
    font-size: var(--font-size-small);
    font-weight: 500;
    white-space: nowrap;
    text-align: center;
    box-shadow: none;
    filter: none;
    cursor: pointer;
    opacity: 0;
    visibility: hidden;
    pointer-events: none;
    transition: max-height .18s ease, margin-top .18s ease, padding .18s ease, opacity .18s ease;
  }

  .workspace-prompt-cancel.visible {
    max-height: 44px;
    margin-top: var(--spacing-3);
    padding: var(--spacing-3) var(--spacing-8);
    border-width: 1px;
    opacity: 1;
    visibility: visible;
    pointer-events: auto;
  }

  .workspace-prompt-cancel:hover {
    background: var(--color-grey-20);
    color: var(--color-font-primary);
    transform: none;
    scale: none;
  }
  .workspace-prompt-cancel:active {
    background: var(--color-grey-30);
    color: var(--color-font-primary);
    transform: none;
    scale: none;
    filter: none;
  }

  .workspace-prompt-composer.collapsible.focused .workspace-prompt-file:hover {
    transform: scale(1.05);
  }

  .workspace-prompt-composer.collapsible textarea {
    display: block;
    max-height: calc(4 * 1.35em);
    overflow-y: auto;
    caret-color: var(--color-font-primary);
    transition: height .18s ease;
  }

  @media (prefers-reduced-motion: reduce) {
    .workspace-prompt-composer,
    .workspace-prompt-composer.collapsible textarea,
    .workspace-prompt-cancel { transition: none; }
    textarea.dictation-processing { animation: none; background: none; color: var(--color-font-secondary, var(--color-font-primary)); }
  }

  .workspace-prompt-composer.collapsed textarea {
    overflow: hidden;
  }

  .workspace-prompt-composer.collapsed.has-text textarea {
    opacity: 0;
  }

  .workspace-prompt-composer.expanded:not(.recording) textarea {
    max-height: 65dvh;
  }

  .workspace-prompt-composer.collapsible.focused .workspace-prompt-text {
    max-height: 65dvh;
  }

  .workspace-prompt-preview {
    position: absolute;
    inset: 0;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    font-size: var(--font-size-p);
    font-weight: 600;
    line-height: 1.35;
    color: var(--color-font-primary);
    pointer-events: none;
  }

  .workspace-prompt-expand {
    position: absolute;
    top: 10px;
    right: 15px;
    display: grid;
    place-items: center;
    width: 28px;
    height: 28px;
    min-width: 0;
    margin: 0;
    padding: 0;
    border: 0;
    border-radius: var(--radius-full);
    background: transparent;
    box-shadow: none;
    filter: none;
  }

  .workspace-prompt-expand span {
    width: 18px;
    height: 18px;
    background: var(--color-primary);
  }

  .workspace-prompt-expand:focus-visible {
    outline: 2px solid var(--color-primary);
    outline-offset: 2px;
  }

  @media (max-width: 400px) {
    .workspace-prompt-composer[data-surface='workflows']:not(.hasFileImport):not(.has-text) {
      padding-inline: 36px;
    }

    .workspace-prompt-composer[data-surface='workflows']:not(.hasFileImport):not(.has-text):not(.focused) .workspace-prompt-actions {
      right: 8px;
    }

    .workspace-prompt-composer[data-surface='workflows']:not(.hasFileImport):not(.has-text) textarea::placeholder {
      font-size: var(--font-size-small);
      font-weight: 600;
      letter-spacing: -.03em;
    }
  }


  textarea {
    width: 100%;
    box-sizing: border-box;
    min-height: 1.5rem;
    max-height: 160px;
    resize: none;
    flex: 1;
    min-width: 0;
    border: 0;
    outline: none;
    padding: 0;
    border-radius: 0;
    color: var(--color-font-primary);
    background: transparent;
    font: inherit;
    font-size: var(--font-size-p);
    font-weight: 600;
    line-height: 1.35;
    text-align: center;
  }

  .workspace-prompt-composer.has-text textarea,
  .workspace-prompt-composer.focused textarea {
    text-align: left;
  }

  textarea::placeholder {
    color: var(--color-grey-60);
    font-weight: 700;
    text-align: center;
  }

  .workspace-prompt-submit {
    min-height: 40px;
    flex-shrink: 0;
    padding: var(--spacing-4) var(--spacing-8);
    border: 0;
    border-radius: var(--radius-8);
    color: var(--color-font-button);
    background: var(--color-button-primary);
    font: inherit;
    font-weight: 800;
    cursor: pointer;
  }

  .workspace-prompt-file {
    position: absolute;
    top: 50%;
    left: 12px;
    display: grid;
    place-items: center;
    width: 40px;
    height: 40px;
    min-width: 0;
    margin: 0;
    padding: 0;
    border: 0;
    border-radius: var(--radius-full);
    background: transparent;
    box-shadow: none;
    filter: none;
    transform: translateY(-50%);
    cursor: pointer;
    /* Focus moves controls into the bottom row; don't animate their old offset through the text. */
    transition: background-color .15s ease-in-out, scale .15s ease-in-out;
  }

  .workspace-prompt-file span {
    width: 25px;
    height: 25px;
    background: var(--color-primary);
  }

  .workspace-prompt-file:hover {
    transform: translateY(-50%) scale(1.05);
  }

  .workspace-prompt-file:focus-visible {
    outline: 2px solid var(--color-button-primary);
    outline-offset: 2px;
  }

  .workspace-prompt-file:disabled,
  .workspace-prompt-submit:disabled,
  .workspace-prompt-mic:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  .workspace-prompt-mic {
    position: relative;
    flex-shrink: 0;
    margin: 0;
    background: var(--color-primary);
    touch-action: none;
    transition: background-color .15s ease-in-out, scale .15s ease-in-out;
  }

  .workspace-prompt-mic:hover {
    transform: scale(1.05);
  }

  @media (max-width: 730px) {
    .workspace-prompt-composer {
      min-height: 64px;
      padding-left: 58px;
      padding-right: 58px;
    }

    .workspace-prompt-composer.has-text,
    .workspace-prompt-composer.focused {
      padding-left: 52px;
      padding-right: var(--spacing-4);
    }

    .workspace-prompt-submit {
      padding-inline: var(--spacing-6);
      font-size: var(--font-size-small);
    }
  }
  .workspace-prompt-composer.embed-presentation {
    min-height: var(--composer-compact-height);
    border-radius: var(--composer-radius);
    background: var(--composer-background);
    box-shadow: var(--composer-shadow);
    cursor: text;
  }
  .workspace-prompt-composer.embed-presentation.focused:not(.recording) {
    min-height: var(--composer-focused-height);
  }
  .embed-presentation textarea,
  .embed-presentation .workspace-prompt-preview {
    font-size: var(--composer-font-size);
    line-height: var(--composer-line-height);
  }
  .workspace-prompt-composer.embed-presentation.collapsible textarea {
    max-height: calc(4 * 1.6em);
  }
  .workspace-prompt-composer.embed-presentation.expanded textarea {
    max-height: min(40dvh, 20rem);
  }
</style>
