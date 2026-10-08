<!--
  Public email-token confirmation result for the standalone website.
  The token comes from the route path and is sent only after an explicit click.
  This avoids consuming one-use tokens during automatic link previews.
  This component uses no account session or browser-stored subscriber state.
  The Signal invitation appears only after the API confirms the token.
  Invalid and expired tokens keep the invitation hidden.
-->
<script lang="ts">
  import { confirmNewsletterSubscription, type NewsletterLanguage } from '../newsletterApi';
  import { newsletterText, type NewsletterKey } from '../data/newsletterLocale';

  let { apiBaseUrl, signalUrl, token, language = 'en' }: { apiBaseUrl: string; signalUrl: string; token: string; language?: NewsletterLanguage } = $props();
  let status = $state<'ready' | 'pending' | 'confirmed' | 'failed'>('ready');
  const t = (key: NewsletterKey) => newsletterText(language, key);

  async function confirm() {
    if (status !== 'ready') return;
    status = 'pending';
    try {
      await confirmNewsletterSubscription(apiBaseUrl, token);
      status = 'confirmed';
    } catch {
      status = 'failed';
    }
  }
</script>

<main class="confirmation" data-testid="newsletter-confirmation">
  <h1>{t('newsletter_public_confirmation_title')}</h1>
  {#if status === 'ready'}
    <p>{t('newsletter_public_confirmation_intro')}</p>
    <button type="button" onclick={confirm} data-testid="newsletter-confirm-button">{t('newsletter_public_confirm_button')}</button>
  {:else if status === 'pending'}
    <p role="status">{t('newsletter_public_confirming')}</p>
  {:else if status === 'confirmed'}
    <p role="status">{t('newsletter_public_confirmed')}</p>
    <a href={signalUrl} target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer" data-testid="newsletter-signal-link">{t('newsletter_public_signal')}</a>
  {:else}
    <p role="alert">{t('newsletter_public_invalid')}</p>
  {/if}
</main>

<style>
  .confirmation { max-width: 720px; margin: 12vh auto; padding: var(--spacing-16); color: var(--color-font-primary); font-family: var(--font-primary); }
  h1 { font-size: clamp(2rem, 4vw, 3rem); }
  p { line-height: 1.6; }
  a, button { display: inline-block; margin-top: var(--spacing-8); padding: var(--spacing-6) var(--spacing-10); border: 0; border-radius: var(--radius-4); background: var(--color-button-primary); color: var(--color-font-button); font: inherit; font-weight: 700; text-decoration: none; cursor: pointer; }
  a:focus-visible, button:focus-visible { outline: 3px solid var(--color-button-primary); outline-offset: 3px; }
</style>
