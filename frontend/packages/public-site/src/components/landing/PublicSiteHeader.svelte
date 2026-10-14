<script lang="ts">
  import { socialLinks, supportedLanguages } from '../../data/siteMetadata';
  import { landingCopy } from './landingLocale';

  interface Props {
    appBaseUrl: string;
    websiteBaseUrl: string;
    language: string;
    onLanguageChange: (code: string) => void;
    availableLanguages?: readonly string[];
    publication?: "news" | "blog";
  }

  let { appBaseUrl, websiteBaseUrl, language, onLanguageChange, availableLanguages, publication }: Props = $props();
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
<header class="site-header" class:with-publication={!!publication} data-testid="public-site-header">
  <a class="wordmark" href={siteUrl('/')} aria-label="OpenMates home"><span>Open</span>Mates</a>
  {#if publication}
    <nav class="publication-links" aria-label={language === 'de' ? 'Veröffentlichungen' : 'Publications'}>
      <a href={siteUrl(`${language === 'de' ? '/de' : ''}/news`)} aria-current={publication === 'news' ? 'page' : undefined}>News</a>
      <a href={siteUrl(`${language === 'de' ? '/de' : ''}/blog`)} aria-current={publication === 'blog' ? 'page' : undefined}>Blog</a>
    </nav>
  {/if}
  <nav class="header-actions" aria-label="Main navigation">
    <a class="header-icon github-link" href={socialLinks.find((item) => item.label === 'GitHub')?.href ?? 'https://github.com/glowingkitty/OpenMates'} target="_blank" rel="noopener noreferrer" aria-label="OpenMates on GitHub"><svg class="header-svg" aria-hidden="true" viewBox="0 0 48 48"><path d="M24 0c-3.152 0-6.273.623-9.184 1.833a23.995 23.995 0 00-7.787 5.22A24.126 24.126 0 000 24.084c0 10.645 6.888 19.677 16.416 22.88 1.2.192 1.584-.554 1.584-1.205v-4.07c-6.648 1.445-8.064-3.227-8.064-3.227-1.104-2.793-2.664-3.54-2.664-3.54-2.184-1.493.168-1.445.168-1.445 2.4.169 3.672 2.48 3.672 2.48 2.088 3.661 5.616 2.577 6.984 2 .216-1.566.84-2.626 1.512-3.228-5.328-.602-10.92-2.673-10.92-11.849 0-2.673.912-4.816 2.472-6.526-.24-.602-1.08-3.107.24-6.358 0 0 2.016-.65 6.6 2.456 1.896-.53 3.96-.795 6-.795s4.104.265 6 .795c4.584-3.107 6.6-2.456 6.6-2.456 1.32 3.25.48 5.756.24 6.358 1.56 1.71 2.472 3.853 2.472 6.526 0 9.2-5.616 11.223-10.968 11.825.864.747 1.656 2.216 1.656 4.456v6.599c0 .65.384 1.42 1.608 1.204C41.136 43.736 48 34.728 48 24.083c0-3.162-.62-6.294-1.827-9.216a24.09 24.09 0 00-5.202-7.813 23.995 23.995 0 00-7.787-5.22A23.928 23.928 0 0024 0z" fill="currentColor"/></svg></a>
    <div class="language-control" bind:this={languageControl}>
      <button class="header-icon language-button" bind:this={languageButton} type="button" aria-label={`${copy.language}: ${supportedLanguages.find((item) => item.code === language)?.nativeName ?? language}`} aria-expanded={languageOpen} aria-controls="landing-language-panel" data-testid="landing-language-button" onclick={() => languageOpen = !languageOpen}><svg class="header-svg" aria-hidden="true" viewBox="0 0 48 48">
<path fill-rule="evenodd" clip-rule="evenodd" d="M34.2667 14.8278C34.7679 14.828 35.2581 14.976 35.6771 15.2536C36.096 15.5313 36.4253 15.9264 36.6244 16.3904L47.762 42.3176C47.9061 42.6315 47.9865 42.9713 47.9984 43.317C48.0104 43.6628 47.9536 44.0074 47.8315 44.3307C47.7093 44.6539 47.5243 44.9493 47.2873 45.1993C47.0503 45.4493 46.766 45.6489 46.4513 45.7864C46.1367 45.9239 45.7979 45.9965 45.455 45.9999C45.112 46.0033 44.7719 45.9374 44.4546 45.8061C44.1373 45.6749 43.8493 45.4809 43.6075 45.2356C43.3656 44.9903 43.1749 44.6987 43.0465 44.3779L40.7436 39.0266H27.7863L25.4903 44.3779C25.2194 45.0092 24.7111 45.506 24.0771 45.7592C23.4431 46.0124 22.7354 46.0011 22.1096 45.7279C21.4838 45.4547 20.9913 44.9419 20.7403 44.3023C20.4894 43.6628 20.5005 42.9488 20.7714 42.3176L31.9089 16.3904C32.1081 15.9264 32.4374 15.5313 32.8563 15.2536C33.2752 14.976 33.7655 14.828 34.2667 14.8278ZM30.0173 33.8411H38.5161L34.2667 23.9404L30.0173 33.8411ZM13.705 1C14.3867 1 15.0404 1.27316 15.5224 1.75939C16.0044 2.24562 16.2752 2.90509 16.2752 3.59272V7.95195C19.2535 8.03875 22.2253 8.28222 25.1784 8.68137C25.8542 8.77305 26.4661 9.13177 26.8797 9.67862C27.2933 10.2255 27.4746 10.9156 27.3837 11.5973C27.2928 12.279 26.9372 12.8963 26.3951 13.3135C25.853 13.7307 25.1688 13.9136 24.493 13.8219C23.7391 13.7182 22.9829 13.626 22.2244 13.5453C21.016 17.7387 19.2081 21.7319 16.8578 25.3992C17.6711 26.4501 18.5302 27.4561 19.4349 28.4172C19.9052 28.915 20.1602 29.5809 20.1439 30.2685C20.1275 30.956 19.841 31.6088 19.3475 32.0833C18.854 32.5577 18.1938 32.815 17.5122 32.7985C16.8307 32.7819 16.1836 32.493 15.7132 31.9951C15.0185 31.2589 14.3487 30.499 13.705 29.717C10.9064 33.1178 7.62579 36.0835 3.96908 38.5184C3.40059 38.8798 2.7144 39.0022 2.05752 38.8595C1.40063 38.7167 0.825289 38.3201 0.45473 37.7547C0.0841708 37.1892 -0.0521315 36.4999 0.0750205 35.8343C0.202172 35.1687 0.582666 34.5798 1.135 34.1937C4.72579 31.795 7.90632 28.8237 10.5522 25.3958C9.87475 24.3421 9.24136 23.2603 8.65371 22.1531C8.33242 21.5466 8.26312 20.8362 8.46107 20.1782C8.65901 19.5202 9.10798 18.9684 9.70921 18.6443C10.3104 18.3202 11.0147 18.2503 11.667 18.45C12.3193 18.6497 12.8663 19.1026 13.1876 19.7091L13.7016 20.6459C15.0312 18.2952 16.1279 15.7889 16.964 13.165C12.2706 12.9789 7.56988 13.1986 2.91358 13.8219C2.23783 13.9136 1.55364 13.7307 1.01155 13.3135C0.469448 12.8963 0.113841 12.279 0.0229529 11.5973C-0.0679352 10.9156 0.113341 10.2255 0.526903 9.67862C0.940466 9.13178 1.55244 8.77305 2.22819 8.68137C5.15251 8.28727 8.12025 8.04413 11.1314 7.95195V3.59272C11.1314 3.25195 11.198 2.91452 11.3274 2.59973C11.4567 2.28494 11.6464 1.99897 11.8854 1.75817C12.1244 1.51737 12.4082 1.32646 12.7204 1.19637C13.0326 1.06628 13.3672 0.999548 13.705 1Z" fill="currentColor"/>
</svg></button>
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
  .header-icon { display: inline-grid; place-items: center; flex: 0 0 42px; width: 42px; height: 42px; min-width: 0; padding: 0; margin: 0; border: 0; border-radius: var(--radius-full); background: transparent; color: var(--color-primary-start); cursor: pointer; scale: 1; filter: none; }
  .language-button { font: inherit; }
  .header-icon:hover { background: var(--color-grey-20); }
  .header-svg { display: block; width: 20px; height: 20px; color: var(--color-primary-start); }
  .publication-links { display: flex; gap: var(--spacing-8); margin-inline-end: auto; }
  .publication-links a { opacity: .5; font-weight: 700; }
  .publication-links a[aria-current="page"] { opacity: 1; }
  .header-link { display: inline-flex; align-items: center; justify-content: center; box-sizing: border-box; height: 41px; min-width: 0; margin: 0; padding: var(--spacing-4) var(--spacing-6); border-radius: var(--radius-full); background: var(--color-button-primary); color: var(--color-font-button); font-family: var(--button-font-family); font-size: var(--button-font-size); font-weight: var(--button-font-weight); box-shadow: 0 2px 8px color-mix(in srgb, var(--color-grey-100) 15%, transparent); white-space: nowrap; transition: all var(--duration-normal) var(--easing-default); }
  .header-link:hover { background: var(--color-button-primary-hover); transform: scale(1.02); }.header-link:active { background: var(--color-button-primary-pressed); transform: scale(.98); box-shadow: none; }
  .language-panel { position: absolute; z-index: 10; inset-inline-end: var(--spacing-4); top: calc(100% + var(--spacing-4)); width: min(320px, calc(100vw - 24px)); max-height: min(70dvh, 560px); overflow: auto; padding: var(--spacing-10); box-sizing: border-box; border: 1px solid var(--color-grey-25); border-radius: var(--radius-5); background: var(--color-grey-0); box-shadow: var(--shadow-lg); }
  .language-heading { display: flex; align-items: center; justify-content: space-between; }.language-heading button { border: 0; background: transparent; color: var(--color-font-primary); font: inherit; font-size: 1.5rem; cursor: pointer; }
  .language-panel p { margin: var(--spacing-4) 0 var(--spacing-8); color: var(--color-font-tertiary); font-size: var(--font-size-small); line-height: 1.4; }
  .language-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--spacing-4); }
  .language-options button { min-width: 0; min-height: 40px; padding: var(--spacing-4); border: 1px solid var(--color-grey-30); border-radius: var(--radius-3); background: var(--color-grey-10); color: var(--color-font-primary); text-align: start; font: inherit; font-size: var(--font-size-small); cursor: pointer; }
  .language-options button:hover, .language-options button.selected { border-color: var(--color-primary-start); background: var(--color-grey-blue); }
  @media (max-width: 760px) { .site-header { padding-inline: var(--spacing-8); gap: var(--spacing-4); }.header-actions { gap: var(--spacing-4); } }
  @media (max-width: 600px) { .site-header.with-publication { flex-wrap: wrap; min-height: 110px; gap: var(--spacing-2); }.with-publication .publication-links { order: 2; width: 100%; justify-content: center; }.with-publication .header-actions { margin-inline-start: auto; } }
  @media (max-width: 460px) { .header-actions { gap: var(--spacing-1); } }
  @media (max-width: 380px) { .site-header { padding-inline: var(--spacing-4); gap: var(--spacing-2); }.header-actions { gap: var(--spacing-2); }.header-icon { flex-basis: 36px; width: 36px; height: 36px; }.header-link { padding-inline: var(--spacing-4); font-size: var(--font-size-small); } }
  @media (max-width: 340px) { .header-actions { gap: 0; }.header-icon { flex-basis: 32px; width: 32px; }.header-link { padding-inline: var(--spacing-3); }.header-link:hover, .header-link:active { transform: none; } }
</style>
