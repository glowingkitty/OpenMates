<!--
  Privacy PII short-link route.
  This page exists only to support the human-friendly /privacy/pii URL.
  It immediately moves users to the hash-only settings deep link so the actual
  in-app settings location remains client-side and is not sent on follow-up
  navigations.
-->

<script lang="ts">
  import { onMount } from 'svelte';

  onMount(() => {
    window.location.replace('/#settings/privacy/pii');
  });
</script>
