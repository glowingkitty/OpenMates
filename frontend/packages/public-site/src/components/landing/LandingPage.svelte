<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { fade } from 'svelte/transition';
  import LandingFeatureAnimation from './LandingFeatureAnimation.svelte';
  import LandingNativeIcon from './LandingNativeIcon.svelte';
  import { landingAppExamples, landingSectionExamples, landingDeviceMedia, type LandingPublication } from './landingPageContent';
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
    serverStatusUrl?: string;
    events?: LandingPublication[];
    news?: LandingPublication[];
    posts?: LandingPublication[];
  }

  let { appBaseUrl, websiteBaseUrl, apiBaseUrl, serverStatusUrl, events = [], news = [], posts = [] }: Props = $props();
  const appUrl = (path: string) => `${appBaseUrl.replace(/\/$/, '')}${path}`;
  const siteUrl = (path: string) => `${websiteBaseUrl.replace(/\/$/, '')}${path}`;

  const promptIntervalMs = 3400;
  const orderedApps = publicApps;
  let activeIndex = $state(0);
  let activeApp = $derived(orderedApps[activeIndex] ?? orderedApps[0]);
  let promptHasChanged = $state(false);
  let heroEntranceComplete = $state(false);
  let reducedMotion = $state(false);
  let chosenLanguage = $state('en');
  let freeUsageAvailable = $state<boolean | null>(null);
  let copy = $derived(landingCopy[chosenLanguage === 'de' ? 'de' : 'en']);
  let composerAlternative = $state(false);
  let touchDevice = $state(false);
  let composerLabel = $derived(composerAlternative ? (touchDevice ? copy.askAnythingTouch : copy.askAnythingDesktop) : (freeUsageAvailable ? copy.tryFree : copy.tryNow));
  const storySections = ['actionable', 'privacy', 'model-choice', 'workflows', 'devices', 'open-source'] as const;
  type StorySection = typeof storySections[number];
  type StoryState = 'pending' | 'playing' | 'finishing' | 'complete';
  const isCustomStory = (section: StorySection): section is 'actionable' | 'privacy' => section === 'actionable' || section === 'privacy';
  let storyStates = $state<Record<StorySection, StoryState>>(Object.fromEntries(storySections.map(section => [section, 'pending'])) as Record<StorySection, StoryState>);
  let activeStory = $state<StorySection | null>(null);
  let pageVisible = $state(true);
  const introElapsed: Partial<Record<StorySection, number>> = {};
  let showSectionNavigation = $state(false);
  let hasNextSection = $state(true);
  let navigateSection = (_direction: number) => {};
  let scrollToSection = (_id: string) => {};
  const storyTransitionTimers = new Map<StorySection, number>();
  function finishStory(section: StorySection): void {
    if (storyStates[section] === 'complete' || storyStates[section] === 'finishing') return;
    if (reducedMotion) { storyStates[section] = 'complete'; return; }
    storyStates[section] = 'finishing';
    // Fade the full-width demonstration before changing to the device layout.
    storyTransitionTimers.set(section, window.setTimeout(() => { storyTransitionTimers.delete(section); storyStates[section] = 'complete'; }, 220));
  }
  async function replayStory(section: StorySection): Promise<void> {
    if (reducedMotion) return;
    const finishing = storyTransitionTimers.get(section);
    if (finishing !== undefined) window.clearTimeout(finishing);
    storyTransitionTimers.delete(section);
    introElapsed[section] = 0;
    storyStates[section] = 'playing';
    await tick();
    scrollToSection(section);
  }

  // Future custom stories can replace this quiet title-only introduction.
  // Count visible time only, so scrolling away never consumes another section.
  $effect(() => {
    const section = activeStory;
    if (!section || isCustomStory(section) || reducedMotion || !pageVisible || storyStates[section] !== 'playing') return;
    let elapsed = introElapsed[section] ?? 0;
    let previous = performance.now();
    let frame = 0;
    const advance = (now: number) => {
      elapsed += Math.min(100, Math.max(0, now - previous));
      previous = now;
      introElapsed[section] = elapsed;
      if (elapsed >= 1400) finishStory(section);
      else frame = requestAnimationFrame(advance);
    };
    frame = requestAnimationFrame(advance);
    return () => cancelAnimationFrame(frame);
  });

  type Feature = { id: StorySection; title1: string; title2: string; body: string; icon: string; baseKey?: string; desktopAlt?: string; mobileAlt?: string; exampleChatId?: string; mediaPath?: string };
  let features = $derived<Feature[]>([
    { id: 'actionable', title1: copy.actionableTitle1, title2: copy.actionableTitle2, body: copy.actionableBody, icon: 'search', baseKey: 'events', desktopAlt: 'OpenMates web chat searching for AI events in Berlin', mobileAlt: 'OpenMates mobile view of an events chat', exampleChatId: landingSectionExamples.actionable },
    { id: 'privacy', title1: copy.privacyTitle1, title2: copy.privacyTitle2, body: copy.privacyBody, icon: 'security', baseKey: 'privacy', desktopAlt: 'OpenMates highlighting sensitive data before sending a message', mobileAlt: 'OpenMates mobile chat highlighting personal data', exampleChatId: landingSectionExamples.privacy },
    { id: 'model-choice', title1: copy.modelChoiceTitle1, title2: copy.modelChoiceTitle2, body: copy.modelChoiceBody, icon: 'coding', baseKey: 'model-selector', desktopAlt: 'OpenMates AI model selector on desktop', mobileAlt: 'OpenMates AI model selector on mobile', exampleChatId: landingSectionExamples['model-choice'] },
    { id: 'workflows', title1: copy.workflowTitle1, title2: copy.workflowTitle2, body: copy.workflowBody, icon: 'workflow', baseKey: 'workflows', desktopAlt: 'OpenMates workflow editor on desktop', mobileAlt: 'OpenMates workflow editor on mobile', exampleChatId: landingSectionExamples.workflows, mediaPath: '/#workflows' },
    { id: 'devices', title1: copy.devicesTitle1, title2: copy.devicesTitle2, body: copy.devicesBody, icon: 'devices', baseKey: 'devices', desktopAlt: 'OpenMates train connections example on desktop', mobileAlt: 'OpenMates train connections example on mobile', exampleChatId: landingSectionExamples.devices },
    { id: 'open-source', title1: copy.sourceTitle1, title2: copy.sourceTitle2, body: copy.sourceBody, icon: 'coding' },
  ]);

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

  // Use the public server status, without importing the app's account or chat services.
  onMount(() => {
    const controller = new AbortController();
    let disposed = false;
    const timeout = window.setTimeout(() => controller.abort(), 4000);
    void (async () => {
      let available = false;
      try {
        const response = await fetch(serverStatusUrl ?? `${apiBaseUrl.replace(/\/$/, '')}/v1/settings/server-status`, {
          cache: 'no-store', credentials: 'omit', signal: controller.signal,
        });
        if (response.ok) {
          const status = await response.json();
          const usage = status?.anonymous_free_usage;
          available = usage?.active === true && usage?.can_send_text !== false;
        }
      } catch { /* Unavailable status must never advertise free testing. */ }
      finally {
        window.clearTimeout(timeout);
        if (!disposed) freeUsageAvailable = available;
      }
    })();
    return () => { disposed = true; window.clearTimeout(timeout); controller.abort(); };
  });

  onMount(() => {
    let storedLanguage: string | null = null;
    try { storedLanguage = localStorage.getItem('preferredLanguage'); } catch { /* Storage can be disabled. */ }
    if (storedLanguage && supportedLanguages.some((item) => item.code === storedLanguage)) chosenLanguage = storedLanguage;
    document.documentElement.lang = chosenLanguage === 'de' ? 'de' : 'en';
    document.documentElement.dir = 'ltr';

    touchDevice = window.matchMedia('(pointer: coarse)').matches || navigator.maxTouchPoints > 0;
    // Section navigation is local UI state. Consume incoming public anchors once,
    // and never persist a reading position in the address bar or restore it on reload.
    const previousRestoration = history.scrollRestoration;
    history.scrollRestoration = 'manual';
    const incomingSection = window.location.hash.slice(1);
    const navigation = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined;
    const isReload = navigation?.type === 'reload';
    if (incomingSection) history.replaceState(history.state, '', window.location.pathname + window.location.search);
    scrollContainer.scrollTop = 0;
    const sectionTargets = () => [...scrollContainer.querySelectorAll<HTMLElement>('.hero, .feature, .newsletter-reveal, .publication-row, .site-footer')];
    let sectionIndex = 0;
    const sectionTop = (element: HTMLElement) => element.getBoundingClientRect().top - scrollContainer.getBoundingClientRect().top + scrollContainer.scrollTop;
    const updateSectionState = () => {
      const sections = sectionTargets();
      const viewport = scrollContainer.getBoundingClientRect();
      const readingLine = viewport.top + viewport.height * .4;
      sectionIndex = Math.max(0, sections.findLastIndex(section => section.getBoundingClientRect().top <= readingLine));
      showSectionNavigation = scrollContainer.scrollTop >= sections[0].offsetHeight - 8;
      hasNextSection = sectionIndex < sections.length - 1;
      const selected = sections[sectionIndex];
      const key = selected?.id;
      activeStory = storySections.includes(key as StorySection) ? key as StorySection : null;
      if (activeStory && storyStates[activeStory] === 'pending') storyStates[activeStory] = 'playing';
    };
    const moveTo = (element: HTMLElement) => scrollContainer.scrollTo({ top: sectionTop(element), behavior: reducedMotion ? 'auto' : 'smooth' });
    navigateSection = direction => {
      const sections = sectionTargets();
      moveTo(sections[Math.min(sections.length - 1, Math.max(0, sectionIndex + direction))]);
    };
    scrollToSection = id => {
      const section = sectionTargets().find(section => section.id === id || (id === 'newsletter' && section.id === 'testflight-signup'));
      if (section) moveTo(section);
    };
    const initialFrame = requestAnimationFrame(() => {
      // Explicit newsletter entry links work on first arrival, then disappear
      // from the URL. Reloading this page always starts at the hero.
      if (!isReload && ['newsletter', 'testflight-signup'].includes(incomingSection)) scrollToSection(incomingSection);
      else scrollContainer.scrollTop = 0;
      updateSectionState();
    });

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
    let progressionSource: 'automatic' | 'manual-momentum' = 'automatic';
    let lastWheelTime = 0;
    let pointer: { id: number; x: number; y: number; position: number; dragging: boolean; lastX: number; lastTime: number; velocity: number } | null = null;
    let suppressClick = false;
    let appChangeCount = 0;
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
    const scheduleFrame = (continuing = false) => {
      if (!frame && !document.hidden && (!reducedMotion || target !== null)) {
        // RAF timestamps describe frame start, which can precede performance.now() under load.
        // Preserve that clock between frames; reset only when starting or resuming the loop.
        if (!continuing) lastFrame = performance.now();
        frame = requestAnimationFrame(tick);
      }
    };

    const modulo = (value: number) => ((value % orderedApps.length) + orderedApps.length) % orderedApps.length;
    const setActive = (index: number, automatic: boolean) => {
      if (index !== activeIndex) {
        activeIndex = index;
        promptHasChanged = true;
        if (automatic) {
          appChangeCount += 1;
          if (appChangeCount % 3 === 0) composerAlternative = !composerAlternative;
        }
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
      progressionSource = 'automatic';
      target = index + Math.round((position - index) / orderedApps.length) * orderedApps.length;
      setActive(index, false);
      if (reducedMotion) {
        position = target;
        target = null;
        renderRail();
      }
      pauseUntil = performance.now() + 2000;
      scheduleFrame();
    };
    const tick = (now: number) => {
      const elapsed = Math.max(0, Math.min(now - lastFrame, 64));
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
        // Manual momentum must finish blending before index changes can count
        // toward the composer prompt. Treat drift within 1% as fully settled.
        if (progressionSource === 'manual-momentum' && Math.abs(velocity - automaticVelocity) <= automaticVelocity * 0.01) {
          velocity = automaticVelocity;
          progressionSource = 'automatic';
        }
        // Integrate exponential friction so release momentum blends into the usual drift.
        const decay = Math.exp(-elapsed / momentumDecayMs);
        position += automaticVelocity * elapsed + (velocity - automaticVelocity) * momentumDecayMs * (1 - decay);
        velocity = automaticVelocity + (velocity - automaticVelocity) * decay;
        setActive(modulo(Math.round(position)), progressionSource === 'automatic');
      }
      renderRail();
      frame = 0;
      scheduleFrame(true);
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
      progressionSource = 'manual-momentum';
      setActive(modulo(Math.round(position)), false);
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
      progressionSource = 'manual-momentum';
      setActive(modulo(Math.round(position)), false);
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
      updateSectionState();
    };
    const updateMotion = () => {
      reducedMotion = motionQuery.matches;
      if (reducedMotion) for (const section of storySections) storyStates[section] = 'complete';
      velocity = automaticVelocity;
      progressionSource = 'automatic';
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
    const suspendRendering = () => {
      cancelAnimationFrame(frame);
      frame = 0;
      if (pointer && railWindow.hasPointerCapture(pointer.id)) railWindow.releasePointerCapture(pointer.id);
      pointer = null;
    };
    const resumeRendering = () => {
      if (document.hidden) return;
      // A suspended page can retain a RAF id whose callback will never run.
      suspendRendering();
      heroEntranceComplete = true;
      velocity = automaticVelocity;
      progressionSource = 'automatic';
      target = null;
      pauseUntil = 0;
      measureRail();
      updateMotion();
    };
    const onVisibilityChange = () => {
      pageVisible = !document.hidden;
      if (document.hidden) suspendRendering();
      else resumeRendering();
    };
    pageVisible = !document.hidden;
    document.addEventListener('visibilitychange', onVisibilityChange);
    window.addEventListener('focus', resumeRendering);
    window.addEventListener('pageshow', resumeRendering);
    window.addEventListener('pagehide', suspendRendering);
    const resizeObserver = new ResizeObserver(() => { measureRail(); revealVisibleSections(); updateSectionState(); });
    resizeObserver.observe(railWindow);
    resizeObserver.observe(scrollContainer);
    scrollContainer.querySelectorAll<HTMLElement>('.hero, .feature, .newsletter-reveal, .publication-row').forEach(section => resizeObserver.observe(section));
    updateSectionState();
    measureRail();
    updateMotion();
    return () => {
      cancelAnimationFrame(frame);
      cancelAnimationFrame(initialFrame);
      storyTransitionTimers.forEach(timer => window.clearTimeout(timer));
      history.scrollRestoration = previousRestoration;
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
      window.removeEventListener('focus', resumeRendering);
      window.removeEventListener('pageshow', resumeRendering);
      window.removeEventListener('pagehide', suspendRendering);
    };
  });
</script>

<div class="landing-page" class:hero-entrance-complete={heroEntranceComplete} bind:this={landingRoot} data-testid="landing-page" lang={chosenLanguage === 'de' ? 'de' : 'en'}>
  <PublicSiteHeader {appBaseUrl} {websiteBaseUrl} language={chosenLanguage} onLanguageChange={selectLanguage} />

  <div class="viewport-container" data-testid="landing-viewport-container">
    <main class="scroll-container" bind:this={scrollContainer} data-testid="landing-scroll-container">
      <section class="hero" aria-labelledby="hero-title" data-testid="landing-hero">
        <div class="hero-visual" data-testid="landing-hero-media">
          <div class="hero-ai-entrance"><div class="hero-ai-visual" aria-hidden="true" data-testid="landing-hero-ai-icon"><span class="hero-ai-glyph"><LandingNativeIcon name="ai" /></span></div></div>
        </div>
        <h1 id="hero-title">{copy.heroLine1}<br />{copy.heroLine2}</h1>
        <div class="hero-prompt-entrance">
          {#if activeApp}
            {#key activeApp.id}
              {#if landingAppExamples[activeApp.id]}
                <a class="prompt-bubble" class:transitioning={promptHasChanged} href={appUrl(`/#chat-id=${encodeURIComponent(landingAppExamples[activeApp.id])}`)} target="_blank" rel="noopener noreferrer" data-testid="landing-prompt" data-active-app={activeApp.id} aria-live="polite">{chosenLanguage === 'de' ? activeApp.promptDe : activeApp.promptEn}</a>
              {:else}
                <p class="prompt-bubble" class:transitioning={promptHasChanged} data-testid="landing-prompt" data-active-app={activeApp.id} aria-live="polite">{chosenLanguage === 'de' ? activeApp.promptDe : activeApp.promptEn}</p>
              {/if}
            {/key}
          {/if}
        </div>
        <p class="hero-speed" data-testid="landing-hero-speed">{copy.inSeconds}</p>
        <div class="rail-window" bind:this={railWindow} data-testid="landing-app-rail" data-active-app={activeApp?.id} role="toolbar" aria-label="OpenMates apps" tabindex="0">
          <div class="rail-track" bind:this={railTrack}>
            {#each [0, 1, 2] as group (group)}
              <div class="rail-group" data-testid="landing-rail-group" aria-hidden={group === 1 ? undefined : 'true'}>
                {#each orderedApps as app, index (app.id)}
                  <button type="button" class="rail-icon" class:highlighted={activeApp?.id === app.id} onclick={() => selectApp(index)} tabindex={group === 1 && activeApp?.id === app.id ? 0 : -1} aria-label={`Show ${app.id} example`} aria-pressed={group === 1 ? activeApp?.id === app.id : undefined} data-app-id={app.id} style={`--rail-icon-bg:${app.gradient}`}><img class="rail-glyph" src={app.iconUrl} alt="" aria-hidden="true" draggable="false" loading="eager" /></button>
                {/each}
              </div>
            {/each}
          </div>
        </div>
        <a class="scroll-cue" href="#actionable" onclick={(event) => { event.preventDefault(); scrollToSection('actionable'); }} data-testid="landing-scroll-cue"><span class="scroll-cue-content"><svg class="cue-arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg><span>{copy.scroll}</span><svg class="cue-arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg></span></a>
      </section>

      {#each features as feature (feature.id)}
        <section class="feature feature-media" class:feature-later={feature.id === 'devices' || feature.id === 'open-source'} class:story-demonstration={isCustomStory(feature.id)} class:story-playing={storyStates[feature.id] !== 'complete'} class:story-finishing={storyStates[feature.id] === 'finishing'} data-story-state={storyStates[feature.id]} id={feature.id} aria-labelledby={`${feature.id}-title`} data-testid={`landing-feature-${feature.id}`} data-reveal>
          <div class="feature-copy">
            <span class={`feature-icon ${feature.icon}-icon`} aria-hidden="true" data-testid="landing-feature-icon"></span>
            <h2 id={`${feature.id}-title`}>{feature.title1}<br />{feature.title2}</h2>
            {#if storyStates[feature.id] === 'complete'}
              <div class="story-copy" in:fade={{ duration: reducedMotion ? 0 : 360 }}>
                <p>{feature.body}</p>
                {#if feature.id === 'actionable'}
                  <a class="text-link" href={appUrl('/#apps')} target="_blank" rel="noopener noreferrer" data-testid="landing-explore-apps">{copy.exploreApps}</a>
                {:else if feature.id === 'privacy'}
                  <div class="feature-links"><a class="text-link" href={siteUrl('/blog')}>{copy.privacyLink}</a><a class="text-link" href={siteUrl('/blog')}>{copy.safetyLink}</a></div>
                {:else if feature.id === 'model-choice'}
                  <div class="feature-links"><a class="text-link" href={siteUrl('/blog')} data-testid="landing-model-selection-link">{copy.modelSelectionLink}</a><a class="text-link" href={siteUrl('/blog')} data-testid="landing-data-ownership-link">{copy.dataOwnershipLink}</a></div>
                {:else if feature.id === 'workflows'}
                  <a class="text-link" href={appUrl('/#workflows')} target="_blank" rel="noopener noreferrer" data-testid="landing-explore-workflows">{copy.exploreWorkflows}</a>
                {:else if feature.id === 'devices'}
                  <div class="feature-links"><a class="text-link" href={appUrl('/')}>{copy.startWebApp}</a><a class="text-link" href="#testflight-signup" onclick={(event) => { event.preventDefault(); scrollToSection('testflight-signup'); }}>{copy.testflight}</a><a class="text-link" href={siteUrl('/blog')}>{copy.developers}</a></div>
                {:else}
                  <div class="feature-links"><a class="text-link" href={siteUrl('/blog')}>{copy.ethics}</a><a class="text-link" href={siteUrl('/blog')}>{copy.selfHosting}</a></div>
                {/if}
              </div>
            {:else}
              <button class="skip-animation" type="button" onclick={() => finishStory(feature.id)} data-testid={`landing-skip-${feature.id}`}>{copy.skipAnimation}</button>
            {/if}
          </div>
          {#if storyStates[feature.id] === 'complete' || isCustomStory(feature.id)}
            <div class="story-surface">
              {#if storyStates[feature.id] === 'complete'}
                <div class="feature-example" in:fade={{ duration: reducedMotion ? 0 : 400, delay: reducedMotion ? 0 : 180 }} data-testid={`landing-feature-media-${feature.id}`}>
                  {#if feature.id === 'open-source'}
                    <a class="source-github" href="https://github.com/glowingkitty/OpenMates" target="_blank" rel="noopener noreferrer" aria-label="OpenMates on GitHub" data-testid="landing-source-github"><svg aria-hidden="true" viewBox="0 0 48 48"><path d="M24 0c-3.152 0-6.273.623-9.184 1.833a23.995 23.995 0 00-7.787 5.22A24.126 24.126 0 000 24.084c0 10.645 6.888 19.677 16.416 22.88 1.2.192 1.584-.554 1.584-1.205v-4.07c-6.648 1.445-8.064-3.227-8.064-3.227-1.104-2.793-2.664-3.54-2.664-3.54-2.184-1.493.168-1.445.168-1.445 2.4.169 3.672 2.48 3.672 2.48 2.088 3.661 5.616 2.577 6.984 2 .216-1.566.84-2.626 1.512-3.228-5.328-.602-10.92-2.673-10.92-11.849 0-2.673.912-4.816 2.472-6.526-.24-.602-1.08-3.107.24-6.358 0 0 2.016-.65 6.6 2.456 1.896-.53 3.96-.795 6-.795s4.104.265 6 .795c4.584-3.107 6.6-2.456 6.6-2.456 1.32 3.25.48 5.756.24 6.358 1.56 1.71 2.472 3.853 2.472 6.526 0 9.2-5.616 11.223-10.968 11.825.864.747 1.656 2.216 1.656 4.456v6.599c0 .65.384 1.42 1.608 1.204C41.136 43.736 48 34.728 48 24.083c0-3.162-.62-6.294-1.827-9.216a24.09 24.09 0 00-5.202-7.813 23.995 23.995 0 00-7.787-5.22A23.928 23.928 0 0024 0z" fill="currentColor" /></svg></a>
                  {:else if feature.baseKey && (feature.exampleChatId || feature.mediaPath)}
                    <DeviceScreenshots baseKey={feature.baseKey} desktopAlt={feature.desktopAlt ?? ''} mobileAlt={feature.mobileAlt ?? ''} href={feature.mediaPath ? appUrl(feature.mediaPath) : appUrl(`/#chat-id=${encodeURIComponent(feature.exampleChatId ?? '')}`)} linkLabel={`${feature.exampleChatId ? copy.openExample : copy.exploreWorkflows}: ${feature.title1} ${feature.title2}`} watchSrc={feature.id === 'devices' ? landingDeviceMedia.devicesWatch : undefined} watchAlt="The OpenMates train connections example on Apple Watch" />
                  {/if}
                  <div class="feature-actions">
                    {#if !reducedMotion}<button class="replay-animation" type="button" onclick={() => replayStory(feature.id)} data-testid={`landing-replay-${feature.id}`}>{copy.replayAnimation}</button>{/if}
                    {#if feature.exampleChatId}<a class="example-link" target="_blank" rel="noopener noreferrer" href={appUrl(`/#chat-id=${encodeURIComponent(feature.exampleChatId)}`)} data-testid={`landing-open-example-${feature.id}`}>{copy.openExample}</a>{/if}
                  </div>
                </div>
              {:else if isCustomStory(feature.id)}
                <div class="story-stage" out:fade={{ duration: reducedMotion ? 0 : 240 }}><LandingFeatureAnimation section={feature.id} active={activeStory === feature.id && storyStates[feature.id] === 'playing'} language={chosenLanguage} onComplete={() => finishStory(feature.id)} /></div>
              {/if}
            </div>
          {/if}
        </section>
      {/each}

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
    {#if showSectionNavigation}
      <button class="section-nav section-nav-previous" type="button" aria-label={copy.previousSection} onclick={() => navigateSection(-1)} data-testid="landing-previous-section"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 14 6-6 6 6" /></svg></button>
      {#if hasNextSection}<button class="section-nav section-nav-next" type="button" aria-label={copy.nextSection} onclick={() => navigateSection(1)} data-testid="landing-next-section"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 10 6 6 6-6" /></svg></button>{/if}
    {/if}
    {#if freeUsageAvailable !== null}
      <a class="composer-link" href={appUrl(freeUsageAvailable ? '/#compose' : '/#signup/basics')} data-testid="landing-compose" aria-label={composerLabel}><span class="composer-ai" aria-hidden="true"><LandingNativeIcon name="ai" /></span><span class="composer-label" data-testid="landing-compose-label" aria-live="polite">{#key composerLabel}<span class="composer-label-text">{composerLabel}</span>{/key}</span><span class="composer-mic" aria-hidden="true"><LandingNativeIcon name="microphone" gradient /></span></a>
    {/if}
  </div>
</div>

<style>
  .landing-page { width: 100%; height: 100dvh; min-width: 0; overflow: hidden; display: flex; flex-direction: column; background: var(--color-grey-0); color: var(--color-font-primary); font-family: var(--font-primary); }
  a { color: inherit; text-decoration: none; }
  a:focus-visible { outline: 3px solid var(--color-primary-start); outline-offset: 3px; }
  .viewport-container { position: relative; flex: 1; min-height: 0; container-type: size; margin: 0 var(--spacing-10) var(--spacing-10); overflow: hidden; border-radius: var(--radius-6); background: var(--color-grey-0); box-shadow: var(--shadow-md); }
  .scroll-container { width: 100%; height: 100%; overflow-x: hidden; overflow-y: auto; overscroll-behavior-y: auto; scroll-behavior: auto; scroll-snap-type: none; -webkit-overflow-scrolling: touch; scroll-padding-bottom: 156px; }
  /* Width and height both constrain the composition: tall tablets can grow while short laptops still fit. */
  .hero { --hero-ai-size: clamp(64px, min(24cqw, 16cqh), 256px); position: relative; height: 100%; box-sizing: border-box; padding: 12px clamp(12px, 2cqw, 32px) 100px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: clamp(8px, min(2cqw, 1.4cqh), 18px); overflow: hidden; text-align: center; background: linear-gradient(135deg, var(--color-primary-start), var(--color-primary-end)); color: var(--color-font-button); }
  .hero > * { flex-shrink: 0; }
  .hero-visual { position: relative; width: var(--hero-ai-size); height: var(--hero-ai-size); display: grid; place-items: center;  }
  .hero-ai-entrance { width: 100%; height: 100%; display: grid; place-items: center; animation: hero-entrance 620ms cubic-bezier(.22, 1, .36, 1) both; }
  .hero-ai-visual { position: relative; display: grid; place-items: center; width: 100%; aspect-ratio: 1; animation: hero-ai-float 8s ease-in-out infinite alternate; }
  .hero-ai-visual::before { content: ''; position: absolute; inset: 4%; border-radius: var(--radius-full); background: radial-gradient(circle at 35% 35%, var(--color-font-button), transparent 70%); filter: blur(32px); opacity: .24; animation: hero-ai-glow 12s ease-in-out infinite alternate; }
  .hero-ai-glyph { position: relative; display: block; width: 72%; height: 72%; color: var(--color-font-button); filter: drop-shadow(0 8px 20px color-mix(in srgb, var(--color-grey-100) 18%, transparent)); }
  @keyframes hero-ai-float { from { transform: translateY(4px); } to { transform: translateY(-8px); } }
  @keyframes hero-ai-glow { from { opacity: .15; transform: translate(-5%, 3%) scale(.9); } to { opacity: .3; transform: translate(6%, -3%) scale(1.12); } }
  .hero h1 { animation: hero-entrance 620ms 100ms cubic-bezier(.22, 1, .36, 1) both; margin: 0; color: var(--color-font-button); max-width: 100%; font-size: clamp(28px, min(8.5cqw, 8.2cqh), 112px); line-height: 1.12; font-weight: 800; letter-spacing: -0.035em; }
  .hero-prompt-entrance { display: flex; justify-content: center; width: 100%; min-width: 0; animation: hero-entrance 570ms 440ms cubic-bezier(.22, 1, .36, 1) both; }
  .prompt-bubble { position: relative; display: block; max-width: min(90%, 720px); margin: 0; padding: clamp(8px, min(1.6cqw, 1.6cqh), 16px) clamp(16px, min(3cqw, 3cqh), 32px); border-radius: var(--radius-5); background: var(--color-grey-blue); color: var(--color-font-primary); opacity: 1; font-size: clamp(18px, min(4cqw, 4.3cqh), 40px); line-height: 1.35; font-weight: 700; box-shadow: var(--shadow-sm); transform-origin: right bottom; }
  .prompt-bubble.transitioning { animation: prompt-appear 420ms ease-out forwards; }
  .prompt-bubble::after { content: ''; position: absolute; inset-inline-end: -12px; bottom: 10px; width: 12px; height: 20px; background: var(--color-grey-blue); -webkit-mask: url('/icons/speechbubble.svg') center / contain no-repeat; mask: url('/icons/speechbubble.svg') center / contain no-repeat; transform: scaleX(-1); }
  @keyframes prompt-appear { from { opacity: 0; transform: scale(0.88); } to { opacity: 1; transform: scale(1); } }
  .hero-speed { animation: hero-entrance 570ms 520ms cubic-bezier(.22, 1, .36, 1) both; margin: 0; color: var(--color-font-button); font-size: clamp(16px, min(3cqw, 3cqh), 28px); line-height: 1.3; font-weight: 700; }
  .rail-window { animation: hero-entrance 620ms 480ms cubic-bezier(.22, 1, .36, 1) both; --icon-size: clamp(56px, min(18cqw, 16cqh), 176px); --icon-gap: clamp(16px, 3cqw, 40px); position: relative; flex: 0 0 calc(var(--icon-size) * 1.08 + 12px); width: 100%; overflow: hidden; touch-action: pan-y; cursor: grab; -webkit-mask-image: linear-gradient(to right, transparent, var(--color-font-button) 9%, var(--color-font-button) 91%, transparent); mask-image: linear-gradient(to right, transparent, var(--color-font-button) 9%, var(--color-font-button) 91%, transparent); }
  .rail-window:active { cursor: grabbing; }
  .rail-track { position: absolute; inset-block: 0; left: 50%; display: flex; width: max-content; will-change: transform; }
  .rail-group { display: flex; align-items: center; gap: var(--icon-gap); width: max-content; padding-inline-end: var(--icon-gap); }
  .rail-icon { display: inline-grid; place-items: center; flex: 0 0 var(--icon-size); width: var(--icon-size); min-width: 0; max-width: var(--icon-size); height: var(--icon-size); margin: 0; padding: 0; border: 0; border-radius: var(--rail-corner-radius, 25%); background: var(--rail-icon-bg); filter: none; opacity: 0.42; cursor: pointer; transition: opacity var(--duration-normal) var(--easing-default), scale var(--duration-normal) var(--easing-default); }
  .rail-icon:hover, .rail-icon:active { background: var(--rail-icon-bg); filter: none; }
  .rail-glyph { display: block; width: calc(var(--icon-size) * 0.53); height: calc(var(--icon-size) * 0.53); object-fit: contain; filter: brightness(0) invert(1); pointer-events: none; }
  .rail-icon.highlighted, .rail-icon:hover, .rail-icon:focus-visible { opacity: 1; scale: 1.08; }
  .rail-window:focus-visible .rail-icon.highlighted, .rail-icon:focus-visible { outline: 3px solid var(--color-font-button); outline-offset: 3px; }
  .scroll-cue { display: inline-flex; align-items: center; justify-content: center; animation: hero-entrance 500ms 1020ms cubic-bezier(.22, 1, .36, 1) both; min-height: 28px; color: var(--color-font-button); font-size: clamp(14px, min(2.8cqw, 2.8cqh), 22px); line-height: 1.4; font-weight: 700; }
  .scroll-cue-content { display: inline-flex; align-items: center; justify-content: center; gap: var(--spacing-6); animation: cue-pulse 1.8s ease-in-out infinite alternate; }
  @keyframes hero-entrance { from { opacity: 0; transform: translateY(12px) scale(.98); } to { opacity: 1; transform: translateY(0) scale(1); } }
  .hero-entrance-complete .hero-ai-entrance, .hero-entrance-complete .hero h1, .hero-entrance-complete .hero-prompt-entrance, .hero-entrance-complete .hero-speed, .hero-entrance-complete .rail-window, .hero-entrance-complete .scroll-cue { animation: none; }
  .cue-arrow { display: block; flex: 0 0 1em; width: 1em; height: 1em; fill: none; stroke: currentColor; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
  @keyframes cue-pulse { from { opacity: .3; } to { opacity: .8; } }
  .composer-link { position: absolute; z-index: 5; left: 50%; bottom: max(var(--spacing-8), env(safe-area-inset-bottom)); transform: translateX(-50%); width: min(629px, calc(100% - 30px)); min-height: 64px; box-sizing: border-box; padding: 0 var(--spacing-12); display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-8); border-radius: 32px; background: var(--color-grey-blue); color: var(--color-font-primary); font-weight: 700; box-shadow: 0 4px 12px color-mix(in srgb, var(--color-grey-100) 8%, transparent); text-align: center; animation: composer-enter 550ms cubic-bezier(.2, .75, .25, 1) both; }
  @keyframes composer-enter { from { opacity: 0; transform: translate(-50%, 24px); } to { opacity: 1; transform: translate(-50%, 0); } }
  .composer-link:hover { box-shadow: var(--shadow-lg); }
  .composer-ai, .composer-mic { display: block; flex: 0 0 24px; width: 24px; height: 24px; color: var(--color-font-tertiary); }
  .composer-label { color: var(--color-font-tertiary); min-width: 0; }
  .composer-label-text { display: inline-block; animation: composer-label-enter 280ms ease-out both; }
  @keyframes composer-label-enter { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
  .section-nav { position: absolute; z-index: 6; left: 50%; transform: translateX(-50%); display: grid; place-items: center; width: 41px; height: 41px; min-width: 0; min-height: 0; margin: 0; padding: var(--spacing-4); box-sizing: border-box; border: 1px solid var(--color-grey-30); border-radius: var(--radius-full); background: var(--color-grey-20); color: var(--color-primary-start); box-shadow: var(--shadow-md); cursor: pointer; scale: 1; filter: none; }
  .section-nav:hover { background: var(--color-grey-30); }.section-nav:focus-visible { outline: 3px solid var(--color-primary-start); outline-offset: 2px; }
  .section-nav-previous { top: var(--spacing-6); }.section-nav-next { bottom: calc(max(var(--spacing-8), env(safe-area-inset-bottom)) + 64px + var(--spacing-6)); }
  .section-nav svg { width: 24px; height: 24px; fill: none; stroke: currentColor; stroke-width: 2.5; stroke-linecap: round; stroke-linejoin: round; }
  .feature.story-playing { grid-template-columns: minmax(0, 1fr); justify-items: center; align-content: center; gap: var(--spacing-12); text-align: center; }
  .story-playing .feature-copy { max-width: 48rem; }.story-playing .feature-icon { margin-inline: auto; }.story-playing h2 { margin-bottom: var(--spacing-6); }
  .story-stage, .skip-animation { transition: opacity 200ms ease-out; }.story-finishing .story-stage, .story-finishing .skip-animation { opacity: 0; pointer-events: none; }
  .story-surface { display: grid; min-width: 0; width: 100%; }.story-surface > :global(*) { grid-area: 1 / 1; min-width: 0; }.story-stage { width: min(100%, 58rem); margin-inline: auto; }
  .skip-animation { min-width: 0; min-height: 0; margin: 0; padding: var(--spacing-4); border: 0; background: transparent; color: var(--color-grey-60); font: inherit; font-size: var(--font-size-small); cursor: pointer; box-shadow: none; }.skip-animation:hover { color: var(--color-font-primary); text-decoration: underline; }

  .feature { min-height: 100%; width: 100%; margin: 0 auto; padding: clamp(48px, 5vw, 96px) clamp(32px, 6vw, 112px) max(156px, env(safe-area-inset-bottom)); box-sizing: border-box; overflow: hidden; }
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
  .feature-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: var(--spacing-4) var(--spacing-12); margin-top: var(--spacing-8); }
  .example-link, .replay-animation { width: fit-content; margin: 0; padding: var(--spacing-4) 0; font-size: var(--font-size-small); font-weight: 500; color: var(--color-grey-70); }
  .replay-animation { min-width: 0; min-height: 0; border: 0; border-radius: var(--radius-2); background: transparent; box-shadow: none; font-family: inherit; cursor: pointer; }
  .replay-animation:hover { color: var(--color-font-primary); text-decoration: underline; }
  .replay-animation:focus-visible, .source-github:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 4px; }
  .source-github { display: grid; place-items: center; width: min(65vw, 320px); aspect-ratio: 1; margin-inline: auto; color: var(--color-font-primary); transition: transform var(--duration-normal), color var(--duration-normal); }
  .source-github svg { display: block; width: 80%; height: 80%; }
  .source-github:hover { transform: translateY(-4px); color: var(--color-primary-start); }
  @media (prefers-reduced-motion: reduce) { .source-github { transition: none; }.source-github:hover { transform: none; } }
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
  @media (max-width: 760px) { .viewport-container { margin: 0 var(--spacing-4) var(--spacing-4); }.feature { min-height: 100%; padding: max(72px, var(--spacing-20)) var(--spacing-8) max(156px, env(safe-area-inset-bottom)); gap: var(--spacing-16); }.feature h2 { margin-bottom: var(--spacing-12); }.publication-row { grid-template-columns: 1fr; gap: var(--spacing-12); padding: var(--spacing-16) var(--spacing-8); }.site-footer { flex-direction: column; align-items: flex-start; padding: var(--spacing-16) var(--spacing-8); }.site-footer nav { justify-content: flex-start; } }
  /* Fit custom stories between the fixed arrows and composer when browser chrome
     leaves a short phone panel. Final reading layouts keep their natural height. */
  @container (max-width: 760px) {
    .feature.story-playing.story-demonstration {
      height: 100cqh;
      grid-template-rows: auto minmax(0, 1fr);
      align-content: stretch;
      gap: clamp(8px, 2cqh, 20px);
      padding-top: calc(41px + var(--spacing-6) * 2);
      padding-bottom: calc(max(var(--spacing-8), env(safe-area-inset-bottom)) + 64px + 41px + var(--spacing-6) * 2);
    }
    .story-playing.story-demonstration .feature-copy { width: 100%; }
    .story-playing.story-demonstration .skip-animation { padding: var(--spacing-2); }
    .story-playing.story-demonstration .feature-icon { width: clamp(24px, 6cqh, 48px); height: clamp(24px, 6cqh, 48px); margin-bottom: clamp(4px, 1.5cqh, 12px); }
    .story-playing.story-demonstration h2 { margin-bottom: var(--spacing-4); font-size: clamp(20px, min(6.8cqw, 4.5cqh), 28px); line-height: 1.2; }
    .story-playing.story-demonstration .story-surface, .story-playing.story-demonstration .story-stage { height: 100%; min-height: 0; }
    .story-playing.story-demonstration .story-stage { --story-animation-height: 100%; }
  }
  @container (max-width: 760px) and (max-height: 560px) {
    .story-playing.story-demonstration .feature-icon { width: 24px; height: 24px; margin-bottom: var(--spacing-2); }
    .story-playing.story-demonstration h2 { margin-bottom: var(--spacing-2); font-size: 20px; line-height: 1.1; }
  }
  @media (max-width: 440px) { .scroll-cue-content { gap: var(--spacing-4); }.publication-cards { grid-template-columns: 1fr; }.publication-card img { height: 170px; } }
  /* Phone sizing balances readable copy with breathing room. The compact rule
     follows panel height after the header and mobile browser chrome take space. */
  @container (max-width: 480px) {
    .hero { --hero-ai-size: clamp(6rem, min(28cqw, 20cqh), 8rem); gap: clamp(.625rem, min(2.6cqw, 1.8cqh), .875rem); }
    .hero h1 { font-size: clamp(2rem, min(9.6cqw, 7.6cqh), 2.75rem); }
    .landing-page:lang(de) .hero h1 { font-size: clamp(1.5rem, min(7.6cqw, 7.2cqh), 2.25rem); }
    .prompt-bubble { box-sizing: border-box; max-width: calc(100% - 1rem); padding: clamp(.5rem, 1.6cqh, .75rem) clamp(.875rem, 3cqw, 1.25rem); font-size: clamp(1.1875rem, min(5.4cqw, 4cqh), 1.5rem); }
    .hero-speed { font-size: clamp(1.0625rem, min(4.6cqw, 3.3cqh), 1.375rem); }
    .rail-window { --icon-size: clamp(4.25rem, min(21cqw, 17cqh), 6rem); }
    .scroll-cue { font-size: clamp(.9375rem, min(4.3cqw, 3.2cqh), 1.125rem); }
  }
  @container (max-width: 480px) and (max-height: 560px) {
    .hero { --hero-ai-size: clamp(4.5rem, min(25cqw, 16cqh), 5rem); gap: var(--spacing-3); padding-bottom: 96px; }
    .hero h1 { font-size: clamp(1.75rem, 8.8cqw, 2.125rem); }
    .landing-page:lang(de) .hero h1 { font-size: clamp(1.375rem, 7.4cqw, 1.75rem); }
    .prompt-bubble { padding: .5rem .875rem; font-size: clamp(1.0625rem, 5.2cqw, 1.25rem); }
    .hero-speed { font-size: 1rem; }
    .rail-window { --icon-size: clamp(3.75rem, min(20cqw, 16cqh), 5rem); }
    .scroll-cue { min-height: 24px; font-size: .875rem; }
  }
  /* A short landscape viewport groups the AI icon beside the text rather than squeezing every row. */
  @media (max-height: 500px) and (min-width: 500px) {
    .hero { display: grid; grid-template-columns: minmax(64px, 1fr) minmax(0, 6fr) minmax(64px, 1fr); grid-template-rows: auto auto auto 64px auto; align-content: center; justify-items: center; gap: 4px 12px; padding: 8px 16px 84px; }
    .hero-visual { grid-column: 1; grid-row: 1 / 4; justify-self: end; width: 64px; height: 64px; }
    .hero h1 { grid-column: 2; font-size: clamp(22px, 6.9cqh, 28px); line-height: 1.06; }
    .prompt-bubble { grid-column: 2; max-width: 100%; padding: 6px 16px; font-size: 16px; }
    .hero-prompt-entrance { grid-column: 2; }.hero-speed { grid-column: 2; font-size: 14px; }
    .rail-window { grid-column: 1 / -1; width: 100%; height: 64px; --icon-size: 48px; --icon-gap: 18px; }
    .scroll-cue { grid-column: 1 / -1; min-height: 24px; font-size: 12px; }
  }
  @media (prefers-reduced-motion: reduce) { .scroll-container { scroll-behavior: auto; }.composer-label-text, .composer-link, .hero-ai-entrance, .hero h1, .hero-prompt-entrance, .hero-speed, .rail-window, .rail-track, .scroll-cue, .scroll-cue-content, .prompt-bubble, .hero-ai-visual, .hero-ai-visual::before { animation: none !important; }.rail-icon, :global(.reveal-ready) .feature-icon, :global(.reveal-ready) .feature-copy h2, :global(.reveal-ready) .feature-copy p, :global(.reveal-ready) .feature-copy .text-link, :global(.reveal-ready) .feature-example, :global(.newsletter-reveal.reveal-ready), :global(.publication-row.reveal-ready) .publication-intro, :global(.publication-row.reveal-ready) .event-cards, :global(.publication-row.reveal-ready) .publication-cards, :global(.publication-row.reveal-ready) .empty-publication { transition: none !important; }.hero-visual { transform: none; } }
</style>
