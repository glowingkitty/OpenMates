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
  /**
   * The element's `id` attribute, if present.
   * Highly stable and grep-able in source code (e.g. `id="send-btn"`).
   */
  id?: string;
  /**
   * Raw value of the `data-action` attribute on the resolved element, if present.
   * Stored separately from `action` (which is the fully-resolved label) so an LLM
   * can search source files directly for `data-action="<value>"`.
   */
  dataAction?: string;
  /**
   * All meaningful CSS classes on the resolved element (filtered: non-Svelte hashes,
   * length ≥ 4, not in the generic blocklist). Allows LLMs to locate the element
   * by searching for `.class-name` in component files.
   */
  classes?: string[];
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Maximum number of entries kept in the circular buffer. */
const MAX_ENTRIES = 20;

/**
 * Sentinel label recorded once when the user opens the Report Issue section.
 * All subsequent interactions *within* that section are suppressed to avoid
 * flooding the action history with form focus/toggle noise that hides the
 * meaningful context that came before opening the panel.
 */
const REPORT_ISSUE_SENTINEL = "Started report issue";

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
  /**
   * Tracks whether we have already emitted the REPORT_ISSUE_SENTINEL entry.
   * Once true, all further events originating from within the report-issue
   * section (`data-section="report-issue"`) are silently dropped so that the
   * action history shows what the user was doing *before* opening the panel,
   * ending cleanly with "Started report issue".
   *
   * Reset to false whenever a non-report-issue event fires, so that if the
   * user closes and reopens the panel another sentinel will be recorded.
   */
  private _reportIssueSentinelEmitted = false;

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
   * Format per line (optional selector fields appended only when present):
   *   [2024-01-15 14:32:01.456] type      element    action  [selector fields...]  [key]
   *
   * Selector fields (for LLM source-code lookup):
   *   id=<value>           — element id attribute (grep: id="<value>")
   *   data-action=<value>  — raw data-action attribute (grep: data-action="<value>")
   *   cls=[a,b,c]          — meaningful CSS classes (grep: .class-name in .svelte files)
   *
   * Example:
   *   [2024-01-15 14:32:01.123] click     button     send-message  id=send-btn  data-action=send-message  cls=[send-message-btn,primary]
   *   [2024-01-15 14:32:05.456] focus     textarea   message-input  id=chat-input  cls=[chat-input]
   *   [2024-01-15 14:32:09.789] keypress  textarea   message-input  id=chat-input  cls=[chat-input]  [Enter]
   */
  getActionHistoryAsText(): string {
    if (this._entries.length === 0) {
      return "(no actions recorded)";
    }
    return this._entries
      .map((entry) => {
        // Full ISO timestamp with milliseconds — matches console log format and
        // enables cross-correlation with backend logs.
        // Format: "2024-01-15 14:32:01.456"
        const ts = new Date(entry.ts)
          .toISOString()
          .replace("T", " ")
          .slice(0, 23);
        const type = entry.type.padEnd(9);
        const element = entry.element.padEnd(10);
        const action = entry.action;

        // Build optional selector suffix — only include fields that are present
        const selectorParts: string[] = [];
        if (entry.id) {
          selectorParts.push(`id=${entry.id}`);
        }
        if (entry.dataAction) {
          selectorParts.push(`data-action=${entry.dataAction}`);
        }
        if (entry.classes && entry.classes.length > 0) {
          selectorParts.push(`cls=[${entry.classes.join(",")}]`);
        }
        const selector =
          selectorParts.length > 0 ? `  ${selectorParts.join("  ")}` : "";

        const key = entry.key ? `  [${entry.key}]` : "";
        return `[${ts}] ${type} ${element} ${action}${selector}${key}`;
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

      // Detect if the interaction is inside the report-issue section.
      // The first such interaction records a single sentinel; all subsequent
      // ones from within the same section are dropped to keep the history clean.
      if (this._isInsideReportIssueSection(target)) {
        if (!this._reportIssueSentinelEmitted) {
          this._reportIssueSentinelEmitted = true;
          this._record({
            type: "click",
            element: "section",
            action: REPORT_ISSUE_SENTINEL,
          });
        }
        // Suppress all further report-issue interactions
        return;
      }

      // Any event outside the section resets the sentinel so the panel can be
      // reopened and produce a new sentinel in the future.
      this._reportIssueSentinelEmitted = false;

      const { element, action, id, dataAction, classes } =
        this._resolveTarget(target);
      if (!action) return;
      this._record({ type: "click", element, action, id, dataAction, classes });
    } catch {
      // Never throw from a passive listener
    }
  };

  private _handleFocusIn = (event: Event): void => {
    try {
      const target = event.target as Element | null;
      if (!target) return;

      // Suppress focus events that originate inside the report-issue section
      // (avoids noisy focus entries for every input field the user tabs through)
      if (this._isInsideReportIssueSection(target)) {
        if (!this._reportIssueSentinelEmitted) {
          this._reportIssueSentinelEmitted = true;
          this._record({
            type: "focus",
            element: "section",
            action: REPORT_ISSUE_SENTINEL,
          });
        }
        return;
      }

      this._reportIssueSentinelEmitted = false;

      // Only track focus on interactive elements
      const tag = target.tagName.toLowerCase();
      if (!INTERACTIVE_TAGS.has(tag) && !target.getAttribute("data-action"))
        return;
      const { element, action, id, dataAction, classes } =
        this._resolveTarget(target);
      if (!action) return;
      this._record({ type: "focus", element, action, id, dataAction, classes });
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

      // Suppress keypresses inside the report-issue section
      if (this._isInsideReportIssueSection(target)) {
        // No sentinel here — click/focus handlers already handle that.
        // Just suppress silently.
        return;
      }

      this._reportIssueSentinelEmitted = false;

      const { element, action, id, dataAction, classes } =
        this._resolveTarget(target);
      if (!action) return;
      this._record({
        type: "keypress",
        element,
        action,
        id,
        dataAction,
        classes,
        key,
      });
    } catch {
      // Never throw from a passive listener
    }
  };

  // -----------------------------------------------------------------------
  // Private: report-issue section detection
  // -----------------------------------------------------------------------

  /**
   * Returns true if `target` is a descendant of an element with
   * `data-section="report-issue"`.
   *
   * Walks at most 30 levels up to cover deeply nested form elements while
   * still being cheap enough to run on every captured event.
   */
  private _isInsideReportIssueSection(target: Element): boolean {
    let current: Element | null = target;
    let depth = 0;
    while (current && depth < 30) {
      if (current.getAttribute("data-section") === "report-issue") {
        return true;
      }
      current = current.parentElement;
      depth++;
    }
    return false;
  }

  // -----------------------------------------------------------------------
  // Private: target resolution
  // -----------------------------------------------------------------------

  /**
   * Walks up the DOM from `target` (at most 6 levels) to find the nearest
   * meaningful interactive ancestor, then derives a privacy-safe action label
   * and selector metadata (id, data-action, CSS classes) useful for locating
   * the element in source code.
   *
   * Returns `{ element: '', action: '' }` if no meaningful target is found
   * (the caller should skip recording in that case).
   */
  private _resolveTarget(target: Element): {
    element: string;
    action: string;
    id?: string;
    dataAction?: string;
    classes?: string[];
  } {
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

      // Collect selector metadata — these allow an LLM to search source files
      // directly for the element (e.g. `id="send-btn"`, `.send-message-btn`).
      const elementId = current.getAttribute("id") || undefined;
      const rawDataAction =
        dataAction && dataAction.trim() ? dataAction.trim() : undefined;
      const meaningfulClasses = this._getMeaningfulClasses(current);
      const classes =
        meaningfulClasses.length > 0 ? meaningfulClasses : undefined;

      return {
        element: tag,
        action: label,
        id: elementId,
        dataAction: rawDataAction,
        classes,
      };
    }

    return { element: "", action: "" };
  }

  /**
   * Returns all CSS classes on an element that are meaningful for source-code
   * searching: not Svelte hashes (no digits), length ≥ 4, not in the generic
   * blocklist. Unlike `_deriveLabelFromClasses`, this returns ALL qualifying
   * classes (not just the first) so the full selector context is available.
   */
  private _getMeaningfulClasses(el: Element): string[] {
    const result: string[] = [];
    for (const cls of Array.from(el.classList)) {
      if (cls.length < 4) continue;
      if (/\d/.test(cls)) continue; // skip Svelte hashes like svelte-abc123
      if (GENERIC_CLASS_NAMES.has(cls.toLowerCase())) continue;
      result.push(cls);
    }
    return result;
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
