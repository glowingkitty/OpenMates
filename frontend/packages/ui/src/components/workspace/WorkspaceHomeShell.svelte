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
  import WorkspaceContinueCard from './WorkspaceContinueCard.svelte';
  import WorkspaceReportIssueButton from './WorkspaceReportIssueButton.svelte';
  import { getContinueGradientColors, getResumeCardGradientStyle } from '../activeChatUtils';
  import { loadDefaultInspirations } from '../../demo_chats/loadDefaultInspirations';
  import type { DailyInspiration } from '../../stores/dailyInspirationStore';
  import { getLucideIcon, getValidIconName } from '../../utils/categoryUtils';

  type WorkspaceSurface = 'chats' | 'projects' | 'workflows' | 'tasks' | 'plans' | 'teams';

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
    centerTestId?: string;
    contentSlotVisible?: boolean;
    contentSlotTestId?: string;
    showReportIssue?: boolean;
    showAllMode?: boolean;
    showAllLabel?: string;
    showAllTestId?: string;
    allItems?: ContinueItem[];
    allItemsViewTestId?: string;
    allItemsGridTestId?: string;
    allItemsToolbarTestId?: string;
    allItemTestId?: string;
    backLabel?: string;
    backTestId?: string;
    searchLabel?: string;
    searchTestId?: string;
    onContinueItem?: (item: ContinueItem) => void;
    onActionItem?: (item: ContinueItem) => void;
    onAllItem?: (item: ContinueItem) => void;
    onStartInspiration?: (inspiration: DailyInspiration) => void;
    onShowAll?: () => void;
    onBackToRecent?: () => void;
    onSearchAll?: () => void;
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
    centerTestId = `${surface}-workspace-center`,
    contentSlotVisible = false,
    contentSlotTestId = `${surface}-workspace-content`,
    showReportIssue = false,
    showAllMode = false,
    showAllLabel = '',
    showAllTestId = `${surface}-show-all`,
    allItems = [],
    allItemsViewTestId = `${surface}-all-items-view`,
    allItemsGridTestId = `${surface}-all-items-grid`,
    allItemsToolbarTestId = `${surface}-all-items-toolbar`,
    allItemTestId = itemTestId,
    backLabel = 'Back to recent',
    backTestId = `${surface}-back-to-recent`,
    searchLabel = 'Search',
    searchTestId = `${surface}-search`,
    onContinueItem,
    onActionItem,
    onAllItem,
    onStartInspiration,
    onShowAll,
    onBackToRecent,
    onSearchAll,
  }: Props = $props();

  let containerWidth = $state(0);
  let viewportWidth = $state(typeof window !== 'undefined' ? window.innerWidth : 1200);
  let viewportHeight = $state(typeof window !== 'undefined' ? window.innerHeight : 800);
  let isTallViewport = $derived(viewportHeight >= 800 && viewportWidth >= 550);
  let hasShowAllLink = $derived(!!onShowAll && showAllLabel.trim().length > 0 && !showAllMode);
  let hasBrowseControls = $derived(!showAllMode && (hasShowAllLink || !!onSearchAll));
  let hasAllItemsToolbar = $derived(showAllMode && (!!onBackToRecent || !!onSearchAll));
  let showTopButtons = $derived(showReportIssue || hasAllItemsToolbar);
  const ChevronRight = getLucideIcon('chevron-right');
  const AllItemsBackIcon = getLucideIcon('grid-2x2');
  const AllItemsSearchIcon = getLucideIcon('search');

  onMount(() => {
    void loadDefaultInspirations({ surface, allowIndexedDB: false });
    const handleResize = () => {
      viewportWidth = window.innerWidth;
      viewportHeight = window.innerHeight;
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  });

  function handleStartInspiration(inspiration: DailyInspiration): void {
    onStartInspiration?.(inspiration);
  }

  function handleContinueItem(item: ContinueItem): void {
    onContinueItem?.(item);
  }

  function handleActionItem(item: ContinueItem): void {
    onActionItem?.(item);
  }

  function handleAllItem(item: ContinueItem): void {
    onAllItem?.(item);
  }

  function handleShowAll(): void {
    onShowAll?.();
  }

  function handleBackToRecent(): void {
    onBackToRecent?.();
  }

  function handleSearchAll(): void {
    onSearchAll?.();
  }

  function continueCardStyle(item: ContinueItem): string {
    return getResumeCardGradientStyle(getContinueGradientColors(item.category ?? 'productivity', item.appId));
  }

</script>

<section class="workspace-home-shell" class:all-items-mode={showAllMode} class:content-slot-mode={contentSlotVisible} data-testid={testId} data-surface={surface} bind:clientWidth={containerWidth}>
  <div class="workspace-scroll-layer" data-testid={contentSlotVisible ? `${surface}-workspace-scroll-layer` : undefined}>
    {#if !showAllMode}
      <div class="daily-inspiration-area workspace-daily-inspiration-area" data-testid={`${surface}-daily-inspiration-area`}>
        <DailyInspirationBanner
          {surface}
          onStartChat={handleStartInspiration}
          containerWidth={containerWidth}
        />
      </div>
    {/if}

    {#if showTopButtons}
      <div class="workspace-top-buttons" class:workspace-all-items-top-buttons={showAllMode}>
        <div class="workspace-left-buttons">
          {#if showReportIssue}
            <WorkspaceReportIssueButton />
          {/if}
        </div>
        {#if hasAllItemsToolbar}
          <div class="workspace-all-items-toolbar" data-testid={allItemsToolbarTestId}>
            {#if onBackToRecent}
              <button type="button" class="workspace-all-items-action" data-testid={backTestId} onclick={handleBackToRecent}>
                <AllItemsBackIcon size={18} color="currentColor" />
                <span>{backLabel}</span>
              </button>
            {/if}
            {#if onSearchAll}
              <button type="button" class="workspace-all-items-action" data-testid={searchTestId} onclick={handleSearchAll}>
                <AllItemsSearchIcon size={18} color="currentColor" />
                <span>{searchLabel}</span>
              </button>
            {/if}
          </div>
        {/if}
        <div class="workspace-right-buttons"></div>
      </div>
    {/if}

    <div class="center-content workspace-center-content" data-testid={centerTestId}>
    {#if showAllMode}
      <div class="workspace-all-items-view" data-testid={allItemsViewTestId}>
        <div class="workspace-all-items-grid" data-testid={allItemsGridTestId}>
          {#each allItems as item (item.id)}
            <WorkspaceContinueCard
              title={item.title}
              summary={item.summary ?? null}
              badge={item.badge ?? null}
              category={item.category ?? 'productivity'}
              appId={item.appId ?? surface}
              icon={item.icon ?? 'sparkles'}
              testId={allItemTestId}
              href={null}
              source={item.source ?? null}
              fluid
              onActivate={() => handleAllItem(item)}
            />
          {/each}
        </div>
      </div>
    {:else}
    <div class="team-profile">
      <div class="welcome-text">
        {#if eyebrow}
          <p class="workspace-eyebrow">{eyebrow}</p>
        {/if}
        <span class="workspace-surface-background-icon" data-testid={`${surface}-workspace-background-icon`} data-surface={surface} aria-hidden="true"></span>
        <h2>{heading}</h2>
        {#if subtitle}
          <p class="workspace-subtitle">{subtitle}</p>
        {/if}
      </div>
    </div>

    {#if actionItems.length > 0}
      <div class="recent-chats-scroll-container" class:centered-row={actionItems.length <= 3} data-testid={actionItemsTestId}>
        {#each actionItems as item (item.id)}
          {@const iconName = getValidIconName(item.icon ?? 'sparkles', item.category ?? 'productivity')}
          {@const IconComponent = getLucideIcon(iconName)}
          {#if isTallViewport}
            <WorkspaceContinueCard
              title={item.title}
              summary={item.summary ?? null}
              badge={item.badge ?? null}
              category={item.category ?? 'productivity'}
              appId={item.appId ?? surface}
              icon={item.icon ?? 'sparkles'}
              testId={itemTestId}
              href={null}
              source={item.source ?? null}
              fluid={false}
              onActivate={() => handleActionItem(item)}
            />
          {:else}
            <button
              type="button"
              class="resume-chat-card"
              data-testid={itemTestId}
              data-card-source={item.source ?? undefined}
              data-category={item.category ?? undefined}
              data-icon={iconName}
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
      {#if hasBrowseControls}
        <div class="workspace-link-row" data-testid={`${surface}-workspace-link-row`}>
          {#if hasShowAllLink}
            <button type="button" class="workspace-show-all-link" data-testid={showAllTestId} data-surface={surface} onclick={handleShowAll}>
              <span class="workspace-link-icon workspace-link-icon-surface" aria-hidden="true"></span>
              <span>{showAllLabel}</span>
            </button>
          {/if}
          {#if onSearchAll}
            <button type="button" class="workspace-show-all-link" data-testid={searchTestId} onclick={handleSearchAll}>
              <AllItemsSearchIcon size={18} color="currentColor" />
              <span>{searchLabel}</span>
            </button>
          {/if}
        </div>
      {/if}
    {:else if continueItems.length > 0}
      <div class="workspace-continue-section" data-testid={continueSectionTestId}>
        <div class="workspace-continue-label">{continueLabel}</div>
        <div class="recent-chats-scroll-container" data-testid="recent-chats-scroll-container">
        {#each continueItems as item (item.id)}
          {@const iconName = getValidIconName(item.icon ?? 'sparkles', item.category ?? 'productivity')}
          {@const IconComponent = getLucideIcon(iconName)}
          {#if isTallViewport}
            <WorkspaceContinueCard
              title={item.title}
              summary={item.summary ?? null}
              badge={item.badge ?? null}
              category={item.category ?? 'productivity'}
              appId={item.appId ?? surface}
              icon={item.icon ?? 'sparkles'}
              testId="resume-chat-large-card"
              href={null}
              source={item.source ?? null}
              fluid={false}
              onActivate={() => handleContinueItem(item)}
            />
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
    {/if}
    </div>

    {#if contentSlotVisible}
      <div class="workspace-content-slot" data-testid={contentSlotTestId}>
        <slot />
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
    background: var(--color-grey-20);
    box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
    color: var(--color-font-primary);
    overflow: hidden;
  }

  .workspace-scroll-layer {
    position: relative;
    width: 100%;
    height: 100%;
    min-height: 0;
    overflow: hidden;
  }

  .workspace-home-shell.content-slot-mode .workspace-scroll-layer {
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    overflow-x: hidden;
    padding-bottom: clamp(108px, 16vh, 152px);
    box-sizing: border-box;
    -webkit-overflow-scrolling: touch;
  }

  .workspace-daily-inspiration-area {
    --daily-inspiration-area-height: clamp(190px, 50.9383cqi, 420px);
    width: 100%;
    height: var(--daily-inspiration-area-height);
    min-height: 250px;
    max-height: 35dvh;
    flex: 0 0 var(--daily-inspiration-area-height);
    max-width: none;
    margin: 0;
    box-sizing: border-box;
  }

  .workspace-top-buttons {
    position: static;
    z-index: var(--z-index-raised-3);
    display: flex;
    width: 100%;
    align-items: center;
    justify-content: space-between;
    padding: 10px 15px 0;
    box-sizing: border-box;
    pointer-events: none;
  }

  .workspace-left-buttons,
  .workspace-right-buttons {
    display: flex;
    min-width: 44px;
    align-items: center;
    gap: var(--spacing-3);
    pointer-events: auto;
  }

  .workspace-right-buttons {
    justify-content: flex-end;
  }

  .workspace-all-items-top-buttons {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    column-gap: var(--spacing-6);
  }

  .workspace-all-items-toolbar {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-8);
    color: var(--color-grey-60);
    pointer-events: auto;
  }

  .workspace-all-items-action {
    appearance: none;
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-2);
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    font-size: var(--font-size-p);
    font-weight: 800;
    cursor: pointer;
    padding: 0;
    box-shadow: none;
    text-shadow: none;
    filter: none;
  }

  .workspace-all-items-action:hover {
    color: var(--color-primary);
    box-shadow: none;
    text-shadow: none;
    filter: none;
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

  .workspace-home-shell.content-slot-mode .workspace-center-content.center-content {
    position: relative;
    top: auto;
    left: auto;
    transform: none;
    flex-shrink: 0;
    margin-top: clamp(22px, 4.5vh, 56px);
  }

  .workspace-home-shell.all-items-mode .workspace-center-content.center-content {
    top: 50%;
  }

  .workspace-all-items-view {
    width: min(100% - 32px, 1120px);
    max-height: min(68vh, 760px);
    display: flex;
    flex-direction: column;
    pointer-events: auto;
  }

  .workspace-all-items-grid {
    --workspace-all-items-fade-size: 34px;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 300px));
    justify-content: center;
    gap: var(--spacing-8);
    max-height: min(58vh, 620px);
    overflow-y: auto;
    padding: var(--workspace-all-items-fade-size) var(--spacing-4);
    box-sizing: border-box;
    scrollbar-width: thin;
    -webkit-mask-image: linear-gradient(
      to bottom,
      transparent 0,
      black var(--workspace-all-items-fade-size),
      black calc(100% - var(--workspace-all-items-fade-size)),
      transparent 100%
    );
    mask-image: linear-gradient(
      to bottom,
      transparent 0,
      black var(--workspace-all-items-fade-size),
      black calc(100% - var(--workspace-all-items-fade-size)),
      transparent 100%
    );
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

  .workspace-center-content .welcome-text {
    position: relative;
    isolation: isolate;
  }

  .workspace-surface-background-icon {
    position: absolute;
    left: 50%;
    top: 50%;
    z-index: -1;
    width: clamp(76px, 11vw, 128px);
    height: clamp(76px, 11vw, 128px);
    background: var(--color-grey-30);
    transform: translate(-50%, -54%);
    pointer-events: none;
    -webkit-mask: url('@openmates/ui/static/icons/chat.svg') center / contain no-repeat;
    mask: url('@openmates/ui/static/icons/chat.svg') center / contain no-repeat;
  }

  .workspace-surface-background-icon[data-surface='projects'] {
    -webkit-mask-image: url('@openmates/ui/static/icons/project.svg');
    mask-image: url('@openmates/ui/static/icons/project.svg');
  }

  .workspace-surface-background-icon[data-surface='plans'] {
    -webkit-mask-image: url('@openmates/ui/static/icons/task.svg');
    mask-image: url('@openmates/ui/static/icons/task.svg');
  }

  .workspace-surface-background-icon[data-surface='workflows'] {
    -webkit-mask-image: url('@openmates/ui/static/icons/workflow.svg');
    mask-image: url('@openmates/ui/static/icons/workflow.svg');
  }

  .workspace-surface-background-icon[data-surface='tasks'] {
    -webkit-mask-image: url('@openmates/ui/static/icons/projectmanagement.svg');
    mask-image: url('@openmates/ui/static/icons/projectmanagement.svg');
  }

  .workspace-surface-background-icon[data-surface='teams'] {
    -webkit-mask-image: url('@openmates/ui/static/icons/team.svg');
    mask-image: url('@openmates/ui/static/icons/team.svg');
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

  .workspace-content-slot {
    width: min(100% - 48px, 1860px);
    margin: clamp(34px, 8vh, 92px) auto 0;
    pointer-events: auto;
  }

  .workspace-home-shell.content-slot-mode .workspace-daily-inspiration-area {
    flex-shrink: 0;
  }

  .workspace-link-row {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-3);
    margin-top: var(--spacing-1);
    pointer-events: auto;
  }

  .workspace-show-all-link {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-2);
    border: none;
    background: transparent;
    padding: var(--spacing-1) 0 0;
    color: var(--color-grey-60);
    font: inherit;
    font-size: 0.92rem;
    font-weight: 720;
    cursor: pointer;
    text-decoration: none;
    box-shadow: none;
    filter: none;
  }

  .workspace-show-all-link:hover {
    text-decoration: underline;
    text-underline-offset: 3px;
  }

  .workspace-link-icon {
    width: 14px;
    height: 14px;
    display: inline-block;
    flex-shrink: 0;
    background: currentColor;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-size: contain;
    mask-size: contain;
  }

  .workspace-link-icon-surface {
    -webkit-mask-image: url('@openmates/ui/static/icons/chat.svg');
    mask-image: url('@openmates/ui/static/icons/chat.svg');
  }

  .workspace-show-all-link[data-surface='projects'] .workspace-link-icon-surface {
    -webkit-mask-image: url('@openmates/ui/static/icons/project.svg');
    mask-image: url('@openmates/ui/static/icons/project.svg');
  }

  .workspace-show-all-link[data-surface='workflows'] .workspace-link-icon-surface {
    -webkit-mask-image: url('@openmates/ui/static/icons/workflow.svg');
    mask-image: url('@openmates/ui/static/icons/workflow.svg');
  }

  .workspace-show-all-link[data-surface='tasks'] .workspace-link-icon-surface {
    -webkit-mask-image: url('@openmates/ui/static/icons/projectmanagement.svg');
    mask-image: url('@openmates/ui/static/icons/projectmanagement.svg');
  }

  .workspace-show-all-link[data-surface='plans'] .workspace-link-icon-surface {
    -webkit-mask-image: url('@openmates/ui/static/icons/task.svg');
    mask-image: url('@openmates/ui/static/icons/task.svg');
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

  .recent-chats-scroll-container.secondary {
    padding-top: 8px;
  }

  @media (min-width: 1100px) {
    .recent-chats-scroll-container.centered-row {
      justify-content: center;
      padding-inline: 48px;
    }
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

  .workspace-home-shell.content-slot-mode .workspace-composer-slot {
    background: linear-gradient(to bottom, transparent 0%, color-mix(in srgb, var(--color-grey-0) 92%, transparent) 40%, var(--color-grey-0) 100%);
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

    .workspace-daily-inspiration-area {
      --daily-inspiration-area-height: 190px;
      min-height: 190px;
    }

    .workspace-center-content .welcome-text h2 {
      font-size: var(--font-size-h2-mobile);
      line-height: 1.08;
    }

    .workspace-center-content.center-content {
      top: calc(50% + 13vh);
    }

    .workspace-home-shell.content-slot-mode .workspace-center-content.center-content {
      top: auto;
      margin-top: clamp(18px, 4vh, 36px);
    }

    .workspace-surface-background-icon {
      width: 76px;
      height: 76px;
    }

    .workspace-home-shell[data-surface='workflows'] .workspace-center-content.center-content {
      top: 32%;
    }

    .workspace-home-shell.all-items-mode .workspace-center-content.center-content {
      top: 50%;
    }

    .workspace-all-items-view {
      width: min(100% - 20px, 1120px);
      max-height: min(64vh, 680px);
    }

    .workspace-all-items-toolbar {
      gap: var(--spacing-5);
    }

    .workspace-all-items-action {
      font-size: var(--font-size-small);
    }

    .workspace-all-items-grid {
      grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
      max-height: min(56vh, 560px);
    }

    .recent-chats-scroll-container {
      padding-left: calc(50% - 150px);
      padding-right: 48px;
    }

    .workspace-composer-slot {
      padding-inline: 0;
      padding-bottom: var(--spacing-5);
    }

    .workspace-home-shell.content-slot-mode .workspace-scroll-layer {
      padding-bottom: 118px;
    }

    .workspace-content-slot {
      width: min(100% - 28px, 1860px);
      margin-top: clamp(28px, 6vh, 54px);
    }
  }
</style>
