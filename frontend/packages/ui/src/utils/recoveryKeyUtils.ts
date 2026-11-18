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

import { text } from "../i18n/translations";
import { get } from "svelte/store";
import { copyToClipboard as clipboardCopy } from "./clipboardUtils";

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
  filename: string = "openmates_recovery_key.txt",
): SaveResult {
  if (!recoveryKey) {
    console.error("[recoveryKeyUtils] No recovery key to download");
    return { success: false, error: "No recovery key provided" };
  }

  try {
    const blob = new Blob([recoveryKey], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    console.log("[recoveryKeyUtils] Recovery key file downloaded");
    return { success: true };
  } catch (error) {
    console.error("[recoveryKeyUtils] Error downloading recovery key:", error);
    return {
      success: false,
      error: error instanceof Error ? error.message : "Download failed",
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
export async function copyRecoveryKeyToClipboard(
  recoveryKey: string,
): Promise<SaveResult> {
  if (!recoveryKey) {
    console.error("[recoveryKeyUtils] No recovery key to copy");
    return { success: false, error: "No recovery key provided" };
  }

  try {
    const result = await clipboardCopy(recoveryKey);
    if (result.success) {
      console.log("[recoveryKeyUtils] Recovery key copied to clipboard");
      return { success: true };
    }
    return { success: false, error: result.error || "Copy failed" };
  } catch (error) {
    console.error("[recoveryKeyUtils] Failed to copy to clipboard:", error);
    return {
      success: false,
      error: error instanceof Error ? error.message : "Copy failed",
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
    title: $text("signup.recovery_key_print_title"),
    warning: $text("signup.recovery_key_print_warning"),
    storageTitle: $text("signup.recovery_key_print_storage_title"),
    storage1: $text("signup.recovery_key_print_storage_1"),
    storage2: $text("signup.recovery_key_print_storage_2"),
    storage3: $text("signup.recovery_key_print_storage_3"),
    storage4: $text("signup.recovery_key_print_storage_4"),
  };
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
  translations?: PrintTranslations,
): SaveResult {
  if (!recoveryKey) {
    console.error("[recoveryKeyUtils] No recovery key to print");
    return { success: false, error: "No recovery key provided" };
  }

  try {
    // Get translations if not provided
    const trans = translations || getPrintTranslations();
    return printRecoveryKeyViaRust(recoveryKey, trans);
  } catch (error) {
    console.error("[recoveryKeyUtils] Error printing recovery key:", error);
    return {
      success: false,
      error: error instanceof Error ? error.message : "Print failed",
    };
  }
}

/**
 * The shared Rust core renders the print page. The window opens
 * synchronously (keeps the click's popup permission); the document is written
 * once Rust answers.
 */
function printRecoveryKeyViaRust(
  recoveryKey: string,
  trans: PrintTranslations,
): SaveResult {
  const printWindow = window.open("", "_blank");
  if (!printWindow) {
    console.error("[recoveryKeyUtils] Could not open print window (popup blocked?)");
    return { success: false, error: "Could not open print window" };
  }
  void import("../services/rustCore/authOperation")
    .then(({ rustAuthFlow }) =>
      rustAuthFlow<string>("recovery_print_html", { recoveryKey, translations: trans }),
    )
    .then((htmlContent) => {
      printWindow.document.write(htmlContent);
      printWindow.document.close();
      printWindow.print();
    })
    .catch((error: unknown) => {
      console.error("[recoveryKeyUtils] Rust print page failed:", error instanceof Error ? error.message : "unknown");
      printWindow.close();
    });
  return { success: true };
}
