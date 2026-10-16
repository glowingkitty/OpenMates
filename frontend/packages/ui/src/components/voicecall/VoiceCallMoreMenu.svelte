<script lang="ts">
  import type { Snippet } from 'svelte';
  import HeaderActionMenu from '../HeaderActionMenu.svelte';

  let { report, share, priorityAction, actions, hasShare, hasPriorityAction, hasActions }: {
    report: Snippet;
    share: Snippet;
    priorityAction: Snippet;
    actions: Snippet;
    hasShare: boolean;
    hasPriorityAction: boolean;
    hasActions: boolean;
  } = $props();
</script>

<!-- Chat and embed fullscreen use this same overlay, focus and action treatment. -->
<HeaderActionMenu
  compactMoreOnly
  triggerTestId="voice-call-more"
  menuTestId="voice-call-more-actions"
  {report} {share} {priorityAction} {actions} {hasShare} {hasPriorityAction}
  actionCount={Number(hasActions)}
/>
