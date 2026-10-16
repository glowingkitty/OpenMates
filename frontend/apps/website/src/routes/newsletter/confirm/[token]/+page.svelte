<script lang="ts">
  import NewsletterConfirmation from '@repo/public-site/components/NewsletterConfirmation.svelte';
  import type { PageData } from './$types';
  let { data }: { data: PageData } = $props();
</script>
<svelte:head><title>Confirm newsletter — OpenMates</title><meta name="robots" content="noindex, nofollow" /></svelte:head>
<NewsletterConfirmation apiBaseUrl={data.apiBaseUrl} signalUrl={data.signalUrl} token={data.token} language={data.language} />
