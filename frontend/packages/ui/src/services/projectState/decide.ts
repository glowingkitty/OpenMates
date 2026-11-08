// frontend/packages/ui/src/services/projectState/decide.ts
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
// Entry point for Project decisions. With VITE_OPENMATES_RUST_CORE=1 every routed
// decision is answered by the shared Rust core in the Worker `chatState` unit
// (web_projects) and there is no TypeScript fallback. Flag-off builds call the
// original TypeScript rules synchronously, so call sites read
// `PROJECT_RUST_CORE ? await decideProject(op, input) : projectRule(op, input)` and
// the default path gains no await. Refusals are data in both paths ({remoteError},
// {focusError}); a thrown rule Error is `{error}` from Rust and is rethrown here.
import { PROJECT_STATE_POLICY, type ProjectStateOpName } from "./policy";

type Rule<K extends ProjectStateOpName> = (typeof PROJECT_STATE_POLICY)[K];
export type ProjectStateInput<K extends ProjectStateOpName> = Parameters<Rule<K>>[0];
export type ProjectStateOutput<K extends ProjectStateOpName> = ReturnType<Rule<K>>;

/** Compile-time flag: the bundler drops the Rust branch from default builds. */
export const PROJECT_RUST_CORE = import.meta.env.VITE_OPENMATES_RUST_CORE === "1";

/** One decision answered by the shared Rust core (flag-on only). */
export async function decideProject<K extends ProjectStateOpName>(
  op: K, input: ProjectStateInput<K>,
): Promise<ProjectStateOutput<K>> {
  // Dynamic import keeps the Worker client out of flag-off bundles (rustPlacement.ts pattern).
  const { chatStateCall } = await import("../rustCore/chatState/chatListUnitClient");
  // The Rust op reads JSON anyway; the round trip strips Svelte $state proxies and
  // other non-cloneable values that MessagePort.postMessage would reject.
  const wire = JSON.parse(JSON.stringify(input) ?? "null") as unknown;
  const answer = await chatStateCall("projectDecide", { op, input: wire });
  if (answer && typeof answer === "object" && !Array.isArray(answer)
    && typeof (answer as { error?: unknown }).error === "string" && Object.keys(answer).length === 1) {
    throw new Error((answer as { error: string }).error);
  }
  return answer as ProjectStateOutput<K>;
}

/** The TypeScript rule run synchronously (flag-off path). */
export function projectRule<K extends ProjectStateOpName>(op: K, input: ProjectStateInput<K>): ProjectStateOutput<K> {
  return (PROJECT_STATE_POLICY[op] as (value: ProjectStateInput<K>) => ProjectStateOutput<K>)(input);
}
