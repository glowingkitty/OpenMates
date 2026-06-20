<!--
  frontend/packages/ui/src/components/interactive_questions/renderers/ChoiceQuestion.svelte

  Choice-type interactive question component (single or multi-select).
  Renders choices stacked vertically with checkbox/radio indicators.
  Uses Svelte 5 Runes for properties and reactivity.

  Architecture: Svelte 5 Socratic assessment UI
-->

<script lang="ts">
  import type { ChoiceQuestionData, ChoiceResponse } from '../types';

  let {
    data,
    value = $bindable(null),
    isValid = $bindable(false),
    disabled = false,
    answeredValue = null
  } = $props<{
    data: ChoiceQuestionData;
    value: ChoiceResponse | null;
    isValid: boolean;
    disabled?: boolean;
    answeredValue?: ChoiceResponse | null;
  }>();

  // Internal state tracking selected option IDs
  let selectedIds = $state<string[]>([]);
  let customAnswer = $state('');

  const LEGACY_CUSTOM_OPTION_PATTERNS = [
    'i give you my own answer',
    'my own answer',
    'own answer',
    'custom answer',
    'something else',
    'other'
  ];

  function isCustomOption(option: { id: string; text: string }): boolean {
    if (data.custom_option_id) return option.id === data.custom_option_id;
    const normalizedText = option.text.trim().toLowerCase();
    return LEGACY_CUSTOM_OPTION_PATTERNS.some((pattern) => normalizedText === pattern || normalizedText.includes(pattern));
  }

  function hasCustomSelection(nextSelectedIds = selectedIds): boolean {
    return data.options.some((option) => nextSelectedIds.includes(option.id) && isCustomOption(option));
  }

  function updateSelection(nextSelectedIds = selectedIds, nextCustomAnswer = customAnswer) {
    selectedIds = nextSelectedIds;
    customAnswer = nextCustomAnswer;

    const needsCustomAnswer = hasCustomSelection(nextSelectedIds);
    isValid = nextSelectedIds.length > 0 && (!needsCustomAnswer || nextCustomAnswer.trim().length > 0);
    if (!isValid) {
      value = null;
      return;
    }

    const response: ChoiceResponse = { id: data.id, selection: nextSelectedIds };
    if (needsCustomAnswer) {
      response.custom_answer = nextCustomAnswer.trim();
    }
    value = response;
  }

  // Initialize selected IDs if already answered (locked)
  $effect(() => {
    if (disabled && answeredValue) {
      selectedIds = answeredValue.selection;
      customAnswer = answeredValue.custom_answer || '';
    }
  });

  // Reset selection if parent clears the value
  $effect(() => {
    if (value === null && !disabled) {
      selectedIds = [];
      customAnswer = '';
    }
  });

  // Handle choice selection
  function handleSelect(optionId: string) {
    if (disabled) return;

    let nextSelectedIds: string[];
    let nextCustomAnswer = customAnswer;

    if (data.multiple) {
      if (selectedIds.includes(optionId)) {
        nextSelectedIds = selectedIds.filter(id => id !== optionId);
      } else {
        nextSelectedIds = [...selectedIds, optionId];
      }
    } else {
      nextSelectedIds = [optionId];
    }

    if (!hasCustomSelection(nextSelectedIds)) {
      nextCustomAnswer = '';
    }

    updateSelection(nextSelectedIds, nextCustomAnswer);
  }

  function handleCustomInput(val: string) {
    if (disabled) return;
    updateSelection(selectedIds, val);
  }

  // Handle keyboard interaction for accessibility
  function handleKeyDown(event: KeyboardEvent, optionId: string) {
    if (disabled) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      handleSelect(optionId);
    }
  }
</script>

<div class="choice-question" class:disabled>
  <div class="options-list">
    {#each data.options as option (option.id)}
      {@const isSelected = selectedIds.includes(option.id)}
      <div
        class="option-item"
        class:selected={isSelected}
        class:interactive={!disabled}
        data-testid={`interactive-question-option-${option.id}`}
        role="button"
        tabindex="0"
        onclick={() => handleSelect(option.id)}
        onkeydown={(e) => handleKeyDown(e, option.id)}
      >
        <div class="indicator-wrapper">
          {#if data.multiple}
            <div class="checkbox" class:checked={isSelected}>
              {#if isSelected}
                <svg viewBox="0 0 24 24" class="check-icon">
                  <path fill="currentColor" d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                </svg>
              {/if}
            </div>
          {:else}
            <div class="radio" class:checked={isSelected}>
              {#if isSelected}
                <div class="radio-inner"></div>
              {/if}
            </div>
          {/if}
        </div>
        <div class="option-text">{option.text}</div>
      </div>
      {#if isSelected && isCustomOption(option)}
        <input
          type="text"
          class="custom-answer-input"
          data-testid="interactive-question-custom-answer"
          value={customAnswer}
          placeholder={data.custom_placeholder || 'Type your own answer'}
          {disabled}
          oninput={(e) => handleCustomInput((e.target as HTMLInputElement).value)}
        />
      {/if}
    {/each}
  </div>
</div>

<style>
  .options-list {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-8, 8px);
    width: 100%;
  }

  .option-item {
    display: flex;
    align-items: flex-start;
    gap: var(--spacing-12, 12px);
    padding: var(--spacing-8, 8px) var(--spacing-12, 12px);
    background: var(--color-grey-10, #f8f9fa);
    border: 1px solid var(--color-grey-20, #e9ecef);
    border-radius: var(--radius-8, 8px);
    transition: all 0.2s ease;
  }

  .option-item.interactive {
    cursor: pointer;
  }

  .option-item.interactive:hover {
    background: var(--color-grey-15, #f1f3f5);
    border-color: var(--color-grey-30, #dee2e6);
  }

  .option-item.selected {
    background: var(--color-grey-5, #ffffff);
    border-color: var(--color-primary, #4dabf7);
    box-shadow: 0 0 0 1px var(--color-primary, #4dabf7);
  }

  .indicator-wrapper {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 20px;
    margin-top: 2px;
  }

  .checkbox {
    width: 18px;
    height: 18px;
    border: 2px solid var(--color-grey-40, #ced4da);
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    transition: all 0.15s ease;
  }

  .checkbox.checked {
    background: var(--color-primary, #4dabf7);
    border-color: var(--color-primary, #4dabf7);
  }

  .check-icon {
    width: 14px;
    height: 14px;
  }

  .radio {
    width: 18px;
    height: 18px;
    border: 2px solid var(--color-grey-40, #ced4da);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s ease;
  }

  .radio.checked {
    border-color: var(--color-primary, #4dabf7);
  }

  .radio-inner {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--color-primary, #4dabf7);
  }

  .option-text {
    font-size: var(--font-size-p, 15px);
    line-height: 1.4;
    color: var(--color-font-primary, #212529);
  }

  .custom-answer-input {
    width: 100%;
    padding: var(--spacing-10, 10px) var(--spacing-12, 12px);
    font-size: var(--font-size-p, 15px);
    background: var(--color-grey-0, #ffffff);
    border: 1px solid var(--color-grey-30, #ced4da);
    border-radius: var(--radius-8, 20px);
    transition: all 0.2s ease;
    box-sizing: border-box;
  }

  .custom-answer-input:focus {
    outline: none;
    border-color: var(--color-primary, #4dabf7);
    box-shadow: 0 0 0 3px rgba(77, 171, 247, 0.22);
  }

  .custom-answer-input:disabled {
    background: var(--color-grey-10, #f8f9fa);
    border-color: var(--color-grey-20, #dee2e6);
    cursor: not-allowed;
    color: var(--color-font-secondary, #495057);
  }

  .disabled {
    opacity: 0.85;
  }
</style>
