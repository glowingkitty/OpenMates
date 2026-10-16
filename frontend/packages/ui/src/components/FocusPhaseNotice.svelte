<!-- Web counterpart: apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift systemContent -->
<script lang="ts">
  import { text } from "../i18n/translations";
  import { settingsDeepLink } from "../stores/settingsDeepLinkStore";
  import { panelState } from "../stores/panelStateStore";
  import { focusPhaseDetailsPath, type FocusPhaseEvent } from "../types/focusPhases";
  let { event, onOpenDetails }: { event: FocusPhaseEvent; onOpenDetails?: (path: string) => void } = $props();
  let path = $derived(focusPhaseDetailsPath(event));
  function openDetails() {
    if (!path) return;
    if (onOpenDetails) onOpenDetails(path);
    else { settingsDeepLink.set(path); panelState.openSettings(); }
  }
</script>
<span data-testid="focus-phase-notice">
  {$text(event.direction === 'backward' ? 'focus_phases.returned' : 'focus_phases.switched')}
  {#if path}<button type="button" class="phase-link" data-testid="focus-phase-details-link" data-focus-detail-path={path} onclick={openDetails}>{event.phase_title}</button>
  {:else}<span>{event.phase_title}</span>{/if}
</span>
<style>
  .phase-link { color: var(--color-primary-start); background: none; border: 0; padding: 0; font: inherit; text-decoration: underline; cursor: pointer; }
  .phase-link:focus-visible { outline: 2px solid var(--color-primary-start); outline-offset: 3px; }
</style>
