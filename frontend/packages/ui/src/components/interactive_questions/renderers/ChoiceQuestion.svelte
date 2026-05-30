<!--
  frontend/packages/ui/src/components/interactive_questions/renderers/ChoiceQuestion.svelte

  Choice-type interactive question component (single or multi-select).
  Renders choices stacked vertically with checkbox/radio indicators.
  Uses Svelte 5 Runes for properties and reactivity.

  Architecture: Svelte 5 Socratic assessment UI
-->

<script lang="ts">
  import type { ChoiceQuestionData } from '../types';

  let {
    data,
    value = $bindable(null),
    isValid = $bindable(false),
    disabled = false,
    answeredValue = null
  } = $props<{
    data: ChoiceQuestionData;
    value: { id: string; selection: string[] } | null;
    isValid: boolean;
    disabled?: boolean;
    answeredValue?: string[] | null;
  }>();

  // Internal state tracking selected option IDs
  let selectedIds = $state<string[]>([]);

  // Initialize selected IDs if already answered (locked)
  $effect(() => {
    if (disabled && answeredValue) {
      selectedIds = answeredValue;
    }
  });

  // Handle choice selection
  function handleSelect(optionId: string) {
    if (disabled) return;

    if (data.multiple) {
      if (selectedIds.includes(optionId)) {
        selectedIds = selectedIds.filter(id => id !== optionId);
      } else {
        selectedIds = [...selectedIds, optionId];
      }
    } else {
      selectedIds = [optionId];
    }

    // Update bindable state
    isValid = selectedIds.length > 0;
    value = isValid ? { id: data.id, selection: selectedIds } : null;
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

  .disabled {
    opacity: 0.85;
  }
</style>
