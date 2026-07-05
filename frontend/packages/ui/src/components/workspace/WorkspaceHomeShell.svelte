<!--
  Shared workspace home shell for OpenMates surfaces.
  Keeps DailyInspirationBanner and continue-card layout reusable across
  chats-adjacent workspaces without importing chat sync, drafts, or message DB.
  Surface-specific pages provide only content, callbacks, and composer actions.
  The shared class names intentionally match the chat welcome screen.
-->

<script lang="ts">
  import DailyInspirationBanner from '../DailyInspirationBanner.svelte';
  import { getContinueGradientColors, getResumeCardGradientStyle } from '../activeChatUtils';
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
  };

  type Props = {
    surface: WorkspaceSurface;
    testId?: string;
    eyebrow: string;
    heading: string;
    subtitle?: string;
    continueLabel?: string;
    continueItems?: ContinueItem[];
    onContinueItem?: (item: ContinueItem) => void;
    onStartInspiration?: (inspiration: WorkspaceInspiration) => void;
  };

  let {
    surface,
    testId = `${surface}-workspace-home`,
    eyebrow,
    heading,
    subtitle = '',
    continueLabel = 'Continue where you left off',
    continueItems = [],
    onContinueItem,
    onStartInspiration,
  }: Props = $props();

  let containerWidth = $state(0);
  const ChevronRight = getLucideIcon('chevron-right');

  function handleStartInspiration(inspiration: WorkspaceInspiration): void {
    onStartInspiration?.(inspiration);
  }

  function handleContinueItem(item: ContinueItem): void {
    onContinueItem?.(item);
  }

  function continueCardStyle(item: ContinueItem): string {
    return getResumeCardGradientStyle(getContinueGradientColors(item.category ?? 'productivity', item.appId));
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
        <p>{eyebrow}</p>
        <h2>{heading}</h2>
        {#if subtitle}
          <p>{subtitle}</p>
        {/if}
      </div>
    </div>

    {#if continueItems.length > 0}
      <div class="workspace-continue-label">{continueLabel}</div>
      <div class="recent-chats-scroll-container" data-testid="recent-chats-scroll-container">
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
    {/if}
  </div>

  <div class="workspace-surface-actions">
    <slot name="actions" />
  </div>

  <div class="workspace-composer-slot">
    <slot name="composer" />
  </div>
</section>

<style>
  .workspace-home-shell {
    min-height: min(900px, calc(100vh - 104px));
    min-height: min(900px, calc(100dvh - 104px));
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: clamp(16px, 3vh, 26px);
    padding: clamp(14px, 2vw, 24px);
    border-radius: var(--radius-16, 32px);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    overflow: hidden;
  }

  .workspace-daily-inspiration-area {
    width: 100%;
    max-width: 1180px;
    flex-shrink: 0;
  }

  .workspace-center-content.center-content {
    position: static;
    transform: none;
    inset: auto;
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

  .workspace-center-content .welcome-text p:first-child {
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
    font-size: clamp(2.4rem, 7vw, 5rem);
    font-weight: 600;
    line-height: 0.98;
    letter-spacing: -0.05em;
  }

  .workspace-center-content .welcome-text p:not(:first-child) {
    margin: 10px 0 0;
    color: var(--color-grey-60);
    font-size: var(--font-size-p);
  }

  .workspace-continue-label {
    margin-top: var(--spacing-6);
    color: var(--color-grey-60);
    font-size: var(--font-size-p);
    font-weight: 600;
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

  .workspace-surface-actions,
  .workspace-composer-slot {
    width: min(920px, 100%);
    display: grid;
    gap: var(--spacing-4);
  }

  @media (min-height: 800px) {
    .recent-chats-scroll-container {
      padding: 35px 48px 12px calc(50% - 150px);
    }
  }

  @media (max-width: 730px) {
    .workspace-home-shell {
      min-height: calc(100vh - 91px);
      min-height: calc(100dvh - 91px);
      align-items: stretch;
      padding: 0;
      gap: var(--spacing-6);
    }

    .workspace-center-content .welcome-text h2 {
      font-size: var(--font-size-h2-mobile);
      line-height: 1.08;
    }

    .recent-chats-scroll-container {
      padding-left: calc(50% - 150px);
      padding-right: 48px;
    }

    .workspace-surface-actions,
    .workspace-composer-slot {
      width: 100%;
      padding-inline: var(--spacing-5);
      box-sizing: border-box;
    }
  }
</style>
