<script lang="ts">
  import { onMount } from 'svelte';
  import type { LandingPublication } from './landingPageContent';
  import { externalLinks } from '../../config/links';
  import { proxyImage } from '../../utils/imageProxy';
  import { appsMetadata } from '../../data/appsMetadata';
  import { resolveIconName } from '../../utils/iconNameResolver';
  import { getCategoryGradientColors } from '../../utils/categoryUtils';

  type Props = {
    appBaseUrl: string;
    websiteBaseUrl: string;
    events?: LandingPublication[];
    news?: LandingPublication[];
    posts?: LandingPublication[];
  };

  let { appBaseUrl, websiteBaseUrl, events = [], news = [], posts = [] }: Props = $props();

  const appUrl = (path: string) => `${appBaseUrl.replace(/\/$/, '')}${path}`;
  const siteUrl = (path: string) => `${websiteBaseUrl.replace(/\/$/, '')}${path}`;

  const screenshots = {
    heroDesktop: '/landing/screenshots/hero-desktop.webp',
    heroMobile: '/landing/screenshots/hero-mobile.webp',
    eventsDesktop: '/landing/screenshots/events-desktop.webp',
    eventsMobile: '/landing/screenshots/events-mobile.webp',
    privacyDesktop: '/landing/screenshots/privacy-desktop.webp',
    privacyMobile: '/landing/screenshots/privacy-mobile.webp',
    workflowsDesktop: '/landing/screenshots/workflows-desktop.webp',
    workflowsMobile: '/landing/screenshots/workflows-mobile.webp',
  };

  const introColors = getCategoryGradientColors('openmates_official');
  const railApps = ['health', 'events', 'code', 'news', 'docs', 'messages', 'audio', 'books', 'travel', 'weather', 'finance', 'files']
    .map((id) => appsMetadata[id])
    .filter((app) => Boolean(app && app.icon_image && !app.internal))
    .map((app) => ({
      appId: app.id,
      iconName: resolveIconName((app.icon_image ?? app.id).replace(/\.svg$/, '').trim()),
    }));
  const primaryRail = [...railApps, ...railApps];
  const secondaryRail = [...railApps.slice(4), ...railApps.slice(0, 4), ...railApps.slice(4), ...railApps.slice(0, 4)];
  const requests = [
    { appId: 'health', text: 'Find doctor appointments' },
    { appId: 'events', text: 'Find events' },
    { appId: 'code', text: 'Build a web app' },
    { appId: 'news', text: 'Catch up on the news' },
  ];
  let requestIndex = $state(0);
  let reducedMotion = $state(false);
  let activeRequest = $derived(requests[requestIndex]);

  onMount(() => {
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    let rotation: number | undefined;
    const updateMotion = () => {
      reducedMotion = motionQuery.matches;
      window.clearInterval(rotation);
      if (reducedMotion) {
        requestIndex = 0;
      } else {
        rotation = window.setInterval(() => { requestIndex = (requestIndex + 1) % requests.length; }, 3500);
      }
    };
    motionQuery.addEventListener('change', updateMotion);
    updateMotion();
    return () => {
      motionQuery.removeEventListener('change', updateMotion);
      window.clearInterval(rotation);
    };
  });
</script>

<div class="landing-page" data-testid="landing-page">
  <header class="site-header">
    <div class="header-start">
      <a class="header-icon menu-link" href={appUrl('/')} aria-label="Open chats in the OpenMates app"><span class="header-mask menu-mask" aria-hidden="true"></span></a>
      <a class="wordmark" href={appUrl('/')} aria-label="OpenMates home"><span>Open</span>Mates</a>
    </div>
    <nav class="workspace-nav" aria-label="OpenMates workspaces">
      <a class="workspace-tab active" href={appUrl('/')} aria-current="page"><span class="header-mask chat-mask" aria-hidden="true"></span><span class="workspace-label">Chats</span></a>
      <a class="workspace-tab" href={appUrl('/#apps')}><span class="header-mask app-mask" aria-hidden="true"></span><span class="workspace-label">Apps</span></a>
    </nav>
    <nav aria-label="Main navigation">
      <a class="header-icon github-link" href={externalLinks.github} target="_blank" rel="noopener noreferrer" aria-label="OpenMates on GitHub"><span class="header-mask github-mask" aria-hidden="true"></span></a>
      <a class="header-link" href={appUrl('/#signup/basics')} data-testid="landing-signup">Login / Signup</a>
      <a class="header-icon settings-link" href={appUrl('/#settings')} aria-label="Open OpenMates settings"><span class="header-mask settings-mask" aria-hidden="true"></span></a>
    </nav>
  </header>

  <div class="viewport-container" data-testid="landing-viewport-container">
    <main class="scroll-container" data-testid="landing-scroll-container">
    <section class="hero" aria-labelledby="hero-title" data-testid="landing-hero" style={`--hero-gradient-start: ${introColors?.start ?? 'var(--color-primary-start)'}; --hero-gradient-end: ${introColors?.end ?? 'var(--color-primary-end)'}`}>
      <div class="hero-visual" aria-label="OpenMates on desktop and mobile">
        <img class="hero-desktop" src={screenshots.heroDesktop} alt="OpenMates web app with a chat open" width="1440" height="832" fetchpriority="high" />
        <img class="hero-mobile" src={screenshots.heroMobile} alt="OpenMates mobile web chat workspace" width="390" height="776" fetchpriority="high" />
      </div>
      <h1 id="hero-title">Your privacy first<br />AI team mates</h1>
      <p class="example-prompt" data-active-app={activeRequest.appId}>{activeRequest.text}</p>
      <div class="app-rails" aria-label="OpenMates apps and capabilities" data-active-app={activeRequest.appId}>
        <div class="app-rail" aria-hidden="true">
          {#each primaryRail as icon, index (`primary-${icon.appId}-${index}`)}
            <span class="rail-icon" class:highlighted={icon.appId === activeRequest.appId} data-app-id={icon.appId} style={`--rail-icon-url: var(--icon-url-${icon.iconName}); --rail-icon-bg: var(--color-app-${icon.appId})`}></span>
          {/each}
        </div>
        <div class="app-rail secondary" aria-hidden="true">
          {#each secondaryRail as icon, index (`secondary-${icon.appId}-${index}`)}
            <span class="rail-icon" class:highlighted={icon.appId === activeRequest.appId} data-app-id={icon.appId} style={`--rail-icon-url: var(--icon-url-${icon.iconName}); --rail-icon-bg: var(--color-app-${icon.appId})`}></span>
          {/each}
        </div>
      </div>
      <a class="scroll-cue" href="#actionable"><span aria-hidden="true">⌄</span>Scroll down to learn more<span aria-hidden="true">⌄</span></a>
    </section>

    <section class="feature feature-media" id="actionable" aria-labelledby="actionable-title" data-testid="landing-feature-actionable">
      <div class="feature-copy">
        <span class="feature-icon subsetting_icon search" aria-hidden="true" data-testid="landing-feature-icon"></span>
        <h2 id="actionable-title">Actionable chats.<br />Not just a wall of text.</h2>
        <p>OpenMates finds you doctor appointments in seconds. As well as events, apartments, travel connections and much more. Unlike other AI chatbots, it doesn’t rely on searching the web - but instead interacts directly with external platforms. And with the workflows feature you can even setup automated regular searches, freeing up your time for more enjoyable things in life.</p>
        <a class="text-link" href={appUrl('/#apps')} target="_blank" rel="noopener noreferrer" data-testid="landing-explore-apps">Explore apps in OpenMates</a>
      </div>
      <div class="feature-example">
        <div class="screenshot-pair">
          <img class="screenshot-desktop" src={screenshots.eventsDesktop} alt="OpenMates web chat searching for AI events in Berlin" width="1440" height="832" loading="lazy" />
          <img class="screenshot-mobile" src={screenshots.eventsMobile} alt="OpenMates mobile view of an events chat" width="390" height="699" loading="lazy" />
        </div>
        <a class="example-link" href={appUrl('/#chat-id=example-ai-workshops-meetups-berlin')}>Open example chat <span aria-hidden="true">↗</span></a>
      </div>
    </section>

    <section class="feature feature-media" id="privacy" aria-labelledby="privacy-title" data-testid="landing-feature-privacy">
      <div class="feature-copy">
        <span class="feature-icon subsetting_icon security" aria-hidden="true" data-testid="landing-feature-icon"></span>
        <h2 id="privacy-title">Privacy &amp; safety<br />by design</h2>
        <p>The most useful AI? Privacy? Safety? Sovereignty?<br />You don’t have to choose. You can have them all, with OpenMates.<br />With features like replacing sensitive data with placeholders, encrypted chats, minimal data processing &amp; multiple layers of AI safety.<br />Powered by the leading AI models from Mistral, Anthropic, OpenAI, Google, Deepseek &amp; more - without ecosystem lock in.</p>
        <div class="feature-links">
          <a class="text-link" href={siteUrl('/blog')}>Learn more about privacy &amp; encryption</a>
          <a class="text-link" href={siteUrl('/blog')}>Learn more about AI safety</a>
        </div>
      </div>
      <div class="feature-example">
        <div class="screenshot-pair">
          <img class="screenshot-desktop" src={screenshots.privacyDesktop} alt="OpenMates web chat showing personal data replaced with placeholders" width="1440" height="832" loading="lazy" />
          <img class="screenshot-mobile" src={screenshots.privacyMobile} alt="OpenMates mobile chat highlighting personal data in the message field" width="390" height="776" loading="lazy" />
        </div>
        <a class="example-link" href={appUrl('/#chat-id=example-plumber-message-email-phone')}>Open example chat <span aria-hidden="true">↗</span></a>
      </div>
    </section>

    <section class="feature feature-media" id="workflows" aria-labelledby="workflows-title" data-testid="landing-feature-workflows">
      <div class="feature-copy">
        <span class="feature-icon subsetting_icon task" aria-hidden="true" data-testid="landing-feature-icon"></span>
        <h2 id="workflows-title">Workflow automation<br />for everyone</h2>
        <p>What if you wouldn’t have to search for apartments, but your AI team mates search for them every hour and filter them based on your criteria and let you know when they find any? Or what if you wouldn’t have to spend hours every month to check out the most interesting upcoming events? And what if you wouldn’t have to remember doing these and other repetitive workflows, because your AI team mates could take care of them for you? And what, if setting up such a workflow would be simple and only take seconds? See for yourself, with the workflows feature in OpenMates.</p>
        <a class="text-link" href={appUrl('/#workflows')} target="_blank" rel="noopener noreferrer" data-testid="landing-explore-workflows">Explore workflows in OpenMates</a>
      </div>
      <div class="feature-example">
        <div class="screenshot-pair">
          <img class="screenshot-desktop" src={screenshots.workflowsDesktop} alt="OpenMates workflow workspace in the web app" width="1440" height="832" loading="lazy" />
          <img class="screenshot-mobile" src={screenshots.workflowsMobile} alt="OpenMates workflow view on mobile" width="390" height="776" loading="lazy" />
        </div>
        <a class="example-link" href={appUrl('/#chat-id=example-library-book-return-workflow')}>Open example chat <span aria-hidden="true">↗</span></a>
      </div>
    </section>

    <section class="feature feature-text" id="devices" aria-labelledby="devices-title" data-testid="landing-feature-devices">
      <div class="feature-copy">
        <span class="feature-icon subsetting_icon devices" aria-hidden="true" data-testid="landing-feature-icon"></span>
        <h2 id="devices-title">A consistent experience,<br />across your devices</h2>
        <p>Unlike any other AI agents software, OpenMates prioritizes a coherent design across your devices. This means you can access all your chats, app skills, workflows and more - from the web app, native apps for Mac, iPad, iPhone and Apple Watch - and even from your terminal and from inside your code.<br />With Android devices &amp; more following.</p>
        <div class="feature-links">
          <a class="text-link" href={appUrl('/')}>Start using the web app</a>
          <a class="text-link" href={siteUrl('/blog')}>Sign up for testing the apps via Apple TestFlight</a>
          <a class="text-link" href={siteUrl('/blog')}>Learn more about OpenMates for developers</a>
        </div>
      </div>
    </section>

    <section class="feature feature-text" id="open-source" aria-labelledby="open-source-title" data-testid="landing-feature-open-source">
      <div class="feature-copy">
        <span class="feature-icon subsetting_icon coding" aria-hidden="true" data-testid="landing-feature-icon"></span>
        <h2 id="open-source-title">Open source &amp;<br />enshittification resilient</h2>
        <p>We are so used to tech products getting worse over time because of profit maximization &amp; greed (a process called enshittification). But various companies have already proven that there is another way. And OpenMates is following those footsteps by putting user interests first in every design &amp; architecture decision. This means OpenMates is open source - to ensure everyone can validate that this commitment is true now and remains so. And for those preferring maximum control over their AI agents - you can even run OpenMates on your own server.</p>
        <div class="feature-links">
          <a class="text-link" href={siteUrl('/blog')}>Learn more about OpenMates ethical stands</a>
          <a class="text-link" href={siteUrl('/blog')}>Learn more about Self-Hosting</a>
        </div>
      </div>
    </section>

    <div class="publication-area">
      <section class="publication-row" aria-labelledby="events-title">
        <div class="publication-intro">
          <h2 id="events-title">Upcoming free<br />OpenMates events</h2>
          <p>Learn how to make better use of OpenMates for getting stuff done &amp; shape its further development with your wishes &amp; feedback.</p>
          <a class="text-link" href={siteUrl('/events')}>Browse events</a>
        </div>
        {#if events.length}
          <div class="publication-cards">
            {#each events.slice(0, 2) as item (item.id)}
              <a class="publication-card" href={item.href}>
                {#if item.image}<img src={proxyImage(item.image, 640)} alt="" loading="lazy" />{/if}
                <div class="card-copy">{#if item.label}<span class="card-label">{item.label}</span>{/if}<h3>{item.title}</h3>{#if item.description}<p>{item.description}</p>{/if}</div>
              </a>
            {/each}
          </div>
        {:else}
          <a class="empty-publication" href={siteUrl('/events')}>See upcoming events <span aria-hidden="true">↗</span></a>
        {/if}
      </section>

      <section class="publication-row" aria-labelledby="news-title">
        <div class="publication-intro">
          <h2 id="news-title">Latest OpenMates<br />news</h2>
          <p>Learn what’s new around OpenMates</p>
          <a class="text-link" href={siteUrl('/news')}>Browse news</a>
        </div>
        {#if news.length}
          <div class="publication-cards">
            {#each news.slice(0, 2) as item (item.id)}
              <a class="publication-card" href={item.href}>
                {#if item.image}<img src={proxyImage(item.image, 640)} alt="" loading="lazy" />{/if}
                <div class="card-copy">{#if item.label}<span class="card-label">{item.label}</span>{/if}<h3>{item.title}</h3>{#if item.description}<p>{item.description}</p>{/if}</div>
              </a>
            {/each}
          </div>
        {:else}
          <a class="empty-publication" href={siteUrl('/news')}>Read the latest news <span aria-hidden="true">↗</span></a>
        {/if}
      </section>

      <section class="publication-row" aria-labelledby="blog-title">
        <div class="publication-intro">
          <h2 id="blog-title">Blog posts</h2>
          <p>Read more about how to better use OpenMates, agentic coding &amp; other thoughts about the industry and the impact of AI on society.</p>
          <a class="text-link" href={siteUrl('/blog')}>Browse the blog</a>
        </div>
        {#if posts.length}
          <div class="publication-cards">
            {#each posts.slice(0, 2) as item (item.id)}
              <a class="publication-card" href={item.href}>
                {#if item.image}<img src={proxyImage(item.image, 640)} alt="" loading="lazy" />{/if}
                <div class="card-copy">{#if item.label}<span class="card-label">{item.label}</span>{/if}<h3>{item.title}</h3>{#if item.description}<p>{item.description}</p>{/if}</div>
              </a>
            {/each}
          </div>
        {:else}
          <a class="empty-publication" href={siteUrl('/blog')}>Read the blog <span aria-hidden="true">↗</span></a>
        {/if}
      </section>
    </div>
  <footer class="site-footer">
    <a class="wordmark" href={appUrl('/')}><span>Open</span>Mates</a>
    <nav aria-label="Footer navigation">
      <a href={siteUrl('/legal/privacy')}>Privacy</a>
      <a href={siteUrl('/legal/terms')}>Terms</a>
      <a href={siteUrl('/legal/imprint')}>Imprint</a>
      <a href={externalLinks.github} target="_blank" rel="noopener noreferrer">GitHub</a>
      <a href={externalLinks.discord} target="_blank" rel="noopener noreferrer">Community</a>
    </nav>
  </footer>
    </main>
    <a class="composer-link" href={appUrl('/#compose')} data-testid="landing-compose" aria-label="Click here to try OpenMates for free">
      <span class="composer-ai" aria-hidden="true"></span>
      <span>Click here to try for free</span>
      <span class="composer-mic" aria-hidden="true"></span>
    </a>
  </div>
</div>

<style>
  .landing-page { width: 100%; height: 100%; min-width: 0; overflow: hidden; display: flex; flex-direction: column; background: var(--color-grey-0); color: var(--color-font-primary); font-family: var(--font-primary); }
  a { color: inherit; text-decoration: none; }
  a:focus-visible { outline: 3px solid var(--color-button-primary); outline-offset: 4px; }
  .site-header { position: relative; flex: 0 0 70px; width: 100%; padding: var(--spacing-4) var(--spacing-10); box-sizing: border-box; display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-8); }
  .site-header nav, .header-start { display: flex; align-items: center; gap: var(--spacing-8); }
  .header-icon { display: inline-grid; place-items: center; flex: 0 0 42px; width: 42px; height: 42px; border-radius: var(--radius-full); color: var(--color-primary-start); }
  .header-icon:hover { background: var(--color-grey-20); }
  .header-mask { display: block; width: 25px; height: 25px; background: currentColor; -webkit-mask: var(--header-icon-url) center / contain no-repeat; mask: var(--header-icon-url) center / contain no-repeat; }
  .menu-mask { --header-icon-url: url('@openmates/ui/static/icons/menu.svg'); }
  .chat-mask { --header-icon-url: url('@openmates/ui/static/icons/chat.svg'); }
  .app-mask { --header-icon-url: url('@openmates/ui/static/icons/app.svg'); }
  .github-mask { --header-icon-url: url('@openmates/ui/static/icons/github.svg'); }
  .settings-mask { --header-icon-url: url('@openmates/ui/static/icons/settings.svg'); }
  .wordmark { font-size: 1.25rem; font-weight: 800; letter-spacing: -0.04em; white-space: nowrap; }
  .wordmark span { color: var(--color-primary-start); }
  .workspace-nav { position: absolute; left: 50%; transform: translateX(-50%); display: flex; gap: 0 !important; padding: var(--spacing-2); border-radius: var(--radius-full); background: var(--color-grey-10); box-shadow: var(--shadow-sm); }
  .workspace-tab { display: inline-flex; align-items: center; justify-content: center; gap: var(--spacing-4); min-width: 58px; min-height: 38px; padding: 0 var(--spacing-6); border-radius: var(--radius-full); font-size: var(--font-size-small); font-weight: 700; }
  .workspace-tab .header-mask { width: 21px; height: 21px; }
  .workspace-tab.active { background: var(--color-primary); color: var(--color-font-button); box-shadow: var(--shadow-sm); }
  .workspace-tab:not(.active):hover { background: var(--color-grey-20); }
  .header-link { display: inline-flex; align-items: center; min-height: 42px; padding: 0 var(--spacing-8); border-radius: var(--radius-5); background: var(--color-button-primary); color: var(--color-font-button); font-weight: 700; box-shadow: var(--shadow-sm); white-space: nowrap; }
  .header-link:hover { background: var(--color-button-primary-hover); }
  .viewport-container { position: relative; flex: 1; min-height: 0; margin: 0 var(--spacing-10) var(--spacing-10); overflow: hidden; border-radius: var(--radius-6); background: var(--color-grey-0); box-shadow: var(--shadow-md); }
  .scroll-container { width: 100%; height: 100%; overflow-x: hidden; overflow-y: auto; overscroll-behavior: contain; scroll-behavior: smooth; }
  .hero { position: relative; height: 100%; box-sizing: border-box; padding: var(--spacing-12) var(--spacing-16) 110px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--spacing-10); overflow: hidden; text-align: center; background: linear-gradient(135deg, var(--hero-gradient-start), var(--hero-gradient-end)); color: var(--color-font-button); }
  .hero-visual { position: relative; flex: 1 1 260px; width: min(600px, 72%); min-height: 0; max-height: 260px; }
  .hero-visual img, .screenshot-pair img { position: absolute; display: block; object-fit: contain; border-radius: var(--radius-5); box-shadow: var(--shadow-lg); background: var(--color-grey-20); }
  .hero-desktop { width: 82%; height: 88%; right: 0; top: 0; }
  .hero-mobile { width: 25%; height: 100%; left: 1%; bottom: 0; object-position: top; }
  .hero h1 { margin: 0; color: var(--color-font-button); font-size: clamp(2.25rem, 4vw, 3.75rem); line-height: 1.12; font-weight: 800; letter-spacing: -0.035em; }
  .example-prompt { max-width: 100%; margin: 0; padding: var(--spacing-6) var(--spacing-12); border-radius: var(--radius-5); background: var(--color-grey-blue); color: var(--color-font-primary); font-size: clamp(1.125rem, 2vw, 1.75rem); font-weight: 700; box-shadow: var(--shadow-sm); }
  .app-rails { width: 100%; display: grid; gap: var(--spacing-8); overflow: hidden; }
  .app-rail { display: flex; align-items: center; gap: var(--spacing-12); width: max-content; animation: rail-move-left 56s linear infinite; }
  .app-rail.secondary { animation-duration: 72s; }
  .rail-icon { flex: 0 0 62px; width: 62px; height: 62px; display: inline-grid; place-items: center; border-radius: var(--radius-5); background: var(--rail-icon-bg); opacity: 0.46; transition: opacity var(--duration-normal) var(--easing-default), transform var(--duration-normal) var(--easing-default); }
  .rail-icon::before { content: ''; display: block; width: 53%; height: 53%; background: var(--color-font-button); -webkit-mask: var(--rail-icon-url) center / contain no-repeat; mask: var(--rail-icon-url) center / contain no-repeat; }
  .rail-icon.highlighted { opacity: 1; transform: scale(1.08); }
  @keyframes rail-move-left { to { transform: translateX(-50%); } }
  .scroll-cue { display: inline-flex; gap: var(--spacing-6); align-items: center; color: var(--color-font-button); font-size: var(--font-size-small); font-weight: 700; }
  .scroll-cue span { font-size: 2rem; line-height: 0.7; }
  .composer-link { position: absolute; z-index: var(--z-index-dropdown); left: 50%; bottom: max(var(--spacing-8), env(safe-area-inset-bottom)); transform: translateX(-50%); width: min(629px, calc(100% - 30px)); min-height: 64px; box-sizing: border-box; padding: 0 var(--spacing-12); display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-8); border-radius: var(--radius-full); background: var(--color-grey-blue); color: var(--color-font-primary); font-weight: 700; box-shadow: var(--shadow-md); text-align: center; }
  .composer-link:hover { box-shadow: var(--shadow-lg); }
  .composer-ai, .composer-mic { display: block; flex: 0 0 24px; width: 24px; height: 24px; background: var(--color-grey-60); -webkit-mask: var(--composer-icon-url) center / contain no-repeat; mask: var(--composer-icon-url) center / contain no-repeat; }
  .composer-ai { --composer-icon-url: url('@openmates/ui/static/icons/ai.svg'); }
  .composer-mic { --composer-icon-url: url('@openmates/ui/static/icons/recordaudio.svg'); }
  .feature { max-width: 1260px; margin: 0 auto; padding: clamp(72px, 9vw, 150px) var(--spacing-24); }
  .feature-media { display: grid; grid-template-columns: minmax(280px, 0.85fr) minmax(0, 1.15fr); align-items: center; gap: clamp(32px, 6vw, 100px); }
  .feature-copy { max-width: 480px; }
  .feature-icon { display: block; width: 48px; height: 48px; margin-bottom: var(--spacing-8); --icon-color: var(--color-primary-start); }
  .feature-icon::after { -webkit-mask-size: 80%; mask-size: 80%; }
  .feature h2, .publication-row h2 { margin: 0 0 var(--spacing-16); font-size: clamp(1.75rem, 2.6vw, 2.5rem); line-height: 1.24; letter-spacing: -0.025em; font-weight: 700; }
  .feature p { margin: 0 0 var(--spacing-12); font-size: var(--font-size-p); line-height: 1.6; }
  .feature-links { display: grid; gap: var(--spacing-4); }
  .text-link { display: inline-block; width: fit-content; font-size: var(--font-size-p); font-weight: 700; color: var(--color-primary-start); }
  .text-link::before { content: '› '; }
  .text-link:hover, .example-link:hover, .site-footer a:hover { text-decoration: underline; }
  .feature-example { min-width: 0; }
  .screenshot-pair { position: relative; width: 100%; aspect-ratio: 1.55; }
  .screenshot-desktop { width: 84%; height: 84%; top: 0; right: 0; }
  .screenshot-mobile { width: 25%; height: 78%; left: 0; bottom: 0; object-position: top; }
  .example-link { display: block; width: fit-content; margin: var(--spacing-8) 0 0 auto; font-size: var(--font-size-small); font-weight: 700; }
  .feature-text { display: flex; justify-content: center; }
  .feature-text .feature-copy { max-width: 720px; width: 100%; }
  .publication-area { background: var(--color-grey-20); padding: var(--spacing-24) 0; }
  .publication-row { max-width: 1260px; margin: auto; padding: var(--spacing-16) var(--spacing-24); display: grid; grid-template-columns: minmax(240px, 0.75fr) minmax(0, 1.25fr); gap: var(--spacing-24); align-items: stretch; }
  .publication-row + .publication-row { border-top: 1px solid var(--color-grey-30); }
  .publication-row h2 { margin-bottom: var(--spacing-8); }
  .publication-intro p { margin: 0 0 var(--spacing-8); color: var(--color-font-tertiary); line-height: 1.5; }
  .publication-cards { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--spacing-8); }
  .publication-card, .empty-publication { min-width: 0; overflow: hidden; border-radius: var(--radius-5); background: var(--color-grey-0); box-shadow: var(--shadow-sm); }
  .publication-card { display: flex; flex-direction: column; }
  .publication-card:hover, .empty-publication:hover { box-shadow: var(--shadow-md); }
  .publication-card img { display: block; width: 100%; height: 150px; object-fit: cover; }
  .card-copy { padding: var(--spacing-10); }
  .card-label { color: var(--color-font-tertiary); font-size: var(--font-size-small); }
  .card-copy h3 { margin: var(--spacing-4) 0; font-size: var(--font-size-h3); line-height: 1.35; }
  .card-copy p { margin: var(--spacing-4) 0 0; color: var(--color-font-tertiary); font-size: var(--font-size-small); line-height: 1.5; }
  .empty-publication { display: flex; align-items: center; justify-content: space-between; min-height: 180px; padding: var(--spacing-16); color: var(--color-primary-start); font-weight: 700; }
  .site-footer { max-width: 1440px; margin: 0 auto 110px; padding: var(--spacing-16) var(--spacing-24); display: flex; justify-content: space-between; gap: var(--spacing-16); align-items: center; }
  .site-footer nav { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--spacing-8); font-size: var(--font-size-small); color: var(--color-font-tertiary); }
  @media (max-width: 760px) {
    .site-header { flex-basis: 70px; padding: var(--spacing-4); }
    .site-header nav, .header-start { gap: var(--spacing-4); }
    .wordmark, .github-link, .workspace-label { display: none; }
    .workspace-nav { position: static; transform: none; margin-right: auto; }
    .workspace-tab { min-width: 44px; padding: 0 var(--spacing-4); }
    .viewport-container { margin: 0 var(--spacing-4) var(--spacing-4); }
    .header-link { padding: 0 var(--spacing-6); font-size: var(--font-size-small); }
    .hero { padding: var(--spacing-12) var(--spacing-8) 110px; gap: var(--spacing-8); }
    .hero-visual { flex-basis: 180px; width: min(480px, 94%); max-height: 200px; }
    .app-rails { gap: var(--spacing-6); }
    .app-rail { gap: var(--spacing-8); }
    .rail-icon { flex-basis: 52px; width: 52px; height: 52px; border-radius: var(--radius-3); }
    .feature { padding: var(--spacing-24) var(--spacing-8); }
    .feature-media { grid-template-columns: 1fr; gap: var(--spacing-16); }
    .feature-copy, .feature-text .feature-copy { max-width: 650px; }
    .feature h2 { margin-bottom: var(--spacing-12); }
    .publication-row { grid-template-columns: 1fr; gap: var(--spacing-12); padding: var(--spacing-16) var(--spacing-8); }
    .site-footer { flex-direction: column; align-items: flex-start; padding: var(--spacing-16) var(--spacing-8); }
    .site-footer nav { justify-content: flex-start; }
  }
  @media (max-width: 440px) {
    .site-header { gap: var(--spacing-2); }
    .header-icon { flex-basis: 38px; width: 38px; height: 38px; }
    .workspace-tab { min-width: 36px; }
    .workspace-tab:not(.active) { display: none; }
    .header-link { padding: 0 var(--spacing-4); }
    .hero h1 { font-size: 2rem; }
    .hero-visual { flex-basis: 155px; }
    .scroll-cue { font-size: var(--font-size-xs); }
    .publication-cards { grid-template-columns: 1fr; }
    .publication-card img { height: 170px; }
  }
  @media (prefers-reduced-motion: reduce) {
    .scroll-container { scroll-behavior: auto; }
    .app-rail { animation: none; }
    .rail-icon { transition: none; }
  }
</style>
