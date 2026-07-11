<!--
  Shared workspace home shell for OpenMates surfaces.
  Keeps DailyInspirationBanner and continue-card layout reusable across
  chats-adjacent workspaces without importing chat sync, drafts, or message DB.
  Surface-specific pages provide only content, callbacks, and composer actions.
  The shared class names intentionally match the chat welcome screen.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import DailyInspirationBanner from '../DailyInspirationBanner.svelte';
  import { getContinueGradientColors, getResumeCardGradientStyle, getResumeLargeCardStyle } from '../activeChatUtils';
  import { loadDefaultInspirations } from '../../demo_chats/loadDefaultInspirations';
  import { getLucideIcon, getValidIconName } from '../../utils/categoryUtils';

  type WorkspaceSurface = 'chats' | 'projects' | 'workflows' | 'tasks' | 'plans';

  type WorkspaceInspiration = {
    phrase: string;
    title?: string;
  };

  type ContinueItem = {
    id: string;
    title: string;
    summary?: string | null;
    badge?: string | null;
    category?: string | null;
    appId?: string | null;
    icon?: string | null;
    source?: 'recent' | 'example';
  };

  type Props = {
    surface: WorkspaceSurface;
    testId?: string;
    eyebrow?: string;
    heading: string;
    subtitle?: string;
    continueLabel?: string;
    continueItems?: ContinueItem[];
    actionItems?: ContinueItem[];
    actionItemsTestId?: string;
    itemTestId?: string;
    continueSectionTestId?: string;
    onContinueItem?: (item: ContinueItem) => void;
    onActionItem?: (item: ContinueItem) => void;
    onStartInspiration?: (inspiration: WorkspaceInspiration) => void;
  };

  let {
    surface,
    testId = `${surface}-workspace-home`,
    eyebrow = '',
    heading,
    subtitle = '',
    continueLabel = 'Continue where you left off',
    continueItems = [],
    actionItems = [],
    actionItemsTestId = `${surface}-workspace-actions`,
    itemTestId = 'resume-chat-card',
    continueSectionTestId = `${surface}-workspace-continue`,
    onContinueItem,
    onActionItem,
    onStartInspiration,
  }: Props = $props();

  let containerWidth = $state(0);
  let viewportWidth = $state(typeof window !== 'undefined' ? window.innerWidth : 1200);
  let viewportHeight = $state(typeof window !== 'undefined' ? window.innerHeight : 800);
  let isTallViewport = $derived(viewportHeight >= 800 && viewportWidth >= 550);
  const ChevronRight = getLucideIcon('chevron-right');

  onMount(() => {
    void loadDefaultInspirations({ surface, allowIndexedDB: false });
    const handleResize = () => {
      viewportWidth = window.innerWidth;
      viewportHeight = window.innerHeight;
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  });

  function handleStartInspiration(inspiration: WorkspaceInspiration): void {
    onStartInspiration?.(inspiration);
  }

  function handleContinueItem(item: ContinueItem): void {
    onContinueItem?.(item);
  }

  function handleActionItem(item: ContinueItem): void {
    onActionItem?.(item);
  }

  function continueCardStyle(item: ContinueItem): string {
    return getResumeCardGradientStyle(getContinueGradientColors(item.category ?? 'productivity', item.appId));
  }

  function continueLargeCardStyle(item: ContinueItem): string {
    return getResumeLargeCardStyle(getContinueGradientColors(item.category ?? 'productivity', item.appId));
  }
</script>

<section class="workspace-home-shell" data-testid={testId} data-surface={surface} bind:clientWidth={containerWidth}>
  <div class="daily-inspiration-area workspace-daily-inspiration-area" data-testid={`${surface}-daily-inspiration-area`}>
    <DailyInspirationBanner
      {surface}
      onStartChat={handleStartInspiration}
      containerWidth={containerWidth}
    />
  </div>

  <div class="center-content workspace-center-content" data-testid={`${surface}-workspace-center`}>
    <div class="team-profile">
      <div class="welcome-text">
        {#if eyebrow}
          <p class="workspace-eyebrow">{eyebrow}</p>
        {/if}
        <h2>{heading}</h2>
        {#if subtitle}
          <p class="workspace-subtitle">{subtitle}</p>
        {/if}
      </div>
    </div>

    {#if actionItems.length > 0}
      <div class="recent-chats-scroll-container" data-testid={actionItemsTestId}>
        {#each actionItems as item (item.id)}
          {@const iconName = getValidIconName(item.icon ?? 'sparkles', item.category ?? 'productivity')}
          {@const IconComponent = getLucideIcon(iconName)}
          {#if isTallViewport}
            <button
              type="button"
              class="resume-chat-large-card"
              data-testid={itemTestId}
              data-card-source={item.source ?? undefined}
              style={continueLargeCardStyle(item)}
              onclick={() => handleActionItem(item)}
            >
              <div class="resume-large-orbs" aria-hidden="true">
                <div class="resume-orb resume-orb-1"></div>
                <div class="resume-orb resume-orb-2"></div>
                <div class="resume-orb resume-orb-3"></div>
              </div>
              <div class="resume-large-deco resume-large-deco-left">
                <IconComponent size={80} color="white" />
              </div>
              <div class="resume-large-deco resume-large-deco-right">
                <IconComponent size={80} color="white" />
              </div>
              <div class="resume-large-content">
                {#if item.badge}
                  <span class="resume-chat-kind-badge">{item.badge}</span>
                {/if}
                <div class="resume-large-icon">
                  <IconComponent size={32} color="white" />
                </div>
                <span class="resume-large-title">{item.title}</span>
                {#if item.summary}
                  <p class="resume-large-summary">{item.summary}</p>
                {/if}
              </div>
            </button>
          {:else}
            <button
              type="button"
              class="resume-chat-card"
              data-testid={itemTestId}
              data-card-source={item.source ?? undefined}
              style={continueCardStyle(item)}
              onclick={() => handleActionItem(item)}
            >
              <div class="resume-chat-compact-icon">
                <IconComponent size={18} color="rgba(255, 255, 255, 0.92)" />
              </div>
              <div class="resume-chat-content">
                {#if item.badge}
                  <span class="resume-chat-kind-badge compact">{item.badge}</span>
                {/if}
                <span class="resume-chat-title" data-testid="resume-chat-title">{item.title}</span>
                {#if item.summary}
                  <span class="resume-chat-summary">{item.summary}</span>
                {/if}
              </div>
              <div class="resume-chat-arrow">
                <ChevronRight size={16} color="rgba(255, 255, 255, 0.88)" />
              </div>
            </button>
          {/if}
        {/each}
      </div>
    {:else if continueItems.length > 0}
      <div class="workspace-continue-section" data-testid={continueSectionTestId}>
        <div class="workspace-continue-label">{continueLabel}</div>
        <div class="recent-chats-scroll-container" data-testid="recent-chats-scroll-container">
        {#each continueItems as item (item.id)}
          {@const iconName = getValidIconName(item.icon ?? 'sparkles', item.category ?? 'productivity')}
          {@const IconComponent = getLucideIcon(iconName)}
          {#if isTallViewport}
            <button
              type="button"
              class="resume-chat-large-card"
              data-testid="resume-chat-large-card"
              style={continueLargeCardStyle(item)}
              onclick={() => handleContinueItem(item)}
            >
              <div class="resume-large-orbs" aria-hidden="true">
                <div class="resume-orb resume-orb-1"></div>
                <div class="resume-orb resume-orb-2"></div>
                <div class="resume-orb resume-orb-3"></div>
              </div>
              <div class="resume-large-deco resume-large-deco-left">
                <IconComponent size={80} color="white" />
              </div>
              <div class="resume-large-deco resume-large-deco-right">
                <IconComponent size={80} color="white" />
              </div>
              <div class="resume-large-content">
                {#if item.badge}
                  <span class="resume-chat-kind-badge">{item.badge}</span>
                {/if}
                <div class="resume-large-icon">
                  <IconComponent size={32} color="white" />
                </div>
                <span class="resume-large-title" data-testid="resume-large-title">{item.title}</span>
                {#if item.summary}
                  <p class="resume-large-summary">{item.summary}</p>
                {/if}
              </div>
            </button>
          {:else}
            <button
              type="button"
              class="resume-chat-card"
              data-testid="resume-chat-card"
              style={continueCardStyle(item)}
              onclick={() => handleContinueItem(item)}
            >
              <div class="resume-chat-compact-icon">
                <IconComponent size={18} color="rgba(255, 255, 255, 0.92)" />
              </div>
              <div class="resume-chat-content">
                {#if item.badge}
                  <span class="resume-chat-kind-badge compact">{item.badge}</span>
                {/if}
                <span class="resume-chat-title" data-testid="resume-chat-title">{item.title}</span>
                {#if item.summary}
                  <span class="resume-chat-summary">{item.summary}</span>
                {/if}
              </div>
              <div class="resume-chat-arrow">
                <ChevronRight size={16} color="rgba(255, 255, 255, 0.88)" />
              </div>
            </button>
          {/if}
        {/each}
        </div>
      </div>
    {/if}

    {#if actionItems.length > 0 && continueItems.length > 0}
      <div class="workspace-continue-section" data-testid={continueSectionTestId}>
        <div class="workspace-continue-label">{continueLabel}</div>
        <div class="recent-chats-scroll-container secondary" data-testid="recent-chats-scroll-container">
        {#each continueItems as item (item.id)}
          {@const iconName = getValidIconName(item.icon ?? 'sparkles', item.category ?? 'productivity')}
          {@const IconComponent = getLucideIcon(iconName)}
          <button
            type="button"
            class="resume-chat-card"
            data-testid="resume-chat-card"
            style={continueCardStyle(item)}
            onclick={() => handleContinueItem(item)}
          >
            <div class="resume-chat-compact-icon">
              <IconComponent size={18} color="rgba(255, 255, 255, 0.92)" />
            </div>
            <div class="resume-chat-content">
              {#if item.badge}
                <span class="resume-chat-kind-badge compact">{item.badge}</span>
              {/if}
              <span class="resume-chat-title" data-testid="resume-chat-title">{item.title}</span>
              {#if item.summary}
                <span class="resume-chat-summary">{item.summary}</span>
              {/if}
            </div>
            <div class="resume-chat-arrow">
              <ChevronRight size={16} color="rgba(255, 255, 255, 0.88)" />
            </div>
          </button>
        {/each}
        </div>
      </div>
    {/if}
  </div>

  <div class="workspace-composer-slot">
    <slot name="composer" />
  </div>
</section>

<style>
  .workspace-home-shell {
    height: 100%;
    min-height: 0;
    position: relative;
    padding: 0;
    border-radius: 17px;
    background: transparent;
    color: var(--color-font-primary);
    overflow: hidden;
  }

  .workspace-daily-inspiration-area {
    width: 100%;
    max-width: none;
    margin: 0;
    flex-shrink: 0;
  }

  .workspace-center-content.center-content {
    position: absolute;
    top: calc(50% + 17.5vh);
    left: 50%;
    transform: translate(-50%, -50%);
    width: 100%;
    max-width: 100%;
    z-index: var(--z-index-raised);
    pointer-events: none;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
  }

  .workspace-center-content .team-profile {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-10);
  }

  .workspace-center-content .workspace-eyebrow {
    margin: 0 0 8px;
    color: var(--color-grey-60);
    font-size: var(--font-size-small);
    font-weight: 800;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }

  .workspace-center-content .welcome-text h2 {
    margin: 0;
    max-width: 920px;
    color: var(--color-grey-80);
    font-size: var(--font-size-h2-mobile);
    font-weight: 600;
  }

  .workspace-center-content .workspace-subtitle {
    margin: 8px 0 0;
    color: var(--color-grey-60);
    font-size: var(--font-size-p);
    font-weight: 600;
  }

  .workspace-continue-label {
    margin-top: var(--spacing-6);
    color: var(--color-grey-60);
    font-size: var(--font-size-p);
    font-weight: 600;
  }

  .workspace-continue-section {
    width: 100%;
  }

  .recent-chats-scroll-container {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: var(--spacing-8);
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
    scroll-behavior: smooth;
    scrollbar-width: none;
    -ms-overflow-style: none;
    visibility: visible;
    padding: 12px 48px 12px calc(50% - 150px);
    box-sizing: border-box;
    pointer-events: auto;
    width: 100%;
    max-width: 100%;
  }

  .recent-chats-scroll-container::-webkit-scrollbar {
    display: none;
  }

  .recent-chats-scroll-container .resume-chat-card {
    min-width: 300px;
    max-width: 300px;
    flex-shrink: 0;
  }

  .recent-chats-scroll-container .resume-chat-large-card {
    flex-shrink: 0;
  }

  .recent-chats-scroll-container.secondary {
    padding-top: 8px;
  }

  .resume-chat-card {
    position: relative;
    display: flex;
    align-items: center;
    gap: var(--spacing-6);
    width: 100%;
    max-width: 400px;
    min-height: 44px;
    padding: var(--spacing-5) var(--spacing-8);
    background-color: transparent;
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: var(--radius-8);
    cursor: pointer;
    overflow: hidden;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.16), 0 2px 6px rgba(0, 0, 0, 0.1);
    transition: background-position 0.25s ease, transform 0.15s ease-out, box-shadow 0.2s ease-out, border-color 0.2s ease;
    background-size: 140% 140%;
    background-position: 0% 50%;
    text-align: left;
    pointer-events: auto;
  }

  .resume-chat-card:hover {
    background-color: transparent;
    border-color: rgba(255, 255, 255, 0.24);
    background-position: 100% 50%;
    transform: translateY(-1px);
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.18), 0 3px 8px rgba(0, 0, 0, 0.12);
  }

  .resume-chat-card:active {
    background-color: transparent;
    transform: scale(0.98);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12), 0 1px 3px rgba(0, 0, 0, 0.08);
    filter: none;
  }

  .resume-chat-card:focus {
    outline: 2px solid rgba(255, 255, 255, 0.5);
    outline-offset: 2px;
  }

  .resume-chat-compact-icon {
    width: 18px;
    min-width: 18px;
    height: 18px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    opacity: 0.96;
  }

  .resume-chat-compact-icon :global(svg) {
    width: 18px;
    height: 18px;
  }

  .resume-chat-content {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-align: left;
  }

  .resume-chat-title {
    font-weight: 600;
    color: rgba(255, 255, 255, 0.96);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    display: block;
    text-shadow: 0 1px 4px rgba(0, 0, 0, 0.22);
  }

  .resume-chat-summary {
    display: block;
    margin-top: 2px;
    color: rgba(255, 255, 255, 0.78);
    font-size: var(--font-size-xxs);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .resume-chat-kind-badge {
    align-self: flex-start;
    display: inline-flex;
    align-items: center;
    width: fit-content;
    border-radius: var(--radius-full);
    padding: 3px 7px;
    background: rgba(255, 255, 255, 0.18);
    color: rgba(255, 255, 255, 0.94);
    font-size: 0.66rem;
    font-weight: 700;
    line-height: 1;
    letter-spacing: 0.01em;
    text-shadow: 0 1px 3px rgba(0, 0, 0, 0.22);
    backdrop-filter: blur(10px);
  }

  .resume-chat-kind-badge.compact {
    margin-bottom: 3px;
  }

  .resume-chat-arrow {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    opacity: 0.82;
  }

  .workspace-composer-slot {
    position: absolute;
    left: 50%;
    right: auto;
    bottom: 0;
    transform: translateX(-50%);
    width: 100%;
    display: grid;
    gap: var(--spacing-4);
    z-index: var(--z-index-raised-2);
    pointer-events: auto;
    padding: 15px;
    box-sizing: border-box;
    justify-items: center;
  }

  .resume-chat-large-card {
    position: relative;
    width: 300px;
    min-width: 300px;
    max-width: 300px;
    height: 200px;
    min-height: 200px;
    max-height: 200px;
    border-radius: 30px;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    border: none;
    padding: 0;
    background-color: transparent;
    pointer-events: auto;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.16), 0 2px 6px rgba(0, 0, 0, 0.1);
    transition: transform 0.15s ease-out, box-shadow 0.2s ease-out;
  }

  .resume-chat-large-card:hover {
    transform: scale(0.98);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12), 0 1px 3px rgba(0, 0, 0, 0.08);
  }

  .resume-chat-large-card:active {
    transform: scale(0.96);
    transition: transform 0.05s ease-out;
  }

  .resume-chat-large-card:focus {
    outline: 2px solid rgba(255, 255, 255, 0.5);
    outline-offset: 2px;
  }

  .resume-large-content {
    position: relative;
    z-index: var(--z-index-raised-3);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-2);
    padding: var(--spacing-8) var(--spacing-12);
    max-width: 260px;
    width: 100%;
    text-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
  }

  .resume-large-content .resume-chat-kind-badge {
    align-self: center;
  }

  .resume-large-icon {
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .resume-large-title {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    font-size: var(--font-size-p);
    font-weight: 700;
    color: var(--color-font-button);
    text-align: center;
    line-height: 1.3;
    max-width: 100%;
  }

  .resume-large-summary {
    margin: 2px 0 0;
    font-size: var(--font-size-xxs);
    font-weight: 500;
    color: rgba(255, 255, 255, 0.85);
    line-height: 1.4;
    text-align: center;
    display: -webkit-box;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .resume-large-orbs {
    position: absolute;
    inset: 0;
    z-index: -1;
    pointer-events: none;
    overflow: hidden;
    border-radius: 30px;
  }

  .resume-orb {
    position: absolute;
    width: 280px;
    height: 240px;
    background: radial-gradient(ellipse at center, var(--orb-color-b) 0%, var(--orb-color-b) 40%, transparent 85%);
    filter: blur(22px);
    opacity: 0.35;
    will-change: transform, border-radius;
  }

  .resume-orb-1 {
    top: -60px;
    left: -70px;
    animation: orbMorph1 11s ease-in-out infinite, resumeOrbDrift1 19s ease-in-out infinite;
  }

  .resume-orb-2 {
    bottom: -80px;
    right: -80px;
    width: 260px;
    height: 220px;
    animation: orbMorph2 13s ease-in-out infinite, resumeOrbDrift2 23s ease-in-out infinite;
  }

  .resume-orb-3 {
    top: -10px;
    left: 25%;
    width: 200px;
    height: 180px;
    opacity: 0.38;
    animation: orbMorph3 17s ease-in-out infinite, resumeOrbDrift3 29s ease-in-out infinite;
  }

  .resume-large-deco {
    position: absolute;
    width: 80px;
    height: 80px;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: var(--z-index-raised);
    pointer-events: none;
    --float-rx: 7px;
    --float-ry: 8px;
    --deco-target-opacity: 0.3;
    animation: decoEnter 0.6s ease-out 0.1s both, decoFloat 16s linear 0.7s infinite;
  }

  .resume-large-deco-left {
    left: -10px;
    bottom: -8px;
    --deco-rotate: -15deg;
  }

  .resume-large-deco-right {
    right: -10px;
    bottom: -8px;
    --deco-rotate: 15deg;
    animation-delay: 0.1s, -8s;
  }

  @media (prefers-reduced-motion: reduce) {
    .resume-orb,
    .resume-large-deco {
      animation: none !important;
    }
  }

  @media (min-height: 800px) {
    .recent-chats-scroll-container {
      padding: 35px 48px 12px calc(50% - 150px);
    }
  }

  @media (max-width: 730px) {
    .workspace-home-shell {
      min-height: 0;
      padding: 0;
    }

    .workspace-center-content .welcome-text h2 {
      font-size: var(--font-size-h2-mobile);
      line-height: 1.08;
    }

    .workspace-center-content.center-content {
      top: calc(50% + 13vh);
    }

    .workspace-home-shell[data-surface='workflows'] .workspace-center-content.center-content {
      top: 25%;
    }

    .recent-chats-scroll-container {
      padding-left: calc(50% - 150px);
      padding-right: 48px;
    }

    .workspace-composer-slot {
      padding-inline: var(--spacing-5);
    }
  }
</style>
