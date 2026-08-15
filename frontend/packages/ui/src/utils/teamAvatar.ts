// frontend/packages/ui/src/utils/teamAvatar.ts
// Shared presentation helpers for encrypted Teams profile metadata.
// Teams V1 stores generated profile metadata client-side encrypted; these
// helpers intentionally accept only safe CSS color values before rendering
// them in Svelte style attributes.
// Spec: docs/specs/teams-v1/spec.yml

import type { TeamViewModel } from '../services/teamService';

const DEFAULT_TEAM_AVATAR_START = 'var(--color-primary-start)';
const DEFAULT_TEAM_AVATAR_END = 'var(--color-primary-end)';

function safeCssColor(value: unknown): string {
  if (typeof value !== 'string') return DEFAULT_TEAM_AVATAR_START;
  const trimmed = value.trim();
  return /^#[0-9a-fA-F]{3,8}$/.test(trimmed) ? trimmed : DEFAULT_TEAM_AVATAR_START;
}

export function getTeamAvatarBackground(team: TeamViewModel | null | undefined): string {
  const color = safeCssColor(team?.profileImageMetadata?.background_color);
  return `linear-gradient(135deg, ${color}, ${DEFAULT_TEAM_AVATAR_END})`;
}
