<script lang="ts">
  import { socialLinks, supportedLanguages } from '../../data/siteMetadata';
  import { landingCopy } from './landingLocale';

  interface Props {
    appBaseUrl: string;
    websiteBaseUrl: string;
    language: string;
    onLanguageChange: (code: string) => void;
    availableLanguages?: readonly string[];
  }

  let { appBaseUrl, websiteBaseUrl, language, onLanguageChange, availableLanguages }: Props = $props();
  const appUrl = (path: string) => `${appBaseUrl.replace(/\/$/, '')}${path}`;
  const siteUrl = (path: string) => `${websiteBaseUrl.replace(/\/$/, '')}${path}`;
  let copy = $derived(landingCopy[language === 'de' ? 'de' : 'en']);
  let languageOptions = $derived(supportedLanguages.filter((option) => !availableLanguages || availableLanguages.includes(option.code)));
  let languageOpen = $state(false);
  let languageControl: HTMLDivElement;
  let languageButton: HTMLButtonElement;

  function closeLanguagePanel(restoreFocus = false): void {
    languageOpen = false;
    if (restoreFocus) languageButton.focus();
  }

  function selectLanguage(code: string): void {
    onLanguageChange(code);
    closeLanguagePanel(true);
  }

  function onPointerDown(event: PointerEvent): void {
    if (languageOpen && !languageControl.contains(event.target as Node)) languageOpen = false;
  }

  function onKeyDown(event: KeyboardEvent): void {
    if (event.key === 'Escape' && languageOpen) closeLanguagePanel(true);
  }
</script>

<svelte:document onpointerdown={onPointerDown} onkeydown={onKeyDown} />
<header class="site-header" data-testid="public-site-header">
  <a class="wordmark" href={siteUrl('/')} aria-label="OpenMates home"><span>Open</span>Mates</a>
  <nav class="header-actions" aria-label="Main navigation">
    <a class="header-icon github-link" href={socialLinks.find((item) => item.label === 'GitHub')?.href ?? 'https://github.com/glowingkitty/OpenMates'} target="_blank" rel="noopener noreferrer" aria-label="OpenMates on GitHub"><span class="header-mask github-mask" aria-hidden="true"></span></a>
    <div class="language-control" bind:this={languageControl}>
      <button class="header-icon language-button" bind:this={languageButton} type="button" aria-label={`${copy.language}: ${supportedLanguages.find((item) => item.code === language)?.nativeName ?? language}`} aria-expanded={languageOpen} aria-controls="landing-language-panel" data-testid="landing-language-button" onclick={() => languageOpen = !languageOpen}><span class="header-mask language-mask" aria-hidden="true"></span></button>
      {#if languageOpen}
        <div class="language-panel" id="landing-language-panel" role="dialog" aria-label={copy.language} data-testid="landing-language-panel">
          <div class="language-heading"><strong>{copy.language}</strong><button type="button" aria-label={copy.close} onclick={() => closeLanguagePanel(true)}>×</button></div>
          <p>{copy.languageHint}</p>
          <div class="language-options">
            {#each languageOptions as option (option.code)}
              <button type="button" class:selected={language === option.code} lang={option.code} aria-pressed={language === option.code} onclick={() => selectLanguage(option.code)}>{option.nativeName ?? option.name}</button>
            {/each}
          </div>
        </div>
      {/if}
    </div>
    <a class="header-link" href={appUrl('/')} data-testid="landing-open-web-app">{copy.openWebApp}</a>
  </nav>
</header>

<style>
  a { color: inherit; text-decoration: none; }
  a:focus-visible, button:focus-visible { outline: 3px solid var(--color-primary-start); outline-offset: 3px; }
  .site-header { position: relative; z-index: 2; flex: 0 0 70px; min-height: 70px; width: 100%; padding: var(--spacing-4) var(--spacing-10); box-sizing: border-box; display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-8); background: var(--color-grey-0); font-family: var(--font-primary); }
  .wordmark { flex: 0 0 auto; font-size: 1.25rem; font-weight: 800; letter-spacing: -0.04em; white-space: nowrap; }
  .wordmark span { color: var(--color-primary-start); }
  .header-actions { display: flex; flex: 0 0 auto; align-items: center; gap: var(--spacing-8); }
  .header-icon { display: inline-grid; place-items: center; flex: 0 0 42px; width: 42px; height: 42px; min-width: 0; padding: 0; margin: 0; border: 0; border-radius: var(--radius-full); background: transparent; color: var(--color-primary-start); cursor: pointer; }
  .language-button { font: inherit; }
  .header-icon:hover { background: var(--color-grey-20); }
  .header-mask { position: relative; display: block; width: 20px; height: 20px; background: var(--color-grey-70); -webkit-mask: var(--icon-url) center / contain no-repeat; mask: var(--icon-url) center / contain no-repeat; transition: background-color .25s ease; }
  .github-mask { --icon-url: url('/icons/github.svg'); }.language-mask { --icon-url: url('/icons/language.svg'); }
  .github-mask, .language-mask { background: var(--color-primary-start); }
  .header-link { display: inline-flex; align-items: center; justify-content: center; box-sizing: border-box; height: 41px; min-width: 0; margin: 0; padding: var(--spacing-4) var(--spacing-6); border-radius: var(--radius-full); background: var(--color-button-primary); color: var(--color-font-button); font-family: var(--button-font-family); font-size: var(--button-font-size); font-weight: var(--button-font-weight); box-shadow: 0 2px 8px color-mix(in srgb, var(--color-grey-100) 15%, transparent); white-space: nowrap; transition: all var(--duration-normal) var(--easing-default); }
  .header-link:hover { background: var(--color-button-primary-hover); transform: scale(1.02); }.header-link:active { background: var(--color-button-primary-pressed); transform: scale(.98); box-shadow: none; }
  .language-panel { position: absolute; z-index: 10; inset-inline-end: var(--spacing-4); top: calc(100% + var(--spacing-4)); width: min(320px, calc(100vw - 24px)); max-height: min(70dvh, 560px); overflow: auto; padding: var(--spacing-10); box-sizing: border-box; border: 1px solid var(--color-grey-25); border-radius: var(--radius-5); background: var(--color-grey-0); box-shadow: var(--shadow-lg); }
  .language-heading { display: flex; align-items: center; justify-content: space-between; }.language-heading button { border: 0; background: transparent; color: var(--color-font-primary); font: inherit; font-size: 1.5rem; cursor: pointer; }
  .language-panel p { margin: var(--spacing-4) 0 var(--spacing-8); color: var(--color-font-tertiary); font-size: var(--font-size-small); line-height: 1.4; }
  .language-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--spacing-4); }
  .language-options button { min-width: 0; min-height: 40px; padding: var(--spacing-4); border: 1px solid var(--color-grey-30); border-radius: var(--radius-3); background: var(--color-grey-10); color: var(--color-font-primary); text-align: start; font: inherit; font-size: var(--font-size-small); cursor: pointer; }
  .language-options button:hover, .language-options button.selected { border-color: var(--color-primary-start); background: var(--color-grey-blue); }
  @media (max-width: 760px) { .site-header { padding-inline: var(--spacing-8); gap: var(--spacing-4); }.header-actions { gap: var(--spacing-4); } }
  @media (max-width: 460px) { .github-link { display: none; } }
  @media (max-width: 360px) { .site-header { padding-inline: var(--spacing-4); gap: var(--spacing-2); }.header-actions { gap: var(--spacing-2); }.header-icon { flex-basis: 36px; width: 36px; height: 36px; }.header-link { padding-inline: var(--spacing-4); font-size: var(--font-size-small); } }
</style>
