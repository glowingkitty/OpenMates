/** Unit-test stand-in for SvelteKit's `$env/dynamic/public`: only PUBLIC_* variables of the test process. */
export const env: Record<string, string | undefined> = Object.fromEntries(
  Object.entries(process.env).filter(([key]) => key.startsWith('PUBLIC_')),
);
