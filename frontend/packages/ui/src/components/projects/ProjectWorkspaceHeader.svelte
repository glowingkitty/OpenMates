<!--
  Figma-aligned Project hero. The shared WorkspaceDetailHeader keeps the
  established inline editing contract while this component owns Project-only
  actions and the persistent blue workspace treatment.
-->
<script lang="ts">
  import HeaderActionMenu from '../HeaderActionMenu.svelte';
  import WorkspaceDetailHeader from '../workspace/WorkspaceDetailHeader.svelte';
  import WorkspaceReportIssueButton from '../workspace/WorkspaceReportIssueButton.svelte';
  import { headerOverlayControls } from '../../actions/headerOverlayControls';
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
</script>

<section class="project-workspace-header" data-testid="project-workspace-header" data-header-system="workspace-detail">
  <div class="project-header-actions" use:headerOverlayControls>
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
    position: absolute;
    inset-block-start: var(--spacing-6);
    inset-inline: var(--spacing-6);
    z-index: 2;
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

    .project-header-actions { inset-block-start: var(--spacing-4); inset-inline: var(--spacing-4); }
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
