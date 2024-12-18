<script lang="ts">
  import type { HTMLInputAttributes } from 'svelte/elements';

  export let type: string = 'text';
  export let placeholder: string = '';
  export let variant: 'search' | 'apikey' | 'teamslug' | 'email' = 'search';
  export let withButton: boolean = false;
  export let buttonText: string = 'Send';
  export let onButtonClick: () => void = () => {};
  export let autofocus: boolean = false;
  export let value: string = '';

  // New props for accessibility and autofill
  export let id: string | undefined = undefined;
  export let name: string | undefined = undefined;
  export let autocomplete: HTMLInputAttributes['autocomplete'] = 'off';

  // State for validation
  let error: string = '';
  let isValid: boolean = true;

  // Validation functions
  const validateEmail = (email: string): boolean => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
  };

  // Handle validation based on field type
  const validate = (value: string) => {
    error = '';
    isValid = true;

    if (type === 'email') {
      if (!value) {
        error = 'Please enter an email address';
        isValid = false;
      } else if (!validateEmail(value)) {
        error = 'Please enter a valid email address';
        isValid = false;
      }
    }
  };

  // Handle button click with validation
  const handleButtonClick = () => {
    validate(value);
    if (isValid) {
      onButtonClick();
    }
  };

  // Handle enter key press
  const handleKeydown = (event: KeyboardEvent) => {
    if (event.key === 'Enter' && withButton) {
      handleButtonClick();
    }
  };
</script>

<div class="icon-field {variant}-field">
  <!-- svelte-ignore a11y-autofocus -->
  <input
    {type}
    {placeholder}
    bind:value
    {id}
    {name}
    {autocomplete}
    class:with-button={withButton}
    class:error={!isValid}
    style={withButton ? 'padding-right: 120px;' : ''}
    {autofocus}
    on:keydown={handleKeydown}
  />
  {#if withButton}
    <button 
      class="field-button" 
      on:click={handleButtonClick}
      type="submit"
    >
      {buttonText}
    </button>
  {/if}
  {#if error}
    <p class="error-message" id={id ? `${id}-error` : undefined} role="alert">{error}</p>
  {/if}
</div>

<style>
  .field-button {
    position: absolute;
    right: 5px;
    top: 50%;
    transform: translateY(-50%);
    padding: 12px 24px;
    height: auto;
    margin: 0;
    z-index: 1;
  }

  .icon-field {
    position: relative;
  }

  .error-message {
    position: absolute;
    bottom: -20px;
    left: 0;
    font-size: 0.8rem;
    color: #e74c3c;
    margin: 0;
  }

  input.error {
    border-color: #e74c3c;
  }
</style>