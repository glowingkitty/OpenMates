// Own the lifetime of Svelte roots mounted by the imperative embed renderers.
// Removing a TipTap node or replacing innerHTML does not unmount these roots.
// Track them by target so every renderer, including nested group children, is
// disposed by the same owner. Dead targets reject late async hydration without
// allocating a new component. Normal remounts keep their existing fast path.
// Architecture: docs/architecture/embeds.md

import { mount as svelteMount, unmount as svelteUnmount } from "svelte";

type ComponentHandle = Parameters<typeof svelteUnmount>[0];
const mounted = new WeakMap<Node, Set<ComponentHandle>>();
const targets = new WeakMap<ComponentHandle, Node>();
const cleanups = new WeakMap<Node, Set<() => void>>();
const disposed = new WeakSet<Node>();
const unmounted = new WeakSet<ComponentHandle>();

export function isEmbedTargetDisposed(target: Node): boolean {
  for (let node: Node | null = target; node; node = node.parentNode) {
    if (disposed.has(node)) return true;
  }
  return false;
}

/** Match Svelte's generic API so existing component prop checks are preserved. */
export const mount = ((component, options) => {
  if (isEmbedTargetDisposed(options.target)) {
    // Cancellation, not a rendering error: the owning message has gone away.
    const cancelled = {} as ReturnType<typeof svelteMount>;
    unmounted.add(cancelled);
    return cancelled;
  }
  const instance = svelteMount(component, options);
  const instances = mounted.get(options.target) ?? new Set<ComponentHandle>();
  instances.add(instance);
  mounted.set(options.target, instances);
  targets.set(instance, options.target);
  return instance;
}) as typeof svelteMount;

export const unmount: typeof svelteUnmount = (instance, options) => {
  if (unmounted.has(instance)) return Promise.resolve();
  unmounted.add(instance);
  const target = targets.get(instance);
  if (target) {
    mounted.get(target)?.delete(instance);
    targets.delete(instance);
  }
  return svelteUnmount(instance, options);
};

/** Retry listeners belong to the node even before a component has mounted. */
export function onEmbedCleanup(target: Node, cleanup: () => void): void {
  if (isEmbedTargetDisposed(target)) {
    cleanup();
    return;
  }
  const callbacks = cleanups.get(target) ?? new Set<() => void>();
  callbacks.add(cleanup);
  cleanups.set(target, callbacks);
}

/** Dispose children before clearing/replacing markup; keep a reusable target alive. */
export function disposeEmbedTree(target: Element, removeTarget = true): void {
  const elements = [target, ...Array.from(target.querySelectorAll("*"))];
  // Mark first: unmount callbacks and pending promises must not resurrect a root.
  for (const element of elements) {
    if (element !== target || removeTarget) disposed.add(element);
  }
  for (const element of elements.reverse()) {
    for (const cleanup of Array.from((element !== target || removeTarget ? cleanups.get(element) : undefined) ?? [])) {
      try { cleanup(); } catch (error) {
        console.error("[EmbedLifecycle] Failed to release renderer resource:", error);
      }
    }
    if (element !== target || removeTarget) cleanups.delete(element);
    for (const instance of Array.from(mounted.get(element) ?? [])) {
      void unmount(instance).catch((error) => {
        console.error("[EmbedLifecycle] Failed to unmount embed:", error);
      });
    }
    mounted.delete(element);
  }
}
