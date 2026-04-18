/**
 * Account Export Service
 *
 * GDPR Article 20 - Right to Data Portability
 *
 * Handles complete export of all user data:
 * - All chats with messages, including all file embeds (images, audio, PDFs, code, transcripts)
 * - Usage history (YAML + CSV)
 * - Invoice PDFs
 * - App memories (decrypted)
 * - User profile data (decrypted email)
 * - Profile image
 *
 * Processing happens entirely client-side:
 * 1. Fetch manifest (list of all data IDs)
 * 2. Sync missing chats to IndexedDB
 * 3. Load all data from IndexedDB
 * 4. Decrypt encrypted data (email, settings/memories)
 * 5. Download profile image blob
 * 6. Convert to YML/CSV format
 * 7. Create ZIP archive with JSZip
 * 8. Download to client
 *
 * See docs/architecture/sync.md for the encryption model.
 */

import JSZip from "jszip";
import { getApiEndpoint, getApiUrl, apiEndpoints } from "../config/api";
import { chatDB } from "./db";
import { convertChatToYaml, generateChatFilename } from "./chatExportService";
import { tipTapToCanonicalMarkdown } from "../message_parsing/serializers";
import { decryptWithMasterKey } from "./cryptoService";
import {
  getCodeEmbedsForChat,
  getImageEmbedsForChat,
  getAudioRecordingsForChat,
  getPDFEmbedsForChat,
  getVideoTranscriptEmbedsForChat,
} from "./zipExportService";
import { userProfile, updateProfile } from "../stores/userProfile";
import { get } from "svelte/store";
import type { Chat, Message } from "../types/chat";

// ============================================================================
// TYPES
// ============================================================================

/**
 * Selective export options — each key controls whether that category is
 * included. All default to true (full export).
 */
export interface ExportOptions {
  includeChats: boolean;
  includeChatFiles: boolean; // images, audio, PDFs, code, transcripts attached to chats
  includeInvoices: boolean;
  includeUsage: boolean;
  includeSettings: boolean; // app memories (decrypted)
  includeProfile: boolean; // user profile + profile image
}

/** Default: everything selected */
export const DEFAULT_EXPORT_OPTIONS: ExportOptions = {
  includeChats: true,
  includeChatFiles: true,
  includeInvoices: true,
  includeUsage: true,
  includeSettings: true,
  includeProfile: true,
};

/**
 * Progress callback for export updates
 */
export interface ExportProgress {
  phase:
    | "init"
    | "manifest"
    | "syncing"
    | "loading"
    | "decrypting"
    | "creating_zip"
    | "downloading_pdfs"
    | "downloading_files"
    | "downloading_profile_image"
    | "complete"
    | "error";
  progress: number; // 0-100
  message: string;
  currentItem?: string;
  error?: string;
}

export type ExportProgressCallback = (progress: ExportProgress) => void;

/**
 * Export manifest from server
 */
interface ExportManifest {
  all_chat_ids: string[];
  total_chats: number;
  total_invoices: number;
  total_usage_entries: number;
  has_app_settings: boolean;
  has_memories: boolean;
  has_usage_data: boolean;
  has_invoices: boolean;
  estimated_size_mb: number;
}

/**
 * Usage entry from server (already decrypted)
 */
interface UsageEntry {
  usage_id: string;
  timestamp: number;
  app_id: string;
  skill_id: string;
  usage_type: string;
  source: string;
  credits_charged: number;
  model_used?: string;
  chat_id?: string;
  message_id?: string;
  cost_system_prompt_credits?: number;
  cost_history_credits?: number;
  cost_response_credits?: number;
  actual_input_tokens?: number;
  actual_output_tokens?: number;
}

/**
 * Invoice from server (with encrypted S3 info for PDF download)
 */
interface InvoiceExport {
  invoice_id: string;
  order_id: string;
  date: string;
  amount_cents: number;
  currency: string;
  credits_purchased: number;
  is_gift_card: boolean;
  refunded_at?: string;
  refund_status: string;
  encrypted_s3_object_key?: string;
  encrypted_aes_key?: string;
  aes_nonce?: string;
  encrypted_filename?: string;
}

/**
 * User profile from server export endpoint
 */
interface UserProfileExport {
  user_id: string;
  username: string;
  encrypted_email_with_master_key?: string;
  email_verified: boolean;
  account_status?: string;
  last_access?: string;
  language: string;
  darkmode: boolean;
  currency: string;
  credits: number;
  tfa_enabled: boolean;
  has_passkey: boolean;
  passkey_count?: number;
  auto_topup_enabled: boolean;
  auto_topup_threshold?: number;
  auto_topup_amount?: number;
}

/**
 * Compliance log entry from server
 */
interface ComplianceLogEntry {
  timestamp: string;
  event_type: string;
  user_id: string;
  consent_type?: string;
  action?: string;
  version?: string;
  status?: string;
  details?: Record<string, unknown>;
}

/**
 * Raw encrypted app settings/memories entry from server
 */
interface AppSettingMemoryEntry {
  id: string;
  app_id: string;
  item_key: string;
  item_type?: string;
  encrypted_item_json: string;
  encrypted_app_key: string;
  created_at: number;
  updated_at: number;
  item_version: number;
}

/**
 * Decrypted app settings/memories entry
 */
interface DecryptedAppSetting {
  app_id: string;
  item_key: string;
  item_type: string;
  value: Record<string, unknown> | string;
  created_at: number;
  updated_at: number;
}

/**
 * Extended user profile with decrypted email
 */
interface DecryptedUserProfile extends UserProfileExport {
  email?: string;
}

/**
 * Export data from server
 */
interface ExportData {
  usage_records: UsageEntry[];
  invoices: InvoiceExport[];
  invoice_ids_for_pdf_download: string[];
  user_profile: UserProfileExport | null;
  app_settings_memories: AppSettingMemoryEntry[];
  compliance_logs: ComplianceLogEntry[];
  usage_error?: string;
  invoice_error?: string;
}

// ============================================================================
// MAIN EXPORT FUNCTION
// ============================================================================

/**
 * Export selected user data as a ZIP file
 *
 * @param onProgress - Callback for progress updates
 * @param options    - Which data categories to include (default: all)
 * @returns Promise that resolves when download completes
 */
export async function exportAllUserData(
  onProgress: ExportProgressCallback,
  options: ExportOptions = DEFAULT_EXPORT_OPTIONS,
): Promise<void> {
  console.warn("[AccountExport] Starting account data export", options);

  try {
    // Phase 1: Initialize
    onProgress({
      phase: "init",
      progress: 0,
      message: "Initializing export...",
    });

    // Phase 2: Fetch manifest
    onProgress({
      phase: "manifest",
      progress: 5,
      message: "Fetching data manifest...",
    });
    const manifest = await fetchExportManifest();
    console.warn(
      `[AccountExport] Manifest: ${manifest.total_chats} chats, ` +
        `${manifest.total_invoices} invoices`,
    );

    // Phase 3: Sync & load chats
    let chats: Chat[] = [];
    let messagesMap = new Map<string, Message[]>();
    if (options.includeChats) {
      onProgress({
        phase: "syncing",
        progress: 10,
        message: `Preparing ${manifest.total_chats} chats...`,
      });
      await syncMissingChats(manifest.all_chat_ids, onProgress);

      onProgress({
        phase: "loading",
        progress: 40,
        message: "Loading chat data...",
      });
      ({ chats, messagesMap } = await loadAllChatsAndMessages(
        manifest.all_chat_ids,
        onProgress,
      ));
    }

    // Phase 4: Fetch server data (usage, invoices, profile, settings)
    onProgress({
      phase: "loading",
      progress: 50,
      message: "Fetching account data...",
    });
    const exportData = await fetchExportData(options);

    // Phase 5: Decrypt data
    onProgress({
      phase: "decrypting",
      progress: 60,
      message: "Decrypting data...",
    });
    const decryptedProfile = options.includeProfile
      ? await decryptUserProfile(exportData.user_profile)
      : null;
    const decryptedSettings = options.includeSettings
      ? await decryptAppSettings(exportData.app_settings_memories)
      : [];

    // Phase 6: Download profile image
    let profileImageBlob: Blob | null = null;
    if (options.includeProfile) {
      onProgress({
        phase: "downloading_profile_image",
        progress: 62,
        message: "Downloading profile image...",
      });
      profileImageBlob = await downloadProfileImage();
    }

    // Phase 7: Download invoice PDFs
    let invoicePDFs = new Map<
      string,
      { data: ArrayBuffer; filename: string }
    >();
    if (options.includeInvoices) {
      onProgress({
        phase: "downloading_pdfs",
        progress: 65,
        message: `Downloading ${exportData.invoices.length} invoice PDFs...`,
      });
      invoicePDFs = await downloadInvoicePDFs(
        exportData.invoice_ids_for_pdf_download,
        onProgress,
      );
    }

    // Phase 8: Create ZIP archive
    onProgress({
      phase: "creating_zip",
      progress: 75,
      message: "Creating ZIP archive...",
    });
    const zipBlob = await createExportZip(
      {
        chats,
        messagesMap,
        usageRecords: exportData.usage_records,
        invoices: exportData.invoices,
        invoicePDFs,
        userProfile: decryptedProfile,
        profileImageBlob,
        appSettings: decryptedSettings,
        complianceLogs: exportData.compliance_logs || [],
        manifest,
        options,
      },
      onProgress,
    );

    // Phase 9: Download ZIP
    onProgress({
      phase: "complete",
      progress: 100,
      message: "Export complete! Downloading...",
    });
    await downloadZip(zipBlob);

    // Update local store so SettingsBackupReminders shows the current timestamp
    // immediately without requiring a full profile reload. The server already persisted
    // last_export_at when the manifest was fetched (see backend/core/api/app/routes/settings.py).
    updateProfile({ last_export_at: new Date().toISOString() });

    console.warn("[AccountExport] Export completed successfully");
  } catch (error) {
    console.error("[AccountExport] Export failed:", error);
    onProgress({
      phase: "error",
      progress: 0,
      message: "Export failed",
      error: error instanceof Error ? error.message : "Unknown error",
    });
    throw error;
  }
}

// ============================================================================
// DATA FETCHING
// ============================================================================

async function fetchExportManifest(): Promise<ExportManifest> {
  const response = await fetch(
    getApiEndpoint(apiEndpoints.settings.exportAccountManifest),
    {
      method: "GET",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
    },
  );
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(
      (err as { detail?: string }).detail || "Failed to fetch export manifest",
    );
  }
  const data = await response.json();
  if (!data.success) throw new Error("Export manifest request failed");
  return data.manifest as ExportManifest;
}

async function fetchExportData(options: ExportOptions): Promise<ExportData> {
  const params = new URLSearchParams({
    include_usage: String(options.includeUsage),
    include_invoices: String(options.includeInvoices),
    include_settings: String(options.includeSettings),
    include_profile: String(options.includeProfile),
  });
  const response = await fetch(
    `${getApiEndpoint(apiEndpoints.settings.exportAccountData)}?${params}`,
    {
      method: "GET",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
    },
  );
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(
      (err as { detail?: string }).detail || "Failed to fetch export data",
    );
  }
  const data = await response.json();
  if (!data.success) throw new Error("Export data request failed");
  return data.data as ExportData;
}

// ============================================================================
// CHAT SYNC & LOADING
// ============================================================================

async function syncMissingChats(
  allChatIds: string[],
  onProgress: ExportProgressCallback,
): Promise<void> {
  const localChats = await chatDB.getAllChats();
  const localChatIds = new Set(localChats.map((c) => c.chat_id));
  const missingCount = allChatIds.filter((id) => !localChatIds.has(id)).length;

  if (missingCount === 0) return;

  console.warn(`[AccountExport] Syncing ${missingCount} missing chats`);
  onProgress({
    phase: "syncing",
    progress: 20,
    message: `Syncing ${missingCount} missing chats...`,
  });
  // Allow the normal WebSocket sync mechanism a moment to process
  await new Promise((resolve) => setTimeout(resolve, 1000));
}

async function loadAllChatsAndMessages(
  chatIds: string[],
  onProgress: ExportProgressCallback,
): Promise<{ chats: Chat[]; messagesMap: Map<string, Message[]> }> {
  const allLocalChats = await chatDB.getAllChats();
  const chatMap = new Map(allLocalChats.map((c) => [c.chat_id, c]));

  const chats: Chat[] = [];
  const messagesMap = new Map<string, Message[]>();
  let processed = 0;

  for (const chatId of chatIds) {
    const chat = chatMap.get(chatId);
    if (chat) {
      chats.push(chat);
      try {
        const messages = await chatDB.getMessagesForChat(chatId);
        messagesMap.set(chatId, messages);
      } catch (err) {
        console.warn(
          `[AccountExport] Failed to load messages for chat ${chatId}:`,
          err,
        );
        messagesMap.set(chatId, []);
      }
    }
    processed++;
    if (processed % 50 === 0) {
      onProgress({
        phase: "loading",
        progress: 40 + Math.round((processed / chatIds.length) * 10),
        message: `Loading chats... ${processed}/${chatIds.length}`,
      });
    }
  }

  return { chats, messagesMap };
}

// ============================================================================
// DECRYPTION
// ============================================================================

async function decryptUserProfile(
  profile: UserProfileExport | null,
): Promise<DecryptedUserProfile | null> {
  if (!profile) return null;
  const result: DecryptedUserProfile = { ...profile };
  if (profile.encrypted_email_with_master_key) {
    try {
      result.email = await decryptWithMasterKey(
        profile.encrypted_email_with_master_key,
      );
    } catch (e) {
      console.warn("[AccountExport] Failed to decrypt email:", e);
    }
  }
  return result;
}

/**
 * Decrypt app settings/memories entries.
 * Uses the same decryptWithMasterKey approach as appSettingsMemoriesStore.
 * The original item_key is stored inside the encrypted JSON as _original_item_key.
 */
async function decryptAppSettings(
  entries: AppSettingMemoryEntry[],
): Promise<DecryptedAppSetting[]> {
  const decrypted: DecryptedAppSetting[] = [];

  for (const entry of entries) {
    try {
      let itemValue: Record<string, unknown> = {};
      let originalItemKey = entry.item_key;

      try {
        const decryptedJson = await decryptWithMasterKey(
          entry.encrypted_item_json,
        );
        if (decryptedJson) {
          itemValue = JSON.parse(decryptedJson) as Record<string, unknown>;
          // Original key is stored inside encrypted JSON for privacy
          if (typeof itemValue._original_item_key === "string") {
            originalItemKey = itemValue._original_item_key;
          }
        }
      } catch (decryptErr) {
        console.warn(
          `[AccountExport] Could not decrypt entry ${entry.id}, including metadata only:`,
          decryptErr,
        );
        itemValue = { _encrypted: true };
      }

      decrypted.push({
        app_id: entry.app_id,
        item_key: originalItemKey,
        item_type: entry.item_type || "",
        value: itemValue,
        created_at: entry.created_at,
        updated_at: entry.updated_at,
      });
    } catch (err) {
      console.error(
        `[AccountExport] Error processing settings entry ${entry.id}:`,
        err,
      );
    }
  }

  return decrypted;
}

// ============================================================================
// PROFILE IMAGE
// ============================================================================

/**
 * Download the user's profile image as a Blob using the authenticated proxy endpoint.
 * Returns null if no profile image is set or on any fetch error.
 */
async function downloadProfileImage(): Promise<Blob | null> {
  const profile = get(userProfile);
  if (!profile?.profile_image_url) return null;

  const url = profile.profile_image_url;

  // Legacy public URL — fetch directly without auth
  if (url.startsWith("http://") || url.startsWith("https://")) {
    try {
      const response = await fetch(url);
      if (!response.ok) return null;
      return await response.blob();
    } catch (e) {
      console.warn(
        "[AccountExport] Failed to download legacy profile image:",
        e,
      );
      return null;
    }
  }

  // Authenticated proxy path (e.g. /v1/users/{userId}/profile-image)
  try {
    const fullUrl = url.startsWith("/") ? `${getApiUrl()}${url}` : url;
    const response = await fetch(fullUrl, { credentials: "include" });
    if (!response.ok) {
      console.warn(
        `[AccountExport] Profile image fetch failed: HTTP ${response.status}`,
      );
      return null;
    }
    return await response.blob();
  } catch (e) {
    console.warn("[AccountExport] Error downloading profile image:", e);
    return null;
  }
}

// ============================================================================
// INVOICE PDF DOWNLOAD
// ============================================================================

async function downloadInvoicePDFs(
  invoiceIds: string[],
  onProgress: ExportProgressCallback,
): Promise<Map<string, { data: ArrayBuffer; filename: string }>> {
  const pdfs = new Map<string, { data: ArrayBuffer; filename: string }>();
  if (invoiceIds.length === 0) return pdfs;

  const BATCH_SIZE = 5;
  let downloaded = 0;

  for (let i = 0; i < invoiceIds.length; i += BATCH_SIZE) {
    const batch = invoiceIds.slice(i, i + BATCH_SIZE);
    const results = await Promise.allSettled(
      batch.map(async (invoiceId) => {
        const response = await fetch(
          getApiEndpoint(
            apiEndpoints.payments.downloadInvoice.replace("{id}", invoiceId),
          ),
          { method: "GET", credentials: "include" },
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const disposition = response.headers.get("Content-Disposition");
        let filename = `Invoice_${invoiceId}.pdf`;
        if (disposition) {
          const match = disposition.match(
            /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/,
          );
          if (match?.[1]) filename = match[1].replace(/['"]/g, "");
        }
        const data = await response.arrayBuffer();
        return { invoiceId, data, filename };
      }),
    );

    for (const result of results) {
      if (result.status === "fulfilled" && result.value) {
        pdfs.set(result.value.invoiceId, {
          data: result.value.data,
          filename: result.value.filename,
        });
      }
    }
    downloaded += batch.length;
    onProgress({
      phase: "downloading_pdfs",
      progress: 65 + Math.round((downloaded / invoiceIds.length) * 8),
      message: `Downloading invoices... ${downloaded}/${invoiceIds.length}`,
    });
  }

  return pdfs;
}

// ============================================================================
// ZIP CREATION
// ============================================================================

interface ZipCreationData {
  chats: Chat[];
  messagesMap: Map<string, Message[]>;
  usageRecords: UsageEntry[];
  invoices: InvoiceExport[];
  invoicePDFs: Map<string, { data: ArrayBuffer; filename: string }>;
  userProfile: DecryptedUserProfile | null;
  profileImageBlob: Blob | null;
  appSettings: DecryptedAppSetting[];
  complianceLogs: ComplianceLogEntry[];
  manifest: ExportManifest;
  options: ExportOptions;
}

async function createExportZip(
  data: ZipCreationData,
  onProgress: ExportProgressCallback,
): Promise<Blob> {
  const zip = new JSZip();
  const profileStore = get(userProfile);
  const username = profileStore?.username || "user";

  // README
  zip.file("README.md", generateReadme(data));

  // metadata.yml
  zip.file("metadata.yml", generateMetadataYml(data, username));

  // ── Profile ────────────────────────────────────────────────────────────
  if (data.options.includeProfile) {
    const profileFolder = zip.folder("profile");
    if (profileFolder) {
      if (data.userProfile) {
        profileFolder.file("profile.yml", generateProfileYml(data.userProfile));
      }
      if (data.profileImageBlob) {
        const ext = data.profileImageBlob.type?.includes("jpeg")
          ? "jpg"
          : "png";
        profileFolder.file(`profile_image.${ext}`, data.profileImageBlob);
      }
    }
  }

  // ── Chats ──────────────────────────────────────────────────────────────
  if (data.options.includeChats && data.chats.length > 0) {
    const chatsFolder = zip.folder("chats");
    if (chatsFolder) {
      let processed = 0;
      for (const chat of data.chats) {
        try {
          const messages = data.messagesMap.get(chat.chat_id) || [];
          const folderName = (await generateChatFilename(chat, "")).replace(
            /\.[^.]+$/,
            "",
          );
          const chatFolder = chatsFolder.folder(folderName);

          if (chatFolder) {
            // YML + Markdown of the conversation
            const yamlContent = await convertChatToYaml(chat, messages, false);
            chatFolder.file(`${folderName}.yml`, yamlContent);

            const markdownContent = convertChatToMarkdown(chat, messages);
            chatFolder.file(`${folderName}.md`, markdownContent);

            if (data.options.includeChatFiles) {
              // Code embeds
              try {
                const codeEmbeds = await getCodeEmbedsForChat(messages);
                for (const embed of codeEmbeds) {
                  const filePath = embed.file_path
                    ? embed.file_path
                    : embed.filename
                      ? `code/${embed.filename}`
                      : `code/${embed.embed_id}.${getFileExt(embed.language)}`;
                  chatFolder.file(filePath, embed.content);
                }
              } catch (e) {
                console.warn(
                  "[AccountExport] Code embeds error in chat",
                  chat.chat_id,
                  e,
                );
              }

              // Video transcripts
              try {
                const transcripts =
                  await getVideoTranscriptEmbedsForChat(messages);
                for (const t of transcripts) {
                  chatFolder.file(`transcripts/${t.filename}`, t.content);
                }
              } catch (e) {
                console.warn(
                  "[AccountExport] Transcript embeds error in chat",
                  chat.chat_id,
                  e,
                );
              }

              // AI-generated & uploaded images
              try {
                const images = await getImageEmbedsForChat(messages);
                for (const img of images) {
                  chatFolder.file(`images/${img.filename}`, img.blob);
                }
              } catch (e) {
                console.warn(
                  "[AccountExport] Image embeds error in chat",
                  chat.chat_id,
                  e,
                );
              }

              // Audio recordings
              try {
                const recordings = await getAudioRecordingsForChat(messages);
                for (const rec of recordings) {
                  chatFolder.file(`uploads/audio/${rec.filename}`, rec.blob);
                  const txFilename =
                    rec.filename.replace(/\.[^.]+$/, "") + "_transcript.txt";
                  chatFolder.file(
                    `uploads/audio/${txFilename}`,
                    rec.transcript,
                  );
                }
              } catch (e) {
                console.warn(
                  "[AccountExport] Audio embeds error in chat",
                  chat.chat_id,
                  e,
                );
              }

              // PDF page screenshots
              try {
                const pdfEmbeds = await getPDFEmbedsForChat(messages);
                for (const pdf of pdfEmbeds) {
                  for (const page of pdf.pages) {
                    chatFolder.file(
                      `uploads/pdfs/${pdf.folderName}/${page.filename}`,
                      page.blob,
                    );
                  }
                }
              } catch (e) {
                console.warn(
                  "[AccountExport] PDF embeds error in chat",
                  chat.chat_id,
                  e,
                );
              }
            }
          }

          processed++;
          if (processed % 10 === 0) {
            onProgress({
              phase: "creating_zip",
              progress: 75 + Math.round((processed / data.chats.length) * 15),
              message: `Adding chats... ${processed}/${data.chats.length}`,
              currentItem: chat.title || chat.chat_id,
            });
          }
        } catch (err) {
          console.warn(
            `[AccountExport] Error processing chat ${chat.chat_id}:`,
            err,
          );
        }
      }
    }
  }

  // ── Usage ──────────────────────────────────────────────────────────────
  if (data.options.includeUsage && data.usageRecords.length > 0) {
    const usageFolder = zip.folder("usage");
    if (usageFolder) {
      usageFolder.file(
        "usage_history.yml",
        generateUsageYml(data.usageRecords),
      );
      usageFolder.file(
        "usage_history.csv",
        generateUsageCsv(data.usageRecords),
      );
    }
  }

  // ── Payments ───────────────────────────────────────────────────────────
  if (data.options.includeInvoices) {
    const paymentsFolder = zip.folder("payments");
    if (paymentsFolder) {
      if (data.invoices.length > 0) {
        paymentsFolder.file("invoices.yml", generateInvoicesYml(data.invoices));
      }
      const pdfsFolder = paymentsFolder.folder("invoice_pdfs");
      if (pdfsFolder) {
        for (const pdf of Array.from(data.invoicePDFs.values())) {
          pdfsFolder.file(pdf.filename, pdf.data);
        }
      }
    }
  }

  // ── Memories ────────────────────────────────────────────────
  if (data.options.includeSettings && data.appSettings.length > 0) {
    const settingsFolder = zip.folder("settings");
    if (settingsFolder) {
      settingsFolder.file(
        "app_settings_and_memories.yml",
        generateAppSettingsYml(data.appSettings),
      );
    }
  }

  // ── Compliance logs ────────────────────────────────────────────────────
  if (data.complianceLogs.length > 0) {
    zip.file(
      "compliance_logs.yml",
      generateComplianceLogsYml(data.complianceLogs),
    );
  }

  const zipBlob = await zip.generateAsync({
    type: "blob",
    compression: "DEFLATE",
    compressionOptions: { level: 6 },
  });

  console.warn(
    `[AccountExport] ZIP created: ${(zipBlob.size / 1024 / 1024).toFixed(2)} MB`,
  );
  return zipBlob;
}

// ============================================================================
// YAML / CSV GENERATION HELPERS
// ============================================================================

function generateReadme(data: ZipCreationData): string {
  const lines: string[] = [
    "# OpenMates Data Export",
    "",
    `Export generated: ${new Date().toISOString()}`,
    "",
    "## Contents",
    "",
  ];

  if (data.options.includeProfile) {
    lines.push("- `profile/profile.yml` — Account profile and settings");
    if (data.profileImageBlob) {
      lines.push("- `profile/profile_image.*` — Profile picture");
    }
  }
  if (data.options.includeChats) {
    lines.push(`- \`chats/\` — All conversations (${data.chats.length} chats)`);
    if (data.options.includeChatFiles) {
      lines.push(
        "  - Each chat folder includes: conversation.yml, conversation.md,",
      );
      lines.push(
        "    images/, uploads/audio/, uploads/pdfs/, code/, transcripts/",
      );
    }
  }
  if (data.options.includeUsage) {
    lines.push(
      `- \`usage/usage_history.yml\` and \`usage_history.csv\` — ` +
        `Usage records (${data.usageRecords.length} entries)`,
    );
  }
  if (data.options.includeInvoices) {
    lines.push(
      `- \`payments/\` — Invoice history and PDFs (${data.invoices.length} invoices)`,
    );
  }
  if (data.options.includeSettings) {
    lines.push(
      "- `settings/app_settings_and_memories.yml` — Decrypted app settings & AI memories",
    );
  }
  lines.push("- `compliance_logs.yml` — Consent history (GDPR)");
  lines.push("- `metadata.yml` — Export metadata");
  lines.push("");
  lines.push("## GDPR Compliance");
  lines.push("");
  lines.push(
    "This export satisfies GDPR Article 20 (Right to Data Portability). " +
      "Data is in structured, machine-readable formats (YAML, CSV, PNG, PDF).",
  );
  lines.push("");
  lines.push("## Questions?");
  lines.push("");
  lines.push("Contact support@openmates.org");

  return lines.join("\n");
}

function generateMetadataYml(data: ZipCreationData, username: string): string {
  return `# OpenMates Export Metadata
export_version: "2.0"
export_timestamp: "${new Date().toISOString()}"
username: "${escapeYml(username)}"

included_categories:
  chats: ${data.options.includeChats}
  chat_files: ${data.options.includeChatFiles}
  usage: ${data.options.includeUsage}
  invoices: ${data.options.includeInvoices}
  settings: ${data.options.includeSettings}
  profile: ${data.options.includeProfile}

statistics:
  total_chats: ${data.chats.length}
  total_invoices: ${data.invoices.length}
  total_usage_records: ${data.usageRecords.length}
  total_app_settings: ${data.appSettings.length}

gdpr_compliance:
  article_20_satisfied: true
  data_categories_included:
    - provided_data
    - observed_data
    - derived_data
`;
}

function generateProfileYml(profile: DecryptedUserProfile): string {
  const email = profile.email ?? "[Encrypted — master key unavailable]";
  let autoTopupSection = `auto_topup:\n  enabled: false`;
  if (profile.auto_topup_enabled) {
    autoTopupSection =
      `auto_topup:\n  enabled: true\n` +
      `  threshold: ${profile.auto_topup_threshold ?? 100}\n` +
      `  amount: ${profile.auto_topup_amount ?? 21000}`;
  }

  return `# User Profile
export_schema_version: "2.0"
user_id: "${profile.user_id}"
username: "${escapeYml(profile.username)}"
email: "${escapeYml(email)}"
email_verified: ${profile.email_verified}

account:
  status: "${profile.account_status ?? "active"}"
  last_access: "${profile.last_access ?? "never"}"

security:
  tfa_enabled: ${profile.tfa_enabled}
  has_passkey: ${profile.has_passkey}
  passkey_count: ${profile.passkey_count ?? 0}

preferences:
  language: "${profile.language}"
  darkmode: ${profile.darkmode}
  currency: "${profile.currency}"

credits:
  current_balance: ${profile.credits}

${autoTopupSection}

# Consent history is in compliance_logs.yml
`;
}

function generateUsageYml(records: UsageEntry[]): string {
  let yml = `# Usage History\nexport_schema_version: "2.0"\ntotal_records: ${records.length}\n\nusage_records:\n`;

  for (const r of records) {
    yml +=
      `  - usage_id: "${r.usage_id}"\n` +
      `    timestamp: ${r.timestamp}\n` +
      `    date: "${new Date(r.timestamp * 1000).toISOString()}"\n` +
      `    app_id: "${r.app_id}"\n` +
      `    skill_id: "${r.skill_id}"\n` +
      `    usage_type: "${r.usage_type}"\n` +
      `    source: "${r.source}"\n` +
      `    credits_charged: ${r.credits_charged}\n`;
    if (r.model_used) yml += `    model_used: "${r.model_used}"\n`;
    if (r.chat_id) yml += `    chat_id: "${r.chat_id}"\n`;
    if (r.actual_input_tokens)
      yml += `    input_tokens: ${r.actual_input_tokens}\n`;
    if (r.actual_output_tokens)
      yml += `    output_tokens: ${r.actual_output_tokens}\n`;
  }

  return yml;
}

/**
 * Generate a CSV version of usage history for easy spreadsheet analysis.
 */
function generateUsageCsv(records: UsageEntry[]): string {
  const header = [
    "usage_id",
    "date",
    "app_id",
    "skill_id",
    "usage_type",
    "source",
    "credits_charged",
    "model_used",
    "chat_id",
    "input_tokens",
    "output_tokens",
  ].join(",");

  const rows = records.map((r) => {
    const fields = [
      csvCell(r.usage_id),
      csvCell(new Date(r.timestamp * 1000).toISOString()),
      csvCell(r.app_id),
      csvCell(r.skill_id),
      csvCell(r.usage_type),
      csvCell(r.source),
      String(r.credits_charged),
      csvCell(r.model_used ?? ""),
      csvCell(r.chat_id ?? ""),
      String(r.actual_input_tokens ?? ""),
      String(r.actual_output_tokens ?? ""),
    ];
    return fields.join(",");
  });

  return [header, ...rows].join("\n");
}

function csvCell(value: string): string {
  // Wrap in quotes if it contains commas, quotes, or newlines
  if (value.includes(",") || value.includes('"') || value.includes("\n")) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function generateInvoicesYml(invoices: InvoiceExport[]): string {
  let yml = `# Invoice History\nexport_schema_version: "2.0"\ntotal_invoices: ${invoices.length}\n\ninvoices:\n`;

  for (const inv of invoices) {
    yml +=
      `  - invoice_id: "${inv.invoice_id}"\n` +
      `    order_id: "${inv.order_id}"\n` +
      `    date: "${inv.date}"\n` +
      `    amount_cents: ${inv.amount_cents}\n` +
      `    amount_formatted: "${(inv.amount_cents / 100).toFixed(2)} ${inv.currency.toUpperCase()}"\n` +
      `    credits_purchased: ${inv.credits_purchased}\n` +
      `    is_gift_card: ${inv.is_gift_card}\n` +
      `    refund_status: "${inv.refund_status}"\n`;
    if (inv.refunded_at) yml += `    refunded_at: "${inv.refunded_at}"\n`;
  }

  return yml;
}

function generateAppSettingsYml(settings: DecryptedAppSetting[]): string {
  // Group by app_id for readability
  const byApp: Record<string, DecryptedAppSetting[]> = {};
  for (const s of settings) {
    if (!byApp[s.app_id]) byApp[s.app_id] = [];
    byApp[s.app_id].push(s);
  }

  let yml =
    `# App Settings and AI Memories\n` +
    `# Content is fully decrypted.\n` +
    `export_schema_version: "2.0"\n` +
    `total_entries: ${settings.length}\n\n` +
    `entries:\n`;

  for (const [appId, entries] of Object.entries(byApp)) {
    yml += `  # ── ${appId} ──\n`;
    for (const entry of entries) {
      yml +=
        `  - app_id: "${appId}"\n` +
        `    item_key: "${escapeYml(entry.item_key)}"\n` +
        `    item_type: "${escapeYml(entry.item_type)}"\n` +
        `    created_at: "${new Date(entry.created_at * 1000).toISOString()}"\n` +
        `    updated_at: "${new Date(entry.updated_at * 1000).toISOString()}"\n`;

      const val = entry.value;
      if (typeof val === "string") {
        yml += `    value: "${escapeYml(val)}"\n`;
      } else if (
        val &&
        typeof val === "object" &&
        !(val as Record<string, unknown>)._encrypted
      ) {
        // Inline the decrypted JSON as nested YAML
        yml += `    value:\n`;
        for (const [k, v] of Object.entries(val)) {
          if (k === "_original_item_key") continue; // internal key
          const strV =
            typeof v === "string" ? `"${escapeYml(v)}"` : JSON.stringify(v);
          yml += `      ${k}: ${strV}\n`;
        }
      } else {
        yml += `    value: "[decryption failed — master key unavailable]"\n`;
      }
    }
  }

  return yml;
}

function generateComplianceLogsYml(logs: ComplianceLogEntry[]): string {
  const consentLogs = logs.filter((l) => l.event_type === "consent");
  const otherLogs = logs.filter((l) => l.event_type !== "consent");
  const pp = consentLogs.find((l) => l.consent_type === "privacy_policy");
  const tos = consentLogs.find((l) => l.consent_type === "terms_of_service");

  let yml =
    `# Compliance Logs — Consent History\n` +
    `export_schema_version: "2.0"\n\n` +
    `current_consent_status:\n` +
    `  privacy_policy:\n` +
    `    accepted: ${pp ? "true" : "false"}\n` +
    `    timestamp: "${pp?.timestamp ?? "not_recorded"}"\n` +
    `    action: "${pp?.action ?? "N/A"}"\n` +
    `  terms_of_service:\n` +
    `    accepted: ${tos ? "true" : "false"}\n` +
    `    timestamp: "${tos?.timestamp ?? "not_recorded"}"\n` +
    `    action: "${tos?.action ?? "N/A"}"\n\n` +
    `consent_history:\n`;

  for (const log of consentLogs) {
    yml +=
      `  - timestamp: "${log.timestamp}"\n` +
      `    consent_type: "${log.consent_type ?? "unknown"}"\n` +
      `    action: "${log.action ?? "granted"}"\n` +
      `    status: "${log.status ?? "success"}"\n`;
  }

  if (otherLogs.length > 0) {
    yml += `\nother_events:\n`;
    for (const log of otherLogs) {
      yml +=
        `  - timestamp: "${log.timestamp}"\n` +
        `    event_type: "${log.event_type}"\n` +
        `    status: "${log.status ?? "success"}"\n`;
    }
  }

  return yml;
}

// ============================================================================
// CHAT MARKDOWN HELPER (lightweight, no PII restore needed for full export)
// ============================================================================

function convertChatToMarkdown(chat: Chat, messages: Message[]): string {
  let md = chat.title ? `# ${chat.title}\n\n` : "";
  const createdMs =
    chat.created_at < 1e12 ? chat.created_at * 1000 : chat.created_at;
  md += `*Created: ${new Date(createdMs).toISOString()}*\n\n---\n\n`;

  for (const message of messages) {
    const tsMs =
      message.created_at < 1e12
        ? message.created_at * 1000
        : message.created_at;
    const ts = new Date(tsMs).toISOString();
    const role = message.role === "assistant" ? "Assistant" : "You";

    let content = "";
    if (typeof message.content === "string") {
      content = message.content;
    } else if (message.content && typeof message.content === "object") {
      content = tipTapToCanonicalMarkdown(message.content);
    }

    md += `## ${role} — ${ts}\n\n${content}\n\n`;
  }

  return md;
}

// ============================================================================
// SMALL UTILITIES
// ============================================================================

function getFileExt(language: string): string {
  const map: Record<string, string> = {
    javascript: "js",
    typescript: "ts",
    python: "py",
    java: "java",
    cpp: "cpp",
    c: "c",
    rust: "rs",
    go: "go",
    ruby: "rb",
    php: "php",
    swift: "swift",
    kotlin: "kt",
    yaml: "yml",
    xml: "xml",
    markdown: "md",
    bash: "sh",
    shell: "sh",
    sql: "sql",
    json: "json",
    css: "css",
    html: "html",
    dockerfile: "Dockerfile",
  };
  return map[language.toLowerCase()] ?? language.toLowerCase();
}

/** Escape double-quotes and backslashes for a YML double-quoted scalar */
function escapeYml(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

// ============================================================================
// DOWNLOAD HELPER
// ============================================================================

async function downloadZip(blob: Blob): Promise<void> {
  const profile = get(userProfile);
  const username = profile?.username || "user";
  const timestamp = new Date()
    .toISOString()
    .slice(0, 19)
    .replace(/[:-]/g, "")
    .replace("T", "_");
  const filename = `openmates_export_${username}_${timestamp}.zip`;

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
