/**
 * Test setup file for Vitest
 * Configures global test environment and mocks
 */

import { vi } from "vitest";

const windowEventTarget = new EventTarget();
const testLocation = {
  hash: "",
  pathname: "/",
  search: "",
};
const testLocalStorage = {
  getItem: vi.fn(),
  setItem: vi.fn(),
  removeItem: vi.fn(),
};
const testSessionStorage = {
  getItem: vi.fn(),
  setItem: vi.fn(),
  removeItem: vi.fn(),
};
const testDocument = {
  activeElement: null,
  body: {
    appendChild: vi.fn(),
    removeChild: vi.fn(),
  },
  cookie: "",
  documentElement: {
    dataset: {},
    removeAttribute: vi.fn(),
    setAttribute: vi.fn(),
    style: { removeProperty: vi.fn(), setProperty: vi.fn() },
  },
  visibilityState: "visible",
  addEventListener: vi.fn(
    (...args: Parameters<EventTarget["addEventListener"]>) =>
      windowEventTarget.addEventListener(...args),
  ),
  removeEventListener: vi.fn(
    (...args: Parameters<EventTarget["removeEventListener"]>) =>
      windowEventTarget.removeEventListener(...args),
  ),
  dispatchEvent: vi.fn((event: Event) => windowEventTarget.dispatchEvent(event)),
  createElement: vi.fn((tagName: string) => ({
    appendChild: vi.fn(),
    click: vi.fn(),
    dataset: {},
    href: "",
    remove: vi.fn(),
    removeChild: vi.fn(),
    setAttribute: vi.fn(),
    style: {},
    tagName: tagName.toUpperCase(),
  })),
  createTextNode: vi.fn((text: string) => ({ textContent: text })),
  getElementById: vi.fn(() => null),
  querySelector: vi.fn(() => null),
};

const testPage = {
  data: {},
  error: null,
  form: null,
  params: {},
  route: { id: null },
  status: 200,
  url: new URL("http://localhost/"),
};

function readable<T>(value: T) {
  return {
    subscribe(run: (current: T) => void) {
      run(value);
      return () => undefined;
    },
  };
}

function defineConfigurableProperty(target: object, property: string, value: unknown): void {
  Object.defineProperty(target, property, {
    value,
    writable: true,
    configurable: true,
  });
}

vi.mock("$app/environment", () => ({
  browser: true,
  building: false,
  dev: true,
  version: "test",
}));

vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  disableScrollHandling: vi.fn(),
  goto: vi.fn(),
  invalidate: vi.fn(),
  invalidateAll: vi.fn(),
  onNavigate: vi.fn(),
  preloadCode: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  replaceState: vi.fn(),
}));

vi.mock("$app/stores", () => ({
  navigating: readable(null),
  page: readable(testPage),
  updated: { ...readable(false), check: vi.fn() },
}));

vi.mock("$app/state", () => ({
  navigating: { current: null },
  page: { current: testPage },
  updated: { check: vi.fn(), current: false },
}));

// Mock browser APIs that might not be available in Node test files without
// replacing jsdom's native DOM objects in component tests.
type MutableWindow = Window & typeof globalThis & Record<string, unknown>;

const fallbackWindow = {
  btoa: (str: string) => Buffer.from(str, "binary").toString("base64"),
  atob: (str: string) => Buffer.from(str, "base64").toString("binary"),
  sessionStorage: testSessionStorage,
  localStorage: testLocalStorage,
  document: testDocument,
  location: testLocation,
  history: {
    replaceState: vi.fn(),
    pushState: vi.fn(),
  },
  // navigator.standalone is read by detectIsPWA() at module-init time in
  // pushNotificationStore. Stub it so the read doesn't throw.
  navigator: {
    standalone: undefined,
    serviceWorker: undefined,
  },
  addEventListener: vi.fn(
    (...args: Parameters<EventTarget["addEventListener"]>) =>
      windowEventTarget.addEventListener(...args),
  ),
  removeEventListener: vi.fn(
    (...args: Parameters<EventTarget["removeEventListener"]>) =>
      windowEventTarget.removeEventListener(...args),
  ),
  dispatchEvent: vi.fn((event: Event) => windowEventTarget.dispatchEvent(event)),
} as unknown as MutableWindow;

if (typeof globalThis.window === "undefined") {
  defineConfigurableProperty(globalThis, "window", fallbackWindow);
}

const activeWindow = globalThis.window as MutableWindow;

if (typeof activeWindow.btoa !== "function") {
  defineConfigurableProperty(activeWindow, "btoa", fallbackWindow.btoa);
}
if (typeof activeWindow.atob !== "function") {
  defineConfigurableProperty(activeWindow, "atob", fallbackWindow.atob);
}
if (typeof globalThis.btoa !== "function") {
  defineConfigurableProperty(globalThis, "btoa", fallbackWindow.btoa);
}
if (typeof globalThis.atob !== "function") {
  defineConfigurableProperty(globalThis, "atob", fallbackWindow.atob);
}
if (typeof activeWindow.matchMedia !== "function") {
  defineConfigurableProperty(
    activeWindow,
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}
if (typeof activeWindow.document === "undefined") {
  defineConfigurableProperty(activeWindow, "document", testDocument);
}
if (typeof activeWindow.localStorage === "undefined") {
  defineConfigurableProperty(activeWindow, "localStorage", testLocalStorage);
}
if (typeof activeWindow.sessionStorage === "undefined") {
  defineConfigurableProperty(activeWindow, "sessionStorage", testSessionStorage);
}
if (typeof activeWindow.location === "undefined") {
  defineConfigurableProperty(activeWindow, "location", testLocation);
}
if (typeof activeWindow.history === "undefined") {
  defineConfigurableProperty(activeWindow, "history", fallbackWindow.history);
}

if (typeof globalThis.localStorage === "undefined") {
  defineConfigurableProperty(globalThis, "localStorage", testLocalStorage);
}

if (typeof globalThis.sessionStorage === "undefined") {
  defineConfigurableProperty(globalThis, "sessionStorage", testSessionStorage);
}

if (typeof globalThis.document === "undefined") {
  defineConfigurableProperty(globalThis, "document", activeWindow.document ?? testDocument);
}

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
  configurable: true,
});

// Mock IndexedDB
const mockIndexedDB = {
  open: vi.fn(),
  deleteDatabase: vi.fn(),
};

Object.defineProperty(global, "indexedDB", {
  value: mockIndexedDB,
  writable: true,
  configurable: true,
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
