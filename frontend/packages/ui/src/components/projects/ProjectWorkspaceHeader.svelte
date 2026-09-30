<!--
  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Projects/ProjectsWorkspaceView.swift
  Figma-aligned Project hero. The shared WorkspaceDetailHeader keeps the
  established inline editing contract while this component owns Project-only
  actions and the persistent blue workspace treatment.
-->
<script lang="ts">
  import HeaderActionMenu from '../HeaderActionMenu.svelte';
  import WorkspaceDetailHeader from '../workspace/WorkspaceDetailHeader.svelte';
  import WorkspaceReportIssueButton from '../workspace/WorkspaceReportIssueButton.svelte';
  import { tooltip } from '../../actions/tooltip';

  interface Props {
    title: string;
    description: string;
    icon: string;
    startedAt: number;
    onSaveTitle: (title: string) => void | Promise<void>;
    onSaveDescription: (description: string) => void | Promise<void>;
    onSettings: () => void;
    onDelete: () => void;
    onClose: () => void;
  }

  let {
    title,
    description,
    icon,
    startedAt,
    onSaveTitle,
    onSaveDescription,
    onSettings,
    onDelete,
    onClose,
  }: Props = $props();

  const startedLabel = $derived(formatStartedDate(startedAt));

  function formatStartedDate(timestamp: number): string {
    if (!Number.isFinite(timestamp) || timestamp <= 0) return 'Started recently';
    const date = new Date(timestamp < 10_000_000_000 ? timestamp * 1000 : timestamp);
    const today = new Date();
    const sameDay = date.toDateString() === today.toDateString();
    const day = sameDay
      ? 'today'
      : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: date.getFullYear() === today.getFullYear() ? undefined : 'numeric' });
    return `Started ${day}, ${date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`;
  }

  function projectHeaderControls(node: HTMLElement) {
    const header = node.closest<HTMLElement>('.project-workspace-header');
    const pane = node.closest<HTMLElement>('.projects-page');
    if (!header || !pane) return {};

    let frame: number | null = null;
    const resizeObserver = new ResizeObserver(schedule);
    const mutations = new MutationObserver(schedule);

    function measure() {
      const paneBounds = pane!.getBoundingClientRect();
      // Fixed descendants use viewport coordinates here. Keep the toolbar
      // aligned with the project pane as the app shell or split view moves it.
      node.style.setProperty('--project-pane-top', `${paneBounds.top}px`);
      node.style.left = `${paneBounds.left}px`;
      node.style.width = `${paneBounds.width}px`;

      const banner = header!.getBoundingClientRect();
      for (const control of node.querySelectorAll<HTMLElement>('.new-chat-button-wrapper, .button-wrapper')) {
        const bounds = control.getBoundingClientRect();
        const overlaps = !control.closest('[data-header-overlay-disabled]') &&
          bounds.bottom > banner.top && bounds.top < banner.bottom &&
          bounds.right > banner.left && bounds.left < banner.right;
        control.toggleAttribute('data-header-overlay', overlaps);
      }
    }

    function schedule() {
      if (frame === null) frame = requestAnimationFrame(() => {
        frame = null;
        measure();
      });
    }

    mutations.observe(node, { childList: true, subtree: true });
    resizeObserver.observe(header);
    // Pane position can move without its size changing (for example when the
    // app shell or a side-by-side viewer changes layout). Watch only its
    // ancestor chain so those layout changes remeasure the fixed coordinates.
    for (let ancestor: HTMLElement | null = pane; ancestor; ancestor = ancestor.parentElement) {
      resizeObserver.observe(ancestor);
      mutations.observe(ancestor, {
        attributes: true,
        attributeFilter: ['class', 'style'],
        childList: ancestor !== document.body,
      });
      if (ancestor === document.body) break;
    }
    window.addEventListener('scroll', schedule, { capture: true, passive: true });
    window.addEventListener('resize', schedule);
    measure();

    return {
      destroy() {
        if (frame !== null) cancelAnimationFrame(frame);
        resizeObserver.disconnect();
        mutations.disconnect();
        window.removeEventListener('scroll', schedule, true);
        window.removeEventListener('resize', schedule);
      },
    };
  }
</script>

<section class="project-workspace-header" data-testid="project-workspace-header" data-header-system="workspace-detail">
  <div class="project-header-actions" data-testid="project-header-actions" use:projectHeaderControls>
    <HeaderActionMenu hasShare={false} actionCount={2} forceOverflow triggerTestId="project-more-button" resetKey={title}>
      {#snippet report()}<WorkspaceReportIssueButton toolbar />{/snippet}
      {#snippet share()}{/snippet}
      {#snippet actions()}
        <div class="new-chat-button-wrapper">
          <button type="button" class="header-action" data-testid="project-settings-button" aria-label="Project settings" onclick={onSettings} use:tooltip>
            <span class="clickable-icon icon_settings top-button" aria-hidden="true"></span><span class="action-label">Settings</span>
          </button>
        </div>
        <div class="new-chat-button-wrapper danger-action">
          <button type="button" class="header-action" data-testid="project-delete-button" aria-label="Delete project" onclick={onDelete} use:tooltip>
            <span class="clickable-icon icon_delete top-button" aria-hidden="true"></span><span class="action-label">Delete project</span>
          </button>
        </div>
      {/snippet}
      {#snippet close()}
        <div class="new-chat-button-wrapper">
          <button type="button" class="header-action" data-testid="project-detail-back" aria-label="Close project" onclick={onClose} use:tooltip>
            <span class="clickable-icon icon_close top-button" aria-hidden="true"></span><span class="action-label">Close</span>
          </button>
        </div>
      {/snippet}
    </HeaderActionMenu>
  </div>

  <span class="project-kicker">Project</span>

  <div class="header-details">
    <WorkspaceDetailHeader
      {title}
      {description}
      category="productivity"
      {icon}
      writable={true}
      {onSaveTitle}
      {onSaveDescription}
      embedded
      iconTestId="project-workspace-icon"
    />
    <span class="started-date" data-testid="project-started-date">{startedLabel}</span>
  </div>
</section>

<style>
  .project-workspace-header {
    position: relative;
    z-index: var(--z-index-raised-3);
    display: grid;
    min-height: clamp(18rem, 46vh, 26.25rem);
    place-items: center;
    overflow: hidden;
    border-radius: 0 0 var(--radius-5) var(--radius-5);
    background:
      radial-gradient(circle at 75% 85%, color-mix(in srgb, var(--color-app-weather-end) 72%, transparent), transparent 48%),
      linear-gradient(135deg, color-mix(in srgb, var(--color-app-weather-start) 78%, var(--color-primary-start)), color-mix(in srgb, var(--color-app-weather-end) 55%, var(--color-primary-end)));
    box-shadow: var(--shadow-sm);
    color: var(--color-font-button);
    isolation: isolate;
  }

  .project-workspace-header::after {
    position: absolute;
    inset: 0;
    z-index: -1;
    background: linear-gradient(115deg, color-mix(in srgb, var(--color-grey-100) 12%, transparent), transparent 54%);
    content: '';
  }

  .project-kicker {
    position: absolute;
    inset-block-start: var(--spacing-8);
    inset-inline-start: 50%;
    transform: translateX(-50%);
    font-size: var(--font-size-small);
    font-weight: 700;
  }

  .project-header-actions {
    position: fixed;
    top: calc(var(--project-pane-top, 0px) + var(--spacing-6));
    z-index: var(--z-index-dropdown-1);
    box-sizing: border-box;
    padding-inline: var(--spacing-6);
    pointer-events: none;
  }

  .project-header-actions :global(.new-chat-button-wrapper) {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--spacing-4);
    border-radius: var(--radius-full);
    background: var(--color-grey-10);
    box-shadow: var(--shadow-md);
    pointer-events: auto;
  }

  .project-header-actions :global(.danger-action .header-action) { color: var(--color-error); }

  .header-details {
    display: grid;
    width: min(44rem, calc(100% - 6rem));
    gap: var(--spacing-12);
    text-align: center;
  }

  .header-details :global(.workspace-detail-header) { color: inherit; }
  .header-details :global(.header-content) { gap: var(--spacing-5); }
  .header-details :global(.header-icon) { height: 3rem; }
  .header-details :global(.header-icon svg) { width: 3rem; height: 3rem; }
  .header-details :global(.title-value),
  .header-details :global(.title-input) { font-size: var(--font-size-h2); }
  .header-details :global(.description-value),
  .header-details :global(textarea) { font-weight: 600; }

  .started-date {
    position: absolute;
    inset-block-end: var(--spacing-8);
    inset-inline-start: 50%;
    transform: translateX(-50%);
    font-size: var(--font-size-small);
    font-weight: 700;
    white-space: nowrap;
  }

  @media (max-width: 730px) {
    .project-workspace-header {
      min-height: 16.25rem;
      border-radius: 0 0 var(--radius-5) var(--radius-5);
    }

    .project-header-actions { top: calc(var(--project-pane-top, 0px) + var(--spacing-4)); padding-inline: var(--spacing-4); }
    .project-kicker { inset-block-start: var(--spacing-5); }
    .header-details { width: calc(100% - 2rem); gap: var(--spacing-8); padding-top: var(--spacing-8); }
    .header-details :global(.header-content) { gap: var(--spacing-4); }
    .header-details :global(.title-value),
    .header-details :global(.title-input) { font-size: var(--font-size-h3); }
  }

  @media (prefers-reduced-motion: reduce) {
    .project-header-actions :global(.new-chat-button-wrapper) { transition: none; }
  }
</style>
