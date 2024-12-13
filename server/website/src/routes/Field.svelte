<script lang="ts">
  export let type: string = 'text';
  export let placeholder: string = '';
  export let variant: 'search' | 'apikey' | 'teamslug' | 'email' = 'search';
</script>

<div class="icon-field {variant}-field">
  <input {type} {placeholder} />
</div>