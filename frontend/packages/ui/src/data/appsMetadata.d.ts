// frontend/packages/ui/src/data/appsMetadata.d.ts
// Type declarations for the gitignored generated appsMetadata.ts module.
// The runtime file is produced by frontend/packages/ui/scripts/generate-apps-metadata.js
// during UI prepare/prebuild steps, but changed-file TypeScript checks can run
// before generated artifacts exist in a clean worktree.

import type { AppMetadata } from '../types/apps';

export const appsMetadata: Record<string, AppMetadata>;
