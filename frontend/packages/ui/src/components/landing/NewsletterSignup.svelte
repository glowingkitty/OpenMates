<!--
  Bare preview adapter for the public website newsletter signup.
  The canonical product component lives in @repo/public-site.
  Its companion fixture uses a relative API URL for local interception.
  No account or settings runtime is loaded by this adapter.
  Keep required public-site props explicit for preview parity.
-->
<script lang="ts">
  import PublicNewsletterSignup from '@repo/public-site/components/NewsletterSignup.svelte';

  let { apiBaseUrl, websiteBaseUrl, language = 'en' }: {
    apiBaseUrl: string;
    websiteBaseUrl: string;
    language?: 'en' | 'de';
  } = $props();
</script>

<PublicNewsletterSignup {apiBaseUrl} {websiteBaseUrl} {language} />
