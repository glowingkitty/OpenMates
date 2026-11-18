<!-- Project timeline tab: loads pages from the Rust core through the shared Worker; presentation lives in ProjectTimeline. -->
<script lang="ts">
  import ProjectTimeline from './ProjectTimeline.svelte';
  import type { ProjectTimelineEntry } from './ProjectTimeline.types';
  import { loadProjectTimelinePage, restoreProjectCommit } from '../../services/rustCore/projects/projectTimelineClient';

  interface Props {
    projectId: string;
    teamId?: string | null;
    onOpenFile: (path: string) => void;
  }

  let { projectId, teamId = null, onOpenFile }: Props = $props();

  let entries = $state<ProjectTimelineEntry[]>([]);
  let nextCursor = $state<string | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let generation = 0;

  async function load(before?: string): Promise<void> {
    const mine = ++generation;
    loading = true;
    error = null;
    try {
      const page = await loadProjectTimelinePage(projectId, teamId, before);
      if (mine !== generation) return;
      entries = before ? [...entries, ...page.entries] : page.entries;
      nextCursor = page.nextCursor;
    } catch (caught) {
      if (mine !== generation) return;
      error = (caught as { code?: unknown } | null)?.code as string ?? 'project_timeline_failed';
    } finally {
      if (mine === generation) loading = false;
    }
  }

  $effect(() => {
    void projectId;
    void teamId;
    entries = [];
    nextCursor = null;
    void load();
  });

  // A refusal rejects with the core's code (UnitPortError.code); ProjectTimeline shows it.
  async function restoreCommit(commitId: string): Promise<void> {
    await restoreProjectCommit(projectId, teamId, commitId);
    await load();
  }
</script>

<ProjectTimeline
  {entries}
  {loading}
  {error}
  hasMore={nextCursor !== null}
  onLoadMore={() => { if (nextCursor && !loading) void load(nextCursor); }}
  onRestoreCommit={restoreCommit}
  {onOpenFile}
/>
