import type { Output } from './workflowBuilder';

/** The source action owns the color of its variable in every workflow picker. */
export function workflowVariableGradient(output: Pick<Output, 'appId'>): string {
  const appId = /^[a-z0-9_-]+$/.test(output.appId ?? '') ? output.appId : '';
  if (!appId) return '';
  return `--variable-start:var(--color-app-${appId}-start,var(--color-primary-start));--variable-end:var(--color-app-${appId}-end,var(--color-primary-end))`;
}
