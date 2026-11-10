// frontend/packages/ui/src/components/embeds/design/designEmbedText.ts
//
// Plain-text renderers for Design app embeds.
// Used by copy/export flows and CLI output so new design embed types remain
// portable outside the browser UI.
//
// Architecture: docs/architecture/embeds.md

import { resolveResultCount, str } from '../../../data/embedTextRenderers';

export function renderDesignIconSearch(content: Record<string, unknown>): string {
	const query = str(content.query) ?? 'Icon search';
	const provider = str(content.provider) ?? 'Iconify';
	const count = resolveResultCount(content);
	const lines = ['**Design | Icon search**', `query: ${query}`, `provider: ${provider}`];
	if (count !== null) lines.push(`icons: ${count}`);
	return lines.join('\n');
}

export function renderDesignIconResult(content: Record<string, unknown>): string {
	const title = str(content.display_name) ?? str(content.name) ?? str(content.icon_id) ?? 'Icon';
	const collection = str(content.collection_name) ?? str(content.prefix);
	const license = str(content.license_title) ?? str(content.license_spdx);
	const svgPath = str(content.svg_path);
	const lines = [`**${title}**`];
	if (collection) lines.push(`collection: ${collection}`);
	if (license) lines.push(`license: ${license}`);
	if (svgPath) lines.push(svgPath);
	return lines.join('\n');
}

const HOOP_TEXT: Record<string, string> = {
  '100x100': '100 x 100 mm', '130x180': '130 x 180 mm', '160x260': '160 x 260 mm', '200x300': '200 x 300 mm',
};

/** Text surface (CLI, SDKs, copy, export) for a design.embroidery result. */
export function renderDesignEmbroidery(content: Record<string, unknown>): string {
  const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const title = str(content.title) ?? 'Embroidery design';
  if (str(content.status) === 'error') {
    return [`**${title}**`, `failed: ${str(content.error) ?? 'conversion failed'}`].join('\n');
  }
  const lines = [`**${title}**`];
  const width = num(content.width_mm);
  const height = num(content.height_mm);
  if (width !== null && height !== null) lines.push(`size: ${Math.round(width)} x ${Math.round(height)} mm`);
  const stitches = num(content.stitch_count);
  if (stitches !== null) lines.push(`stitches: ${stitches}`);
  const changes = num(content.thread_changes);
  if (changes !== null) lines.push(`thread changes: ${changes}`);
  const minutes = num(content.estimated_minutes);
  if (minutes !== null) lines.push(`estimated sewing time: ${minutes} min`);
  const threadMetres = num(content.thread_length_m);
  if (threadMetres !== null) lines.push(`estimated thread: ${threadMetres} m`);
  const hoop = str(content.hoop);
  const fits = str(content.fits_hoop);
  if (hoop && HOOP_TEXT[hoop] && fits === 'yes') lines.push(`fits hoop ${HOOP_TEXT[hoop]}`);
  if (hoop && HOOP_TEXT[hoop] && fits === 'no') lines.push(`too large for hoop ${HOOP_TEXT[hoop]}`);
  const fabric = str(content.fabric);
  if (fabric) lines.push(`fabric: ${fabric}`);
  const files = content.files;
  if (typeof files === 'object' && files !== null) {
    const formats = ['dst', 'pes', 'exp', 'jef', 'vp3'].filter((format) => format in files);
    if (formats.length > 0) lines.push(`files: ${formats.map((format) => format.toUpperCase()).join(', ')}`);
  }
  const threads = Array.isArray(content.threads) ? content.threads : [];
  threads.forEach((thread, index) => {
    if (typeof thread !== 'object' || thread === null) return;
    const row = thread as Record<string, unknown>;
    lines.push(`thread ${index + 1}: ${str(row.name) ?? str(row.colour_hex) ?? ''} (${num(row.stitch_count) ?? 0} stitches)`);
  });
  const notes = Array.isArray(content.notes) ? content.notes : [];
  for (const note of notes) {
    const noteText = typeof note === 'object' && note !== null ? str((note as Record<string, unknown>).text) : null;
    if (noteText) lines.push(`note: ${noteText}`);
  }
  return lines.join('\n');
}
