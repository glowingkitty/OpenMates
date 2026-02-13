/**
 * Recovery Key Utilities
 * ======================
 * Shared utility functions for recovery key save operations.
 * Used by both signup flow (RecoveryKeyTopContent) and settings flow (SettingsRecoveryKey).
 * 
 * This module provides:
 * - Download recovery key as file
 * - Copy recovery key to clipboard
 * - Print recovery key with formatted page
 */

import { text } from '../i18n/translations';
import { get } from 'svelte/store';

// ========================================================================
// TYPES
// ========================================================================

/** Result of a save operation */
export interface SaveResult {
    success: boolean;
    error?: string;
}

/** Translations for the print page */
export interface PrintTranslations {
    title: string;
    warning: string;
    storageTitle: string;
    storage1: string;
    storage2: string;
    storage3: string;
    storage4: string;
}

// ========================================================================
// DOWNLOAD
// ========================================================================

/**
 * Download the recovery key as a text file.
 * @param recoveryKey - The recovery key string to download
 * @param filename - Optional filename (defaults to 'openmates_recovery_key.txt')
 * @returns SaveResult indicating success or failure
 */
export function downloadRecoveryKey(
    recoveryKey: string,
    filename: string = 'openmates_recovery_key.txt'
): SaveResult {
    if (!recoveryKey) {
        console.error('[recoveryKeyUtils] No recovery key to download');
        return { success: false, error: 'No recovery key provided' };
    }

    try {
        const blob = new Blob([recoveryKey], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        console.log('[recoveryKeyUtils] Recovery key file downloaded');
        return { success: true };
    } catch (error) {
        console.error('[recoveryKeyUtils] Error downloading recovery key:', error);
        return { 
            success: false, 
            error: error instanceof Error ? error.message : 'Download failed' 
        };
    }
}

// ========================================================================
// COPY TO CLIPBOARD
// ========================================================================

/**
 * Copy the recovery key to clipboard.
 * @param recoveryKey - The recovery key string to copy
 * @returns Promise<SaveResult> indicating success or failure
 */
export async function copyRecoveryKeyToClipboard(recoveryKey: string): Promise<SaveResult> {
    if (!recoveryKey) {
        console.error('[recoveryKeyUtils] No recovery key to copy');
        return { success: false, error: 'No recovery key provided' };
    }

    try {
        await navigator.clipboard.writeText(recoveryKey);
        console.log('[recoveryKeyUtils] Recovery key copied to clipboard');
        return { success: true };
    } catch (error) {
        console.error('[recoveryKeyUtils] Failed to copy to clipboard:', error);
        return { 
            success: false, 
            error: error instanceof Error ? error.message : 'Copy failed' 
        };
    }
}

// ========================================================================
// PRINT
// ========================================================================

/**
 * Get translations for the print page.
 * Uses the $text store to get translated strings.
 * @returns PrintTranslations object with all needed strings
 */
export function getPrintTranslations(): PrintTranslations {
    // Access the text store using get() since we're outside a component
    const $text = get(text);
    
    return {
        title: $text('signup.recovery_key_print_title'),
        warning: $text('signup.recovery_key_print_warning'),
        storageTitle: $text('signup.recovery_key_print_storage_title'),
        storage1: $text('signup.recovery_key_print_storage_1'),
        storage2: $text('signup.recovery_key_print_storage_2'),
        storage3: $text('signup.recovery_key_print_storage_3'),
        storage4: $text('signup.recovery_key_print_storage_4')
    };
}

/**
 * Generate the HTML content for the print page.
 * @param recoveryKey - The recovery key to display
 * @param translations - Translated strings for the page content
 * @returns HTML string for the print page
 */
export function generatePrintPageHtml(
    recoveryKey: string,
    translations: PrintTranslations
): string {
    return `
        <!DOCTYPE html>
        <html>
        <head>
            <title>${translations.title}</title>
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                    padding: 40px;
                    max-width: 600px;
                    margin: 0 auto;
                }
                h1 {
                    color: #333;
                    font-size: 24px;
                    margin-bottom: 20px;
                }
                .warning {
                    background: #fff3cd;
                    border: 1px solid #ffc107;
                    border-radius: 8px;
                    padding: 16px;
                    margin-bottom: 24px;
                }
                .warning p {
                    margin: 0;
                    color: #856404;
                }
                .key-container {
                    background: #f5f5f5;
                    border: 2px dashed #ccc;
                    border-radius: 8px;
                    padding: 20px;
                    text-align: center;
                }
                .recovery-key {
                    font-family: 'Courier New', monospace;
                    font-size: 18px;
                    font-weight: bold;
                    letter-spacing: 2px;
                    word-break: break-all;
                    color: #333;
                }
                .instructions {
                    margin-top: 24px;
                    color: #666;
                    font-size: 14px;
                }
                .instructions li {
                    margin-bottom: 8px;
                }
            </style>
        </head>
        <body>
            <h1>🔐 ${translations.title}</h1>
            <div class="warning">
                <p><strong>⚠️ ${translations.warning}</strong></p>
            </div>
            <div class="key-container">
                <div class="recovery-key">${recoveryKey}</div>
            </div>
            <div class="instructions">
                <p><strong>${translations.storageTitle}</strong></p>
                <ul>
                    <li>${translations.storage1}</li>
                    <li>${translations.storage2}</li>
                    <li>${translations.storage3}</li>
                    <li>${translations.storage4}</li>
                </ul>
            </div>
        </body>
        </html>
    `;
}

/**
 * Open print dialog with the recovery key.
 * Creates a new window with formatted print page and triggers print.
 * @param recoveryKey - The recovery key to print
 * @param translations - Optional translations (will be fetched if not provided)
 * @returns SaveResult indicating success or failure
 */
export function printRecoveryKey(
    recoveryKey: string,
    translations?: PrintTranslations
): SaveResult {
    if (!recoveryKey) {
        console.error('[recoveryKeyUtils] No recovery key to print');
        return { success: false, error: 'No recovery key provided' };
    }

    try {
        // Get translations if not provided
        const trans = translations || getPrintTranslations();
        
        // Generate the print page HTML
        const htmlContent = generatePrintPageHtml(recoveryKey, trans);

        // Open print window
        const printWindow = window.open('', '_blank');
        if (!printWindow) {
            console.error('[recoveryKeyUtils] Could not open print window (popup blocked?)');
            return { success: false, error: 'Could not open print window' };
        }

        printWindow.document.write(htmlContent);
        printWindow.document.close();
        printWindow.print();

        console.log('[recoveryKeyUtils] Recovery key print dialog opened');
        return { success: true };
    } catch (error) {
        console.error('[recoveryKeyUtils] Error printing recovery key:', error);
        return { 
            success: false, 
            error: error instanceof Error ? error.message : 'Print failed' 
        };
    }
}

