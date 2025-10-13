<script lang="ts">
  import type { HTMLInputAttributes } from 'svelte/elements';

  // Props using Svelte 5 runes
  let { 
    type = 'text',
    placeholder = '',
    variant = 'search',
    withButton = false,
    buttonText = 'Send',
    onButtonClick = () => {},
    value = '',
    id = undefined,
    name = undefined,
    autocomplete = 'off'
  }: {
    type?: 'text' | 'email' | 'search' | 'tel' | 'url' | 'number';
    placeholder?: string;
    variant?: 'search' | 'apikey' | 'teamslug' | 'email';
    withButton?: boolean;
    buttonText?: string;
    onButtonClick?: () => void;
    value?: string;
    id?: string | undefined;
    name?: string | undefined;
    autocomplete?: HTMLInputAttributes['autocomplete'];
  } = $props();

  let error: string = $state('');
  let isValid: boolean = $state(true);

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
      oninput={handleInput}
      {id}
      {name}
      {autocomplete}
      class:with-button={withButton}
      class:error={!isValid}
      style={withButton ? 'padding-right: 120px;' : ''}
      onkeydown={handleKeydown}
    />
  {:else if type === 'email'}
    <input
      type="email"
      {placeholder}
      value={value}
      oninput={handleInput}
      {id}
      {name}
      {autocomplete}
      class:with-button={withButton}
      class:error={!isValid}
      style={withButton ? 'padding-right: 120px;' : ''}
      onkeydown={handleKeydown}
    />
  {:else if type === 'search'}
    <input
      type="search"
      {placeholder}
      value={value}
      oninput={handleInput}
      {id}
      {name}
      {autocomplete}
      class:with-button={withButton}
      class:error={!isValid}
      style={withButton ? 'padding-right: 120px;' : ''}
      onkeydown={handleKeydown}
    />
  {:else if type === 'tel'}
    <input
      type="tel"
      {placeholder}
      value={value}
      oninput={handleInput}
      {id}
      {name}
      {autocomplete}
      class:with-button={withButton}
      class:error={!isValid}
      style={withButton ? 'padding-right: 120px;' : ''}
      onkeydown={handleKeydown}
    />
  {:else if type === 'url'}
    <input
      type="url"
      {placeholder}
      value={value}
      oninput={handleInput}
      {id}
      {name}
      {autocomplete}
      class:with-button={withButton}
      class:error={!isValid}
      style={withButton ? 'padding-right: 120px;' : ''}
      onkeydown={handleKeydown}
    />
  {:else if type === 'number'}
    <input
      type="number"
      {placeholder}
      value={value}
      oninput={handleInput}
      {id}
      {name}
      {autocomplete}
      class:with-button={withButton}
      class:error={!isValid}
      style={withButton ? 'padding-right: 120px;' : ''}
      onkeydown={handleKeydown}
    />
  {/if}

  {#if withButton}
    <button 
      class="field-button" 
      onclick={handleButtonClick}
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
