import { DOMParser, XMLSerializer, type Node as XmlNode, type Element as XmlElement } from '@xmldom/xmldom';

const ascii = (bytes: Uint8Array, offset: number, length: number): string =>
  String.fromCharCode(...bytes.subarray(offset, offset + length));
const be16 = (b: Uint8Array, p: number) => (b[p]! << 8) | b[p + 1]!;
const le16 = (b: Uint8Array, p: number) => b[p]! | (b[p + 1]! << 8);
const be32 = (b: Uint8Array, p: number) => (b[p]! * 0x1000000 + (b[p + 1]! << 16) + (b[p + 2]! << 8) + b[p + 3]!) >>> 0;
const le32 = (b: Uint8Array, p: number) => (b[p]! + (b[p + 1]! << 8) + (b[p + 2]! << 16) + b[p + 3]! * 0x1000000) >>> 0;
const requireBytes = (b: Uint8Array, p: number, n: number): void => {
  if (!Number.isSafeInteger(p) || !Number.isSafeInteger(n) || p < 0 || n < 0 || p + n > b.length) throw new Error('Malformed image');
};
const concat = (parts: Uint8Array[]): Uint8Array => {
  const size = parts.reduce((n, p) => n + p.length, 0);
  const out = new Uint8Array(size);
  let offset = 0;
  for (const part of parts) { out.set(part, offset); offset += part.length; }
  return out;
};

function tiffOrientation(data: Uint8Array, t = 0): number | undefined {
  requireBytes(data, t, 8);
  const little = ascii(data, t, 2) === 'II';
  if (!little && ascii(data, t, 2) !== 'MM') return;
  const r16 = (p: number) => little ? le16(data, p) : be16(data, p);
  const r32 = (p: number) => little ? le32(data, p) : be32(data, p);
  if (r16(t + 2) !== 42) return;
  const ifd = t + r32(t + 4);
  requireBytes(data, ifd, 2);
  const count = r16(ifd);
  requireBytes(data, ifd + 2, count * 12);
  for (let i = 0; i < count; i++) {
    const p = ifd + 2 + i * 12;
    if (r16(p) === 0x0112 && r16(p + 2) === 3 && r32(p + 4) === 1) {
      const value = r16(p + 8);
      return value >= 1 && value <= 8 ? value : undefined;
    }
  }
}

function jpegOrientation(segment: Uint8Array): number | undefined {
  if (segment.length < 16 || ascii(segment, 4, 6) !== 'Exif\0\0') return;
  return tiffOrientation(segment, 10);
}

const minimalTiffOrientation = (orientation: number) => Uint8Array.from([
  73, 73, 42, 0, 8, 0, 0, 0, 1, 0,
  0x12, 1, 3, 0, 1, 0, 0, 0, orientation, 0, 0, 0,
  0, 0, 0, 0,
]);

function minimalOrientationSegment(orientation: number): Uint8Array {
  // Fresh APP1 EXIF contains exactly one technical field, with no camera/GPS data.
  return concat([Uint8Array.of(0xff, 0xe1, 0, 34, 69, 120, 105, 102, 0, 0), minimalTiffOrientation(orientation)]);
}

function jpeg(bytes: Uint8Array): Uint8Array {
  requireBytes(bytes, 0, 4);
  if (bytes[0] !== 0xff || bytes[1] !== 0xd8) throw new Error('Malformed JPEG');
  const parts: Uint8Array[] = [bytes.subarray(0, 2)];
  let p = 2;
  let orientation: number | undefined;
  let sawScan = false;
  while (p < bytes.length) {
    if (bytes[p++] !== 0xff) throw new Error('Malformed JPEG marker');
    while (bytes[p] === 0xff) p++;
    requireBytes(bytes, p, 1);
    const marker = bytes[p++]!;
    if (marker === 0xd9) {
      if (!sawScan) throw new Error('JPEG has no image data');
      if (orientation && orientation !== 1) parts.splice(1, 0, minimalOrientationSegment(orientation));
      parts.push(Uint8Array.of(0xff, 0xd9));
      return concat(parts);
    }
    if (marker === 0x00 || marker === 0xd8 || (marker >= 0xd0 && marker <= 0xd7)) throw new Error('Malformed JPEG marker');
    requireBytes(bytes, p, 2);
    const length = be16(bytes, p);
    if (length < 2) throw new Error('Malformed JPEG segment');
    const start = p - 2;
    requireBytes(bytes, p, length);
    p += length;
    if (marker === 0xe1 && orientation === undefined && ascii(bytes, start + 4, Math.min(6, length - 2)) === 'Exif\0\0') {
      try { orientation = jpegOrientation(bytes.subarray(start, p)); } catch { /* malformed EXIF is discarded */ }
    }
    // All APP and COM segments can carry identifying text, including private APP markers.
    if (marker === 0xee && length === 14 && ascii(bytes, start + 4, 5) === 'Adobe') {
      // APP14 transform is needed for CMYK/YCCK display; replace all other fields.
      const transform = bytes[p - 1]!;
      if (transform <= 2) parts.push(Uint8Array.of(255, 238, 0, 14, 65, 100, 111, 98, 101, 0, 100, 0, 0, 0, 0, transform));
    } else if (!(marker >= 0xe0 && marker <= 0xef) && marker !== 0xfe) parts.push(bytes.subarray(start, p));
    if (marker === 0xda) {
      sawScan = true;
      const scanStart = p;
      while (p < bytes.length - 1) {
        if (bytes[p] !== 0xff) { p++; continue; }
        const next = bytes[p + 1]!;
        if (next === 0x00 || next === 0xff || (next >= 0xd0 && next <= 0xd7)) { p += 2; continue; }
        break;
      }
      requireBytes(bytes, p, 2);
      parts.push(bytes.subarray(scanStart, p));
    }
  }
  throw new Error('JPEG is missing EOI');
}

const pngSignature = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10]);
const pngAllowed = new Set(['IHDR', 'PLTE', 'IDAT', 'IEND', 'tRNS', 'gAMA', 'cHRM', 'sRGB', 'sBIT', 'cICP', 'bKGD', 'acTL', 'fcTL', 'fdAT']);
function pngCrc(data: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of data) {
    crc ^= byte;
    for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}
function pngChunk(type: string, data: Uint8Array): Uint8Array {
  const out = new Uint8Array(12 + data.length);
  new DataView(out.buffer).setUint32(0, data.length, false);
  out.set(new TextEncoder().encode(type), 4);
  out.set(data, 8);
  new DataView(out.buffer).setUint32(out.length - 4, pngCrc(out.subarray(4, out.length - 4)), false);
  return out;
}
function png(bytes: Uint8Array): Uint8Array {
  requireBytes(bytes, 0, 8);
  if (!pngSignature.every((v, i) => bytes[i] === v)) throw new Error('Malformed PNG');
  const parts = [bytes.subarray(0, 8)];
  let p = 8, ihdr = false, idat = false;
  let orientation: number | undefined;
  while (p < bytes.length) {
    requireBytes(bytes, p, 12);
    const length = be32(bytes, p);
    const type = ascii(bytes, p + 4, 4);
    requireBytes(bytes, p, 12 + length);
    if (!/^[A-Za-z]{4}$/.test(type)) throw new Error('Malformed PNG chunk');
    if (!ihdr && type !== 'IHDR') throw new Error('PNG missing IHDR');
    if (type === 'IHDR') {
      if (ihdr || length !== 13) throw new Error('Malformed PNG IHDR');
      ihdr = true;
    }
    if (type === 'IDAT') idat = true;
    if (type === 'IEND' && (length !== 0 || !idat)) throw new Error('Malformed PNG IEND');
    if (type === 'eXIf' && orientation === undefined) {
      try { orientation = tiffOrientation(bytes.subarray(p + 8, p + 8 + length)); } catch { /* malformed EXIF is discarded */ }
    }
    if (!pngAllowed.has(type) && type[0] === type[0]!.toUpperCase()) throw new Error('Unsupported critical PNG chunk');
    if (type === 'IEND' && orientation && orientation !== 1) parts.splice(2, 0, pngChunk('eXIf', minimalTiffOrientation(orientation)));
    if (pngAllowed.has(type)) parts.push(bytes.subarray(p, p + 12 + length));
    p += 12 + length;
    if (type === 'IEND') return concat(parts);
  }
  throw new Error('PNG is missing IEND');
}

const webpAllowed = new Set(['VP8X', 'VP8 ', 'VP8L', 'ALPH', 'ANIM', 'ANMF']);
function webpChunk(type: string, data: Uint8Array): Uint8Array {
  const out = new Uint8Array(8 + data.length + (data.length & 1));
  out.set(new TextEncoder().encode(type), 0);
  new DataView(out.buffer).setUint32(4, data.length, true);
  out.set(data, 8);
  return out;
}
function webpFrame(data: Uint8Array): Uint8Array {
  requireBytes(data, 0, 16);
  const parts: Uint8Array[] = [data.subarray(0, 16)];
  let p = 16, image = false;
  while (p < data.length) {
    requireBytes(data, p, 8);
    const type = ascii(data, p, 4), size = le32(data, p + 4);
    const end = p + 8 + size + (size & 1);
    requireBytes(data, p, end - p);
    if (type === 'ALPH' || type === 'VP8 ' || type === 'VP8L') parts.push(data.subarray(p, end));
    if (type === 'VP8 ' || type === 'VP8L') image = true;
    p = end;
  }
  if (!image) throw new Error('WebP frame has no image data');
  return concat(parts);
}
function webp(bytes: Uint8Array): Uint8Array {
  requireBytes(bytes, 0, 12);
  if (ascii(bytes, 0, 4) !== 'RIFF' || ascii(bytes, 8, 4) !== 'WEBP') throw new Error('Malformed WebP');
  const end = 8 + le32(bytes, 4);
  if (end < 12 || end > bytes.length) throw new Error('Malformed WebP size');
  const parts: Uint8Array[] = [];
  let p = 12, image = false;
  while (p < end) {
    requireBytes(bytes, p, 8);
    const type = ascii(bytes, p, 4);
    const size = le32(bytes, p + 4);
    const chunkEnd = p + 8 + size + (size & 1);
    if (chunkEnd > end) throw new Error('Malformed WebP chunk');
    if (webpAllowed.has(type)) {
      if (type === 'VP8X') {
        if (size !== 10) throw new Error('Malformed WebP VP8X');
        const copy = bytes.slice(p, chunkEnd);
        copy[8] = copy[8]! & ~0x2c; // ICC, EXIF, XMP flags
        parts.push(copy);
      } else if (type === 'ANMF') parts.push(webpChunk('ANMF', webpFrame(bytes.subarray(p + 8, p + 8 + size))));
      else parts.push(bytes.subarray(p, chunkEnd));
      if (type === 'VP8 ' || type === 'VP8L' || type === 'ANMF') image = true;
    }
    p = chunkEnd;
  }
  if (!image) throw new Error('WebP has no image data');
  const payload = concat(parts);
  const out = new Uint8Array(12 + payload.length);
  out.set([82, 73, 70, 70], 0);
  new DataView(out.buffer).setUint32(4, out.length - 8, true);
  out.set([87, 69, 66, 80], 8);
  out.set(payload, 12);
  return out;
}

function gif(bytes: Uint8Array): Uint8Array {
  requireBytes(bytes, 0, 13);
  if (!['GIF87a', 'GIF89a'].includes(ascii(bytes, 0, 6))) throw new Error('Malformed GIF');
  let p = 13;
  const globalColorSize = bytes[10]! & 0x80 ? 3 * (1 << ((bytes[10]! & 7) + 1)) : 0;
  requireBytes(bytes, p, globalColorSize);
  p += globalColorSize;
  const parts = [bytes.subarray(0, p)];
  let image = false;
  const blocks = (): void => {
    while (true) {
      requireBytes(bytes, p, 1);
      const n = bytes[p++]!;
      requireBytes(bytes, p, n);
      p += n;
      if (!n) return;
    }
  };
  while (p < bytes.length) {
    const start = p, kind = bytes[p++]!;
    if (kind === 0x3b) {
      if (!image) throw new Error('GIF has no image');
      parts.push(Uint8Array.of(0x3b));
      return concat(parts);
    }
    if (kind === 0x2c) {
      image = true;
      requireBytes(bytes, p, 9);
      const flags = bytes[p + 8]!;
      p += 9;
      const localColorSize = flags & 0x80 ? 3 * (1 << ((flags & 7) + 1)) : 0;
      requireBytes(bytes, p, localColorSize + 1);
      p += localColorSize + 1;
      blocks();
      parts.push(bytes.subarray(start, p));
      continue;
    }
    if (kind !== 0x21) throw new Error('Malformed GIF block');
    requireBytes(bytes, p, 1);
    const label = bytes[p++]!;
    if (label === 0xf9) {
      requireBytes(bytes, p, 6);
      if (bytes[p] !== 4 || bytes[p + 5] !== 0) throw new Error('Malformed GIF graphic control');
      p += 6;
      parts.push(bytes.subarray(start, p));
    } else if (label === 0xff || label === 0x01) {
      requireBytes(bytes, p, 1);
      const n = bytes[p++]!;
      requireBytes(bytes, p, n);
      const app = label === 0xff ? ascii(bytes, p, n) : '';
      p += n;
      blocks();
      // NETSCAPE/ANIMEXTS carries loop count; plain text is visible content.
      if (label === 0x01 || app === 'NETSCAPE2.0' || app === 'ANIMEXTS1.0') parts.push(bytes.subarray(start, p));
    } else { blocks(); }
  }
  throw new Error('GIF is missing trailer');
}

function bmp(bytes: Uint8Array): Uint8Array | undefined {
  requireBytes(bytes, 0, 54);
  if (ascii(bytes, 0, 2) !== 'BM') throw new Error('Malformed BMP');
  // Rebuild only uncompressed 24/32-bit Windows V3 bitmaps. Other BMP variants
  // need a decoder, especially V4/V5 with color profiles and embedded payloads.
  if (le32(bytes, 14) !== 40 || le16(bytes, 26) !== 1 || le32(bytes, 30) !== 0) return;
  const bpp = le16(bytes, 28), width = new DataView(bytes.buffer, bytes.byteOffset).getInt32(18, true);
  const height = new DataView(bytes.buffer, bytes.byteOffset).getInt32(22, true);
  if (![24, 32].includes(bpp) || width <= 0 || height === 0 || le32(bytes, 46) !== 0) return;
  const row = Math.ceil(width * bpp / 32) * 4, pixelBytes = row * Math.abs(height), offset = le32(bytes, 10);
  if (!Number.isSafeInteger(pixelBytes) || offset < 54) throw new Error('Malformed BMP dimensions');
  requireBytes(bytes, offset, pixelBytes);
  const out = new Uint8Array(54 + pixelBytes);
  out.set(bytes.subarray(0, 54));
  new DataView(out.buffer).setUint32(2, out.length, true);
  new DataView(out.buffer).setUint32(10, 54, true);
  new DataView(out.buffer).setUint32(34, pixelBytes, true);
  out.fill(0, 6, 10);
  out.fill(0, 38, 54); // resolution and reserved palette fields can identify software/devices
  out.set(bytes.subarray(offset, offset + pixelBytes), 54);
  return out;
}

function svg(bytes: Uint8Array): Uint8Array {
  const input = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (/<!\s*(?:DOCTYPE|ENTITY)\b/i.test(input)) throw new Error('SVG declarations are unsupported');
  const errors: string[] = [];
  const document = new DOMParser({ onError: (level, message) => { if (level !== 'warning') errors.push(message); } }).parseFromString(input, 'image/svg+xml');
  if (errors.length || document.documentElement?.localName !== 'svg') throw new Error('Malformed SVG');
  const svgNamespace = 'http://www.w3.org/2000/svg';
  const xlinkNamespace = 'http://www.w3.org/1999/xlink';
  const filenameOrPathAttribute = /(?:file-?name|file-?path|path-?name|doc-?name|doc-?base|directory|folder|(?:^|[-_:])path$|^(?:href|src)$)/i;
  function hasFilenameOrPath(node: XmlNode): boolean {
    if (node.nodeType !== 1) return false;
    const element = node as XmlElement;
    for (let i = 0; i < element.attributes.length; i++) {
      if (filenameOrPathAttribute.test(element.attributes.item(i)!.localName ?? '')) return true;
    }
    for (let child = node.firstChild; child; child = child.nextSibling) {
      if (hasFilenameOrPath(child)) return true;
    }
    return false;
  }
  function scrubDataImage(value: string): string {
    const match = /^data:(image\/(?:jpeg|jpg|png|webp|gif|bmp));base64,([A-Za-z0-9+/=]+)$/i.exec(value);
    if (!match) return value;
    const decoded = atob(match[2]!);
    const nested = new Uint8Array(decoded.length);
    for (let i = 0; i < decoded.length; i++) nested[i] = decoded.charCodeAt(i);
    const cleaned = stripImageMetadata(nested, match[1]!);
    if (!cleaned) return value;
    const chunks: string[] = [];
    for (let i = 0; i < cleaned.length; i += 8192) chunks.push(String.fromCharCode(...cleaned.subarray(i, i + 8192)));
    return `data:${match[1]!.toLowerCase()};base64,${btoa(chunks.join(''))}`;
  }
  function clean(node: XmlNode, inForeignObject = false): void {
    for (let child = node.firstChild; child;) {
      const next = child.nextSibling;
      if (child.nodeType === 8 || child.nodeType === 7 || child.nodeType === 10) node.removeChild(child);
      else if (child.nodeType === 1) {
        const element = child as XmlElement;
        if (element.namespaceURI === svgNamespace && element.localName === 'metadata') node.removeChild(child);
        else if (!inForeignObject && element.namespaceURI !== svgNamespace && !hasFilenameOrPath(element)) node.removeChild(child);
        else clean(child, inForeignObject || (element.namespaceURI === svgNamespace && element.localName === 'foreignObject'));
      }
      child = next;
    }
    if (node.nodeType !== 1) return;
    const element = node as XmlElement;
    for (let i = element.attributes.length - 1; i >= 0; i--) {
      const attr = element.attributes.item(i)!;
      if (attr.name === 'xmlns' || attr.name.startsWith('xmlns:')) continue;
      if (!inForeignObject && attr.namespaceURI && attr.namespaceURI !== svgNamespace && attr.namespaceURI !== xlinkNamespace && !filenameOrPathAttribute.test(attr.localName ?? '')) element.removeAttributeNode(attr);
      else if ((attr.localName === 'href') && attr.value.startsWith('data:image/')) attr.value = scrubDataImage(attr.value);
    }
  }
  clean(document);
  return new TextEncoder().encode(new XMLSerializer().serializeToString(document));
}

/** Remove embedded identifying image metadata while retaining supported image content. */
export function stripImageMetadata(bytes: Uint8Array, mimeType: string): Uint8Array | undefined {
  switch (mimeType.toLowerCase().split(';', 1)[0]?.trim()) {
    case 'image/jpeg': case 'image/jpg': return jpeg(bytes);
    case 'image/png': return png(bytes);
    case 'image/webp': return webp(bytes);
    case 'image/gif': return gif(bytes);
    case 'image/bmp': return bmp(bytes);
    case 'image/svg+xml': return svg(bytes);
    default: return undefined;
  }
}
