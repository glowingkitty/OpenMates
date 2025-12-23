/**
 * Console Log Collector Service
 *
 * This service captures console messages for debugging purposes when users report issues.
 * It maintains a circular buffer of the last 100 console messages to be included in issue reports.
 */

export interface ConsoleLogEntry {
    timestamp: number;
    level: 'log' | 'info' | 'warn' | 'error' | 'debug';
    message: string;
    args: any[];
}

class LogCollectorService {
    private logs: ConsoleLogEntry[] = [];
    private maxLogs = 100;
    private originalConsole: {
        log: typeof console.log;
        info: typeof console.info;
        warn: typeof console.warn;
        error: typeof console.error;
        debug: typeof console.debug;
    };

    constructor() {
        // Store original console methods
        this.originalConsole = {
            log: console.log,
            info: console.info,
            warn: console.warn,
            error: console.error,
            debug: console.debug
        };

        this.interceptConsole();
    }

    /**
     * Intercept console methods to capture logs
     */
    private interceptConsole(): void {
        const interceptMethod = (level: 'log' | 'info' | 'warn' | 'error' | 'debug', originalMethod: Function) => {
            return (...args: any[]) => {
                // Call original method first
                originalMethod.apply(console, args);

                // Capture the log entry
                this.captureLog(level, args);
            };
        };

        console.log = interceptMethod('log', this.originalConsole.log);
        console.info = interceptMethod('info', this.originalConsole.info);
        console.warn = interceptMethod('warn', this.originalConsole.warn);
        console.error = interceptMethod('error', this.originalConsole.error);
        console.debug = interceptMethod('debug', this.originalConsole.debug);
    }

    /**
     * Capture a console log entry
     */
    private captureLog(level: 'log' | 'info' | 'warn' | 'error' | 'debug', args: any[]): void {
        try {
            // Convert arguments to strings safely
            const message = args.map(arg => {
                if (typeof arg === 'string') {
                    return arg;
                } else if (arg === null) {
                    return 'null';
                } else if (arg === undefined) {
                    return 'undefined';
                } else if (typeof arg === 'object') {
                    try {
                        return JSON.stringify(arg, null, 2);
                    } catch (e) {
                        return '[Object object - circular or non-serializable]';
                    }
                } else {
                    return String(arg);
                }
            }).join(' ');

            const logEntry: ConsoleLogEntry = {
                timestamp: Date.now(),
                level,
                message: this.sanitizeMessage(message),
                args: this.sanitizeArgs(args)
            };

            // Add to circular buffer
            this.logs.push(logEntry);

            // Keep only last maxLogs entries
            if (this.logs.length > this.maxLogs) {
                this.logs.shift();
            }
        } catch (error) {
            // Silently fail to avoid infinite loops
            this.originalConsole.error('LogCollector: Failed to capture log', error);
        }
    }

    /**
     * Sanitize log message to remove sensitive information
     */
    private sanitizeMessage(message: string): string {
        // Remove potential API keys, tokens, passwords, etc.
        return message
            .replace(/sk-api-[a-zA-Z0-9-]{32,}/g, '[API-KEY-REDACTED]')
            .replace(/bearer\s+[a-zA-Z0-9._-]{32,}/gi, '[TOKEN-REDACTED]')
            .replace(/password["\s]*[:=]["\s]*[^"\s\]},]+/gi, 'password: [REDACTED]')
            .replace(/token["\s]*[:=]["\s]*[^"\s\]},]+/gi, 'token: [REDACTED]')
            .replace(/key["\s]*[:=]["\s]*[^"\s\]},]+/gi, 'key: [REDACTED]')
            .replace(/auth["\s]*[:=]["\s]*[^"\s\]},]+/gi, 'auth: [REDACTED]')
            .slice(0, 1000); // Limit message length
    }

    /**
     * Sanitize arguments to remove sensitive information
     */
    private sanitizeArgs(args: any[]): any[] {
        return args.map(arg => {
            if (typeof arg === 'string') {
                return this.sanitizeMessage(arg);
            } else if (typeof arg === 'object' && arg !== null) {
                try {
                    const sanitized = { ...arg };
                    // Remove common sensitive fields
                    if (sanitized.password) sanitized.password = '[REDACTED]';
                    if (sanitized.token) sanitized.token = '[REDACTED]';
                    if (sanitized.apiKey) sanitized.apiKey = '[REDACTED]';
                    if (sanitized.authorization) sanitized.authorization = '[REDACTED]';
                    if (sanitized.bearer) sanitized.bearer = '[REDACTED]';
                    return sanitized;
                } catch (e) {
                    return '[Object - could not sanitize]';
                }
            }
            return arg;
        });
    }

    /**
     * Get recent console logs
     */
    public getLogs(count?: number): ConsoleLogEntry[] {
        const logsToReturn = count ? this.logs.slice(-count) : [...this.logs];
        return logsToReturn;
    }

    /**
     * Format logs as text for inclusion in issue reports
     */
    public getLogsAsText(count: number = 100): string {
        const logs = this.getLogs(count);
        if (logs.length === 0) {
            return 'No console logs available.';
        }

        const formatLog = (log: ConsoleLogEntry): string => {
            const date = new Date(log.timestamp);
            const timestamp = date.toISOString().replace('T', ' ').slice(0, 19);
            const level = log.level.toUpperCase().padEnd(5);
            return `[${timestamp}] ${level} ${log.message}`;
        };

        return logs.map(formatLog).join('\n');
    }

    /**
     * Clear all captured logs
     */
    public clearLogs(): void {
        this.logs = [];
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
        this.clearLogs();
    }
}

// Create singleton instance
export const logCollector = new LogCollectorService();

// Export for manual control if needed
export { LogCollectorService };