<!--
  Public newsletter form for the standalone OpenMates website.
  Three explicit choices travel with the pending confirmation token.
  Apple beta updates begin unchecked and require a separate opt-in.
  A submit acknowledgment does not claim that the address is subscribed.
  The API request omits credentials and preserves the backend rate limit.
-->
<script lang="ts">
  import { requestNewsletterSubscription, type NewsletterChoices, type NewsletterLanguage } from '../newsletterApi';
  import { newsletterText, type NewsletterKey } from '../data/newsletterLocale';

  let { apiBaseUrl, websiteBaseUrl, language = 'en' }: { apiBaseUrl: string; websiteBaseUrl: string; language?: NewsletterLanguage } = $props();
  let email = $state('');
  let categories = $state<NewsletterChoices>({
    openmates_events: true,
    software_updates: true,
    apple_beta_updates: false,
  });
  let submitting = $state(false);
  let accepted = $state(false);
  let error = $state('');
  const t = (key: NewsletterKey) => newsletterText(language, key);

  function isDarkTheme(): boolean {
    const resolvedTheme = document.documentElement.dataset.theme;
    return resolvedTheme === 'dark' || (!resolvedTheme && window.matchMedia('(prefers-color-scheme: dark)').matches);
  }

  async function subscribe(event: SubmitEvent) {
    event.preventDefault();
    if (submitting) return;
    submitting = true;
    error = '';
    try {
      await requestNewsletterSubscription(apiBaseUrl, email, { ...categories }, language, isDarkTheme());
      accepted = true;
      email = '';
    } catch {
      error = t('newsletter_public_request_error');
    } finally {
      submitting = false;
    }
  }
</script>

<section class="newsletter-signup" id="newsletter" aria-labelledby="newsletter-title" data-testid="landing-newsletter">
  <div class="newsletter-copy">
    <h2 id="newsletter-title">{t('newsletter_public_title')}</h2>
    <p>{t('newsletter_public_intro')}</p>
  </div>
  {#if accepted}
    <p class="status success" role="status" data-testid="newsletter-requested">{t('newsletter_public_neutral')}</p>
  {:else}
    <form onsubmit={subscribe}>
      <fieldset>
        <legend>{t('newsletter_public_choices')}</legend>
        <label><input type="checkbox" bind:checked={categories.openmates_events} /> {t('newsletter_public_events')}</label>
        <label><input type="checkbox" bind:checked={categories.software_updates} /> {t('newsletter_public_software')}</label>
        <label><input type="checkbox" bind:checked={categories.apple_beta_updates} /> {t('newsletter_public_apple_beta')}</label>
      </fieldset>
      <div class="email-row">
        <label for="newsletter-email">{t('newsletter_public_email')}</label>
        <div class="submit-row">
          <input id="newsletter-email" type="email" autocomplete="email" required bind:value={email} disabled={submitting} placeholder={t('newsletter_public_email_placeholder')} />
          <button type="submit" disabled={submitting}>{submitting ? t('newsletter_public_sending') : t('newsletter_public_subscribe')}</button>
        </div>
      </div>
      {#if error}<p class="status error" role="alert">{error}</p>{/if}
      <p class="privacy-note">{t('newsletter_public_privacy_note')} <a href={new URL('/legal/privacy', websiteBaseUrl).href}>{t('newsletter_public_privacy_link')}</a></p>
    </form>
  {/if}
</section>

<style>
  .newsletter-signup { max-width: 1260px; margin: auto; padding: clamp(72px, 9vw, 150px) var(--spacing-24); display: grid; grid-template-columns: minmax(220px, .8fr) minmax(280px, 1.2fr); gap: var(--spacing-24); color: var(--color-font-primary); }
  h2 { margin: 0 0 var(--spacing-8); font-size: clamp(1.75rem, 2.6vw, 2.5rem); line-height: 1.24; }
  p { line-height: 1.6; }
  fieldset { display: grid; gap: var(--spacing-6); margin: 0 0 var(--spacing-12); padding: 0; border: 0; }
  legend { margin-bottom: var(--spacing-6); font-weight: 700; }
  fieldset label { display: flex; align-items: center; gap: var(--spacing-4); cursor: pointer; }
  input[type='checkbox'] { width: 1.2rem; height: 1.2rem; accent-color: var(--color-button-primary); }
  .email-row > label { display: block; margin-bottom: var(--spacing-4); font-weight: 700; }
  .submit-row { display: flex; gap: var(--spacing-4); }
  input[type='email'] { min-width: 0; flex: 1; padding: var(--spacing-6); border: 1px solid var(--color-grey-40); border-radius: var(--radius-4); font: inherit; }
  button { padding: var(--spacing-6) var(--spacing-10); border: 0; border-radius: var(--radius-4); background: var(--color-button-primary); color: var(--color-font-button); font: inherit; font-weight: 700; cursor: pointer; }
  button:disabled { opacity: .6; cursor: wait; }
  input:focus-visible, button:focus-visible, a:focus-visible { outline: 3px solid var(--color-button-primary); outline-offset: 3px; }
  .privacy-note { color: var(--color-font-tertiary); font-size: var(--font-size-small); }
  .privacy-note a { color: var(--color-primary-start); text-decoration: underline; }
  .status { margin: 0; padding: var(--spacing-8); border-radius: var(--radius-4); }
  .success { background: var(--color-grey-blue); }
  .error { color: var(--color-error); }
  @media (max-width: 760px) { .newsletter-signup { grid-template-columns: 1fr; gap: var(--spacing-8); padding: var(--spacing-24) var(--spacing-8); } }
  @media (max-width: 440px) { .submit-row { flex-direction: column; } }
</style>
