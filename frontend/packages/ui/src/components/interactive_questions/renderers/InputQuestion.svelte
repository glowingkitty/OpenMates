<!--
  frontend/packages/ui/src/components/interactive_questions/renderers/InputQuestion.svelte

  Input-type interactive question component (sequential text inputs form).
  Displays labeled text inputs and validates that required fields are filled out.
  Uses Svelte 5 Runes for properties and reactivity.

  Architecture: Svelte 5 Socratic assessment UI
-->

<script lang="ts">
  import type { InputQuestionData } from '../types';

  let {
    data,
    value = $bindable(null),
    isValid = $bindable(false),
    disabled = false,
    answeredValue = null
  } = $props<{
    data: InputQuestionData;
    value: { id: string; inputs: Record<string, string> } | null;
    isValid: boolean;
    disabled?: boolean;
    answeredValue?: Record<string, string> | null;
  }>();

  // Reactive map for text inputs
  let fieldValues = $state<Record<string, string>>({});

  // Initialize input fields with default blank entries
  $effect.pre(() => {
    const initial: Record<string, string> = {};
    for (const field of data.fields) {
      initial[field.id] = '';
    }
    fieldValues = initial;
  });

  // Load answered values when locked
  $effect(() => {
    if (disabled && answeredValue) {
      fieldValues = { ...answeredValue };
    }
  });

  // Handle value change on keyup/change
  function handleInput(fieldId: string, val: string) {
    if (disabled) return;
    fieldValues = { ...fieldValues, [fieldId]: val };

    // Validate that all required fields have non-empty values
    let allRequiredFilled = true;
    for (const field of data.fields) {
      if (field.required) {
        const val = fieldValues[field.id];
        if (!val || !val.trim()) {
          allRequiredFilled = false;
          break;
        }
      }
    }

    isValid = allRequiredFilled;
    value = isValid ? { id: data.id, inputs: fieldValues } : null;
  }
</script>

<div class="input-question" class:disabled>
  <div class="fields-stack">
    {#each data.fields as field (field.id)}
      <div class="field-item">
        <label for={field.id} class="field-label">
          {field.label}
          {#if field.required}
            <span class="required-asterisk">*</span>
          {/if}
        </label>
        <input
          type="text"
          id={field.id}
          value={fieldValues[field.id] || ''}
          placeholder={field.placeholder || ''}
          {disabled}
          oninput={(e) => handleInput(field.id, (e.target as HTMLInputElement).value)}
          class="text-input"
        />
      </div>
    {/each}
  </div>
</div>

<style>
  .fields-stack {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-16, 16px);
    width: 100%;
  }

  .field-item {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-6, 6px);
    width: 100%;
  }

  .field-label {
    font-size: var(--font-size-small, 13px);
    font-weight: 500;
    color: var(--color-font-secondary, #495057);
  }

  .required-asterisk {
    color: var(--color-error, #fa5252);
    margin-left: 2px;
  }

  .text-input {
    width: 100%;
    padding: var(--spacing-10, 10px) var(--spacing-12, 12px);
    font-size: var(--font-size-p, 15px);
    background: var(--color-grey-0, #ffffff);
    border: 1px solid var(--color-grey-30, #ced4da);
    border-radius: var(--radius-8, 20px);
    transition: all 0.2s ease;
    box-sizing: border-box;
  }

  .text-input:focus {
    outline: none;
    border-color: var(--color-primary, #4dabf7);
    box-shadow: 0 0 0 3px rgba(77, 171, 247, 0.22);
  }

  .text-input:disabled {
    background: var(--color-grey-10, #f8f9fa);
    border-color: var(--color-grey-20, #dee2e6);
    cursor: not-allowed;
    color: var(--color-font-secondary, #495057);
  }

  .disabled {
    opacity: 0.9;
  }
</style>
