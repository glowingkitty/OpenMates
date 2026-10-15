/** Bounded recovery work; dependencies settle fully before their descendants start. */
export async function runRecoveryBatch<T, R>(
  items: readonly T[], work: (item: T, index: number) => Promise<R>,
  dependsOn: (item: T, dependency: T, index: number, dependencyIndex: number) => boolean = () => false,
): Promise<R[]> {
  const results: R[] = new Array(items.length);
  const pending = new Set(items.map((_, index) => index));
  const complete = new Set<number>();
  const active = new Map<number, Promise<void>>();
  let failed = false;
  let failure: unknown;
  while (pending.size || active.size) {
    if (!failed) for (const index of pending) {
      if (active.size >= 4) break;
      if (items.some((dependency, other) => other !== index && !complete.has(other)
        && dependsOn(items[index], dependency, index, other))) continue;
      pending.delete(index);
      const task = Promise.resolve().then(() => work(items[index], index)).then(
        result => { results[index] = result; complete.add(index); },
        error => { if (!failed) { failed = true; failure = error; } },
      ).finally(() => { active.delete(index); });
      active.set(index, task);
    }
    if (!active.size) {
      if (failed) throw failure;
      throw new Error("Recovery embed dependency is cyclic or unresolved; outputs remain pending.");
    }
    await Promise.race(active.values());
    if (failed && !active.size) throw failure;
  }
  return results;
}
