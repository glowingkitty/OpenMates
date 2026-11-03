import { afterEach, describe, expect, it } from 'vitest';
import { isRustCoreRegistered, registerRustCoreWorkerFactory, requireRustCoreWorkerFactory } from '../host/workerFactoryRegistry';

describe('rust core worker factory registry', () => {
  let unregister: (() => void) | null = null;
  afterEach(() => { unregister?.(); unregister = null; });

  // contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
  it('reports not enabled until a factory is registered (flag OFF behaviour)', () => {
    expect(isRustCoreRegistered()).toBe(false);
    expect(() => requireRustCoreWorkerFactory()).toThrow('rust_core_not_enabled');
  });
  // contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
  it('returns the registered factory and unregisters only its own registration', () => {
    const first = async () => { throw new Error('unused'); };
    const second = async () => { throw new Error('unused'); };
    const dropFirst = registerRustCoreWorkerFactory(first);
    unregister = registerRustCoreWorkerFactory(second);
    expect(requireRustCoreWorkerFactory()).toBe(second);
    dropFirst();
    expect(requireRustCoreWorkerFactory()).toBe(second);
    unregister();
    unregister = null;
    expect(isRustCoreRegistered()).toBe(false);
  });
});
