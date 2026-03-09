declare module '*.yml' {
  const content: any;
  export default content;
}

declare module '*.yaml' {
  const content: any;
  export default content;
}

declare module '*.svelte' {
  const component: any;
  export default component;
}

// OpenObserve browser SDK — optional dependency, never installed in prod
// (endpoint not publicly exposed). Declared here to satisfy TypeScript.
declare module '@openobserve/browser-rum' {
  export const openobserveRum: {
    init(config: Record<string, unknown>): void;
    setUser(user: Record<string, unknown>): void;
    clearUser(): void;
    startSessionReplayRecording(): void;
    stopSessionReplayRecording(): void;
  };
}
declare module '@openobserve/browser-logs' {
  export const openobserveLogs: {
    init(config: Record<string, unknown>): void;
  };
}
