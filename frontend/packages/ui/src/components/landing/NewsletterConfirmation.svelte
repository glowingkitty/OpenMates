<!--
  Bare preview adapter for the public newsletter confirmation result.
  The canonical product component lives in @repo/public-site.
  A fake token and relative API URL permit isolated response interception.
  Signal is a fixture URL and never opened by the preview automatically.
  Keep all required public-site props explicit for preview parity.
-->
<script lang="ts">
  import PublicNewsletterConfirmation from '@repo/public-site/components/NewsletterConfirmation.svelte';

  let { apiBaseUrl, signalUrl, token, language = 'en' }: {
    apiBaseUrl: string;
    signalUrl: string;
    token: string;
    language?: 'en' | 'de';
  } = $props();
</script>

<PublicNewsletterConfirmation {apiBaseUrl} {signalUrl} {token} {language} />
