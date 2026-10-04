<!--
  WorkspacePromptComposer.svelte
  Neutral workspace prompt field for non-chat home surfaces.
  Mirrors the empty chat composer affordance without importing chat sync,
  drafts, embeddings, PII, or credit state. Owning surfaces provide submit
  behavior and any future microphone pipeline.
-->

<script lang="ts">
  import { tick } from 'svelte';
  import { text } from '../../i18n/translations';
  import RecordAudio from '../enter_message/RecordAudio.svelte';
  import type { AudioRealtimeTranscriptionHandle } from '../../services/audioRealtimeTranscription';
  import type { AudioWaveformData } from '../../utils/audioWaveform';

  type WorkspaceSurface = 'projects' | 'workflows' | 'tasks' | 'plans';

  type SubmitCallback = (value: string) => void | boolean | Promise<void | boolean>;
  type MicCallback = () => void | Promise<void>;
  type RecordedAudio = { blob: Blob; duration: number; mimeType: string; waveform?: AudioWaveformData; realtime?: AudioRealtimeTranscriptionHandle; liveTranscript?: string };

  let {
    surface,
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
    onAudioRecorded,
    onRecordingClose,
  }: {
    surface: WorkspaceSurface;
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
    fileImport?: { label: string; testId: string; onClick: () => void };
    recording?: boolean;
    onAudioRecorded?: (event: CustomEvent<RecordedAudio>) => void | Promise<void>;
    onRecordingClose?: () => void;
  } = $props();

  let textareaElement = $state<HTMLTextAreaElement | null>(null);
  let focused = $derived(focusActive);
  let expanded = $state(false);
  const hasText = $derived(value.trim().length > 0);
  const collapsible = $derived(surface === 'workflows' || surface === 'tasks');
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
    const height = collapsed || recording ? lineHeight : expanded ? maximum : collapsible && focused ? lineHeight * 4 : Math.min(textareaElement.scrollHeight, maximum);
    textareaElement.style.height = `${height}px`;
    if (collapsed) textareaElement.scrollTop = 0;
  }

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
    if (event.isComposing) return;
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
  class:focused
  class:has-text={hasText}
  class:hasFileImport={!!fileImport}
  class:recording
  class:collapsible
  class:collapsed
  class:expanded
  data-testid={testId}
  data-surface={surface}
  onfocusin={handleFocusIn}
  onfocusout={handleFocusOut}
  onsubmit={(event) => {
    event.preventDefault();
    void submitComposer();
  }}
>
  {#if fileImport}
    <button
      class="workspace-prompt-file"
      type="button"
      data-testid={fileImport.testId}
      aria-label={fileImport.label}
      title={fileImport.label}
      disabled={disabled || submitting}
      onmousedown={(event) => { if (collapsible) event.preventDefault(); }}
      onclick={fileImport.onClick}
    ><span class="clickable-icon icon_files" aria-hidden="true"></span></button>
  {:else}
    <span class="workspace-prompt-ai-icon" aria-hidden="true"></span>
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
    oninput={() => void syncTextareaHeight()}
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
  {#if hasText}
    <button
      class="workspace-prompt-submit"
      type="submit"
      data-testid={submitTestId}
      disabled={disabled || submitting}
      onmousedown={(event) => { if (collapsible) event.preventDefault(); }}
    >{submitting ? submittingLabel : submitLabel}</button>
  {/if}
  <button
      class="clickable-icon icon_recordaudio workspace-prompt-mic"
      type="button"
      data-testid={micTestId}
      aria-label="Voice input"
      disabled={disabled || submitting}
      onmousedown={(event) => { if (collapsible) event.preventDefault(); }}
      onclick={() => void onMicClick()}
    ></button>
  {#if recording}
    <RecordAudio initialPosition={{ x: 0, y: 0 }} enableRealtime={true}
      correctionContext={surface === 'workflows' ? 'workflow' : undefined}
      on:audiorecorded={(event) => void onAudioRecorded?.(event)}
      on:close={() => onRecordingClose?.()}
      on:cancel={() => onRecordingClose?.()} />
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

  .workspace-prompt-composer.recording {
    min-height: 220px;
    border-radius: 24px;
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

  .workspace-prompt-composer.collapsible.focused .workspace-prompt-submit {
    position: absolute;
    right: 58px;
    bottom: 16px;
    margin: 0;
  }

  .workspace-prompt-composer.collapsible.focused .workspace-prompt-ai-icon,
  .workspace-prompt-composer.collapsible.focused .workspace-prompt-file,
  .workspace-prompt-composer.collapsible.focused .workspace-prompt-mic {
    top: auto;
    transform: none;
  }

  .workspace-prompt-composer.collapsible.focused .workspace-prompt-ai-icon {
    bottom: 24px;
  }

  .workspace-prompt-composer.collapsible.focused .workspace-prompt-file,
  .workspace-prompt-composer.collapsible.focused .workspace-prompt-mic {
    bottom: 16px;
  }

  .workspace-prompt-composer.collapsible.focused .workspace-prompt-mic { right: 18px; }

  .workspace-prompt-cancel {
    display: block;
    width: max-content;
    max-height: 0;
    margin: 0 0 0 48px;
    border: 0;
    padding: 0 8px;
    overflow: hidden;
    background: transparent;
    color: var(--color-font-secondary);
    font: inherit;
    cursor: pointer;
    opacity: 0;
    pointer-events: none;
    transition: max-height .18s ease, margin-top .18s ease, padding .18s ease, opacity .18s ease;
  }

  .workspace-prompt-cancel.visible {
    max-height: 44px;
    margin-top: 8px;
    padding: 8px;
    opacity: 1;
    pointer-events: auto;
  }

  .workspace-prompt-cancel:hover { color: var(--color-font-primary); }

  .workspace-prompt-composer.collapsible.focused .workspace-prompt-file:hover,
  .workspace-prompt-composer.collapsible.focused .workspace-prompt-mic:hover {
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

    .workspace-prompt-composer[data-surface='workflows']:not(.hasFileImport):not(.has-text) .workspace-prompt-ai-icon {
      left: 8px;
    }

    .workspace-prompt-composer[data-surface='workflows']:not(.hasFileImport):not(.has-text) .workspace-prompt-mic {
      right: 8px;
    }

    .workspace-prompt-composer[data-surface='workflows']:not(.hasFileImport):not(.has-text) textarea::placeholder {
      font-size: var(--font-size-small);
      font-weight: 600;
      letter-spacing: -.03em;
    }
  }

  .workspace-prompt-ai-icon {
    position: absolute;
    top: 50%;
    left: 22px;
    width: 24px;
    height: 24px;
    background: color-mix(in srgb, var(--color-font-primary) 72%, transparent);
    transform: translateY(-50%);
    -webkit-mask-image: url('@openmates/ui/static/icons/ai.svg');
    mask-image: url('@openmates/ui/static/icons/ai.svg');
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-size: contain;
    mask-size: contain;
    pointer-events: none;
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

  .workspace-prompt-composer.collapsible.has-text:not(.focused) .workspace-prompt-submit {
    margin-right: 38px;
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
    position: absolute;
    top: 50%;
    right: 24px;
    background: var(--color-primary);
    transform: translateY(-50%);
    touch-action: none;
    transition: background-color .15s ease-in-out, scale .15s ease-in-out;
  }

  .workspace-prompt-mic:hover {
    transform: translateY(-50%) scale(1.05);
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
</style>
