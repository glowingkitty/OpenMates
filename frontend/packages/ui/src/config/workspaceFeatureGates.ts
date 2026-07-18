// frontend/packages/ui/src/config/workspaceFeatureGates.ts
//
// Frontend release gates for top-level workspace surfaces.
// Backend feature availability remains the server-side source of truth, but
// unreleased workspace entry points must also be hidden by the current web build
// so older/stale backends cannot expose UI tabs before product rollout.
//
// Spec: docs/specs/simplified-feature-availability/spec.yml

type DisabledFeatureMap = Record<string, true> | null;

const RELEASED_OPTIONAL_WORKSPACE_FEATURES = new Set<string>([
  'platform:tasks',
  'platform:workflows',
]);

export function isWorkspaceFeatureAvailable(
  featureId: string,
  disabledById: DisabledFeatureMap,
  defaultEnabled: boolean = false,
): boolean {
  if (featureId === 'platform:chats') {
    return disabledById ? disabledById[featureId] !== true : true;
  }

  if (!RELEASED_OPTIONAL_WORKSPACE_FEATURES.has(featureId)) {
    return false;
  }

  return disabledById ? disabledById[featureId] !== true : defaultEnabled;
}
