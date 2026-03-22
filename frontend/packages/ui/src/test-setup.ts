/**
 * Test setup file for Vitest
 * Configures global test environment and mocks
 */

import { vi } from "vitest";

// Mock browser APIs that might not be available in test environment.
//
// NOTE: This replaces the entire window object. Any browser API needed by
// modules imported at test time must be stubbed here. Missing stubs cause
// "Cannot read properties of undefined" crashes at module-init time.
Object.defineProperty(global, "window", {
  value: {
    btoa: (str: string) => Buffer.from(str, "binary").toString("base64"),
    atob: (str: string) => Buffer.from(str, "base64").toString("binary"),
    sessionStorage: {
      getItem: vi.fn(),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    },
    localStorage: {
      getItem: vi.fn(),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    },
    // navigator.standalone is read by detectIsPWA() at module-init time in
    // pushNotificationStore. Stub it so the read doesn't throw.
    navigator: {
      standalone: undefined,
      serviceWorker: undefined,
    },
    // matchMedia is called by detectIsPWA() for '(display-mode: standalone)'.
    // jsdom does not implement it; without a stub every file that transitively
    // imports pushNotificationStore crashes with:
    //   TypeError: window.matchMedia is not a function
    matchMedia: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  },
  writable: true,
});

// Mock crypto.subtle for key derivation tests
Object.defineProperty(global, "crypto", {
  value: {
    subtle: {
      importKey: vi.fn(),
      deriveBits: vi.fn(),
      digest: vi.fn(),
    },
    randomUUID: vi.fn(() => "test-uuid-123"),
  },
  writable: true,
});

// Mock IndexedDB
const mockIndexedDB = {
  open: vi.fn(),
  deleteDatabase: vi.fn(),
};

Object.defineProperty(global, "indexedDB", {
  value: mockIndexedDB,
  writable: true,
});

// Suppress console warnings in tests
const originalConsoleWarn = console.warn;
console.warn = (...args) => {
  if (
    typeof args[0] === "string" &&
    (args[0].includes("vitest") || args[0].includes("test"))
  ) {
    return;
  }
  originalConsoleWarn(...args);
};
