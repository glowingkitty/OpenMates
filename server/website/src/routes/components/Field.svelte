<script lang="ts">
  export let type: string = 'text';
  export let placeholder: string = '';
  export let variant: 'search' | 'apikey' | 'teamslug' | 'email' = 'search';
  export let withButton: boolean = false;
  export let buttonText: string = 'Send';
  export let onButtonClick: () => void = () => {};
  export let autofocus: boolean = false;
</script>

<div class="icon-field {variant}-field">
  <!-- svelte-ignore a11y-autofocus -->
  <input
    {type}
    {placeholder}
    class:with-button={withButton}
    style={withButton ? 'padding-right: 120px;' : ''}
    autofocus={autofocus}
  />
  {#if withButton}
    <button class="field-button" on:click={onButtonClick}>
      {buttonText}
    </button>
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
</style>