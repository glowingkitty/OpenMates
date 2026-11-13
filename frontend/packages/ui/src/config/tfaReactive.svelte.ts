/**
 * Reactive 2FA app list for flag builds, where the shared Rust core owns the
 * list and pushes it after the page loaded (spec: specifications/features/auth
 * #auth.signup.current-flow). A `$state` array notifies components that already
 * rendered or captured it; `config/tfa.ts` exports it as `tfaApps`. A factory
 * (not a module-level array) keeps flag-off bundles free of the state runtime.
 */
export function createReactiveTfaApps(): string[] {
  const apps: string[] = $state([]);
  return apps;
}
