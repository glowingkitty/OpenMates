// frontend/packages/ui/src/services/projectState/projectFileDecide.ts
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
// Flag-on (VITE_OPENMATES_RUST_CORE=1) answer path for the hosted Project file
// decisions of projectFilePolicy.ts: the shared Rust core (web_projects
// hosted_files ops) in the Worker `chatState` unit, with no TypeScript fallback.
// Web callers pass `decidePolicy: PROJECT_RUST_CORE ? decideProjectFile : undefined`
// on the HostedProjectFileAdapter, so flag-off builds drop this module and keep the
// synchronous rules. Only paths, hidden flags and job arguments cross; never file
// content or keys.
import type { ProjectFileDecider, ProjectFileOutput } from "./projectFilePolicy";

/** One hosted file decision answered by the shared Rust core (flag-on only). */
export const decideProjectFile: ProjectFileDecider = async (op, input) => {
  // Dynamic import keeps the Worker client out of flag-off bundles (rustPlacement.ts pattern).
  const { chatStateCall } = await import("../rustCore/chatState/chatListUnitClient");
  const wire = JSON.parse(JSON.stringify(input) ?? "null") as unknown;
  return (await chatStateCall("projectDecide", { op, input: wire })) as ProjectFileOutput<typeof op>;
};
