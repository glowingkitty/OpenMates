/**
 * userActionTracker.ts
 *
 * Passive user-action history tracker for issue reporting.
 *
 * Design goals:
 * - ZERO component modifications required for basic coverage.
 *   A single delegated event listener on `document` captures every click,
 *   focus, and key-press across the entire application.
 * - PRIVACY-SAFE: we never capture text content typed by the user or any
 *   element `.value` / `.textContent`. Labels are derived from developer-authored
 *   attributes only (`data-action`, `aria-label`, `title`, `placeholder`).
 * - Explicit opt-in for important elements: adding `data-action="name"` to a
 *   button or input gives a clean, stable label that survives Svelte re-renders.
 * - SURVIVES tab reloads: history is stored in `sessionStorage` so it persists
 *   across hard page reloads (F5) within the same browser tab but is cleared
 *   when the tab is closed (unlike `localStorage`).
 * - MAX_ENTRIES (20) circular buffer: oldest entries are dropped automatically.
 *
 * Architecture:
 * - Instantiated once as a singleton (exported as `userActionTracker`).
 * - Starts listening at module load time — no explicit `init()` call needed.
 * - The singleton is imported in the app entry point to ensure interception
 *   begins immediately.
 *
 * Entry format (stored as JSON in sessionStorage):
 * ```json
 * [
 *   {
 *     "ts": 1709900000000,
 *     "type": "click",
 *     "element": "button",
 *     "action": "send-message"
 *   },
 *   {
 *     "ts": 1709900005000,
 *     "type": "keypress",
 *     "element": "div",
 *     "action": "message-input",
 *     "key": "Enter"
 *   }
 * ]
 * ```
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** The kind of user interaction that was captured. */
type ActionType = "click" | "focus" | "keypress";

/** A single recorded user action. */
export interface ActionEntry {
  /** Unix timestamp in milliseconds. */
  ts: number;
  /** Type of interaction. */
  type: ActionType;
  /** Lowercase HTML tag name of the target element (e.g. "button", "input"). */
  element: string;
  /**
   * Human-readable action label derived from (in priority order):
   *   1. `data-action` attribute on the element or an ancestor
   *   2. `aria-label` attribute
   *   3. `title` attribute
   *   4. `placeholder` attribute (inputs / textareas only)
   *   5. First meaningful CSS class name (non-Svelte, length > 3)
   *   6. Element tag name as last resort
   */
  action: string;
  /** Only set for `keypress` events: the key name (e.g. "Enter", "Escape"). */
  key?: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Maximum number of entries kept in the circular buffer. */
const MAX_ENTRIES = 20;

/** sessionStorage key used to persist the circular buffer. */
const SESSION_STORAGE_KEY = "_om_action_history";

/**
 * HTML element types that are considered "interactive" and worth recording.
 * Interactions on non-interactive parents are ignored unless they carry a
 * `data-action` attribute.
 */
const INTERACTIVE_TAGS = new Set([
  "button",
  "a",
  "input",
  "textarea",
  "select",
  "summary",
  "label",
  "details",
  "video",
  "audio",
]);

/** Keyboard keys that are meaningful to track (avoid noise from printable keys). */
const TRACKED_KEYS = new Set([
  "Enter",
  "Escape",
  "Tab",
  "ArrowUp",
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
  "Backspace",
  "Delete",
  "Space",
]);

/**
 * CSS class names that are too generic to be useful as action labels.
 * These are skipped when building the class-name fallback.
 */
const GENERIC_CLASS_NAMES = new Set([
  "active",
  "disabled",
  "hidden",
  "visible",
  "open",
  "closed",
  "selected",
  "checked",
  "focus",
  "hover",
  "loading",
  "error",
  "success",
  "warning",
  "info",
  "light",
  "dark",
  "small",
  "large",
  "left",
  "right",
  "top",
  "bottom",
  "center",
  "flex",
  "grid",
  "block",
  "inline",
  "relative",
  "absolute",
  "fixed",
  "sticky",
  "overflow",
  "truncate",
  "wrapper",
  "container",
  "content",
  "inner",
  "outer",
  "row",
  "col",
  "icon",
  "text",
  "label",
  "title",
  "body",
  "header",
  "footer",
  "main",
  "nav",
  "menu",
  "list",
  "item",
  "link",
  "btn",
  "button",
  "input",
  "form",
  "field",
  "group",
  "section",
  "page",
  "panel",
  "modal",
  "dialog",
  "card",
  "badge",
  "tag",
  "chip",
]);

// ---------------------------------------------------------------------------
// UserActionTrackerService
// ---------------------------------------------------------------------------

class UserActionTrackerService {
  /** In-memory copy of the circular buffer (synced with sessionStorage). */
  private _entries: ActionEntry[] = [];
  /** Whether the event listeners have been attached. */
  private _listening = false;

  constructor() {
    this._loadFromStorage();
    this._startListening();
  }

  // -----------------------------------------------------------------------
  // Public API
  // -----------------------------------------------------------------------

  /**
   * Returns a copy of all recorded action entries, oldest first.
   */
  getActionHistory(): ActionEntry[] {
    return [...this._entries];
  }

  /**
   * Returns the action history as a formatted text block suitable for
   * inclusion in an issue report.
   *
   * Format per line:
   *   [HH:MM:SS] type     element  action  [key]
   *
   * Example:
   *   [14:32:01] click    button   new-chat
   *   [14:32:05] focus    div      message-input
   *   [14:32:09] keypress div      message-input  [Enter]
   */
  getActionHistoryAsText(): string {
    if (this._entries.length === 0) {
      return "(no actions recorded)";
    }
    return this._entries
      .map((entry) => {
        const time = new Date(entry.ts).toLocaleTimeString("en-GB", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        });
        const type = entry.type.padEnd(9);
        const element = entry.element.padEnd(10);
        const action = entry.action;
        const key = entry.key ? `  [${entry.key}]` : "";
        return `[${time}] ${type} ${element} ${action}${key}`;
      })
      .join("\n");
  }

  /**
   * Clears the action history from both memory and sessionStorage.
   * Called automatically on application logout if needed.
   */
  clearActionHistory(): void {
    this._entries = [];
    try {
      sessionStorage.removeItem(SESSION_STORAGE_KEY);
    } catch {
      // sessionStorage may be unavailable in some contexts (e.g., private mode)
    }
  }

  /**
   * Tears down all event listeners. Useful for testing.
   */
  destroy(): void {
    if (!this._listening) return;
    document.removeEventListener("click", this._handleClick, true);
    document.removeEventListener("focusin", this._handleFocusIn, true);
    document.removeEventListener("keydown", this._handleKeyDown, true);
    this._listening = false;
  }

  // -----------------------------------------------------------------------
  // Private: event listeners
  // -----------------------------------------------------------------------

  private _startListening(): void {
    if (typeof document === "undefined") {
      // SSR / non-browser context — skip silently
      return;
    }
    if (this._listening) return;

    // Use capture phase so we see events before any `stopPropagation` call
    document.addEventListener("click", this._handleClick, true);
    document.addEventListener("focusin", this._handleFocusIn, true);
    document.addEventListener("keydown", this._handleKeyDown, true);
    this._listening = true;
  }

  private _handleClick = (event: Event): void => {
    try {
      const target = event.target as Element | null;
      if (!target) return;
      const { element, action } = this._resolveTarget(target);
      if (!action) return;
      this._record({ type: "click", element, action });
    } catch {
      // Never throw from a passive listener
    }
  };

  private _handleFocusIn = (event: Event): void => {
    try {
      const target = event.target as Element | null;
      if (!target) return;
      // Only track focus on interactive elements
      const tag = target.tagName.toLowerCase();
      if (!INTERACTIVE_TAGS.has(tag) && !target.getAttribute("data-action"))
        return;
      const { element, action } = this._resolveTarget(target);
      if (!action) return;
      this._record({ type: "focus", element, action });
    } catch {
      // Never throw from a passive listener
    }
  };

  private _handleKeyDown = (event: Event): void => {
    try {
      const ke = event as KeyboardEvent;
      const key = ke.key;
      if (!TRACKED_KEYS.has(key)) return;

      const target = ke.target as Element | null;
      if (!target) return;
      const { element, action } = this._resolveTarget(target);
      if (!action) return;
      this._record({ type: "keypress", element, action, key });
    } catch {
      // Never throw from a passive listener
    }
  };

  // -----------------------------------------------------------------------
  // Private: target resolution
  // -----------------------------------------------------------------------

  /**
   * Walks up the DOM from `target` (at most 6 levels) to find the nearest
   * meaningful interactive ancestor, then derives a privacy-safe action label.
   *
   * Returns `{ element: '', action: '' }` if no meaningful target is found
   * (the caller should skip recording in that case).
   */
  private _resolveTarget(target: Element): { element: string; action: string } {
    let current: Element | null = target;
    let depth = 0;

    while (current && depth < 6) {
      const tag = current.tagName.toLowerCase();
      const dataAction = current.getAttribute("data-action");
      const role = current.getAttribute("role");
      const isInteractive =
        INTERACTIVE_TAGS.has(tag) ||
        role === "button" ||
        role === "link" ||
        role === "menuitem" ||
        role === "tab" ||
        role === "checkbox" ||
        role === "radio" ||
        role === "switch" ||
        !!dataAction;

      if (!isInteractive) {
        current = current.parentElement;
        depth++;
        continue;
      }

      // Derive action label using priority order
      const label = this._deriveLabel(current, tag);
      if (!label) {
        current = current.parentElement;
        depth++;
        continue;
      }

      return { element: tag, action: label };
    }

    return { element: "", action: "" };
  }

  /**
   * Derives a privacy-safe human-readable label for an element.
   *
   * Priority:
   *   1. `data-action` attribute (developer-authored, explicit)
   *   2. `aria-label` attribute (developer-authored, accessibility)
   *   3. `title` attribute
   *   4. `placeholder` attribute (inputs / textareas — developer-authored)
   *   5. First meaningful CSS class name
   *   6. Element's tag name (last resort)
   */
  private _deriveLabel(el: Element, tag: string): string {
    // 1. data-action (highest priority — explicit developer annotation)
    const dataAction = el.getAttribute("data-action");
    if (dataAction && dataAction.trim()) {
      return this._sanitizeLabel(dataAction.trim());
    }

    // 2. aria-label
    const ariaLabel = el.getAttribute("aria-label");
    if (ariaLabel && ariaLabel.trim()) {
      return this._sanitizeLabel(ariaLabel.trim());
    }

    // 3. title
    const title = el.getAttribute("title");
    if (title && title.trim()) {
      return this._sanitizeLabel(title.trim());
    }

    // 4. placeholder (inputs/textareas only — developer-authored hint text)
    if (tag === "input" || tag === "textarea") {
      const placeholder = el.getAttribute("placeholder");
      if (placeholder && placeholder.trim()) {
        return this._sanitizeLabel(placeholder.trim());
      }
    }

    // 5. First meaningful CSS class name
    const classLabel = this._deriveLabelFromClasses(el);
    if (classLabel) {
      return classLabel;
    }

    // 6. Tag name as last resort (only if it's clearly interactive)
    if (tag === "button" || tag === "a" || tag === "select") {
      return tag;
    }

    return "";
  }

  /**
   * Tries to derive a useful label from the element's CSS class list.
   *
   * Rules:
   * - Skip classes shorter than 4 characters (too generic)
   * - Skip classes that contain digits (likely Svelte hash suffixes like `svelte-abc123`)
   * - Skip classes in the GENERIC_CLASS_NAMES blocklist
   * - Prefer longer, more descriptive class names
   * - Return the first qualifying class, converted from kebab-case to a readable label
   */
  private _deriveLabelFromClasses(el: Element): string {
    const classes = Array.from(el.classList);
    for (const cls of classes) {
      if (cls.length < 4) continue;
      if (/\d/.test(cls)) continue; // skip Svelte hashes and numeric suffixes
      if (GENERIC_CLASS_NAMES.has(cls.toLowerCase())) continue;
      // Convert kebab-case to space-separated for readability
      return cls.replace(/-/g, " ");
    }
    return "";
  }

  /**
   * Sanitizes a label string:
   * - Truncate to 60 chars to keep entries compact
   * - Remove HTML tags (defense in depth)
   * - Replace newlines/tabs with spaces
   */
  private _sanitizeLabel(label: string): string {
    return label
      .replace(/<[^>]*>/g, "") // strip HTML tags
      .replace(/[\n\r\t]/g, " ") // normalize whitespace
      .trim()
      .slice(0, 60);
  }

  // -----------------------------------------------------------------------
  // Private: circular buffer management
  // -----------------------------------------------------------------------

  /**
   * Records a new action entry into the circular buffer and persists to
   * sessionStorage.
   *
   * Deduplication: if the last entry has the same type + action and was
   * recorded within 500ms, skip it (prevents double-fire on composited events).
   */
  private _record(partial: Omit<ActionEntry, "ts">): void {
    const entry: ActionEntry = { ts: Date.now(), ...partial };

    // Deduplicate rapid same-event pairs (e.g., click + focusin from same interaction)
    if (this._entries.length > 0) {
      const last = this._entries[this._entries.length - 1];
      if (
        last.type === entry.type &&
        last.action === entry.action &&
        entry.ts - last.ts < 500
      ) {
        return;
      }
    }

    // Add entry and enforce max size (circular buffer — drop oldest)
    this._entries.push(entry);
    if (this._entries.length > MAX_ENTRIES) {
      this._entries.shift();
    }

    this._saveToStorage();
  }

  // -----------------------------------------------------------------------
  // Private: sessionStorage persistence
  // -----------------------------------------------------------------------

  private _loadFromStorage(): void {
    try {
      const raw = sessionStorage.getItem(SESSION_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        // Only keep entries within the last 2 hours to avoid stale data on reload
        const cutoff = Date.now() - 2 * 60 * 60 * 1000;
        this._entries = parsed
          .filter((e: unknown) => typeof e === "object" && e !== null)
          .filter((e: ActionEntry) => e.ts > cutoff)
          .slice(-MAX_ENTRIES);
      }
    } catch {
      // sessionStorage unavailable or corrupted — start fresh
      this._entries = [];
    }
  }

  private _saveToStorage(): void {
    try {
      sessionStorage.setItem(
        SESSION_STORAGE_KEY,
        JSON.stringify(this._entries),
      );
    } catch {
      // sessionStorage may be full or unavailable — fail silently
    }
  }
}

// ---------------------------------------------------------------------------
// Singleton export
// ---------------------------------------------------------------------------

/**
 * Singleton user action tracker instance.
 *
 * Imported in the app entry point (app.ts) so tracking begins on app load.
 * Imported in SettingsReportIssue to include action history in issue reports.
 */
export const userActionTracker = new UserActionTrackerService();
