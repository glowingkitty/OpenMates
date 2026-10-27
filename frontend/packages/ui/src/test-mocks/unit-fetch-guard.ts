/** Shared Vitest transport baseline. Never retain or delegate to native fetch. */
export const blockedUnitFetch: typeof fetch = async () => {
  throw new Error("Unmocked fetch blocked in UI unit tests; mock the request explicitly.");
};

export function installUnitFetchGuard(target: object): void {
  // This must be the original property Vitest snapshots for stubGlobal/spyOn.
  // Registering it with vi.stubGlobal would restore the real transport on cleanup.
  Object.defineProperty(target, "fetch", {
    value: blockedUnitFetch,
    writable: true,
    configurable: true,
  });
}
