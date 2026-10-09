<script lang="ts">
  import { onMount } from 'svelte';
  import { landingAppOrder, landingAppExamples, type LandingPublication } from './landingPageContent';
  import DeviceScreenshots from '../DeviceScreenshots.svelte';
  import NewsletterSignup from '../NewsletterSignup.svelte';
  import PublicSiteHeader from './PublicSiteHeader.svelte';
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
  const orderedApps = landingAppOrder.map((id) => publicApps.find((app) => app.id === id)).filter((app): app is (typeof publicApps)[number] => !!app);
  const firstVisibleIndex = 0;
  let activeIndex = $state(firstVisibleIndex);
  let activeApp = $derived(orderedApps[activeIndex] ?? orderedApps[0]);
  let promptHasChanged = $state(false);
  let railPlaying = $state(false);
  let reducedMotion = $state(false);
  let chosenLanguage = $state('en');
  let copy = $derived(landingCopy[chosenLanguage === 'de' ? 'de' : 'en']);
  let landingRoot: HTMLDivElement;
  let scrollContainer: HTMLElement;

  function selectLanguage(code: string): void {
    chosenLanguage = code;
    try { localStorage.setItem('preferredLanguage', code); } catch { /* Storage can be disabled. */ }
    document.documentElement.lang = code === 'de' ? 'de' : 'en';
    document.documentElement.dir = 'ltr';
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
      if (!railPlaying || orderedApps.length === 0) return;
      const nextIndex = (firstVisibleIndex + Math.floor((now - startedAt) / promptIntervalMs)) % orderedApps.length;
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
      railPlaying = !reducedMotion && orderedApps.length > 0;
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
    motionQuery.addEventListener('change', updateMotion);
    scrollContainer.addEventListener('scroll', onScroll, { passive: true });
    updateMotion();
    return () => {
      cancelAnimationFrame(frame);
      observer?.disconnect();
      motionQuery.removeEventListener('change', updateMotion);
      scrollContainer.removeEventListener('scroll', onScroll);
    };
  });
</script>

<div class="landing-page" bind:this={landingRoot} data-testid="landing-page" lang={chosenLanguage === 'de' ? 'de' : 'en'}>
  <PublicSiteHeader {appBaseUrl} {websiteBaseUrl} language={chosenLanguage} onLanguageChange={selectLanguage} />

  <div class="viewport-container" data-testid="landing-viewport-container">
    <main class="scroll-container" bind:this={scrollContainer} data-testid="landing-scroll-container">
      <section class="hero" aria-labelledby="hero-title" data-testid="landing-hero">
        <div class="hero-visual" data-testid="landing-hero-media">
          <div class="hero-device-scale"><DeviceScreenshots baseKey="hero" desktopAlt="OpenMates web app chat workspace" mobileAlt="OpenMates mobile web chat workspace" eager hero /></div>
        </div>
        <h1 id="hero-title">{copy.heroLine1}<br />{copy.heroLine2}</h1>
        {#if activeApp}
          {#key activeApp.id}
            {#if landingAppExamples[activeApp.id]}
              <a class="prompt-bubble" class:transitioning={promptHasChanged} href={appUrl(`/#chat-id=${encodeURIComponent(landingAppExamples[activeApp.id])}`)} target="_blank" rel="noopener noreferrer" data-testid="landing-prompt" data-active-app={activeApp.id} aria-live="polite">{chosenLanguage === 'de' ? activeApp.promptDe : activeApp.promptEn} ↗</a>
            {:else}
              <p class="prompt-bubble" class:transitioning={promptHasChanged} data-testid="landing-prompt" data-active-app={activeApp.id} aria-live="polite">{chosenLanguage === 'de' ? activeApp.promptDe : activeApp.promptEn}</p>
            {/if}
          {/key}
        {/if}
        <p class="hero-speed" data-testid="landing-hero-speed">{copy.inSeconds}</p>
        <div class="rail-window" data-testid="landing-app-rail" data-active-app={activeApp?.id} aria-label="OpenMates apps">
          <div class="rail-track" class:playing={railPlaying} style={`--rail-duration:${Math.max(orderedApps.length, 1) * promptIntervalMs}ms`}>
            {#each [0, 1, 2] as group (group)}
              <div class="rail-group" data-testid="landing-rail-group" aria-hidden={group === 1 ? undefined : 'true'}>
                {#each orderedApps as app (app.id)}
                  <a class="rail-icon" class:highlighted={activeApp?.id === app.id} href={appUrl(`/#apps/${app.id}`)} target="_blank" rel="noopener noreferrer" tabindex={group === 1 ? undefined : -1} aria-label={`${app.id} app`} data-app-id={app.id} style={`--rail-icon-bg:${app.gradient};--rail-icon-url:url('${app.iconUrl}')`}></a>
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

      <section class="feature feature-media" id="model-choice" aria-labelledby="model-choice-title" data-testid="landing-feature-model-choice" data-reveal>
        <div class="feature-copy">
          <span class="feature-icon coding-icon" aria-hidden="true" data-testid="landing-feature-icon"></span>
          <h2 id="model-choice-title">{copy.modelChoiceTitle1}<br />{copy.modelChoiceTitle2}</h2>
          <p>{copy.modelChoiceBody}</p>
        </div>
        <div class="feature-example" data-testid="landing-feature-media-model-choice"><DeviceScreenshots baseKey="model-selector" desktopAlt="OpenMates AI model selector on desktop" mobileAlt="OpenMates AI model selector on mobile" /></div>
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
        <div><a class="wordmark" href={siteUrl('/')}><span>Open</span>Mates</a><p>{copy.social}</p><div class="social-links">{#each socialLinks as social (social.label)}<a href={social.href} target="_blank" rel="noopener noreferrer" aria-label={social.label}><img src={social.iconUrl} alt="" width="22" height="22" /></a>{/each}</div></div>
        <nav aria-label="Footer navigation"><a href={siteUrl('/legal/privacy')}>{copy.privacy}</a><a href={siteUrl('/legal/terms')}>{copy.terms}</a><a href={siteUrl('/legal/imprint')}>{copy.imprint}</a></nav>
      </footer>
    </main>
    <a class="composer-link" href={appUrl('/#compose')} data-testid="landing-compose" aria-label={copy.tryFree}><span class="composer-ai" aria-hidden="true"></span><span>{copy.tryFree}</span><span class="composer-mic" aria-hidden="true"></span></a>
  </div>
</div>

<style>
  .landing-page { width: 100%; height: 100dvh; min-width: 0; overflow: hidden; display: flex; flex-direction: column; background: var(--color-grey-0); color: var(--color-font-primary); font-family: var(--font-primary); }
  a { color: inherit; text-decoration: none; }
  a:focus-visible { outline: 3px solid var(--color-primary-start); outline-offset: 3px; }
  .viewport-container { position: relative; flex: 1; min-height: 0; margin: 0 var(--spacing-10) var(--spacing-10); overflow: hidden; border-radius: var(--radius-6); background: var(--color-grey-0); box-shadow: var(--shadow-md); }
  .scroll-container { width: 100%; height: 100%; overflow-x: hidden; overflow-y: auto; overscroll-behavior: contain; scroll-behavior: smooth; }
  .hero { position: relative; height: 100%; box-sizing: border-box; padding: 0 var(--spacing-16) 90px; display: flex; flex-direction: column; align-items: center; justify-content: flex-start; gap: var(--spacing-4); overflow: hidden; text-align: center; background: linear-gradient(135deg, var(--color-primary-start), var(--color-primary-end)); color: var(--color-font-button); }
  .hero-visual { position: relative; flex: 1 1 0; min-height: 0; width: 100%; display: grid; place-items: center; container-type: size; transform: translateY(var(--hero-parallax-y, 0px)); }
  .hero-device-scale { width: min(100%, 170cqh, 1040px); }
  .hero h1 { margin: 0; color: var(--color-font-button); font-size: clamp(2.25rem, 4vw, 3.75rem); line-height: 1.12; font-weight: 800; letter-spacing: -0.035em; }
  .prompt-bubble { position: relative; display: block; max-width: min(90%, 720px); margin: 0; padding: var(--spacing-6) var(--spacing-12); border-radius: var(--radius-5); background: var(--color-grey-blue); color: var(--color-font-primary); opacity: 1; font-size: clamp(1.125rem, 2vw, 1.75rem); font-weight: 700; box-shadow: var(--shadow-sm); transform-origin: right bottom; }
  .prompt-bubble.transitioning { animation: prompt-appear 420ms ease-out forwards; }
  .prompt-bubble::after { content: ''; position: absolute; inset-inline-end: -12px; bottom: 10px; width: 12px; height: 20px; background: var(--color-grey-blue); -webkit-mask: url('/icons/speechbubble.svg') center / contain no-repeat; mask: url('/icons/speechbubble.svg') center / contain no-repeat; transform: scaleX(-1); }
  @keyframes prompt-appear { from { opacity: 0; transform: scale(0.88); } to { opacity: 1; transform: scale(1); } }
  .hero-speed { margin: 0; color: var(--color-font-button); font-size: var(--font-size-p); font-weight: 700; }
  .rail-window { --icon-size: clamp(74px, 6.5vw, 96px); --icon-gap: clamp(18px, 2vw, 30px); position: relative; flex: 0 0 calc(var(--icon-size) + 12px); width: 100%; overflow: hidden; -webkit-mask-image: linear-gradient(to right, transparent, var(--color-font-button) 9%, var(--color-font-button) 91%, transparent); mask-image: linear-gradient(to right, transparent, var(--color-font-button) 9%, var(--color-font-button) 91%, transparent); }
  .rail-track { position: absolute; inset-block: 0; left: 50%; display: flex; width: max-content; transform: translateX(calc(-33.333333333% - var(--icon-size) / 2 + min(8vw, 110px))); }
  .rail-track.playing { animation: rail-loop var(--rail-duration) linear infinite; }
  .rail-group { display: flex; align-items: center; gap: var(--icon-gap); width: max-content; padding-inline-end: var(--icon-gap); }
  .rail-icon { display: inline-grid; place-items: center; flex: 0 0 var(--icon-size); width: var(--icon-size); height: var(--icon-size); border-radius: 34%; background: var(--rail-icon-bg); opacity: 0.42; transition: opacity var(--duration-normal) var(--easing-default), scale var(--duration-normal) var(--easing-default); }
  .rail-icon::before { content: ''; width: 53%; height: 53%; background: var(--color-font-button); -webkit-mask: var(--rail-icon-url) center / contain no-repeat; mask: var(--rail-icon-url) center / contain no-repeat; }
  .rail-icon.highlighted, .rail-icon:hover, .rail-icon:focus-visible { opacity: 1; scale: 1.08; }
  @keyframes rail-loop { from { transform: translateX(calc(-33.333333333% - var(--icon-size) / 2 + min(8vw, 110px))); } to { transform: translateX(calc(-66.666666667% - var(--icon-size) / 2 + min(8vw, 110px))); } }
  .scroll-cue { display: inline-flex; align-items: center; justify-content: center; gap: var(--spacing-6); min-height: 32px; color: var(--color-font-button); font-size: var(--font-size-small); font-weight: 700; animation: cue-pulse 1.8s ease-in-out infinite alternate; }
  .cue-arrow { display: block; flex: 0 0 20px; width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
  @keyframes cue-pulse { from { opacity: .3; } to { opacity: .8; } }
  .composer-link { position: absolute; z-index: 5; left: 50%; bottom: max(var(--spacing-8), env(safe-area-inset-bottom)); transform: translateX(-50%); width: min(629px, calc(100% - 30px)); min-height: 64px; box-sizing: border-box; padding: 0 var(--spacing-12); display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-8); border-radius: 32px; background: var(--color-grey-blue); color: var(--color-font-primary); font-weight: 700; box-shadow: 0 4px 12px color-mix(in srgb, var(--color-grey-100) 8%, transparent); text-align: center; }
  .composer-link:hover { box-shadow: var(--shadow-lg); }
  .composer-ai, .composer-mic { display: block; flex: 0 0 24px; width: 24px; height: 24px; background: var(--color-grey-60); -webkit-mask: var(--composer-icon-url) center / contain no-repeat; mask: var(--composer-icon-url) center / contain no-repeat; }
  .composer-ai { --composer-icon-url: url('/icons/ai.svg'); }.composer-mic { --composer-icon-url: url('/icons/recordaudio.svg'); }
  .feature { min-height: 100%; width: 100%; margin: 0 auto; padding: clamp(48px, 5vw, 96px) clamp(32px, 6vw, 112px); box-sizing: border-box; overflow: hidden; }
  .feature-media { display: grid; grid-template-columns: minmax(280px, .72fr) minmax(0, 1.28fr); align-items: center; gap: clamp(28px, 4vw, 76px); }
  .feature-copy { max-width: 480px; }.feature-later .feature-copy { max-width: 580px; }
  .feature-icon { display: block; width: 48px; height: 48px; margin-bottom: var(--spacing-8); background: var(--color-primary-start); -webkit-mask: var(--feature-icon-url) center / 80% no-repeat; mask: var(--feature-icon-url) center / 80% no-repeat; }
  .search-icon { --feature-icon-url: url('/icons/search.svg'); }.security-icon { --feature-icon-url: url('/icons/security.svg'); }.workflow-icon { --feature-icon-url: url('/icons/workflow.svg'); }.devices-icon { --feature-icon-url: url('/icons/devices.svg'); }.coding-icon { --feature-icon-url: url('/icons/coding.svg'); }
  .feature h2, .publication-row h2 { margin: 0 0 var(--spacing-16); font-size: clamp(1.75rem, 2.6vw, 2.5rem); line-height: 1.24; letter-spacing: -0.025em; font-weight: 700; }
  .feature p { margin: 0 0 var(--spacing-12); font-size: var(--font-size-p); line-height: 1.6; }.feature-links { display: grid; gap: var(--spacing-4); }
  .text-link { display: inline-block; width: fit-content; font-size: var(--font-size-p); font-weight: 700; color: var(--color-primary-start); }.text-link::before { content: '› '; }
  .text-link:hover, .example-link:hover, .site-footer a:hover { text-decoration: underline; }
  .feature-example { min-width: 0; width: 118%; }.feature-later .feature-example { width: 118%; }
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
  .site-footer .wordmark { font-size: 1.25rem; font-weight: 800; letter-spacing: -0.04em; white-space: nowrap; }.site-footer .wordmark span { color: var(--color-primary-start); }
  .site-footer nav { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--spacing-8); font-size: var(--font-size-small); color: var(--color-font-tertiary); }.social-links { display: flex; flex-wrap: wrap; gap: var(--spacing-4); }
  .social-links a { display: inline-grid; place-items: center; width: 38px; height: 38px; border-radius: var(--radius-full); background: var(--color-grey-20); }.social-links a:hover { background: var(--color-grey-blue); }.social-links img { display: block; width: 22px; height: 22px; }
  @media (max-width: 900px) { .feature-media { grid-template-columns: 1fr; }.feature-copy, .feature-later .feature-copy { max-width: 680px; }.feature-example, .feature-later .feature-example { width: 100%; margin: 0 auto; } }
  @media (max-width: 760px) { .viewport-container { margin: 0 var(--spacing-4) var(--spacing-4); }.hero { padding: var(--spacing-4) var(--spacing-8) 90px; gap: var(--spacing-2); justify-content: center; }.hero-visual { flex: 0 1 auto; width: min(130px, 34vw, 26dvh); container-type: normal; }.hero-device-scale { width: 100%; }.rail-window { --icon-size: clamp(64px, 15vw, 88px); --icon-gap: var(--spacing-8); }.feature { min-height: 100%; padding: var(--spacing-20) var(--spacing-8); gap: var(--spacing-16); }.feature h2 { margin-bottom: var(--spacing-12); }.publication-row { grid-template-columns: 1fr; gap: var(--spacing-12); padding: var(--spacing-16) var(--spacing-8); }.site-footer { flex-direction: column; align-items: flex-start; padding: var(--spacing-16) var(--spacing-8); }.site-footer nav { justify-content: flex-start; } }
  @media (max-width: 440px) { .hero h1 { font-size: 2rem; }.scroll-cue { font-size: var(--font-size-xs); gap: var(--spacing-4); }.publication-cards { grid-template-columns: 1fr; }.publication-card img { height: 170px; } }
  @media (prefers-reduced-motion: reduce) { .scroll-container { scroll-behavior: auto; }.rail-track, .scroll-cue, .prompt-bubble { animation: none !important; }.scroll-cue { opacity: .8; }.rail-icon, :global(.reveal-ready) { transition: none; }.hero-visual { transform: none; } }
</style>
