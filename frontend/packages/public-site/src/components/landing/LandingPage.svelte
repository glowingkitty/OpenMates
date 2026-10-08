<script lang="ts">
  import { onMount } from 'svelte';
  import type { LandingPublication } from './landingPageContent';
  import DeviceScreenshots from '../DeviceScreenshots.svelte';
  import NewsletterSignup from '../NewsletterSignup.svelte';
  import { publicApps } from '../../data/publicApps';
  import { socialLinks, supportedLanguages } from '../../data/siteMetadata';
  import { proxyImage } from '../../data/proxyImage';
  import { landingCopy } from './landingLocale';

  interface Props {
    appBaseUrl: string;
    websiteBaseUrl: string;
    apiBaseUrl: string;
    events?: LandingPublication[];
    news?: LandingPublication[];
    posts?: LandingPublication[];
  }

  let { appBaseUrl, websiteBaseUrl, apiBaseUrl, events = [], news = [], posts = [] }: Props = $props();
  const appUrl = (path: string) => `${appBaseUrl.replace(/\/$/, '')}${path}`;
  const siteUrl = (path: string) => `${websiteBaseUrl.replace(/\/$/, '')}${path}`;

  const promptIntervalMs = 3400;
  const firstVisibleIndex = Math.floor(publicApps.length / 2);
  let activeIndex = $state(firstVisibleIndex);
  let activeApp = $derived(publicApps[activeIndex] ?? publicApps[0]);
  let promptHasChanged = $state(false);
  let railPlaying = $state(false);
  let reducedMotion = $state(false);
  let chosenLanguage = $state('en');
  let copy = $derived(landingCopy[chosenLanguage === 'de' ? 'de' : 'en']);
  let languageOpen = $state(false);
  let landingRoot: HTMLDivElement;
  let languageControl: HTMLDivElement;
  let languageButton: HTMLButtonElement;
  let scrollContainer: HTMLElement;

  function closeLanguagePanel(restoreFocus = false): void {
    languageOpen = false;
    if (restoreFocus) languageButton.focus();
  }

  function selectLanguage(code: string): void {
    chosenLanguage = code;
    try { localStorage.setItem('preferredLanguage', code); } catch { /* Storage can be disabled. */ }
    document.documentElement.lang = code === 'de' ? 'de' : 'en';
    document.documentElement.dir = 'ltr';
    closeLanguagePanel(true);
  }

  onMount(() => {
    let storedLanguage: string | null = null;
    try { storedLanguage = localStorage.getItem('preferredLanguage'); } catch { /* Storage can be disabled. */ }
    if (storedLanguage && supportedLanguages.some((item) => item.code === storedLanguage)) chosenLanguage = storedLanguage;
    document.documentElement.lang = chosenLanguage === 'de' ? 'de' : 'en';
    document.documentElement.dir = 'ltr';

    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0;
    let startedAt = 0;
    let observer: IntersectionObserver | undefined;

    const tick = (now: number) => {
      if (!railPlaying || publicApps.length === 0) return;
      const nextIndex = (firstVisibleIndex + Math.floor((now - startedAt) / promptIntervalMs)) % publicApps.length;
      if (nextIndex !== activeIndex) {
        activeIndex = nextIndex;
        promptHasChanged = true;
      }
      frame = requestAnimationFrame(tick);
    };
    const onScroll = () => {
      if (reducedMotion) return;
      landingRoot.style.setProperty('--hero-parallax-y', `${Math.min(scrollContainer.scrollTop * 0.12, 48)}px`);
    };
    const updateMotion = () => {
      reducedMotion = motionQuery.matches;
      cancelAnimationFrame(frame);
      activeIndex = firstVisibleIndex;
      promptHasChanged = false;
      railPlaying = !reducedMotion && publicApps.length > 0;
      if (railPlaying) {
        startedAt = performance.now();
        frame = requestAnimationFrame(tick);
      }
      observer?.disconnect();
      landingRoot.querySelectorAll<HTMLElement>('[data-reveal]').forEach((element) => {
        element.classList.remove('reveal-ready');
        element.classList.remove('revealed');
      });
      if (!reducedMotion && 'IntersectionObserver' in window) {
        observer = new IntersectionObserver((entries) => {
          for (const entry of entries) if (entry.isIntersecting) {
            entry.target.classList.add('revealed');
            observer?.unobserve(entry.target);
          }
        }, { root: scrollContainer, threshold: 0.12 });
        landingRoot.querySelectorAll<HTMLElement>('[data-reveal]').forEach((element) => {
          element.classList.add('reveal-ready');
          observer?.observe(element);
        });
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      if (languageOpen && !languageControl.contains(event.target as Node)) languageOpen = false;
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && languageOpen) closeLanguagePanel(true);
    };
    motionQuery.addEventListener('change', updateMotion);
    scrollContainer.addEventListener('scroll', onScroll, { passive: true });
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    updateMotion();
    return () => {
      cancelAnimationFrame(frame);
      observer?.disconnect();
      motionQuery.removeEventListener('change', updateMotion);
      scrollContainer.removeEventListener('scroll', onScroll);
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  });
</script>

<div class="landing-page" bind:this={landingRoot} data-testid="landing-page" lang={chosenLanguage === 'de' ? 'de' : 'en'}>
  <header class="site-header">
    <a class="wordmark" href={appUrl('/')} aria-label="OpenMates home"><span>Open</span>Mates</a>
    <nav class="workspace-nav" aria-label="OpenMates workspaces">
      <a href={appUrl('/')} aria-label="Chats" data-testid="landing-nav-chats"><span class="header-mask chat-mask" aria-hidden="true"></span></a>
      <a href={appUrl('/#apps')} aria-label="Apps" data-testid="landing-nav-apps"><span class="header-mask app-mask" aria-hidden="true"></span></a>
      <a href={appUrl('/#workflows')} aria-label="Workflows" data-testid="landing-nav-workflows"><span class="header-mask workflow-mask" aria-hidden="true"></span></a>
    </nav>
    <nav class="header-actions" aria-label="Main navigation">
      <a class="header-icon github-link" href={socialLinks.find((item) => item.label === 'GitHub')?.href ?? 'https://github.com/glowingkitty/OpenMates'} target="_blank" rel="noopener noreferrer" aria-label="OpenMates on GitHub"><span class="header-mask github-mask" aria-hidden="true"></span></a>
      <a class="header-link" href={appUrl('/#signup/basics')} data-testid="landing-signup"><span class="desktop-login">{copy.login}</span><span class="mobile-login">{copy.signup}</span></a>
      <div class="language-control" bind:this={languageControl}>
        <button class="header-icon language-button" bind:this={languageButton} type="button" aria-label={`${copy.language}: ${supportedLanguages.find((item) => item.code === chosenLanguage)?.nativeName ?? chosenLanguage}`} aria-expanded={languageOpen} aria-controls="landing-language-panel" data-testid="landing-language-button" onclick={() => languageOpen = !languageOpen}><span class="header-mask language-mask" aria-hidden="true"></span><span class="language-code" aria-hidden="true">{chosenLanguage.toUpperCase()}</span></button>
        {#if languageOpen}
          <div class="language-panel" id="landing-language-panel" role="dialog" aria-label={copy.language} data-testid="landing-language-panel">
            <div class="language-heading"><strong>{copy.language}</strong><button type="button" aria-label={copy.close} onclick={() => closeLanguagePanel(true)}>×</button></div>
            <p>{copy.languageHint}</p>
            <div class="language-options">
              {#each supportedLanguages as language (language.code)}
                <button type="button" class:selected={chosenLanguage === language.code} lang={language.code} aria-pressed={chosenLanguage === language.code} onclick={() => selectLanguage(language.code)}>{language.nativeName ?? language.name}</button>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    </nav>
  </header>

  <div class="viewport-container" data-testid="landing-viewport-container">
    <main class="scroll-container" bind:this={scrollContainer} data-testid="landing-scroll-container">
      <section class="hero" aria-labelledby="hero-title" data-testid="landing-hero">
        <div class="hero-visual" data-testid="landing-hero-media">
          <DeviceScreenshots baseKey="hero" desktopAlt="OpenMates web app chat workspace" mobileAlt="OpenMates mobile web chat workspace" eager />
        </div>
        <h1 id="hero-title">{copy.heroLine1}<br />{copy.heroLine2}</h1>
        {#if activeApp}
          {#key activeApp.id}
            <p class="prompt-bubble" class:transitioning={promptHasChanged} data-testid="landing-prompt" data-active-app={activeApp.id} aria-live="polite">{chosenLanguage === 'de' ? activeApp.promptDe : activeApp.promptEn}</p>
          {/key}
        {/if}
        <p class="hero-speed" data-testid="landing-hero-speed">{copy.inSeconds}</p>
        <div class="rail-window" data-testid="landing-app-rail" data-active-app={activeApp?.id} aria-label="OpenMates apps">
          <div class="rail-track" class:playing={railPlaying} style={`--rail-duration:${Math.max(publicApps.length, 1) * promptIntervalMs}ms`}>
            {#each [0, 1] as group (group)}
              <div class="rail-group" data-testid="landing-rail-group" aria-hidden="true">
                {#each publicApps as app (app.id)}
                  <span class="rail-icon" class:highlighted={activeApp?.id === app.id} data-app-id={app.id} style={`--rail-icon-bg:${app.gradient};--rail-icon-url:url('${app.iconUrl}')`}></span>
                {/each}
              </div>
            {/each}
          </div>
        </div>
        <a class="scroll-cue" href="#actionable" data-testid="landing-scroll-cue"><svg class="cue-arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg><span>{copy.scroll}</span><svg class="cue-arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg></a>
      </section>

      <section class="feature feature-media" id="actionable" aria-labelledby="actionable-title" data-testid="landing-feature-actionable" data-reveal>
        <div class="feature-copy">
          <span class="feature-icon search-icon" aria-hidden="true" data-testid="landing-feature-icon"></span>
          <h2 id="actionable-title">{copy.actionableTitle1}<br />{copy.actionableTitle2}</h2>
          <p>{copy.actionableBody}</p>
          <a class="text-link" href={appUrl('/#apps')} target="_blank" rel="noopener noreferrer" data-testid="landing-explore-apps">{copy.exploreApps}</a>
        </div>
        <div class="feature-example" data-testid="landing-feature-media-actionable">
          <DeviceScreenshots baseKey="events" desktopAlt="OpenMates web chat searching for AI events in Berlin" mobileAlt="OpenMates mobile view of an events chat" />
          <a class="example-link" href={appUrl('/#chat-id=example-ai-workshops-meetups-berlin')}>{copy.openExample} ↗</a>
        </div>
      </section>

      <section class="feature feature-media" id="privacy" aria-labelledby="privacy-title" data-testid="landing-feature-privacy" data-reveal>
        <div class="feature-copy">
          <span class="feature-icon security-icon" aria-hidden="true" data-testid="landing-feature-icon"></span>
          <h2 id="privacy-title">{copy.privacyTitle1}<br />{copy.privacyTitle2}</h2>
          <p>{copy.privacyBody}</p>
          <div class="feature-links"><a class="text-link" href={siteUrl('/blog')}>{copy.privacyLink}</a><a class="text-link" href={siteUrl('/blog')}>{copy.safetyLink}</a></div>
        </div>
        <div class="feature-example" data-testid="landing-feature-media-privacy">
          <DeviceScreenshots baseKey="privacy" desktopAlt="OpenMates web chat with personal data replaced by placeholders" mobileAlt="OpenMates mobile chat highlighting personal data" />
          <a class="example-link" href={appUrl('/#chat-id=example-plumber-message-email-phone')}>{copy.openExample} ↗</a>
        </div>
      </section>

      <section class="feature feature-media" id="workflows" aria-labelledby="workflows-title" data-testid="landing-feature-workflows" data-reveal>
        <div class="feature-copy">
          <span class="feature-icon workflow-icon" aria-hidden="true" data-testid="landing-feature-icon"></span>
          <h2 id="workflows-title">{copy.workflowTitle1}<br />{copy.workflowTitle2}</h2>
          <p>{copy.workflowBody}</p>
          <a class="text-link" href={appUrl('/#workflows')} target="_blank" rel="noopener noreferrer" data-testid="landing-explore-workflows">{copy.exploreWorkflows}</a>
        </div>
        <div class="feature-example" data-testid="landing-feature-media-workflows">
          <DeviceScreenshots baseKey="workflows" desktopAlt="OpenMates workflow workspace" mobileAlt="OpenMates workflow view on mobile" />
          <a class="example-link" href={appUrl('/#chat-id=example-library-book-return-workflow')}>{copy.openExample} ↗</a>
        </div>
      </section>

      <section class="feature feature-media feature-later" id="devices" aria-labelledby="devices-title" data-testid="landing-feature-devices" data-reveal>
        <div class="feature-copy">
          <span class="feature-icon devices-icon" aria-hidden="true" data-testid="landing-feature-icon"></span>
          <h2 id="devices-title">{copy.devicesTitle1}<br />{copy.devicesTitle2}</h2>
          <p>{copy.devicesBody}</p>
          <div class="feature-links">
            <a class="text-link" href={appUrl('/')}>{copy.startWebApp}</a>
            <a class="text-link" href="#testflight-signup">{copy.testflight}</a>
            <a class="text-link" href={siteUrl('/blog')}>{copy.developers}</a>
          </div>
        </div>
        <div class="feature-example" data-testid="landing-feature-media-devices"><DeviceScreenshots baseKey="devices" desktopAlt="The same OpenMates chat on desktop" mobileAlt="The same OpenMates chat in the mobile web app" /></div>
      </section>

      <section class="feature feature-media feature-later" id="open-source" aria-labelledby="open-source-title" data-testid="landing-feature-open-source" data-reveal>
        <div class="feature-copy">
          <span class="feature-icon coding-icon" aria-hidden="true" data-testid="landing-feature-icon"></span>
          <h2 id="open-source-title">{copy.sourceTitle1}<br />{copy.sourceTitle2}</h2>
          <p>{copy.sourceBody}</p>
          <div class="feature-links"><a class="text-link" href={siteUrl('/blog')}>{copy.ethics}</a><a class="text-link" href={siteUrl('/blog')}>{copy.selfHosting}</a></div>
        </div>
        <div class="feature-example" data-testid="landing-feature-media-open-source"><DeviceScreenshots baseKey="open-source" desktopAlt="OpenMates public source repository" mobileAlt="OpenMates source repository on mobile" /></div>
      </section>

      <div id="testflight-signup"><NewsletterSignup {apiBaseUrl} {websiteBaseUrl} language={chosenLanguage === 'de' ? 'de' : 'en'} /></div>

      <div class="publication-area">
        <section class="publication-row" aria-labelledby="events-title" data-testid="landing-events">
          <div class="publication-intro"><h2 id="events-title">{copy.eventsTitle}</h2><p>{copy.eventsBody}</p></div>
          {#if events.length}
            <div class="event-cards" data-testid="landing-event-cards">
              {#each events as item (item.id)}
                <a class="publication-card" href={item.href} target="_blank" rel="noopener noreferrer" data-testid="landing-event-card">
                  {#if item.image}<img src={proxyImage(item.image, 640)} alt="" loading="lazy" />{/if}
                  <div class="card-copy">{#if item.label}<span class="card-label">{item.label}</span>{/if}<h3>{item.title}</h3>{#if item.description}<p>{item.description}</p>{/if}</div>
                </a>
              {/each}
            </div>
          {:else}<p class="empty-publication">{copy.eventsEmpty}</p>{/if}
        </section>
        <section class="publication-row" aria-labelledby="news-title">
          <div class="publication-intro"><h2 id="news-title">{copy.newsTitle}</h2><p>{copy.newsBody}</p><a class="text-link" href={siteUrl('/news')}>{copy.newsBrowse}</a></div>
          {#if news.length}<div class="publication-cards">{#each news.slice(0, 2) as item (item.id)}<a class="publication-card" href={item.href}>{#if item.image}<img src={proxyImage(item.image, 640)} alt="" loading="lazy" />{/if}<div class="card-copy">{#if item.label}<span class="card-label">{item.label}</span>{/if}<h3>{item.title}</h3>{#if item.description}<p>{item.description}</p>{/if}</div></a>{/each}</div>{:else}<a class="empty-publication" href={siteUrl('/news')}>{copy.newsEmpty} ↗</a>{/if}
        </section>
        <section class="publication-row" aria-labelledby="blog-title">
          <div class="publication-intro"><h2 id="blog-title">{copy.blogTitle}</h2><p>{copy.blogBody}</p><a class="text-link" href={siteUrl('/blog')}>{copy.blogBrowse}</a></div>
          {#if posts.length}<div class="publication-cards">{#each posts.slice(0, 2) as item (item.id)}<a class="publication-card" href={item.href}>{#if item.image}<img src={proxyImage(item.image, 640)} alt="" loading="lazy" />{/if}<div class="card-copy">{#if item.label}<span class="card-label">{item.label}</span>{/if}<h3>{item.title}</h3>{#if item.description}<p>{item.description}</p>{/if}</div></a>{/each}</div>{:else}<a class="empty-publication" href={siteUrl('/blog')}>{copy.blogEmpty} ↗</a>{/if}
        </section>
      </div>

      <footer class="site-footer">
        <div><a class="wordmark" href={appUrl('/')}><span>Open</span>Mates</a><p>{copy.social}</p><div class="social-links">{#each socialLinks as social (social.label)}<a href={social.href} target="_blank" rel="noopener noreferrer" aria-label={social.label}><img src={social.iconUrl} alt="" width="22" height="22" /></a>{/each}</div></div>
        <nav aria-label="Footer navigation"><a href={siteUrl('/legal/privacy')}>{copy.privacy}</a><a href={siteUrl('/legal/terms')}>{copy.terms}</a><a href={siteUrl('/legal/imprint')}>{copy.imprint}</a></nav>
      </footer>
    </main>
    <a class="composer-link" href={appUrl('/#compose')} data-testid="landing-compose" aria-label={copy.tryFree}><span class="composer-ai" aria-hidden="true"></span><span>{copy.tryFree}</span><span class="composer-mic" aria-hidden="true"></span></a>
  </div>
</div>

<style>
  .landing-page { width: 100%; height: 100dvh; min-width: 0; overflow: hidden; display: flex; flex-direction: column; background: var(--color-grey-0); color: var(--color-font-primary); font-family: var(--font-primary); }
  a { color: inherit; text-decoration: none; }
  a:focus-visible, button:focus-visible { outline: 3px solid var(--color-primary-start); outline-offset: 3px; }
  .site-header { position: relative; z-index: 2; flex: 0 0 70px; width: 100%; padding: var(--spacing-4) var(--spacing-10); box-sizing: border-box; display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-8); }
  .wordmark { font-size: 1.25rem; font-weight: 800; letter-spacing: -0.04em; white-space: nowrap; }
  .wordmark span { color: var(--color-primary-start); }
  .workspace-nav { --icon-tab-width: 4.5rem; position: absolute; left: 50%; transform: translateX(-50%); display: flex; align-items: center; width: max-content; height: 2.8rem; overflow: hidden; border-radius: 3.25rem; background: var(--color-grey-10); filter: drop-shadow(0 .25rem .25rem color-mix(in srgb, var(--color-grey-100) 14%, transparent)); }
  .workspace-nav a { position: relative; display: inline-flex; align-items: center; justify-content: center; flex: 0 0 var(--icon-tab-width); width: var(--icon-tab-width); min-width: var(--icon-tab-width); height: 2.8rem; min-height: 2.8rem; box-sizing: border-box; padding: 0; background: transparent; cursor: pointer; }
  .workspace-nav a::before { content: ''; position: absolute; inset: 0; border-radius: 3.25rem; background: linear-gradient(135deg, color-mix(in srgb, var(--color-primary-start) 50%, transparent), color-mix(in srgb, var(--color-primary-end) 50%, transparent)); opacity: 0; transition: opacity .25s ease; }
  .workspace-nav a:hover::before, .workspace-nav a:focus-visible::before { opacity: 1; }
  .workspace-nav a:hover .header-mask, .workspace-nav a:focus-visible .header-mask { background: var(--color-font-button); }
  .header-actions { display: flex; align-items: center; gap: var(--spacing-8); }
  .header-icon { display: inline-grid; place-items: center; flex: 0 0 42px; width: 42px; height: 42px; border: 0; border-radius: var(--radius-full); background: transparent; color: var(--color-primary-start); cursor: pointer; }
  .language-button { display: inline-flex; gap: var(--spacing-2); width: auto; min-width: 52px; padding: 0 var(--spacing-4); font: inherit; font-size: var(--font-size-small); font-weight: 700; }
  .header-icon:hover { background: var(--color-grey-20); }
  .header-mask { position: relative; display: block; width: 20px; height: 20px; background: var(--color-grey-70); -webkit-mask: var(--icon-url) center / contain no-repeat; mask: var(--icon-url) center / contain no-repeat; transition: background-color .25s ease; }
  .chat-mask { --icon-url: url('/icons/chat.svg'); }.app-mask { --icon-url: url('/icons/app.svg'); }.workflow-mask { --icon-url: url('/icons/workflow.svg'); }.github-mask { --icon-url: url('/icons/github.svg'); }.language-mask { --icon-url: url('/icons/language.svg'); }
  .github-mask, .language-mask { background: var(--color-primary-start); }
  .header-link { display: inline-flex; align-items: center; justify-content: center; box-sizing: border-box; height: 41px; min-width: 0; max-width: 240px; overflow: hidden; margin: 0; padding: var(--spacing-4) var(--spacing-6); border-radius: var(--radius-3); background: var(--color-button-primary); color: var(--color-font-button); font-family: var(--button-font-family); font-size: var(--button-font-size); font-weight: var(--button-font-weight); box-shadow: 0 2px 8px color-mix(in srgb, var(--color-grey-100) 15%, transparent); white-space: nowrap; transition: all var(--duration-normal) var(--easing-default); }
  .header-link:hover { background: var(--color-button-primary-hover); transform: scale(1.02); }.header-link:active { background: var(--color-button-primary-pressed); transform: scale(.98); box-shadow: none; }.mobile-login { display: none; }
  .language-control { position: relative; }
  .language-panel { position: absolute; z-index: 10; inset-inline-end: 0; top: calc(100% + var(--spacing-4)); width: min(320px, calc(100vw - 24px)); max-height: min(70dvh, 560px); overflow: auto; padding: var(--spacing-10); box-sizing: border-box; border: 1px solid var(--color-grey-25); border-radius: var(--radius-5); background: var(--color-grey-0); box-shadow: var(--shadow-lg); }
  .language-heading { display: flex; align-items: center; justify-content: space-between; }.language-heading button { border: 0; background: transparent; color: var(--color-font-primary); font: inherit; font-size: 1.5rem; cursor: pointer; }
  .language-panel p { margin: var(--spacing-4) 0 var(--spacing-8); color: var(--color-font-tertiary); font-size: var(--font-size-small); line-height: 1.4; }
  .language-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--spacing-4); }
  .language-options button { min-width: 0; min-height: 40px; padding: var(--spacing-4); border: 1px solid var(--color-grey-30); border-radius: var(--radius-3); background: var(--color-grey-10); color: var(--color-font-primary); text-align: start; font: inherit; font-size: var(--font-size-small); cursor: pointer; }
  .language-options button:hover, .language-options button.selected { border-color: var(--color-primary-start); background: var(--color-grey-blue); }
  .viewport-container { position: relative; flex: 1; min-height: 0; margin: 0 var(--spacing-10) var(--spacing-10); overflow: hidden; border-radius: var(--radius-6); background: var(--color-grey-0); box-shadow: var(--shadow-md); }
  .scroll-container { width: 100%; height: 100%; overflow-x: hidden; overflow-y: auto; overscroll-behavior: contain; scroll-behavior: smooth; }
  .hero { position: relative; height: 100%; box-sizing: border-box; padding: var(--spacing-12) var(--spacing-16) 112px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--spacing-8); overflow: hidden; text-align: center; background: linear-gradient(135deg, var(--color-primary-start), var(--color-primary-end)); color: var(--color-font-button); }
  .hero-visual { position: relative; flex: 0 0 auto; width: min(720px, 75%, 55dvh); transform: translateY(var(--hero-parallax-y, 0px)); }
  .hero h1 { margin: 0; color: var(--color-font-button); font-size: clamp(2.25rem, 4vw, 3.75rem); line-height: 1.12; font-weight: 800; letter-spacing: -0.035em; }
  .prompt-bubble { position: relative; max-width: min(90%, 720px); margin: 0; padding: var(--spacing-6) var(--spacing-12); border-radius: var(--radius-5); background: var(--color-grey-blue); color: var(--color-font-primary); opacity: 1; font-size: clamp(1.125rem, 2vw, 1.75rem); font-weight: 700; box-shadow: var(--shadow-sm); transform-origin: right bottom; }
  .prompt-bubble.transitioning { animation: prompt-appear 420ms ease-out forwards; }
  .prompt-bubble::after { content: ''; position: absolute; inset-inline-end: -12px; bottom: 10px; width: 12px; height: 20px; background: var(--color-grey-blue); -webkit-mask: url('/icons/speechbubble.svg') center / contain no-repeat; mask: url('/icons/speechbubble.svg') center / contain no-repeat; transform: scaleX(-1); }
  @keyframes prompt-appear { from { opacity: 0; transform: scale(0.88); } to { opacity: 1; transform: scale(1); } }
  .hero-speed { margin: calc(-1 * var(--spacing-4)) 0 0; color: var(--color-font-button); font-size: var(--font-size-p); font-weight: 700; }
  .rail-window { --icon-size: clamp(74px, 7.2vw, 112px); --icon-gap: clamp(18px, 2vw, 30px); position: relative; flex: 0 0 calc(var(--icon-size) + 12px); width: 100%; overflow: hidden; -webkit-mask-image: linear-gradient(to right, transparent, var(--color-font-button) 9%, var(--color-font-button) 91%, transparent); mask-image: linear-gradient(to right, transparent, var(--color-font-button) 9%, var(--color-font-button) 91%, transparent); }
  .rail-track { position: absolute; inset-block: 0; left: 50%; display: flex; width: max-content; transform: translateX(calc(-25% - var(--icon-size) / 2)); }
  .rail-track.playing { animation: rail-loop var(--rail-duration) linear infinite; }
  .rail-group { display: flex; align-items: center; gap: var(--icon-gap); width: max-content; padding-inline-end: var(--icon-gap); }
  .rail-icon { display: inline-grid; place-items: center; flex: 0 0 var(--icon-size); width: var(--icon-size); height: var(--icon-size); border-radius: var(--radius-5); background: var(--rail-icon-bg); opacity: 0.42; transition: opacity var(--duration-normal) var(--easing-default), scale var(--duration-normal) var(--easing-default); }
  .rail-icon::before { content: ''; width: 53%; height: 53%; background: var(--color-font-button); -webkit-mask: var(--rail-icon-url) center / contain no-repeat; mask: var(--rail-icon-url) center / contain no-repeat; }
  .rail-icon.highlighted { opacity: 1; scale: 1.08; }
  @keyframes rail-loop { from { transform: translateX(calc(-25% - var(--icon-size) / 2)); } to { transform: translateX(calc(-75% - var(--icon-size) / 2)); } }
  .scroll-cue { display: inline-flex; align-items: center; justify-content: center; gap: var(--spacing-6); min-height: 32px; color: var(--color-font-button); font-size: var(--font-size-small); font-weight: 700; animation: cue-pulse 1.8s ease-in-out infinite alternate; }
  .cue-arrow { display: block; flex: 0 0 20px; width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
  @keyframes cue-pulse { from { opacity: .3; } to { opacity: .8; } }
  .composer-link { position: absolute; z-index: 5; left: 50%; bottom: max(var(--spacing-8), env(safe-area-inset-bottom)); transform: translateX(-50%); width: min(629px, calc(100% - 30px)); min-height: 64px; box-sizing: border-box; padding: 0 var(--spacing-12); display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-8); border-radius: 32px; background: var(--color-grey-blue); color: var(--color-font-primary); font-weight: 700; box-shadow: 0 4px 12px color-mix(in srgb, var(--color-grey-100) 8%, transparent); text-align: center; }
  .composer-link:hover { box-shadow: var(--shadow-lg); }
  .composer-ai, .composer-mic { display: block; flex: 0 0 24px; width: 24px; height: 24px; background: var(--color-grey-60); -webkit-mask: var(--composer-icon-url) center / contain no-repeat; mask: var(--composer-icon-url) center / contain no-repeat; }
  .composer-ai { --composer-icon-url: url('/icons/ai.svg'); }.composer-mic { --composer-icon-url: url('/icons/recordaudio.svg'); }
  .feature { max-width: 1320px; margin: 0 auto; padding: clamp(72px, 9vw, 150px) var(--spacing-24); }
  .feature-media { display: grid; grid-template-columns: minmax(280px, .85fr) minmax(0, 1.15fr); align-items: center; gap: clamp(32px, 6vw, 100px); }
  .feature-copy { max-width: 480px; }.feature-later .feature-copy { max-width: 580px; }
  .feature-icon { display: block; width: 48px; height: 48px; margin-bottom: var(--spacing-8); background: var(--color-primary-start); -webkit-mask: var(--feature-icon-url) center / 80% no-repeat; mask: var(--feature-icon-url) center / 80% no-repeat; }
  .search-icon { --feature-icon-url: url('/icons/search.svg'); }.security-icon { --feature-icon-url: url('/icons/security.svg'); }.workflow-icon { --feature-icon-url: url('/icons/workflow.svg'); }.devices-icon { --feature-icon-url: url('/icons/devices.svg'); }.coding-icon { --feature-icon-url: url('/icons/coding.svg'); }
  .feature h2, .publication-row h2 { margin: 0 0 var(--spacing-16); font-size: clamp(1.75rem, 2.6vw, 2.5rem); line-height: 1.24; letter-spacing: -0.025em; font-weight: 700; }
  .feature p { margin: 0 0 var(--spacing-12); font-size: var(--font-size-p); line-height: 1.6; }.feature-links { display: grid; gap: var(--spacing-4); }
  .text-link { display: inline-block; width: fit-content; font-size: var(--font-size-p); font-weight: 700; color: var(--color-primary-start); }.text-link::before { content: '› '; }
  .text-link:hover, .example-link:hover, .site-footer a:hover { text-decoration: underline; }
  .feature-example { min-width: 0; width: 100%; }.feature-later .feature-example { width: min(100%, 700px); }
  .example-link { display: block; width: fit-content; margin: var(--spacing-8) 0 0 auto; font-size: var(--font-size-small); font-weight: 700; }
  [data-reveal] { opacity: 1; transform: none; }:global(.reveal-ready:not(.revealed)) { opacity: 0; transform: translateY(24px); }:global(.reveal-ready) { transition: opacity 600ms ease, transform 600ms ease; }
  .publication-area { background: var(--color-grey-20); padding: var(--spacing-24) 0; }
  .publication-row { max-width: 1320px; margin: auto; padding: var(--spacing-16) var(--spacing-24); display: grid; grid-template-columns: minmax(240px, .75fr) minmax(0, 1.25fr); gap: var(--spacing-24); align-items: stretch; }
  .publication-row + .publication-row { border-top: 1px solid var(--color-grey-30); }.publication-row h2 { margin-bottom: var(--spacing-8); }
  .publication-intro p { margin: 0 0 var(--spacing-8); color: var(--color-font-tertiary); line-height: 1.5; }
  .publication-cards { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--spacing-8); }
  .event-cards { display: flex; gap: var(--spacing-8); min-width: 0; overflow-x: auto; scroll-snap-type: x proximity; padding: var(--spacing-2) var(--spacing-2) var(--spacing-8); }
  .event-cards .publication-card { flex: 0 0 clamp(250px, 24vw, 340px); scroll-snap-align: start; }
  .publication-card, .empty-publication { min-width: 0; overflow: hidden; border-radius: var(--radius-5); background: var(--color-grey-0); box-shadow: var(--shadow-sm); }.publication-card { display: flex; flex-direction: column; }.publication-card:hover, a.empty-publication:hover { box-shadow: var(--shadow-md); }
  .publication-card img { display: block; width: 100%; height: 150px; object-fit: cover; }.card-copy { padding: var(--spacing-10); }.card-label { color: var(--color-font-tertiary); font-size: var(--font-size-small); }
  .card-copy h3 { margin: var(--spacing-4) 0; font-size: var(--font-size-h3); line-height: 1.35; }.card-copy p { margin: var(--spacing-4) 0 0; color: var(--color-font-tertiary); font-size: var(--font-size-small); line-height: 1.5; }
  .empty-publication { display: flex; align-items: center; justify-content: space-between; min-height: 180px; margin: 0; padding: var(--spacing-16); color: var(--color-primary-start); font-weight: 700; }
  .site-footer { max-width: 1320px; margin: 0 auto 110px; padding: var(--spacing-16) var(--spacing-24); display: flex; justify-content: space-between; gap: var(--spacing-16); align-items: center; }.site-footer p { color: var(--color-font-tertiary); font-size: var(--font-size-small); }
  .site-footer nav { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--spacing-8); font-size: var(--font-size-small); color: var(--color-font-tertiary); }.social-links { display: flex; flex-wrap: wrap; gap: var(--spacing-4); }
  .social-links a { display: inline-grid; place-items: center; width: 38px; height: 38px; border-radius: var(--radius-full); background: var(--color-grey-20); }.social-links a:hover { background: var(--color-grey-blue); }.social-links img { display: block; width: 22px; height: 22px; }
  @media (min-width: 761px) and (max-height: 820px) { .hero { gap: var(--spacing-6); padding-bottom: 96px; }.hero-visual { width: min(720px, 75%, 45dvh); } }
  @media (max-width: 900px) { .wordmark { display: none; }.workspace-nav { position: static; transform: none; margin-right: auto; }.site-header { justify-content: flex-end; }.feature-media { grid-template-columns: 1fr; }.feature-copy, .feature-later .feature-copy { max-width: 680px; }.feature-example, .feature-later .feature-example { max-width: 700px; margin: 0 auto; } }
  @media (max-width: 760px) { .site-header { padding: var(--spacing-4); gap: var(--spacing-2); }.header-actions { gap: var(--spacing-4); }.github-link { display: none; }.workspace-nav { --icon-tab-width: clamp(3rem, calc(33.333vw - 58px), 4.5rem); }.desktop-login { display: none; }.mobile-login { display: inline; }.header-icon { flex-basis: 38px; width: 38px; height: 38px; }.language-button { flex-basis: auto; width: auto; }.viewport-container { margin: 0 var(--spacing-4) var(--spacing-4); }.hero { padding: var(--spacing-12) var(--spacing-8) 112px; gap: var(--spacing-6); }.hero-visual { width: min(480px, 94%, 35dvh); }.rail-window { --icon-size: clamp(64px, 15vw, 88px); --icon-gap: var(--spacing-8); }.feature { padding: var(--spacing-24) var(--spacing-8); gap: var(--spacing-16); }.feature h2 { margin-bottom: var(--spacing-12); }.publication-row { grid-template-columns: 1fr; gap: var(--spacing-12); padding: var(--spacing-16) var(--spacing-8); }.site-footer { flex-direction: column; align-items: flex-start; padding: var(--spacing-16) var(--spacing-8); }.site-footer nav { justify-content: flex-start; } }
  @media (max-width: 440px) { .hero h1 { font-size: 2rem; }.hero-visual { flex-basis: 150px; }.scroll-cue { font-size: var(--font-size-xs); gap: var(--spacing-4); }.publication-cards { grid-template-columns: 1fr; }.publication-card img { height: 170px; } }
  @media (prefers-reduced-motion: reduce) { .scroll-container { scroll-behavior: auto; }.rail-track, .scroll-cue, .prompt-bubble { animation: none !important; }.scroll-cue { opacity: .8; }.rail-icon, :global(.reveal-ready) { transition: none; }.hero-visual { transform: none; } }
</style>
