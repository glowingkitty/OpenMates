<script lang="ts">
  import Header from '../Header.svelte';
</script>

<!-- Match workspace routes that mount their own Header under the root page. -->
<Header context="webapp" isLoggedIn={true} />
