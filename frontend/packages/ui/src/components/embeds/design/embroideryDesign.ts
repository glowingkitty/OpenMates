/**
 * Typed view of a design.embroidery result embed (`design-embroidery`).
 *
 * The decoded content is untrusted transport data, so every field is checked
 * here once; the preview, the fullscreen and the text renderer share the result.
 * Nothing here exposes encryption keys to the UI beyond the file descriptors the
 * crypto helpers need.
 */

/** Colour of the fabric in the rendered stitch preview; media areas use it so no other colour shows around it. */
export const EMBROIDERY_FABRIC_COLOUR = '#f4f1ea';

export const EMBROIDERY_FORMATS = ['dst', 'pes', 'exp', 'jef', 'vp3'] as const;
export type EmbroideryFormat = (typeof EMBROIDERY_FORMATS)[number];

export const EMBROIDERY_HOOPS = ['none', '100x100', '130x180', '160x260', '200x300'] as const;
export type EmbroideryHoop = (typeof EMBROIDERY_HOOPS)[number];

export const EMBROIDERY_FABRICS = ['light', 'normal', 'stretchy'] as const;
export type EmbroideryFabric = (typeof EMBROIDERY_FABRICS)[number];

/** Values the user picks to ask for a new conversion of the same graphic. */
export interface EmbroiderySettings {
  widthMm: number;
  hoop: EmbroideryHoop;
  fabric: EmbroideryFabric;
  /** Sew-on border width in mm; 0 means no border. */
  borderMm: number;
}

/** Border widths offered in the settings; 0 means none. */
export const EMBROIDERY_BORDERS_MM = [0, 2, 3, 4, 6] as const;

export const EMBROIDERY_MIN_WIDTH_MM = 20;
export const EMBROIDERY_MAX_WIDTH_MM = 400;

export const EMBROIDERY_ERROR_CODES = [
  'unreadable_svg', 'nothing_to_sew', 'too_many_stitches', 'timeout', 'sandbox_failed', 'invalid_source',
] as const;
export type EmbroideryErrorCode = (typeof EMBROIDERY_ERROR_CODES)[number];

/** Note codes with a translation; any other code shows the server's plain-language text. */
export const EMBROIDERY_FINDINGS = [
  'gradient_or_filter', 'live_text', 'embedded_pixel_image', 'detail_below_1mm', 'more_than_12_colours',
] as const;

/** Every note code that can reach the user: sandbox notes, rework notes, one solved_/unsolved_ pair per finding. */
export const EMBROIDERY_NOTE_CODES = [
  'background_removed', 'tiny_details_removed', 'lines_running', 'gradient_flattened', 'effects_ignored',
  'image_left_out', 'text_left_out', 'rotate_for_hoop', 'rework_failed', 'instructions_applied', 'border_added',
  'sized_to_hoop',
  ...EMBROIDERY_FINDINGS.map((finding) => `solved_${finding}`),
  ...EMBROIDERY_FINDINGS.map((finding) => `unsolved_${finding}`),
] as const;

export interface EmbroideryFile {
  s3_key: string;
  aes_nonce?: string;
  format?: string;
  encryption?: string;
  size_bytes?: number;
  mime_type?: string;
}

export interface EmbroideryThread {
  colourHex: string;
  name: string;
  stitchCount: number;
  /** Rough sewing minutes of this thread; null for results stored before it existed. */
  estimatedMinutes: number | null;
  /** Rough upper thread of this colour in metres; null for results stored before it existed. */
  threadLengthM: number | null;
}

export interface EmbroideryNote {
  code: string;
  text: string;
  /** Whole number some translations insert, for example the left-out detail count. */
  count: number | null;
  /** Border width in mm of the `border_added` note. */
  mm: number | null;
}

export interface EmbroideryDesign {
  status: 'processing' | 'finished' | 'error';
  title: string;
  widthMm: number | null;
  heightMm: number | null;
  stitchCount: number | null;
  threadChanges: number | null;
  estimatedMinutes: number | null;
  /** Rough upper thread of the whole design in metres. */
  threadLengthM: number | null;
  hoop: EmbroideryHoop;
  fitsHoop: 'yes' | 'no' | 'not_checked';
  fabric: EmbroideryFabric | null;
  /** Sew-on border width in mm; 0 when the result has no border. */
  borderMm: number;
  reworked: boolean;
  threads: EmbroideryThread[];
  notes: EmbroideryNote[];
  files: Partial<Record<string, EmbroideryFile>>;
  s3BaseUrl: string;
  aesKey: string;
  /** Content-level nonce of results written with the legacy media scheme (files then carry none). */
  aesNonce: string;
  sourceEmbedRef: string;
  error: string;
  errorCode: EmbroideryErrorCode | null;
  /** Direct media for component previews and store examples; skips S3 decryption. */
  previewImageUrl: string;
  preparedSvgText: string;
  /** Bytes saved for any format by a component preview (no S3 there). */
  previewDownloadText: string;
}

const HEX_COLOUR = /^#[0-9a-fA-F]{3,8}$/;

const num = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;
const string = (value: unknown): string => (typeof value === 'string' ? value : '');
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

function oneOf<T extends string>(value: unknown, allowed: readonly T[]): T | null {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value) ? (value as T) : null;
}

function readThreads(value: unknown): EmbroideryThread[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).map((row) => {
    const hex = string(row.colour_hex);
    return {
      colourHex: HEX_COLOUR.test(hex) ? hex : '',
      name: string(row.name) || hex,
      stitchCount: num(row.stitch_count) ?? 0,
      estimatedMinutes: num(row.estimated_minutes),
      threadLengthM: num(row.thread_length_m),
    };
  });
}

function readNotes(value: unknown): EmbroideryNote[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).map((row) => ({ code: string(row.code), text: string(row.text), count: num(row.count), mm: num(row.mm) }))
    .filter((note) => note.code || note.text);
}

function readFiles(value: unknown): Partial<Record<string, EmbroideryFile>> {
  if (!isRecord(value)) return {};
  const files: Partial<Record<string, EmbroideryFile>> = {};
  for (const [key, file] of Object.entries(value)) {
    if (isRecord(file) && typeof file.s3_key === 'string') files[key] = file as unknown as EmbroideryFile;
  }
  return files;
}

/** Read the decoded embed content; `status` falls back to the embed row status. */
export function readEmbroideryDesign(
  content: Record<string, unknown> | null | undefined,
  fallbackStatus?: string,
): EmbroideryDesign {
  const c = content ?? {};
  const rawStatus = string(c.status) || fallbackStatus;
  const status = rawStatus === 'processing' || rawStatus === 'error' ? rawStatus : 'finished';
  return {
    status,
    title: string(c.title),
    widthMm: num(c.width_mm),
    heightMm: num(c.height_mm),
    stitchCount: num(c.stitch_count),
    threadChanges: num(c.thread_changes),
    estimatedMinutes: num(c.estimated_minutes),
    threadLengthM: num(c.thread_length_m),
    hoop: oneOf(c.hoop, EMBROIDERY_HOOPS) ?? 'none',
    fitsHoop: oneOf(c.fits_hoop, ['yes', 'no', 'not_checked'] as const) ?? 'not_checked',
    fabric: oneOf(c.fabric, EMBROIDERY_FABRICS),
    borderMm: (num(c.border_mm) ?? 0) > 0 ? Math.round(num(c.border_mm) ?? 0) : 0,
    reworked: c.reworked === true,
    threads: readThreads(c.threads),
    notes: readNotes(c.notes),
    files: readFiles(c.files),
    s3BaseUrl: string(c.s3_base_url),
    aesKey: string(c.aes_key),
    aesNonce: string(c.aes_nonce),
    sourceEmbedRef: string(c.source_embed_ref),
    error: string(c.error),
    errorCode: oneOf(c.error_code, EMBROIDERY_ERROR_CODES),
    previewImageUrl: string(c.previewImageUrl),
    preparedSvgText: string(c.preparedSvgText),
    previewDownloadText: string(c.previewDownloadText),
  };
}

/** "100x100" becomes "100 × 100 mm". */
export function formatHoop(hoop: EmbroideryHoop): string {
  return hoop === 'none' ? '' : `${hoop.replace('x', ' × ')} mm`;
}

export function formatSize(design: Pick<EmbroideryDesign, 'widthMm' | 'heightMm'>): string {
  if (design.widthMm === null || design.heightMm === null) return '';
  return `${Math.round(design.widthMm)} × ${Math.round(design.heightMm)} mm`;
}

/** Whole stitches with the thousands separator of the active locale. */
export function formatCount(value: number | null): string {
  return value === null ? '' : value.toLocaleString();
}

/** "47 min" or "1 h 5 min". Units are language-neutral abbreviations. */
export function formatDuration(minutes: number | null): string {
  if (minutes === null) return '';
  const whole = Math.max(1, Math.round(minutes));
  return whole < 60 ? `${whole} min` : `${Math.floor(whole / 60)} h ${whole % 60} min`;
}

/** "80 cm", "4.5 m" or "62 m": rough thread length. Units are language-neutral. */
export function formatThreadLength(metres: number | null): string {
  if (metres === null) return '';
  if (metres < 1) return `${Math.max(10, Math.round(metres * 100))} cm`;
  return metres < 10 ? `${(Math.round(metres * 10) / 10).toLocaleString()} m` : `${Math.round(metres).toLocaleString()} m`;
}

/** Failed result: the translation key for the plain-words reason. */
export function errorTranslationKey(code: EmbroideryErrorCode | null): string {
  return `embeds.design.embroidery.error.${code ?? 'generic'}`;
}

export function noteTranslationKey(code: string): string | null {
  return (EMBROIDERY_NOTE_CODES as readonly string[]).includes(code)
    ? `embeds.design.embroidery.note.${code}`
    : null;
}
