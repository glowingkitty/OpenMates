<!--
  WorkspacePromptComposer.svelte
  Neutral workspace prompt field for non-chat home surfaces.
  Mirrors the empty chat composer affordance without importing chat sync,
  drafts, embeddings, PII, or credit state. Owning surfaces provide submit
  behavior and any future microphone pipeline.
-->

<script lang="ts">
  import { tick } from 'svelte';

  type WorkspaceSurface = 'projects' | 'workflows' | 'tasks' | 'plans';

  type SubmitCallback = (value: string) => void | Promise<void>;
  type MicCallback = () => void | Promise<void>;

  let {
    surface,
    value = $bindable(''),
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
  }: {
    surface: WorkspaceSurface;
    value?: string;
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
  } = $props();

  let textareaElement = $state<HTMLTextAreaElement | null>(null);
  let focused = $state(false);
  const hasText = $derived(value.trim().length > 0);

  async function syncTextareaHeight(): Promise<void> {
    await tick();
    if (!textareaElement) return;
    textareaElement.style.height = 'auto';
    textareaElement.style.height = `${Math.min(textareaElement.scrollHeight, 160)}px`;
  }

  async function submitComposer(): Promise<void> {
    const trimmedValue = value.trim();
    if (!trimmedValue || disabled || submitting) return;
    await onSubmit(trimmedValue);
    await syncTextareaHeight();
  }

  function handleKeydown(event: KeyboardEvent): void {
    if (event.key !== 'Enter' || event.shiftKey) return;
    event.preventDefault();
    void submitComposer();
  }

  $effect(() => {
    void value;
    void syncTextareaHeight();
  });
</script>

<form
  class="workspace-prompt-composer"
  class:focused
  class:has-text={hasText}
  data-testid={testId}
  data-surface={surface}
  onsubmit={(event) => {
    event.preventDefault();
    void submitComposer();
  }}
>
  <span class="workspace-prompt-ai-icon" aria-hidden="true"></span>
  <textarea
    bind:this={textareaElement}
    bind:value
    rows="1"
    data-testid={inputTestId}
    {placeholder}
    {disabled}
    aria-label={placeholder}
    onfocus={() => {
      focused = true;
    }}
    onblur={() => {
      focused = false;
    }}
    oninput={() => void syncTextareaHeight()}
    onkeydown={handleKeydown}
  ></textarea>
  {#if hasText}
    <button
      class="workspace-prompt-submit"
      type="submit"
      data-testid={submitTestId}
      disabled={disabled || submitting}
    >{submitting ? submittingLabel : submitLabel}</button>
  {:else}
    <button
      class="clickable-icon icon_recordaudio workspace-prompt-mic"
      type="button"
      data-testid={micTestId}
      aria-label="Voice input"
      disabled={disabled}
      onclick={() => void onMicClick()}
    ></button>
  {/if}
</form>

<style>
  .workspace-prompt-composer {
    position: relative;
    display: flex;
    width: min(629px, 100%);
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
  }

  .workspace-prompt-composer.has-text,
  .workspace-prompt-composer.focused {
    border-radius: 24px;
    padding-left: 56px;
    padding-right: var(--spacing-5);
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
    min-height: 64px;
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
