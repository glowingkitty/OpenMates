<script lang="ts">
  export let type: 'text' | 'email' | 'search' | 'tel' | 'url' | 'number' = 'text';
  export let placeholder: string = '';
  export let value: string = '';
  export let icon: 'search' | 'apikey' | 'teamslug' | 'email' | null = null;
</script>

<div class="icon-field {icon ? `${icon}-field` : ''}">
  <input
    {type}
    {placeholder}
    bind:value
    on:input
    on:change
  />
</div>