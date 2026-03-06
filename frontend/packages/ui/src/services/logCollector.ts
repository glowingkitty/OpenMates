/**
 * Console Log Collector Service
 *
 * Captures console messages for debugging and issue reporting.
 * Maintains two circular buffers:
 *   - Main buffer (500 entries): all log levels
 *   - Error buffer (100 entries): only error + warn — survives noise eviction
 *
 * The separate error buffer solves the problem where critical decryption errors
 * and other failures get evicted by high-volume noise (WebSocket pings,
 * ShareMetadataQueue, OfflineBanner, etc.) before the user can run debug.logs().
 *
 * Also supports real-time listeners via onNewLog() / offNewLog() callbacks, used by the
 * ClientLogForwarder to forward admin console logs to the server for centralized debugging.
 */

export interface ConsoleLogEntry {
  timestamp: number;
  level: "log" | "info" | "warn" | "error" | "debug";
  message: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  args: any[];
}

/** Log levels that can be used to filter getLogs() results */
export type LogLevel = ConsoleLogEntry["level"];

/** Callback type for new log entry listeners (used by ClientLogForwarder) */
export type LogEntryListener = (entry: ConsoleLogEntry) => void;

/** Maximum entries in the main (all-levels) circular buffer */
const MAX_MAIN_LOGS = 500;

/** Maximum entries in the error/warn-only circular buffer */
const MAX_ERROR_LOGS = 100;

/** Maximum length of a single log message before truncation */
const MAX_MESSAGE_LENGTH = 1000;

class LogCollectorService {
  /** Main circular buffer — all log levels */
  private logs: ConsoleLogEntry[] = [];

  /**
   * Separate circular buffer for error + warn entries only.
   * These are the most important logs for debugging and must survive
   * even when the main buffer is full of routine noise.
   */
  private errorLogs: ConsoleLogEntry[] = [];

  private originalConsole: {
    log: typeof console.log;
    info: typeof console.info;
    warn: typeof console.warn;
    error: typeof console.error;
    debug: typeof console.debug;
  };
  /** Registered listeners notified on each new log entry (e.g. ClientLogForwarder) */
  private listeners: Set<LogEntryListener> = new Set();

  constructor() {
    // Store original console methods
    this.originalConsole = {
      log: console.log,
      info: console.info,
      warn: console.warn,
      error: console.error,
      debug: console.debug,
    };

    this.interceptConsole();
  }

  /**
   * Intercept console methods to capture logs
   */
  private interceptConsole(): void {
    const interceptMethod = (
      level: "log" | "info" | "warn" | "error" | "debug",
      originalMethod: (...args: unknown[]) => void,
    ) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return (...args: any[]) => {
        // Call original method first
        originalMethod.apply(console, args);

        // Capture the log entry
        this.captureLog(level, args);
      };
    };

    console.log = interceptMethod("log", this.originalConsole.log);
    console.info = interceptMethod("info", this.originalConsole.info);
    console.warn = interceptMethod("warn", this.originalConsole.warn);
    console.error = interceptMethod("error", this.originalConsole.error);
    console.debug = interceptMethod("debug", this.originalConsole.debug);
  }

  /**
   * Capture a console log entry into both buffers (main + error if applicable).
   */
  private captureLog(
    level: "log" | "info" | "warn" | "error" | "debug",
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    args: any[],
  ): void {
    try {
      // Convert arguments to strings safely
      const message = args
        .map((arg) => {
          if (typeof arg === "string") {
            return arg;
          } else if (arg === null) {
            return "null";
          } else if (arg === undefined) {
            return "undefined";
          } else if (typeof arg === "object") {
            try {
              return JSON.stringify(arg, null, 2);
            } catch {
              return "[Object object - circular or non-serializable]";
            }
          } else {
            return String(arg);
          }
        })
        .join(" ");

      const logEntry: ConsoleLogEntry = {
        timestamp: Date.now(),
        level,
        message: this.sanitizeMessage(message),
        args: this.sanitizeArgs(args),
      };

      // Add to main circular buffer (all levels)
      this.logs.push(logEntry);
      if (this.logs.length > MAX_MAIN_LOGS) {
        this.logs.shift();
      }

      // Also add error/warn entries to the dedicated error buffer
      // so they survive even when the main buffer is full of noise
      if (level === "error" || level === "warn") {
        this.errorLogs.push(logEntry);
        if (this.errorLogs.length > MAX_ERROR_LOGS) {
          this.errorLogs.shift();
        }
      }

      // Notify registered listeners (e.g. ClientLogForwarder for admin log forwarding)
      this.listeners.forEach((listener) => {
        try {
          listener(logEntry);
        } catch {
          // Never let a listener error break console logging
        }
      });
    } catch (error) {
      // Silently fail to avoid infinite loops
      this.originalConsole.error("LogCollector: Failed to capture log", error);
    }
  }

  /**
   * Sanitize log message to remove sensitive information
   */
  private sanitizeMessage(message: string): string {
    // Remove potential API keys, tokens, passwords, etc.
    return message
      .replace(/sk-api-[a-zA-Z0-9-]{32,}/g, "[API-KEY-REDACTED]")
      .replace(/bearer\s+[a-zA-Z0-9._-]{32,}/gi, "[TOKEN-REDACTED]")
      .replace(/password["\s]*[:=]["\s]*[^"\s\]},]+/gi, "password: [REDACTED]")
      .replace(/token["\s]*[:=]["\s]*[^"\s\]},]+/gi, "token: [REDACTED]")
      .replace(/key["\s]*[:=]["\s]*[^"\s\]},]+/gi, "key: [REDACTED]")
      .replace(/auth["\s]*[:=]["\s]*[^"\s\]},]+/gi, "auth: [REDACTED]")
      .slice(0, MAX_MESSAGE_LENGTH);
  }

  /**
   * Sanitize arguments to remove sensitive information
   */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private sanitizeArgs(args: any[]): any[] {
    return args.map((arg) => {
      if (typeof arg === "string") {
        return this.sanitizeMessage(arg);
      } else if (typeof arg === "object" && arg !== null) {
        try {
          const sanitized = { ...arg };
          // Remove common sensitive fields
          if (sanitized.password) sanitized.password = "[REDACTED]";
          if (sanitized.token) sanitized.token = "[REDACTED]";
          if (sanitized.apiKey) sanitized.apiKey = "[REDACTED]";
          if (sanitized.authorization) sanitized.authorization = "[REDACTED]";
          if (sanitized.bearer) sanitized.bearer = "[REDACTED]";
          return sanitized;
        } catch {
          return "[Object - could not sanitize]";
        }
      }
      return arg;
    });
  }

  /**
   * Get recent console logs, optionally filtered by level.
   *
   * @param count - Max entries to return (default: all)
   * @param level - Filter to a single level (e.g. "error"), or omit for all levels
   */
  public getLogs(count?: number, level?: LogLevel): ConsoleLogEntry[] {
    let source: ConsoleLogEntry[];

    if (level === "error" || level === "warn") {
      // For error/warn, use the dedicated error buffer for better retention
      source =
        level === "error"
          ? this.errorLogs.filter((e) => e.level === "error")
          : this.errorLogs.filter((e) => e.level === "warn");
    } else if (level) {
      // For other specific levels, filter the main buffer
      source = this.logs.filter((e) => e.level === level);
    } else {
      source = this.logs;
    }

    return count ? source.slice(-count) : [...source];
  }

  /**
   * Get only error and warn entries from the dedicated error buffer.
   * These entries survive even when the main buffer is full of routine noise.
   *
   * @param count - Max entries to return (default: all error/warn entries)
   */
  public getErrorLogs(count?: number): ConsoleLogEntry[] {
    return count ? this.errorLogs.slice(-count) : [...this.errorLogs];
  }

  /**
   * Format logs as text for inclusion in issue reports.
   * Includes both the main buffer tail and any error-buffer entries that
   * might have been evicted from the main buffer.
   */
  public getLogsAsText(count: number = 500): string {
    // Merge main buffer with error buffer (dedup by timestamp+message)
    const mainLogs = this.getLogs(count);
    const errorLogs = this.getErrorLogs();

    // Build a Set of keys from main logs for fast dedup lookup
    const mainKeys = new Set(
      mainLogs.map(
        (l) => `${l.timestamp}:${l.level}:${l.message.slice(0, 80)}`,
      ),
    );

    // Find error-buffer entries missing from the main buffer (evicted by noise)
    const rescuedErrors = errorLogs.filter(
      (e) =>
        !mainKeys.has(
          `${e.timestamp}:${e.level}:${e.message.slice(0, 80)}`,
        ),
    );

    // Merge and sort chronologically, then take the last `count` entries
    const merged = [...rescuedErrors, ...mainLogs]
      .sort((a, b) => a.timestamp - b.timestamp)
      .slice(-count);

    if (merged.length === 0) {
      return "No console logs available.";
    }

    const formatLog = (log: ConsoleLogEntry): string => {
      const date = new Date(log.timestamp);
      // Include milliseconds (.slice(0, 23)) to match action history format
      // and enable precise cross-correlation with backend logs.
      // Format: "2024-01-15 14:32:01.456"
      const timestamp = date.toISOString().replace("T", " ").slice(0, 23);
      const level = log.level.toUpperCase().padEnd(5);
      return `[${timestamp}] ${level} ${log.message}`;
    };

    return merged.map(formatLog).join("\n");
  }

  /**
   * Register a listener that is called for each new log entry.
   * Used by ClientLogForwarder to receive logs in real-time for server forwarding.
   */
  public onNewLog(listener: LogEntryListener): void {
    this.listeners.add(listener);
  }

  /**
   * Unregister a previously registered log entry listener.
   */
  public offNewLog(listener: LogEntryListener): void {
    this.listeners.delete(listener);
  }

  /**
   * Clear all captured logs (both main and error buffers)
   */
  public clearLogs(): void {
    this.logs = [];
    this.errorLogs = [];
  }

  /**
   * Restore original console methods and stop capturing
   */
  public destroy(): void {
    console.log = this.originalConsole.log;
    console.info = this.originalConsole.info;
    console.warn = this.originalConsole.warn;
    console.error = this.originalConsole.error;
    console.debug = this.originalConsole.debug;
    this.listeners.clear();
    this.clearLogs();
  }
}

// Create singleton instance
export const logCollector = new LogCollectorService();

// Export for manual control if needed
export { LogCollectorService };
