// frontend/packages/ui/src/components/workflows/workflowSidePanelE2EHook.ts
//
// Dev-only Playwright hook for the chat workflow side panel. On localhost and
// *.dev.openmates.org it exposes window.__openmatesE2EWorkflowSidePanel so a
// spec can open/close the panel through the real store and observe each
// workflowSidePanelSaved event. Production hosts never receive the global.

import {
  closeWorkflowSidePanel,
  openWorkflowSidePanel,
  workflowSidePanelSaved,
  type WorkflowSidePanelRequest,
  type WorkflowSidePanelSaved
} from '../../stores/workflowSidePanelStore';

export interface WorkflowSidePanelE2EHook {
  open: (request: WorkflowSidePanelRequest) => void;
  close: () => void;
  /** Every saved event reported while the hook is installed, in order. */
  savedEvents: WorkflowSidePanelSaved[];
}

function isE2EHost(hostname: string): boolean {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname.endsWith('.dev.openmates.org');
}

/** Install the hook once per page; returns the uninstall function (a no-op off dev hosts). */
export function installWorkflowSidePanelE2EHook(): () => void {
  if (typeof window === 'undefined' || !isE2EHost(window.location.hostname)) return () => {};
  const testWindow = window as unknown as { __openmatesE2EWorkflowSidePanel?: WorkflowSidePanelE2EHook };
  const hook: WorkflowSidePanelE2EHook = {
    open: (request) => openWorkflowSidePanel(request),
    close: () => closeWorkflowSidePanel(),
    savedEvents: []
  };
  const unsubscribe = workflowSidePanelSaved.subscribe((event) => {
    if (event) hook.savedEvents.push(event);
  });
  testWindow.__openmatesE2EWorkflowSidePanel = hook;
  return () => {
    unsubscribe();
    if (testWindow.__openmatesE2EWorkflowSidePanel === hook) delete testWindow.__openmatesE2EWorkflowSidePanel;
  };
}
