/**
 * frontend/packages/ui/src/components/embeds/images/imageDownloadUtils.ts
 *
 * Utilities for downloading AI-generated images with proper filenames
 * and embedded metadata.
 *
 * - generateImageFilename(): Creates a human-readable filename from the prompt
 * - embedPngMetadata(): Injects PNG tEXt chunks with AI generation metadata
 *   (prompt, model, software) into the raw PNG bytes so the metadata is
 *   visible in macOS Finder, Windows Explorer, and image viewers.
 *
 * The backend already injects XMP metadata (IPTC 2025.1 compliant) into the
 * original PNG before encryption. This module adds PNG tEXt chunks as an
 * additional layer that is more widely visible in file managers and basic
 * image viewers.
 */

/**
 * Generate a clean, human-readable filename from a prompt string.
 *
 * Rules:
 * - Lowercase, words separated by underscores
 * - Only alphanumeric characters and underscores
 * - Truncated to ~60 characters (at a word boundary)
 * - Prefixed with "openmates_" for brand recognition
 * - Falls back to "openmates_generated_image" if prompt is empty
 *
 * @param prompt - The image generation prompt
 * @param extension - File extension without dot (default: "png")
 * @returns A sanitized filename string
 */
export function generateImageFilename(
  prompt: string | undefined,
  extension = "png",
): string {
  if (!prompt || prompt.trim().length === 0) {
    return `openmates_generated_image.${extension}`;
  }

  // Normalize: lowercase, replace non-alphanumeric with spaces, collapse whitespace
  let slug = prompt
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  // Truncate to ~60 chars at a word boundary
  if (slug.length > 60) {
    slug = slug.substring(0, 60);
    const lastSpace = slug.lastIndexOf(" ");
    if (lastSpace > 20) {
      slug = slug.substring(0, lastSpace);
    }
  }

  // Replace spaces with underscores
  slug = slug.replace(/\s/g, "_");

  // Remove trailing underscores
  slug = slug.replace(/_+$/, "");

  if (slug.length === 0) {
    return `openmates_generated_image.${extension}`;
  }

  return `openmates_${slug}.${extension}`;
}

// ─────────────────────────────────────────────────────────────
// PNG tEXt chunk injection
//
// PNG files consist of a signature (8 bytes) followed by a series of chunks.
// Each chunk has: 4-byte length, 4-byte type, data, 4-byte CRC32.
// We inject tEXt chunks (for ASCII metadata) right after the IHDR chunk
// so that file managers and image viewers can read them.
//
// tEXt chunk format: keyword + null byte + text value
// Standard keywords: Comment, Description, Software, Source, Author, Title
//
// Reference: https://www.w3.org/TR/png/#11tEXt
// ─────────────────────────────────────────────────────────────

/** PNG file signature (first 8 bytes of every valid PNG) */
const PNG_SIGNATURE = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);

/**
 * Metadata fields to embed in the PNG tEXt chunks.
 * These should match the XMP metadata injected by the backend
 * (see backend/core/api/app/utils/image_processing.py _generate_ai_xmp).
 */
export interface PngAiMetadata {
  /** The generation prompt */
  prompt?: string;
  /** The AI model used (e.g. "Google gemini-3-pro-image-preview") */
  model?: string;
  /** Software that created the image */
  software?: string;
  /** ISO timestamp of when the image was generated */
  generatedAt?: string;
}

/**
 * Embed AI generation metadata as PNG tEXt chunks into raw PNG bytes.
 *
 * This injects standard PNG text metadata that is widely supported:
 * - "Description": prompt text (shown in macOS Finder, Windows properties)
 * - "Comment": Structured AI generation info (prompt, model, software)
 * - "Software": "OpenMates"
 * - "Source": "OpenMates AI"
 * - "Title": prompt text (short form)
 *
 * The metadata is injected right after the IHDR chunk.
 * If the input is not a valid PNG, the original bytes are returned unchanged.
 *
 * @param pngBytes - Raw PNG file bytes (as ArrayBuffer or Uint8Array)
 * @param metadata - AI generation metadata to embed
 * @returns New Uint8Array with metadata injected, or original bytes if not PNG
 */
export function embedPngMetadata(
  pngBytes: ArrayBuffer | Uint8Array,
  metadata: PngAiMetadata,
): Uint8Array {
  const data =
    pngBytes instanceof Uint8Array ? pngBytes : new Uint8Array(pngBytes);

  // Verify PNG signature
  if (data.length < 8 || !isPngSignature(data)) {
    return data;
  }

  // Build tEXt chunks to inject.
  // These mirror the XMP metadata injected by the backend (image_processing.py)
  // so that file managers show consistent info regardless of download method.
  const chunks: Uint8Array[] = [];

  // "Description" - matches XMP dc:description format (multi-line with model, timestamp, prompt).
  // macOS Finder shows this in the "More Info" section.
  const descParts: string[] = [];
  descParts.push("AI-generated on OpenMates");
  if (metadata.model) {
    descParts.push(`Model: ${metadata.model}`);
  }
  if (metadata.generatedAt) {
    descParts.push(`Generated at: ${metadata.generatedAt}`);
  }
  if (metadata.prompt) {
    descParts.push(`Prompt: ${metadata.prompt}`);
  }
  if (descParts.length > 0) {
    chunks.push(createTextChunk("Description", descParts.join("\n")));
  }

  // "Comment" - same structured AI generation info (some viewers read Comment instead of Description)
  chunks.push(createTextChunk("Comment", descParts.join("\n")));

  // "Software" - creation tool
  chunks.push(createTextChunk("Software", metadata.software || "OpenMates"));

  // "Source" - origin
  chunks.push(createTextChunk("Source", "OpenMates AI"));

  // "Title" - prompt text (matches XMP dc:title)
  if (metadata.prompt) {
    // Truncate title to 200 chars for reasonableness
    const title =
      metadata.prompt.length > 200
        ? metadata.prompt.substring(0, 200) + "..."
        : metadata.prompt;
    chunks.push(createTextChunk("Title", title));
  }

  if (chunks.length === 0) {
    return data;
  }

  // Find the end of the IHDR chunk to insert our text chunks after it.
  // PNG structure: [8-byte signature] [IHDR chunk] [other chunks...] [IEND chunk]
  // IHDR chunk: 4-byte length + 4-byte "IHDR" + data + 4-byte CRC
  const ihdrLength = readUint32(data, 8);
  const insertOffset = 8 + 4 + 4 + ihdrLength + 4; // after signature + IHDR chunk

  if (insertOffset > data.length) {
    return data; // malformed PNG
  }

  // Calculate total size of new chunks
  const totalNewBytes = chunks.reduce((sum, chunk) => sum + chunk.length, 0);

  // Build new PNG: [before insert] + [new chunks] + [after insert]
  const result = new Uint8Array(data.length + totalNewBytes);
  result.set(data.subarray(0, insertOffset), 0);

  let offset = insertOffset;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.length;
  }

  result.set(data.subarray(insertOffset), offset);

  return result;
}

// ─────────────────────────────────────────────────────────────
// Internal helpers
// ─────────────────────────────────────────────────────────────

/**
 * Check if the first 8 bytes match the PNG signature.
 */
function isPngSignature(data: Uint8Array): boolean {
  for (let i = 0; i < PNG_SIGNATURE.length; i++) {
    if (data[i] !== PNG_SIGNATURE[i]) return false;
  }
  return true;
}

/**
 * Read a big-endian uint32 from a Uint8Array at the given offset.
 */
function readUint32(data: Uint8Array, offset: number): number {
  return (
    ((data[offset] << 24) >>> 0) +
    (data[offset + 1] << 16) +
    (data[offset + 2] << 8) +
    data[offset + 3]
  );
}

/**
 * Write a big-endian uint32 into a Uint8Array at the given offset.
 */
function writeUint32(data: Uint8Array, offset: number, value: number): void {
  data[offset] = (value >>> 24) & 0xff;
  data[offset + 1] = (value >>> 16) & 0xff;
  data[offset + 2] = (value >>> 8) & 0xff;
  data[offset + 3] = value & 0xff;
}

/**
 * Create a PNG tEXt chunk.
 *
 * Format: [4-byte length][4-byte "tEXt"][keyword + \0 + text][4-byte CRC32]
 *
 * @param keyword - Standard PNG text keyword (e.g. "Comment", "Description")
 * @param text - The text value (ASCII/Latin-1)
 */
function createTextChunk(keyword: string, text: string): Uint8Array {
  const encoder = new TextEncoder();
  const keywordBytes = encoder.encode(keyword);
  const textBytes = encoder.encode(text);

  // Chunk data = keyword + null separator + text
  const chunkDataLength = keywordBytes.length + 1 + textBytes.length;
  const typeBytes = encoder.encode("tEXt");

  // Full chunk: 4 (length) + 4 (type) + data + 4 (CRC)
  const chunk = new Uint8Array(4 + 4 + chunkDataLength + 4);

  // Write length (of data only, not including type/length/CRC)
  writeUint32(chunk, 0, chunkDataLength);

  // Write type "tEXt"
  chunk.set(typeBytes, 4);

  // Write keyword
  chunk.set(keywordBytes, 8);

  // Null separator (already 0 from Uint8Array initialization)
  // chunk[8 + keywordBytes.length] = 0;

  // Write text value
  chunk.set(textBytes, 8 + keywordBytes.length + 1);

  // Compute CRC32 over type + data (not length field, not CRC field itself)
  const crcData = chunk.subarray(4, 4 + 4 + chunkDataLength);
  const crc = crc32(crcData);
  writeUint32(chunk, 4 + 4 + chunkDataLength, crc);

  return chunk;
}

// ─────────────────────────────────────────────────────────────
// CRC32 implementation for PNG chunk checksums
// ─────────────────────────────────────────────────────────────

/** CRC32 lookup table (computed once, cached). */
let crc32Table: Uint32Array | null = null;

/**
 * Build the CRC32 lookup table (standard polynomial 0xEDB88320).
 */
function ensureCrc32Table(): Uint32Array {
  if (crc32Table) return crc32Table;
  crc32Table = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let j = 0; j < 8; j++) {
      if (c & 1) {
        c = 0xedb88320 ^ (c >>> 1);
      } else {
        c = c >>> 1;
      }
    }
    crc32Table[i] = c >>> 0;
  }
  return crc32Table;
}

/**
 * Compute CRC32 of a Uint8Array (used for PNG chunk checksums).
 */
function crc32(data: Uint8Array): number {
  const table = ensureCrc32Table();
  let crc = 0xffffffff;
  for (let i = 0; i < data.length; i++) {
    crc = table[(crc ^ data[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}
