<script lang="ts">
  import { onMount } from 'svelte';
  import { landingAppExamples, type LandingPublication } from './landingPageContent';
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
  const orderedApps = publicApps;
  let activeIndex = $state(0);
  let activeApp = $derived(orderedApps[activeIndex] ?? orderedApps[0]);
  let promptHasChanged = $state(false);
  let reducedMotion = $state(false);
  let chosenLanguage = $state('en');
  let copy = $derived(landingCopy[chosenLanguage === 'de' ? 'de' : 'en']);
  let landingRoot: HTMLDivElement;
  let scrollContainer: HTMLElement;
  let railWindow: HTMLDivElement;
  let railTrack: HTMLDivElement;
  let selectApp = (_index: number) => {};

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
    let position = 0;
    let pitch = 1;
    let iconSize = 1;
    let target: number | null = null;
    let lastFrame = performance.now();
    let pauseUntil = 0;
    const automaticVelocity = 1 / promptIntervalMs;
    const momentumDecayMs = 550;
    const maxVelocity = 0.02;
    let velocity = automaticVelocity;
    let lastWheelTime = 0;
    let pointer: { id: number; x: number; y: number; position: number; dragging: boolean; lastX: number; lastTime: number; velocity: number } | null = null;
    let suppressClick = false;
    let observer: IntersectionObserver | undefined;
    const revealedSections = new WeakSet<HTMLElement>();
    const revealSection = (element: HTMLElement) => {
      revealedSections.add(element);
      element.classList.add('revealed');
      observer?.unobserve(element);
    };
    const revealVisibleSections = () => {
      const viewport = scrollContainer.getBoundingClientRect();
      for (const element of landingRoot.querySelectorAll<HTMLElement>('[data-reveal]')) {
        if (revealedSections.has(element)) continue;
        const box = element.getBoundingClientRect();
        const visibleHeight = Math.min(box.bottom, viewport.bottom) - Math.max(box.top, viewport.top);
        // Background tabs can miss observer notifications. User scrolling must never leave content hidden.
        if (visibleHeight >= Math.min(box.height, viewport.height) * 0.12 && visibleHeight > 0) revealSection(element);
      }
    };
    const scheduleFrame = () => {
      if (!frame && !document.hidden && (!reducedMotion || target !== null)) {
        lastFrame = performance.now();
        frame = requestAnimationFrame(tick);
      }
    };

    const modulo = (value: number) => ((value % orderedApps.length) + orderedApps.length) % orderedApps.length;
    const setActive = (index: number) => {
      if (index !== activeIndex) {
        activeIndex = index;
        promptHasChanged = true;
      }
    };
    const renderRail = () => {
      if (!orderedApps.length) return;
      if (target === null && (position >= orderedApps.length || position < 0)) position = modulo(position);
      // Group 1 is the canonical cycle; identical groups on either side cover the seam.
      const groupWidth = orderedApps.length * pitch;
      railTrack.style.transform = `translate3d(${-groupWidth - iconSize / 2 - position * pitch}px, 0, 0)`;
    };
    const measureRail = () => {
      const icons = railTrack.querySelectorAll<HTMLElement>('.rail-group:nth-child(2) .rail-icon');
      if (!icons.length) return;
      iconSize = parseFloat(getComputedStyle(icons[0]).width);
      railWindow.style.setProperty('--rail-corner-radius', `${Math.round(iconSize * 0.25)}px`);
      pitch = railTrack.querySelector<HTMLElement>('.rail-group')!.getBoundingClientRect().width / icons.length;
      renderRail();
    };
    selectApp = (index: number) => {
      if (!orderedApps.length) return;
      velocity = automaticVelocity;
      target = index + Math.round((position - index) / orderedApps.length) * orderedApps.length;
      setActive(index);
      if (reducedMotion) {
        position = target;
        target = null;
        renderRail();
      }
      pauseUntil = performance.now() + 2000;
      scheduleFrame();
    };
    const tick = (now: number) => {
      const elapsed = Math.min(now - lastFrame, 64);
      lastFrame = now;
      if (target !== null) {
        const distance = target - position;
        position += distance * Math.min(1, elapsed / 135);
        if (Math.abs(target - position) < 0.002) {
          position = target;
          target = null;
          pauseUntil = now + 2000;
        }
      } else if (!reducedMotion && !document.hidden && !pointer?.dragging && now >= pauseUntil) {
        // Integrate exponential friction so release momentum blends into the usual drift.
        const decay = Math.exp(-elapsed / momentumDecayMs);
        position += automaticVelocity * elapsed + (velocity - automaticVelocity) * momentumDecayMs * (1 - decay);
        velocity = automaticVelocity + (velocity - automaticVelocity) * decay;
        setActive(modulo(Math.round(position)));
      }
      renderRail();
      frame = 0;
      scheduleFrame();
    };
    const onWheel = (event: WheelEvent) => {
      const horizontal = event.shiftKey ? event.deltaY : event.deltaX;
      if (Math.abs(horizontal) <= Math.abs(event.shiftKey ? event.deltaX : event.deltaY)) return;
      event.preventDefault();
      target = null;
      const now = performance.now();
      const gap = now - lastWheelTime;
      const sample = Math.max(-maxVelocity, Math.min(maxVelocity, horizontal / pitch / (gap > 100 || !lastWheelTime ? 16 : Math.max(16, gap))));
      velocity = now - lastWheelTime > 100 ? sample : velocity * 0.35 + sample * 0.65;
      lastWheelTime = now;
      position += horizontal / pitch;
      setActive(modulo(Math.round(position)));
      pauseUntil = 0;
      renderRail();
      scheduleFrame();
    };
    const onPointerDown = (event: PointerEvent) => {
      if (event.button !== 0 || pointer) return;
      pointer = { id: event.pointerId, x: event.clientX, y: event.clientY, position, dragging: false, lastX: event.clientX, lastTime: performance.now(), velocity: 0 };
    };
    const onPointerMove = (event: PointerEvent) => {
      if (!pointer || event.pointerId !== pointer.id) return;
      const dx = event.clientX - pointer.x;
      const dy = event.clientY - pointer.y;
      if (!pointer.dragging && Math.abs(dx) > 8 && Math.abs(dx) > Math.abs(dy)) {
        pointer.dragging = true;
        railWindow.setPointerCapture(event.pointerId);
      }
      if (!pointer.dragging) return;
      target = null;
      const now = performance.now();
      const sample = Math.max(-maxVelocity, Math.min(maxVelocity, (pointer.lastX - event.clientX) / pitch / Math.max(1, now - pointer.lastTime)));
      pointer.velocity = pointer.velocity * 0.35 + sample * 0.65;
      pointer.lastX = event.clientX;
      pointer.lastTime = now;
      position = pointer.position - dx / pitch;
      setActive(modulo(Math.round(position)));
      pauseUntil = 0;
      renderRail();
    };
    const onPointerEnd = (event: PointerEvent) => {
      if (!pointer || event.pointerId !== pointer.id) return;
      if (pointer.dragging) {
        suppressClick = event.type === 'pointerup';
        if (suppressClick) window.setTimeout(() => { suppressClick = false; }, 0);
        velocity = event.type === 'pointerup' && performance.now() - pointer.lastTime < 120 ? pointer.velocity : automaticVelocity;
        pauseUntil = 0;
        if (railWindow.hasPointerCapture(event.pointerId)) railWindow.releasePointerCapture(event.pointerId);
      }
      pointer = null;
      scheduleFrame();
    };
    const onClickCapture = (event: MouseEvent) => {
      if (!suppressClick) return;
      event.preventDefault();
      event.stopPropagation();
      suppressClick = false;
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      const index = modulo(activeIndex + (event.key === 'ArrowRight' ? 1 : -1));
      selectApp(index);
      railTrack.querySelectorAll<HTMLButtonElement>('.rail-group:nth-child(2) .rail-icon')[index]?.focus({ preventScroll: true });
    };
    const onScroll = () => {
      revealVisibleSections();
      if (reducedMotion) return;
      landingRoot.style.setProperty('--hero-parallax-y', `${Math.min(scrollContainer.scrollTop * 0.12, 48)}px`);
    };
    const updateMotion = () => {
      reducedMotion = motionQuery.matches;
      velocity = automaticVelocity;
      if (reducedMotion && target !== null) {
        position = target;
        target = null;
        renderRail();
      }
      scheduleFrame();
      observer?.disconnect();
      const sections = landingRoot.querySelectorAll<HTMLElement>('[data-reveal]');
      sections.forEach((element) => {
        element.classList.remove('reveal-ready');
        element.classList.toggle('revealed', revealedSections.has(element));
      });
      if (!reducedMotion && 'IntersectionObserver' in window) {
        observer = new IntersectionObserver((entries) => {
          for (const entry of entries) if (entry.isIntersecting) {
            revealSection(entry.target as HTMLElement);
          }
        }, { root: scrollContainer, threshold: 0.12 });
        sections.forEach((element) => {
          element.classList.add('reveal-ready');
          if (!revealedSections.has(element)) observer?.observe(element);
        });
      }
      revealVisibleSections();
    };
    motionQuery.addEventListener('change', updateMotion);
    scrollContainer.addEventListener('scroll', onScroll, { passive: true });
    railWindow.addEventListener('wheel', onWheel, { passive: false });
    railWindow.addEventListener('pointerdown', onPointerDown);
    railWindow.addEventListener('pointermove', onPointerMove);
    railWindow.addEventListener('pointerup', onPointerEnd);
    railWindow.addEventListener('pointercancel', onPointerEnd);
    window.addEventListener('pointerup', onPointerEnd);
    window.addEventListener('pointercancel', onPointerEnd);
    railWindow.addEventListener('click', onClickCapture, true);
    railWindow.addEventListener('keydown', onKeyDown);
    const onVisibilityChange = () => {
      if (document.hidden) {
        cancelAnimationFrame(frame);
        frame = 0;
      } else {
        velocity = automaticVelocity;
        pointer = null;
        updateMotion();
      }
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    window.addEventListener('focus', revealVisibleSections);
    window.addEventListener('pageshow', revealVisibleSections);
    const resizeObserver = new ResizeObserver(() => { measureRail(); revealVisibleSections(); });
    resizeObserver.observe(railWindow);
    measureRail();
    updateMotion();
    return () => {
      cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      observer?.disconnect();
      motionQuery.removeEventListener('change', updateMotion);
      scrollContainer.removeEventListener('scroll', onScroll);
      railWindow.removeEventListener('wheel', onWheel);
      railWindow.removeEventListener('pointerdown', onPointerDown);
      railWindow.removeEventListener('pointermove', onPointerMove);
      railWindow.removeEventListener('pointerup', onPointerEnd);
      railWindow.removeEventListener('pointercancel', onPointerEnd);
      window.removeEventListener('pointerup', onPointerEnd);
      window.removeEventListener('pointercancel', onPointerEnd);
      railWindow.removeEventListener('click', onClickCapture, true);
      railWindow.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      window.removeEventListener('focus', revealVisibleSections);
      window.removeEventListener('pageshow', revealVisibleSections);
    };
  });
</script>

<div class="landing-page" bind:this={landingRoot} data-testid="landing-page" lang={chosenLanguage === 'de' ? 'de' : 'en'}>
  <PublicSiteHeader {appBaseUrl} {websiteBaseUrl} language={chosenLanguage} onLanguageChange={selectLanguage} />

  <div class="viewport-container" data-testid="landing-viewport-container">
    <main class="scroll-container" bind:this={scrollContainer} data-testid="landing-scroll-container">
      <section class="hero" aria-labelledby="hero-title" data-testid="landing-hero">
        <div class="hero-visual" data-testid="landing-hero-media">
          <div class="hero-ai-visual" aria-hidden="true" data-testid="landing-hero-ai-icon"><span class="hero-ai-glyph"></span></div>
        </div>
        <h1 id="hero-title">{copy.heroLine1}<br />{copy.heroLine2}</h1>
        {#if activeApp}
          {#key activeApp.id}
            {#if landingAppExamples[activeApp.id]}
              <a class="prompt-bubble" class:transitioning={promptHasChanged} href={appUrl(`/#chat-id=${encodeURIComponent(landingAppExamples[activeApp.id])}`)} target="_blank" rel="noopener noreferrer" data-testid="landing-prompt" data-active-app={activeApp.id} aria-live="polite">{chosenLanguage === 'de' ? activeApp.promptDe : activeApp.promptEn}</a>
            {:else}
              <p class="prompt-bubble" class:transitioning={promptHasChanged} data-testid="landing-prompt" data-active-app={activeApp.id} aria-live="polite">{chosenLanguage === 'de' ? activeApp.promptDe : activeApp.promptEn}</p>
            {/if}
          {/key}
        {/if}
        <p class="hero-speed" data-testid="landing-hero-speed">{copy.inSeconds}</p>
        <div class="rail-window" bind:this={railWindow} data-testid="landing-app-rail" data-active-app={activeApp?.id} role="toolbar" aria-label="OpenMates apps" tabindex="0">
          <div class="rail-track" bind:this={railTrack}>
            {#each [0, 1, 2] as group (group)}
              <div class="rail-group" data-testid="landing-rail-group" aria-hidden={group === 1 ? undefined : 'true'}>
                {#each orderedApps as app, index (app.id)}
                  <button type="button" class="rail-icon" class:highlighted={activeApp?.id === app.id} onclick={() => selectApp(index)} tabindex={group === 1 && activeApp?.id === app.id ? 0 : -1} aria-label={`Show ${app.id} example`} aria-pressed={group === 1 ? activeApp?.id === app.id : undefined} data-app-id={app.id} style={`--rail-icon-bg:${app.gradient};--rail-icon-url:url('${app.iconUrl}')`}><span class="rail-glyph" aria-hidden="true"></span></button>
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

      <div id="testflight-signup" class="newsletter-reveal" data-testid="landing-newsletter-reveal" data-reveal><NewsletterSignup {apiBaseUrl} {websiteBaseUrl} language={chosenLanguage === 'de' ? 'de' : 'en'} /></div>

      <div class="publication-area">
        <section class="publication-row" aria-labelledby="events-title" data-testid="landing-events" data-reveal>
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
        <section class="publication-row" aria-labelledby="news-title" data-testid="landing-news" data-reveal>
          <div class="publication-intro"><h2 id="news-title">{copy.newsTitle}</h2><p>{copy.newsBody}</p><a class="text-link" href={siteUrl('/news')}>{copy.newsBrowse}</a></div>
          {#if news.length}<div class="publication-cards">{#each news.slice(0, 2) as item (item.id)}<a class="publication-card" href={item.href}>{#if item.image}<img src={proxyImage(item.image, 640)} alt="" loading="lazy" />{/if}<div class="card-copy">{#if item.label}<span class="card-label">{item.label}</span>{/if}<h3>{item.title}</h3>{#if item.description}<p>{item.description}</p>{/if}</div></a>{/each}</div>{:else}<a class="empty-publication" href={siteUrl('/news')}>{copy.newsEmpty} ↗</a>{/if}
        </section>
        <section class="publication-row" aria-labelledby="blog-title" data-testid="landing-blog" data-reveal>
          <div class="publication-intro"><h2 id="blog-title">{copy.blogTitle}</h2><p>{copy.blogBody}</p><a class="text-link" href={siteUrl('/blog')}>{copy.blogBrowse}</a></div>
          {#if posts.length}<div class="publication-cards">{#each posts.slice(0, 2) as item (item.id)}<a class="publication-card" href={item.href}>{#if item.image}<img src={proxyImage(item.image, 640)} alt="" loading="lazy" />{/if}<div class="card-copy">{#if item.label}<span class="card-label">{item.label}</span>{/if}<h3>{item.title}</h3>{#if item.description}<p>{item.description}</p>{/if}</div></a>{/each}</div>{:else}<a class="empty-publication" href={siteUrl('/blog')}>{copy.blogEmpty} ↗</a>{/if}
        </section>
      </div>

      <footer class="site-footer">
        <div><a class="wordmark" href={siteUrl('/')}><span>Open</span>Mates</a><p>{copy.social}</p><div class="social-links">{#each socialLinks as social (social.label)}<a href={social.href} target="_blank" rel="noopener noreferrer" aria-label={social.label}><span class="social-icon" aria-hidden="true" style={`--social-icon-url:url('${social.iconUrl}')`}></span></a>{/each}</div></div>
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
  .hero { position: relative; height: 100%; box-sizing: border-box; padding: 0 var(--spacing-16) 90px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--spacing-4); overflow: hidden; text-align: center; background: linear-gradient(135deg, var(--color-primary-start), var(--color-primary-end)); color: var(--color-font-button); }
  .hero-visual { position: relative; flex: 1 1 0; min-height: 0; max-height: clamp(116px, 23dvh, 240px); width: 100%; display: grid; place-items: end center; container-type: size; transform: translateY(var(--hero-parallax-y, 0px)); }
  .hero-ai-visual { position: relative; display: grid; place-items: center; width: min(100cqh, clamp(116px, 30cqh, 230px)); aspect-ratio: 1; animation: hero-ai-float 8s ease-in-out infinite alternate; }
  .hero-ai-visual::before { content: ''; position: absolute; inset: 4%; border-radius: var(--radius-full); background: radial-gradient(circle at 35% 35%, var(--color-font-button), transparent 70%); filter: blur(32px); opacity: .24; animation: hero-ai-glow 12s ease-in-out infinite alternate; }
  .hero-ai-glyph { position: relative; display: block; width: 72%; height: 72%; background: var(--color-font-button); -webkit-mask: url('/icons/ai.svg') center / contain no-repeat; mask: url('/icons/ai.svg') center / contain no-repeat; filter: drop-shadow(0 8px 20px color-mix(in srgb, var(--color-grey-100) 18%, transparent)); }
  @keyframes hero-ai-float { from { transform: translateY(4px); } to { transform: translateY(-8px); } }
  @keyframes hero-ai-glow { from { opacity: .15; transform: translate(-5%, 3%) scale(.9); } to { opacity: .3; transform: translate(6%, -3%) scale(1.12); } }
  .hero h1 { margin: 0; color: var(--color-font-button); font-size: clamp(2.25rem, 4vw, 3.75rem); line-height: 1.12; font-weight: 800; letter-spacing: -0.035em; }
  .prompt-bubble { position: relative; display: block; max-width: min(90%, 720px); margin: 0; padding: var(--spacing-6) var(--spacing-12); border-radius: var(--radius-5); background: var(--color-grey-blue); color: var(--color-font-primary); opacity: 1; font-size: clamp(1.125rem, 2vw, 1.75rem); font-weight: 700; box-shadow: var(--shadow-sm); transform-origin: right bottom; }
  .prompt-bubble.transitioning { animation: prompt-appear 420ms ease-out forwards; }
  .prompt-bubble::after { content: ''; position: absolute; inset-inline-end: -12px; bottom: 10px; width: 12px; height: 20px; background: var(--color-grey-blue); -webkit-mask: url('/icons/speechbubble.svg') center / contain no-repeat; mask: url('/icons/speechbubble.svg') center / contain no-repeat; transform: scaleX(-1); }
  @keyframes prompt-appear { from { opacity: 0; transform: scale(0.88); } to { opacity: 1; transform: scale(1); } }
  .hero-speed { margin: 0; color: var(--color-font-button); font-size: var(--font-size-p); font-weight: 700; }
  .rail-window { --icon-size: clamp(74px, 6.5vw, 96px); --icon-gap: clamp(18px, 2vw, 30px); position: relative; flex: 0 0 calc(var(--icon-size) + 12px); width: 100%; overflow: hidden; touch-action: pan-y; cursor: grab; -webkit-mask-image: linear-gradient(to right, transparent, var(--color-font-button) 9%, var(--color-font-button) 91%, transparent); mask-image: linear-gradient(to right, transparent, var(--color-font-button) 9%, var(--color-font-button) 91%, transparent); }
  .rail-window:active { cursor: grabbing; }
  .rail-track { position: absolute; inset-block: 0; left: 50%; display: flex; width: max-content; will-change: transform; }
  .rail-group { display: flex; align-items: center; gap: var(--icon-gap); width: max-content; padding-inline-end: var(--icon-gap); }
  .rail-icon { display: inline-grid; place-items: center; flex: 0 0 var(--icon-size); width: var(--icon-size); min-width: 0; max-width: var(--icon-size); height: var(--icon-size); margin: 0; padding: 0; border: 0; border-radius: var(--rail-corner-radius, 25%); background: var(--rail-icon-bg); filter: none; opacity: 0.42; cursor: pointer; transition: opacity var(--duration-normal) var(--easing-default), scale var(--duration-normal) var(--easing-default); }
  .rail-icon:hover, .rail-icon:active { background: var(--rail-icon-bg); filter: none; }
  .rail-glyph { display: block; width: calc(var(--icon-size) * 0.53); height: calc(var(--icon-size) * 0.53); background: var(--color-font-button); -webkit-mask: var(--rail-icon-url) center / contain no-repeat; mask: var(--rail-icon-url) center / contain no-repeat; }
  .rail-icon.highlighted, .rail-icon:hover, .rail-icon:focus-visible { opacity: 1; scale: 1.08; }
  .rail-window:focus-visible .rail-icon.highlighted, .rail-icon:focus-visible { outline: 3px solid var(--color-font-button); outline-offset: 3px; }
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
  .feature-example { min-width: 0; width: 100%; }
  @media (min-width: 901px) { .feature-example :global(.device-screenshots) { width: 118%; } }
  .example-link { display: block; width: fit-content; margin: var(--spacing-8) 0 0 auto; font-size: var(--font-size-small); font-weight: 700; }
  :global(.reveal-ready) .feature-icon, :global(.reveal-ready) .feature-copy h2, :global(.reveal-ready) .feature-copy p, :global(.reveal-ready) .feature-copy .text-link, :global(.reveal-ready) .feature-example { transition: opacity 700ms cubic-bezier(.2, .75, .25, 1), transform 700ms cubic-bezier(.2, .75, .25, 1); }
  :global(.reveal-ready) .feature-copy p, :global(.reveal-ready) .feature-copy .text-link { transition-delay: 90ms; }
  :global(.reveal-ready) .feature-example { transition-delay: 180ms; }
  :global(.reveal-ready:not(.revealed)) .feature-icon, :global(.reveal-ready:not(.revealed)) .feature-copy h2, :global(.reveal-ready:not(.revealed)) .feature-copy p, :global(.reveal-ready:not(.revealed)) .feature-copy .text-link { opacity: 0; transform: translateY(18px); }
  :global(.reveal-ready:not(.revealed)) .feature-example { opacity: 0; transform: translateY(22px) scale(.975); }
  :global(.newsletter-reveal.reveal-ready) { transition: opacity 700ms cubic-bezier(.2, .75, .25, 1), transform 700ms cubic-bezier(.2, .75, .25, 1); }
  :global(.newsletter-reveal.reveal-ready:not(.revealed)) { opacity: 0; transform: translateY(18px); }
  :global(.publication-row.reveal-ready) .publication-intro, :global(.publication-row.reveal-ready) .event-cards, :global(.publication-row.reveal-ready) .publication-cards, :global(.publication-row.reveal-ready) .empty-publication { transition: opacity 700ms cubic-bezier(.2, .75, .25, 1), transform 700ms cubic-bezier(.2, .75, .25, 1); }
  :global(.publication-row.reveal-ready) .event-cards, :global(.publication-row.reveal-ready) .publication-cards, :global(.publication-row.reveal-ready) .empty-publication { transition-delay: 130ms; }
  :global(.publication-row.reveal-ready:not(.revealed)) .publication-intro { opacity: 0; transform: translateY(18px); }
  :global(.publication-row.reveal-ready:not(.revealed)) .event-cards, :global(.publication-row.reveal-ready:not(.revealed)) .publication-cards, :global(.publication-row.reveal-ready:not(.revealed)) .empty-publication { opacity: 0; transform: translateY(22px) scale(.985); }
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
  .social-links a { display: inline-grid; place-items: center; width: 38px; height: 38px; border-radius: var(--radius-full); background: var(--color-grey-20); }.social-links a:hover { background: var(--color-grey-blue); }.social-icon { display: block; width: 22px; height: 22px; background: var(--color-grey-80); mask: var(--social-icon-url) center / contain no-repeat; -webkit-mask: var(--social-icon-url) center / contain no-repeat; }
  @media (max-width: 900px) { .feature-media { grid-template-columns: 1fr; }.feature-copy, .feature-later .feature-copy { max-width: 680px; }.feature-example, .feature-later .feature-example { width: 100%; margin: 0 auto; } }
  @media (max-width: 760px) { .viewport-container { margin: 0 var(--spacing-4) var(--spacing-4); }.hero { padding: var(--spacing-4) var(--spacing-8) 90px; gap: var(--spacing-2); justify-content: center; }.hero-visual { flex: 0 1 auto; width: min(130px, 34vw, 26dvh); container-type: normal; }.hero-ai-visual { width: 100%; }.rail-window { --icon-size: clamp(64px, 15vw, 88px); --icon-gap: var(--spacing-8); }.feature { min-height: 100%; padding: var(--spacing-20) var(--spacing-8); gap: var(--spacing-16); }.feature h2 { margin-bottom: var(--spacing-12); }.publication-row { grid-template-columns: 1fr; gap: var(--spacing-12); padding: var(--spacing-16) var(--spacing-8); }.site-footer { flex-direction: column; align-items: flex-start; padding: var(--spacing-16) var(--spacing-8); }.site-footer nav { justify-content: flex-start; } }
  @media (max-width: 440px) { .hero h1 { font-size: 2rem; }.scroll-cue { font-size: var(--font-size-xs); gap: var(--spacing-4); }.publication-cards { grid-template-columns: 1fr; }.publication-card img { height: 170px; } }
  @media (prefers-reduced-motion: reduce) { .scroll-container { scroll-behavior: auto; }.rail-track, .scroll-cue, .prompt-bubble, .hero-ai-visual, .hero-ai-visual::before { animation: none !important; }.scroll-cue { opacity: .8; }.rail-icon, :global(.reveal-ready) .feature-icon, :global(.reveal-ready) .feature-copy h2, :global(.reveal-ready) .feature-copy p, :global(.reveal-ready) .feature-copy .text-link, :global(.reveal-ready) .feature-example, :global(.newsletter-reveal.reveal-ready), :global(.publication-row.reveal-ready) .publication-intro, :global(.publication-row.reveal-ready) .event-cards, :global(.publication-row.reveal-ready) .publication-cards, :global(.publication-row.reveal-ready) .empty-publication { transition: none !important; }.hero-visual { transform: none; } }
</style>
