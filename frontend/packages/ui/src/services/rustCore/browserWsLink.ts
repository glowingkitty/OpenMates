/**
 * Thin browser adapter for the shared Rust WebSocket link
 * (`openmates_sdk::ws_link` via `BrowserWsLink` / `BrowserConnectionFeedback`).
 *
 * Rust owns every connection, reconnect, heartbeat, owner-consistency and
 * routing decision. This adapter owns only browser IO: the physical
 * `WebSocket`, `setTimeout`, `JSON.parse` of inbound frames (payload objects
 * go to JS handlers), the handler functions themselves, EventTarget events and
 * the page lifecycle listeners. It executes the returned commands verbatim.
 *
 * The public surface mirrors `webSocketService` so the coordinator can swap the
 * implementation behind `VITE_OPENMATES_RUST_CORE` without touching callers.
 * Nothing here is imported by the flag-off application.
 */

export type MessageHandler = (payload: unknown) => void | Promise<void>;

/** Structural view of the wasm `BrowserWsLink` export. */
export interface WsLinkCore {
  session(now: number, authenticated: boolean, loggingOut: boolean, hasToken: boolean): string;
  connect(now: number): string;
  retry(now: number): string;
  force_reconnect(now: number, reason: string): string;
  disconnect(now: number): string;
  refreshed(now: number, refresh: number, outcome: number, hasToken: boolean): string;
  opened(now: number, socket: number): string;
  errored(now: number, socket: number): string;
  closed(now: number, socket: number, code: number, reason: string, wasClean: boolean): string;
  timer(now: number, kind: number, seq: number): string;
  online(now: number): string;
  network_changed(now: number): string;
  resumed(now: number, source: number): string;
  foreground(now: number, foreground: boolean, source: number): string;
  data_activity(now: number): void;
  intern(messageType: string): number;
  frame_id(now: number, socket: number, typeId: number): number;
  frame_id_message(now: number, socket: number, typeId: number, errorMessage: string): number;
  frame(now: number, socket: number, messageType: string, errorMessage?: string): number;
  handlers(messageType: string): Uint32Array;
  drain(): string;
  on(messageType: string, handler: number): number;
  off(messageType: string, handler: number): boolean;
  clear(messageType: string): boolean;
  clear_all(): number;
  declare_family(family: number): void;
  open_socket(): number | undefined;
  status(): string;
}

/** Minimal `WebSocket` surface the adapter uses. */
export interface WebSocketLike {
  readonly readyState: number;
  onopen: ((event: unknown) => void) | null;
  /** `timeStamp` is the event's `performance.now()`-based time (every browser `MessageEvent`). */
  onmessage: ((event: { data: unknown; timeStamp: number }) => void) | null;
  onerror: ((event: unknown) => void) | null;
  onclose: ((event: { code: number; reason: string; wasClean: boolean }) => void) | null;
  send(data: string): void;
  close(code?: number, reason?: string): void;
}

export const REFRESH_OUTCOME = { ready: 0, signedOut: 1, principalMismatch: 2, failed: 3 } as const;
export type RefreshOutcomeCode = (typeof REFRESH_OUTCOME)[keyof typeof REFRESH_OUTCOME];
export const RESUME_SOURCE = { visibilitychange: 0, pageshow: 1 } as const;
export const LIFECYCLE_SOURCE = {
  open: 0, heartbeat: 1, visibilitychange: 2, focus: 3, blur: 4, pagehide: 5, recovery_requires_foreground: 6,
} as const;
export const FAMILY = { appSettings: 0, webhooks: 1, connectedAccounts: 2, highlights: 3 } as const;

const ACTION_MASK = 0x0f;
const FRAME_COMMANDS = 0x10;
const NOT_INTERNED = 0xffffffff;
const enum Action { Dispatch = 0, DispatchSerialized = 1, Buffer = 2, BufferEvictOldest = 3, Ignore = 4, Unhandled = 5, Stale = 6, UnknownTypeId = 7 }
const OPEN = 1;

export interface WsLinkPlatform {
  /** Monotonic milliseconds (`performance.now()`), the base of `MessageEvent.timeStamp`. */
  now(): number;
  setTimeout(callback: () => void, ms: number): void;
  /** A new socket for the current session, URL built with the current `ws_token`. */
  createSocket(): WebSocketLike;
  /** Refresh the session with the expected-principal header; classify the answer. */
  refreshSession(reason: string): Promise<{ outcome: RefreshOutcomeCode; hasToken: boolean }>;
  /** `document.visibilityState === 'visible' && document.hasFocus()`. */
  isForeground(): boolean;
  /** `websocketStatus.setStatus` / `setError`. */
  setStatus(status: string, error: string | null): void;
  /** Outgoing frame text; the default is `JSON.stringify({ type, payload })`. */
  serialize?(type: string, payload: unknown): string;
}

type LinkCommand =
  | { op: 'refresh'; refresh: number; reason: string }
  | { op: 'open'; socket: number }
  | { op: 'close'; socket: number; code: number; reason: string }
  | { op: 'ping'; socket: number }
  | { op: 'lifecycle'; socket: number; foreground: boolean; source: string }
  | { op: 'schedule'; timer: number; seq: number; delay: number }
  | { op: 'status'; status: string; error: string | null }
  | { op: 'emit'; event: string; code?: number; reason?: string | null; type?: string }
  | { op: 'settle'; ok: boolean; reason?: string };

/** One allocation per frame: `type` is `null` exactly when parsing failed. */
export type ParsedFrame =
  | { type: string; payload: unknown; errorMessage: string | undefined; error?: undefined; data?: undefined }
  | { type: null; payload?: undefined; errorMessage?: undefined; error: 'parse' | 'unknown_structure'; data: unknown };

export function parseLinkFrame(text: string): ParsedFrame {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return { type: null, error: 'parse', data: text };
  }
  if (raw === null) return { type: null, error: 'parse', data: text };
  const record = raw as Record<string, unknown>;
  if (typeof record.type === 'string') {
    const payload = record.payload !== undefined ? record.payload : record;
    return { type: record.type, payload, errorMessage: record.type === 'error' ? errorMessageOf(payload) : undefined };
  }
  if (typeof record.event === 'string') {
    return { type: record.event, payload: record, errorMessage: record.event === 'error' ? errorMessageOf(record) : undefined };
  }
  return { type: null, error: 'unknown_structure', data: raw };
}

function errorMessageOf(payload: unknown): string | undefined {
  if (payload !== null && typeof payload === 'object' && typeof (payload as { message?: unknown }).message === 'string') {
    return (payload as { message: string }).message;
  }
  return typeof payload === 'string' ? payload : undefined;
}

export class RustWsLink extends EventTarget {
  private readonly sockets = new Map<number, WebSocketLike>();
  private readonly handlers = new Map<number, MessageHandler>();
  private readonly handlerIds = new WeakMap<MessageHandler, number>();
  private readonly buffered = new Map<string, unknown[]>();
  /**
   * Per message type: the core's `intern` id and its handler order, refreshed
   * after every registration change. One lookup per frame. Types beyond the
   * core's intern table get an entry only while they have handlers.
   */
  private readonly types = new Map<string, { id: number; handlers: MessageHandler[] }>();
  private waiters: Array<{ resolve: () => void; reject: (reason: unknown) => void }> = [];
  private phasedQueue: Promise<void> = Promise.resolve();
  private nextHandlerId = 1;

  constructor(private readonly core: WsLinkCore, private readonly platform: WsLinkPlatform) {
    super();
  }

  /** Feed the auth store and logout flags (`authStore` subscription). */
  setSession(authenticated: boolean, loggingOut: boolean, hasToken: boolean): void {
    this.run(this.core.session(this.platform.now(), authenticated, loggingOut, hasToken));
  }

  /** Families whose handlers register after a dynamic import buffer early frames. */
  declareFamily(family: number): void {
    this.core.declare_family(family);
  }

  connect(): Promise<void> {
    const settled = new Promise<void>((resolve, reject) => this.waiters.push({ resolve, reject }));
    this.run(this.core.connect(this.platform.now()));
    return settled;
  }

  disconnect(): void { this.run(this.core.disconnect(this.platform.now())); }
  disconnectAndClearHandlers(): void { this.disconnect(); this.clearAllHandlers(); }
  retryConnection(): void { this.run(this.core.retry(this.platform.now())); }
  forceReconnect(reason: string): void { this.run(this.core.force_reconnect(this.platform.now(), reason)); }
  handleOnline(): void { this.run(this.core.online(this.platform.now())); }
  handleNetworkChange(): void { this.run(this.core.network_changed(this.platform.now())); }
  handleResume(source: number): void { this.run(this.core.resumed(this.platform.now(), source)); }
  setForeground(foreground: boolean, source: number): void { this.run(this.core.foreground(this.platform.now(), foreground, source)); }
  notifyDataActivity(): void { this.core.data_activity(this.platform.now()); }

  isConnected(): boolean {
    const socket = this.core.open_socket();
    return socket !== undefined && this.sockets.get(socket)?.readyState === OPEN;
  }

  /** Opaque identity of the open socket for receipt-bound sends. */
  getConnectionForSend(): object | null {
    const socket = this.core.open_socket();
    return socket === undefined ? null : this.sockets.get(socket) ?? null;
  }

  requestForegroundRecoveryDiscovery(requestId?: string): void {
    if (!this.platform.isForeground()) return;
    this.setForeground(true, LIFECYCLE_SOURCE.recovery_requires_foreground);
    const socket = this.getConnectionForSend() as WebSocketLike | null;
    socket?.send(JSON.stringify({ type: 'request_recovery_discovery', payload: requestId ? { request_id: requestId } : {} }));
  }

  async sendMessage(type: string, payload: unknown, options?: { expectedConnection: object | null }): Promise<void> {
    const assertExpected = () => {
      if (options && (!options.expectedConnection || options.expectedConnection !== this.getConnectionForSend())) {
        throw Object.assign(new Error('WebSocket receipt connection changed before message dispatch'), { code: 'websocket_receipt_connection_changed' });
      }
    };
    assertExpected();
    if (!this.isConnected()) {
      await this.connect().catch(() => { throw new Error('WebSocket not connected'); });
    }
    const socket = this.getConnectionForSend() as WebSocketLike | null;
    if (!socket || socket.readyState !== OPEN) throw new Error('WebSocket not connected after reconnect attempt');
    assertExpected();
    socket.send(this.platform.serialize ? this.platform.serialize(type, payload) : JSON.stringify({ type, payload }));
  }

  on<T = unknown>(messageType: string, handler: (payload: T) => void | Promise<void>): void {
    const fn = handler as MessageHandler;
    let id = this.handlerIds.get(fn);
    if (id === undefined) {
      id = this.nextHandlerId++;
      this.handlerIds.set(fn, id);
      this.handlers.set(id, fn);
    }
    const replay = this.core.on(messageType, id);
    if (replay < 0) {
      console.warn(`[RustWsLink] Handler already registered for "${messageType}". Skipping duplicate registration.`);
      return;
    }
    this.mirror(messageType);
    const kept = this.buffered.get(messageType);
    this.buffered.delete(messageType);
    for (const buffered of replay > 0 && kept ? kept.slice(-replay) : []) {
      void Promise.resolve(fn(buffered)).catch((error) => console.error(`[RustWsLink] Replayed "${messageType}" handler failed:`, error));
    }
  }

  off<T = unknown>(messageType: string, handler: (payload: T) => void | Promise<void>): void {
    const id = this.handlerIds.get(handler as MessageHandler);
    if (id !== undefined && this.core.off(messageType, id)) this.mirror(messageType);
  }

  clearHandlers(messageType: string): void {
    this.core.clear(messageType);
    this.mirror(messageType);
  }

  clearAllHandlers(): void {
    this.core.clear_all();
    for (const entry of this.types.values()) entry.handlers = [];
    this.dispatchEvent(new CustomEvent('handlers_cleared'));
  }

  private mirror(messageType: string): void {
    const ids = this.core.handlers(messageType);
    const handlers: MessageHandler[] = [];
    for (const id of ids) {
      const handler = this.handlers.get(id);
      if (!handler) throw new Error(`[RustWsLink] core routed unknown handler id ${id}`);
      handlers.push(handler);
    }
    const entry = this.entry(messageType);
    if (entry) entry.handlers = handlers;
    else if (handlers.length) this.types.set(messageType, { id: NOT_INTERNED, handlers });
  }

  private entry(type: string): { id: number; handlers: MessageHandler[] } | undefined {
    let entry = this.types.get(type);
    if (entry === undefined) {
      const id = this.core.intern(type);
      if (id === NOT_INTERNED) return undefined;
      entry = { id, handlers: [] };
      this.types.set(type, entry);
    }
    return entry;
  }

  private run(json: string): void {
    for (const command of JSON.parse(json) as LinkCommand[]) this.execute(command);
  }

  private execute(command: LinkCommand): void {
    switch (command.op) {
      case 'refresh':
        void this.platform.refreshSession(command.reason).then(
          ({ outcome, hasToken }) => this.run(this.core.refreshed(this.platform.now(), command.refresh, outcome, hasToken)),
          (error: unknown) => {
            console.warn('[RustWsLink] Session refresh before WebSocket retry failed:', error);
            this.run(this.core.refreshed(this.platform.now(), command.refresh, REFRESH_OUTCOME.failed, false));
          },
        );
        return;
      case 'open':
        this.open(command.socket);
        return;
      case 'close': {
        const socket = this.sockets.get(command.socket);
        this.sockets.delete(command.socket);
        if (!socket) return;
        socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null;
        socket.close(command.code, command.reason);
        return;
      }
      case 'ping':
        this.sockets.get(command.socket)?.send('{"type":"ping","payload":{}}');
        return;
      case 'lifecycle':
        this.sockets.get(command.socket)?.send(JSON.stringify({
          type: 'native_client_lifecycle',
          payload: { is_foreground: command.foreground, client_type: 'web', source: command.source },
        }));
        return;
      case 'schedule':
        this.platform.setTimeout(() => this.run(this.core.timer(this.platform.now(), command.timer, command.seq)), command.delay);
        return;
      case 'status':
        this.platform.setStatus(command.status, command.error);
        return;
      case 'emit':
        this.dispatchEvent(new CustomEvent(command.event, { detail: emitDetail(command) }));
        return;
      case 'settle': {
        const waiters = this.waiters;
        this.waiters = [];
        for (const waiter of waiters) {
          if (command.ok) waiter.resolve();
          else waiter.reject(command.reason);
        }
        return;
      }
    }
  }

  private open(id: number): void {
    let socket: WebSocketLike;
    try {
      socket = this.platform.createSocket();
    } catch (error) {
      // Construction failure (bad URL, blocked scheme) is an attempt failure:
      // report it and let the core run its normal backoff path.
      console.error('[RustWsLink] Failed to create WebSocket:', error);
      this.dispatchEvent(new CustomEvent('connection_failed_initial', { detail: error }));
      this.run(this.core.errored(this.platform.now(), id));
      this.run(this.core.closed(this.platform.now(), id, 1006, '', false));
      return;
    }
    this.sockets.set(id, socket);
    socket.onopen = () => this.run(this.core.opened(this.platform.now(), id));
    socket.onerror = () => this.run(this.core.errored(this.platform.now(), id));
    socket.onclose = (event) => {
      this.sockets.delete(id);
      this.run(this.core.closed(this.platform.now(), id, event.code, event.reason ?? '', event.wasClean));
    };
    socket.onmessage = (event) => this.receive(id, event.data, event.timeStamp);
  }

  private receive(id: number, data: unknown, now: number): void {
    const parsed = parseLinkFrame(data as string);
    if (parsed.type === null) {
      this.dispatchEvent(new CustomEvent('message_error', {
        detail: { error: parsed.error === 'parse' ? 'Parsing/handling error' : 'Unknown message structure', data: parsed.data },
      }));
      return;
    }
    const { type, payload, errorMessage } = parsed;
    const entry = this.entry(type);
    const code = entry === undefined || entry.id === NOT_INTERNED
      ? this.core.frame(now, id, type, errorMessage)
      : errorMessage === undefined
        ? this.core.frame_id(now, id, entry.id)
        : this.core.frame_id_message(now, id, entry.id, errorMessage);
    if (code & FRAME_COMMANDS) this.run(this.core.drain());
    const action = code & ACTION_MASK;
    if (action === Action.UnknownTypeId) throw new Error(`[RustWsLink] core rejected the interned id of "${type}"`);
    if (action === Action.Stale) return;
    this.dispatchEvent(new CustomEvent('message', { detail: { type, payload } }));
    switch (action) {
      case Action.Dispatch:
        void this.runHandlers(type, routed(type, entry), payload);
        return;
      case Action.DispatchSerialized: {
        const handlers = routed(type, entry);
        const next = () => this.runHandlers(type, handlers, payload);
        this.phasedQueue = this.phasedQueue.then(next, next);
        return;
      }
      case Action.Buffer:
      case Action.BufferEvictOldest: {
        const kept = this.buffered.get(type) ?? [];
        if (action === Action.BufferEvictOldest) kept.shift();
        kept.push(payload);
        this.buffered.set(type, kept);
        return;
      }
      case Action.Unhandled:
        console.warn(`[RustWsLink] No handlers found for message.type: "${type}".`);
        return;
    }
  }

  /** Handlers run in order, each awaited; one failing handler never stops the rest. */

  private async runHandlers(type: string, handlers: MessageHandler[], payload: unknown): Promise<void> {
    for (let index = 0; index < handlers.length; index++) {
      try {
        await handlers[index](payload);
      } catch (error) {
        console.error(`[RustWsLink] Error in message handler #${index + 1} for type "${type}":`, error);
      }
    }
  }
}

function routed(type: string, entry: { handlers: MessageHandler[] } | undefined): MessageHandler[] {
  if (!entry?.handlers.length) throw new Error(`[RustWsLink] core dispatched "${type}" without mirrored handlers`);
  return entry.handlers;
}

function emitDetail(command: Extract<LinkCommand, { op: 'emit' }>): unknown {
  switch (command.event) {
    case 'close': return { code: command.code };
    case 'authError': return command.reason ? { reason: command.reason } : undefined;
    case 'reAuthRequired': return { type: command.type };
    default: return undefined;
  }
}

/** Page lifecycle wiring; returns a detach function. */
export function attachBrowserLifecycle(
  link: RustWsLink,
  env: { window: Window; document: Document; navigator: Navigator },
  hooks: { onWake?: (source: string) => void } = {},
): () => void {
  const { window: win, document: doc } = env;
  const foreground = () => doc.visibilityState === 'visible' && doc.hasFocus();
  const wake = (source: string) => hooks.onWake?.(source);
  const listeners: Array<[EventTarget, string, EventListener]> = [
    [win, 'online', () => { wake('online'); link.handleOnline(); }],
    [doc, 'visibilitychange', () => {
      link.setForeground(foreground(), LIFECYCLE_SOURCE.visibilitychange);
      if (doc.visibilityState !== 'visible') return;
      wake('visibilitychange');
      link.handleResume(RESUME_SOURCE.visibilitychange);
    }],
    [win, 'focus', () => link.setForeground(foreground(), LIFECYCLE_SOURCE.focus)],
    [win, 'blur', () => link.setForeground(false, LIFECYCLE_SOURCE.blur)],
    [win, 'pagehide', () => link.setForeground(false, LIFECYCLE_SOURCE.pagehide)],
    [win, 'pageshow', (event) => {
      if (!(event as PageTransitionEvent).persisted) return;
      wake('pageshow');
      link.handleResume(RESUME_SOURCE.pageshow);
    }],
  ];
  const connection = (env.navigator as Navigator & { connection?: EventTarget }).connection;
  if (connection && typeof connection.addEventListener === 'function') {
    listeners.push([connection, 'change', () => { wake('connection-change'); link.handleNetworkChange(); }]);
  }
  for (const [target, type, listener] of listeners) target.addEventListener(type, listener);
  return () => {
    for (const [target, type, listener] of listeners) target.removeEventListener(type, listener);
  };
}
