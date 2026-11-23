<!-- frontend/packages/ui/src/components/projects/ProjectCreatedEvent.svelte
     Connects the "Created <name> project" chat event to the client core: the undo decision runs in
     the core (projectUndoCreatedGuard, via undoCreatedProject); the persisted undone state is the
     Project no longer existing, checked on mount so it survives reload.
     Spec: projects.creation.assistant-inferred -->
<script lang="ts">
  import { onMount } from 'svelte';
  import ProjectCreatedEventNotice from './ProjectCreatedEventNotice.svelte';
  import { createdProjectIsGone, createdProjectUndoAvailable, undoCreatedProject } from '../../services/projectCreatedUndo';

  let { chatId, projectId, projectName }: { chatId: string; projectId: string; projectName: string } = $props();

  let undone = $state(false);
  let undoing = $state(false);
  let failed = $state(false);

  onMount(async () => {
    if (createdProjectUndoAvailable()) undone = await createdProjectIsGone(projectId);
  });

  async function undo() {
    if (undoing) return;
    undoing = true;
    failed = false;
    try {
      await undoCreatedProject(chatId, projectId);
      undone = true;
    } catch (error) {
      console.warn('[ProjectCreatedEvent] Undo failed', error);
      failed = true;
    } finally {
      undoing = false;
    }
  }
</script>

<ProjectCreatedEventNotice {projectName} {undone} {undoing} {failed}
  onOpen={() => { window.location.hash = `project-id=${encodeURIComponent(projectId)}`; }}
  onUndo={createdProjectUndoAvailable() && chatId ? undo : undefined} />
