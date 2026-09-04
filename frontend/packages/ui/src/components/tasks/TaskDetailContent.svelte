<!--
  TaskDetailContent.svelte
  Shared read-only Task detail presentation used by the board fullscreen and
  stable /tasks/:task_id route. It resolves linked encrypted workspace names
  client-side while dependency status remains safe server-visible metadata.
  Design reference: Figma Website node 5754:76027.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { SettingsSectionHeading } from '../settings/elements';
  import WorkspaceContinueCard from '../workspace/WorkspaceContinueCard.svelte';
  import TaskActivity from './TaskActivity.svelte';
  import { chatDB } from '../../services/db';
  import { listProjects } from '../../services/projectService';
  import {
    listUserTaskDependencies,
    listUserTasks,
    type UserTaskDependencyViewModel,
    type UserTaskActivityEntry,
    type UserTaskViewModel,
  } from '../../services/userTaskService';
  import { listUserPlans } from '../../services/userPlanService';
  import { userProfile } from '../../stores/userProfile';
  import { text } from '../../i18n/translations';

  interface TaskDetailRelatedData {
    projects: Array<{ id: string; title: string; description: string }>;
    plan: { id: string; title: string; description: string } | null;
    chat: { id: string; title: string } | null;
    dependencies: Array<UserTaskDependencyViewModel & { title: string }>;
  }

  let {
    task,
    related,
    showTitle = true,
    activityEntries,
    teamId,
  }: {
    task: UserTaskViewModel;
    related?: TaskDetailRelatedData;
    showTitle?: boolean;
    activityEntries?: UserTaskActivityEntry[];
    teamId?: string;
  } = $props();

  let resolvedRelated = $state<TaskDetailRelatedData>({ projects: [], plan: null, chat: null, dependencies: [] });
  let relationLoadFailed = $state(false);
  let creatorName = $derived($userProfile.username.trim() || 'You');

  const priorityLabels = ['No priority', 'Low', 'Medium', 'High', 'Urgent'];
  const blockedReasonKeys: Record<string, string> = {
    needs_user_input: 'tasks.blocked_reason.needs_user_input',
    waiting_for_approval: 'tasks.blocked_reason.waiting_for_approval',
    missing_credentials: 'tasks.blocked_reason.missing_credentials',
    ambiguous_requirement: 'tasks.blocked_reason.ambiguous_requirement',
    external_dependency: 'tasks.blocked_reason.external_dependency',
    environment_unavailable: 'tasks.blocked_reason.environment_unavailable',
    verification_failed: 'tasks.blocked_reason.verification_failed',
    other: 'tasks.blocked_reason.other',
  };

  onMount(() => {
    if (related) {
      resolvedRelated = related;
      return;
    }
    void loadRelatedData();
  });

  async function loadRelatedData(): Promise<void> {
    try {
      const dependencies = await listUserTaskDependencies(task.task_id);
      const [projects, plans, tasks, chat] = await Promise.all([
        task.linkedProjectIds.length > 0 ? listProjects() : Promise.resolve([]),
        task.planId || dependencies.some((item) => item.targetKind === 'plan') ? listUserPlans() : Promise.resolve([]),
        dependencies.some((item) => item.targetKind === 'task') ? listUserTasks() : Promise.resolve([]),
        task.primaryChatId ? chatDB.getChat(task.primaryChatId) : Promise.resolve(null),
      ]);
      resolvedRelated = {
        projects: task.linkedProjectIds.map((id) => {
          const project = projects.find((candidate) => candidate.project_id === id);
          return { id, title: project?.name || 'Connected project', description: project?.description || '' };
        }),
        plan: task.planId ? (() => {
          const plan = plans.find((candidate) => candidate.plan_id === task.planId);
          return { id: task.planId, title: plan?.title || 'Connected plan', description: plan?.goal || '' };
        })() : null,
        chat: task.primaryChatId ? { id: task.primaryChatId, title: chat?.title || 'Connected chat' } : null,
        dependencies: dependencies.map((dependency) => {
          const title = dependency.targetKind === 'task'
            ? tasks.find((candidate) => candidate.task_id === dependency.targetId)?.title
            : plans.find((candidate) => candidate.plan_id === dependency.targetId)?.title;
          return { ...dependency, title: title || `${dependency.targetKind === 'task' ? 'Task' : 'Plan'} dependency` };
        }),
      };
    } catch (error) {
      relationLoadFailed = true;
      console.error('[TaskDetailContent] Failed to load linked task context:', error);
    }
  }

  function statusLabel(status: UserTaskViewModel['status']): string {
    return status === 'todo' ? 'To do' : status.replace('_', ' ').replace(/^./, (value) => value.toUpperCase());
  }

  function priorityLabel(priority: number): string {
    return priorityLabels[Math.max(0, Math.min(priorityLabels.length - 1, priority))];
  }

  function assigneeLabel(): string {
    return task.assigneeType === 'ai' ? 'OpenMates' : creatorName;
  }

  function blockedReasonFallback(): string {
    return $text(blockedReasonKeys[task.blockedReasonCode ?? ''] ?? 'tasks.blocked_reason.other');
  }

  function formatDate(timestamp: number): string {
    return new Intl.DateTimeFormat('en-US', { year: 'numeric', month: 'short', day: 'numeric' }).format(new Date(timestamp * 1000));
  }

  function createdLabel(): string {
    const seconds = Math.max(0, Math.floor(Date.now() / 1000) - task.createdAt);
    if (seconds < 60) return 'Created seconds ago';
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `Created ${minutes} minute${minutes === 1 ? '' : 's'} ago`;
    return `Created ${formatDate(task.createdAt)}`;
  }
</script>

<article class="task-detail-content" data-testid="task-detail-content">
  {#if showTitle}
    <header class="route-header">
      <span class="task-icon" aria-hidden="true"></span>
      <div>
        <h1 data-testid="task-detail-title">{task.title || 'Untitled task'}</h1>
        <p>{createdLabel()} by {creatorName}</p>
      </div>
      <div class="header-badges" aria-label="Task status and priority">
        <span class="priority" data-testid="task-detail-priority">{priorityLabel(task.priority)}</span>
        <span data-testid="task-detail-status">{statusLabel(task.status)}</span>
      </div>
    </header>
  {/if}

  <section class="detail-section wide" data-testid="task-detail-description">
    <SettingsSectionHeading title="Description" icon="document" />
    <p class:empty={!task.description}>{task.description || 'No description added.'}</p>
  </section>

  {#if task.status === 'blocked'}
    <section class="detail-section wide blocked" data-testid="task-detail-blocked-reason">
      <SettingsSectionHeading title={$text('tasks.blocked_heading')} icon="warning" />
      <p>{task.blockedReason || blockedReasonFallback()}</p>
    </section>
  {/if}

  <div class="detail-grid">
    <section class="detail-section" data-testid="task-detail-assignee">
      <SettingsSectionHeading title="Assigned to" icon="user" />
      <p class="identity">{assigneeLabel()}</p>
    </section>

    <section class="detail-section" data-testid="task-detail-due">
      <SettingsSectionHeading title="Due" icon="calendar" />
      <p class:empty={!task.dueAt}>{task.dueAt ? formatDate(task.dueAt) : 'No due date.'}</p>
    </section>

    <section class="detail-section" data-testid="task-detail-projects">
      <SettingsSectionHeading title={`Connected project${resolvedRelated.projects.length === 1 ? '' : 's'}`} icon="document" />
      {#if resolvedRelated.projects.length > 0}
        <div class="workspace-cards">
          {#each resolvedRelated.projects as project (project.id)}
            <WorkspaceContinueCard title={project.title} summary={project.description || null} badge="Project" category="productivity" appId="projects" icon="folder" testId="task-detail-project-card" href={`/projects/${encodeURIComponent(project.id)}`} source={null} fluid={false} onActivate={null} />
          {/each}
        </div>
      {:else}<p class="empty">No connected project.</p>{/if}
    </section>

    <section class="detail-section" data-testid="task-detail-plan">
      <SettingsSectionHeading title="Connected plan" icon="document" />
      {#if resolvedRelated.plan}
        <div class="workspace-cards">
          <WorkspaceContinueCard title={resolvedRelated.plan.title} summary={resolvedRelated.plan.description || null} badge="Plan" category="productivity" appId="plans" icon="clipboard-list" testId="task-detail-plan-card" href={`/plans/${encodeURIComponent(resolvedRelated.plan.id)}`} source={null} fluid={false} onActivate={null} />
        </div>
      {:else}<p class="empty">No connected plan.</p>{/if}
    </section>

    <section class="detail-section wide" data-testid="task-detail-dependencies">
      <SettingsSectionHeading title="Blockers and dependencies" icon="task" />
      {#if resolvedRelated.dependencies.length > 0}
        <p>These plans and tasks must be completed before this task can start.</p>
        <div class="dependency-list">
          {#each resolvedRelated.dependencies as dependency (dependency.edgeId)}
            <a href={`/${dependency.targetKind === 'task' ? 'tasks' : 'plans'}/${encodeURIComponent(dependency.targetId)}`}>
              <strong>{dependency.title}</strong>
              <span>{statusLabel(dependency.targetStatus as UserTaskViewModel['status'])}{dependency.satisfied ? ' - complete' : ' - blocking'}</span>
            </a>
          {/each}
        </div>
      {:else}<p class="empty">No blockers or dependencies.</p>{/if}
    </section>

    <section class="detail-section" data-testid="task-detail-tags">
      <SettingsSectionHeading title="Tags" icon="settings" />
      {#if task.tags.length > 0}
        <div class="tags">{#each task.tags as tag}<span>#{tag.replace(/^#/, '')}</span>{/each}</div>
      {:else}<p class="empty">No tags.</p>{/if}
    </section>

    <section class="detail-section" data-testid="task-detail-chat">
      <SettingsSectionHeading title="Connected chat" icon="chat" />
      {#if task.externalChat}
        <div class="linked-card compact external" data-testid="task-detail-external-chat">
          <strong>{task.externalChat.title || task.externalChat.id}</strong>
          <span>OpenCode</span>
        </div>
      {:else if resolvedRelated.chat}
        <a class="linked-card compact" href={`/#chat-id=${encodeURIComponent(resolvedRelated.chat.id)}`}><strong>{resolvedRelated.chat.title}</strong></a>
      {:else}<p class="empty">No connected chat.</p>{/if}
    </section>
  </div>

  {#if relationLoadFailed}<p class="relation-error" role="alert">Some connected task details could not be loaded.</p>{/if}
  <TaskActivity {task} {teamId} initialEntries={activityEntries} />
</article>

<style>
  .task-detail-content { width: min(980px, calc(100% - 40px)); margin: 0 auto; padding: 40px 0 100px; color: var(--color-font-primary); }
  .route-header { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 16px; margin-bottom: 28px; padding: 26px; border-radius: 24px; background: linear-gradient(135deg, var(--color-app-tasks-start, var(--color-primary-start)), var(--color-app-tasks-end, var(--color-primary-end))); color: var(--color-grey-0); }
  .task-icon { width: 42px; height: 42px; background: currentColor; mask: var(--icon-url-task) center / contain no-repeat; }
  h1, p { margin: 0; }
  h1 { font-size: clamp(1.5rem, 3vw, 2.25rem); line-height: 1.15; }
  .route-header p { margin-top: 8px; opacity: 0.8; }
  .header-badges, .tags { display: flex; flex-wrap: wrap; gap: 8px; }
  .header-badges span, .tags span { padding: 6px 10px; border-radius: var(--radius-full); font-size: var(--font-size-xs); font-weight: 700; }
  .header-badges span { background: color-mix(in srgb, var(--color-grey-0) 20%, transparent); }
  .header-badges .priority { background: var(--color-error); color: var(--color-grey-0); }
  .detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 32px 44px; }
  .detail-section.wide { grid-column: 1 / -1; }
  .detail-section > p { padding: 0 8px; line-height: 1.55; white-space: pre-wrap; }
  .detail-section .empty { color: var(--color-font-secondary); }
  .identity { color: var(--color-primary); font-weight: 700; }
  .blocked > p { padding: 16px 18px; overflow-wrap: anywhere; border-radius: 16px; background: color-mix(in srgb, var(--color-error) 12%, transparent); border: 1px solid color-mix(in srgb, var(--color-error) 35%, transparent); }
  .dependency-list { display: grid; gap: 12px; }
  .workspace-cards { display: flex; justify-content: center; padding: 0 8px; }
  .linked-card, .dependency-list a { display: flex; flex-direction: column; gap: 7px; min-height: 88px; padding: 20px; border-radius: 22px; box-sizing: border-box; text-decoration: none; }
  .linked-card { justify-content: center; background: linear-gradient(135deg, var(--color-app-tasks-start, var(--color-primary-start)), var(--color-app-tasks-end, var(--color-primary-end))); color: var(--color-grey-0); text-align: center; box-shadow: 0 7px 14px color-mix(in srgb, var(--color-grey-100) 14%, transparent); }
  .linked-card.compact { min-height: 72px; }
  .linked-card.external span { font-size: var(--font-size-xs); opacity: 0.8; }
  .dependency-list { grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 14px; }
  .dependency-list a { background: var(--color-grey-10); border: 1px solid var(--color-grey-25); color: var(--color-font-primary); }
  .dependency-list span { color: var(--color-font-secondary); font-size: var(--font-size-xs); }
  .tags { padding: 0 8px; }
  .tags span { background: var(--color-primary); color: var(--color-font-button); }
  .relation-error { margin-top: 28px; padding: 14px; border-radius: 12px; background: var(--color-error); color: var(--color-grey-0); }
  @media (max-width: 700px) {
    .task-detail-content { width: calc(100% - 32px); padding-top: 28px; }
    .route-header { grid-template-columns: auto minmax(0, 1fr); padding: 20px; }
    .header-badges { grid-column: 1 / -1; }
    .detail-grid { grid-template-columns: minmax(0, 1fr); gap: 28px; }
    .detail-section.wide { grid-column: auto; }
    .dependency-list { grid-template-columns: minmax(0, 1fr); }
  }
</style>
