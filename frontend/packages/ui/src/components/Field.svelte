<script lang="ts">
  import type { HTMLInputAttributes } from 'svelte/elements';

  export let type: 'text' | 'email' | 'search' | 'tel' | 'url' | 'number' = 'text';
  export let placeholder: string = '';
  export let variant: 'search' | 'apikey' | 'teamslug' | 'email' = 'search';
  export let withButton: boolean = false;
  export let buttonText: string = 'Send';
  export let onButtonClick: () => void = () => {};
  export let autofocus: boolean = false;
  export let value: string = '';

  export let id: string | undefined = undefined;
  export let name: string | undefined = undefined;
  export let autocomplete: HTMLInputAttributes['autocomplete'] = 'off';

  let error: string = '';
  let isValid: boolean = true;

  const validateEmail = (email: string): boolean => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
  };

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

  const handleButtonClick = () => {
    validate(value);
    if (isValid) {
      onButtonClick();
    }
  };

  const handleKeydown = (event: KeyboardEvent) => {
    if (event.key === 'Enter' && withButton) {
      handleButtonClick();
    }
  };

  const handleInput = (event: Event) => {
    const target = event.target as HTMLInputElement;
    value = target.value;
  };
</script>

<div class="icon-field {variant}-field">
  {#if type === 'text'}
    <input
      type="text"
      {placeholder}
      value={value}
      on:input={handleInput}
      {id}
      {name}
      {autocomplete}
      class:with-button={withButton}
      class:error={!isValid}
      style={withButton ? 'padding-right: 120px;' : ''}
      {autofocus}
      on:keydown={handleKeydown}
    />
  {:else if type === 'email'}
    <input
      type="email"
      {placeholder}
      value={value}
      on:input={handleInput}
      {id}
      {name}
      {autocomplete}
      class:with-button={withButton}
      class:error={!isValid}
      style={withButton ? 'padding-right: 120px;' : ''}
      {autofocus}
      on:keydown={handleKeydown}
    />
  {:else if type === 'search'}
    <input
      type="search"
      {placeholder}
      value={value}
      on:input={handleInput}
      {id}
      {name}
      {autocomplete}
      class:with-button={withButton}
      class:error={!isValid}
      style={withButton ? 'padding-right: 120px;' : ''}
      {autofocus}
      on:keydown={handleKeydown}
    />
  {:else if type === 'tel'}
    <input
      type="tel"
      {placeholder}
      value={value}
      on:input={handleInput}
      {id}
      {name}
      {autocomplete}
      class:with-button={withButton}
      class:error={!isValid}
      style={withButton ? 'padding-right: 120px;' : ''}
      {autofocus}
      on:keydown={handleKeydown}
    />
  {:else if type === 'url'}
    <input
      type="url"
      {placeholder}
      value={value}
      on:input={handleInput}
      {id}
      {name}
      {autocomplete}
      class:with-button={withButton}
      class:error={!isValid}
      style={withButton ? 'padding-right: 120px;' : ''}
      {autofocus}
      on:keydown={handleKeydown}
    />
  {:else if type === 'number'}
    <input
      type="number"
      {placeholder}
      value={value}
      on:input={handleInput}
      {id}
      {name}
      {autocomplete}
      class:with-button={withButton}
      class:error={!isValid}
      style={withButton ? 'padding-right: 120px;' : ''}
      {autofocus}
      on:keydown={handleKeydown}
    />
  {/if}

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
