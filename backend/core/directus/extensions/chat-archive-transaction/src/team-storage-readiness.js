/** Server-side financial readiness for new Team archive copies and pruning.
 * Mirror the valid self_host branch of server_mode.py. A conflicting or
 * malformed cloud witness cannot bypass the billing readiness guard.
 */
export function teamArchiveFinancialReady(hashedTeamId, env = process.env) {
  if (!hashedTeamId) return true;
  if (env.OPENMATES_DEPLOYMENT_MODE === 'self_host'
    && env.OPENMATES_CLOUD_OVERLAY_ENABLED !== 'true'
    && env.OPENMATES_CLOUD_OVERLAY_PACKAGE !== 'OpenMatesCloud') return true;
  return env.TEAM_STORAGE_BILLING_ENABLED === '1';
}
