/** Best-effort, lossless audio metadata removal. An undefined result means use the original. */

const ascii = (bytes: Uint8Array, offset: number, length: number): string =>
  String.fromCharCode(...bytes.subarray(offset, offset + length));

const matches = (bytes: Uint8Array, offset: number, value: string): boolean =>
  offset >= 0 && offset + value.length <= bytes.length && ascii(bytes, offset, value.length) === value;

const u32le = (bytes: Uint8Array, offset: number): number =>
  (bytes[offset] | (bytes[offset + 1] << 8) | (bytes[offset + 2] << 16) | (bytes[offset + 3] << 24)) >>> 0;

const u32be = (bytes: Uint8Array, offset: number): number =>
  ((bytes[offset] << 24) | (bytes[offset + 1] << 16) | (bytes[offset + 2] << 8) | bytes[offset + 3]) >>> 0;

const put32le = (bytes: Uint8Array, offset: number, value: number): void => {
  bytes[offset] = value & 255;
  bytes[offset + 1] = (value >>> 8) & 255;
  bytes[offset + 2] = (value >>> 16) & 255;
  bytes[offset + 3] = (value >>> 24) & 255;
};

function stripWav(bytes: Uint8Array): Uint8Array | undefined {
  if (bytes.length < 44 || !matches(bytes, 0, 'RIFF') || !matches(bytes, 8, 'WAVE') ||
      u32le(bytes, 4) !== bytes.length - 8) return undefined;
  const chunks: Uint8Array[] = [];
  let offset = 12;
  let hasFormat = false;
  let hasData = false;
  let changed = false;
  while (offset < bytes.length) {
    if (offset + 8 > bytes.length) return undefined;
    const length = u32le(bytes, offset + 4);
    const end = offset + 8 + length + (length & 1);
    if (!Number.isSafeInteger(end) || end > bytes.length) return undefined;
    const id = ascii(bytes, offset, 4);
    if (id === 'fmt ' || id === 'data' || id === 'fact') {
      if (id === 'fmt ') hasFormat = true;
      if (id === 'data') hasData = true;
      chunks.push(bytes.subarray(offset, end));
    } else if (id === 'LIST' && matches(bytes, offset + 8, 'wavl')) {
      // LIST/wavl can contain audio blocks and must not be dropped.
      return undefined;
    } else changed = true;
    offset = end;
  }
  if (!hasFormat || !hasData) return undefined;
  if (!changed) return bytes;
  const length = 12 + chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  if (length - 8 > 0xffffffff) return undefined;
  const output = new Uint8Array(length);
  output.set(bytes.subarray(0, 12));
  put32le(output, 4, length - 8);
  let cursor = 12;
  for (const chunk of chunks) { output.set(chunk, cursor); cursor += chunk.length; }
  return output;
}

function synchsafe(bytes: Uint8Array, offset: number): number | undefined {
  if (offset + 4 > bytes.length || bytes.subarray(offset, offset + 4).some(value => value & 0x80)) return undefined;
  return (bytes[offset] << 21) | (bytes[offset + 1] << 14) | (bytes[offset + 2] << 7) | bytes[offset + 3];
}

function stripMp3OrAdts(bytes: Uint8Array, adts: boolean): Uint8Array | undefined {
  let start = 0;
  let end = bytes.length;
  while (matches(bytes, start, 'ID3')) {
    if (start + 10 > end || bytes[start + 3] < 2 || bytes[start + 3] > 4) return undefined;
    const size = synchsafe(bytes, start + 6);
    if (size === undefined) return undefined;
    const footer = (bytes[start + 5] & 0x10) !== 0 ? 10 : 0;
    const next = start + 10 + size + footer;
    if (next > end || (footer && !matches(bytes, next - 10, '3DI'))) return undefined;
    start = next;
  }
  // Tags occur in either order at the tail. APE's size includes its footer; a
  // separate 32-byte header, when present, precedes that size.
  let removed: boolean;
  do {
    removed = false;
    if (end - start >= 128 && matches(bytes, end - 128, 'TAG')) { end -= 128; removed = true; }
    if (end - start >= 32 && matches(bytes, end - 32, 'APETAGEX')) {
      const footer = end - 32;
      const size = u32le(bytes, footer + 12);
      if (size < 32 || size > end - start) return undefined;
      let tagStart = end - size;
      if (tagStart - 32 >= start && matches(bytes, tagStart - 32, 'APETAGEX')) tagStart -= 32;
      end = tagStart;
      removed = true;
    }
  } while (removed);
  if (end - start < (adts ? 7 : 4) || bytes[start] !== 0xff || (bytes[start + 1] & 0xf0) !== 0xf0) return undefined;
  if (adts) {
    if ((bytes[start + 1] & 0x06) !== 0 || (bytes[start + 2] & 0x3c) === 0x3c) return undefined;
  } else if ((bytes[start + 1] & 0x08) !== 0x08 || (bytes[start + 1] & 0x06) === 0) return undefined;
  return start === 0 && end === bytes.length ? bytes : bytes.slice(start, end);
}

const MP4_METADATA = new Set(['udta', 'meta', 'uuid', 'ilst', 'keys', 'ID32', 'XMP_', '©nam', '©ART', '©alb', '©day', '©too', '©cmt', '©wrt']);
const MP4_CONTAINERS = new Set(['moov', 'trak', 'mdia', 'minf', 'stbl', 'edts', 'dinf', 'mvex', 'moof', 'traf', 'mfra', 'tref', 'ipro', 'iprp', 'ipco', 'wave']);

function stripMp4(bytes: Uint8Array): Uint8Array | undefined {
  if (bytes.length < 16 || !matches(bytes, 4, 'ftyp')) return undefined;
  const output = bytes.slice();
  let changed = false;
  let sawMedia = false;
  let count = 0;
  function walk(start: number, end: number, depth: number): boolean {
    if (depth > 16) return false;
    let position = start;
    while (position < end) {
      if (++count > 100000 || position + 8 > end) return false;
      const size32 = u32be(bytes, position);
      const type = ascii(bytes, position + 4, 4);
      let header = 8;
      let size = size32;
      if (size32 === 1) {
        if (position + 16 > end) return false;
        const high = u32be(bytes, position + 8);
        size = high * 0x100000000 + u32be(bytes, position + 12);
        header = 16;
      } else if (size32 === 0) size = end - position;
      if (!Number.isSafeInteger(size) || size < header || position + size > end) return false;
      if (type === 'mdat') sawMedia = true;
      if (MP4_METADATA.has(type)) {
        output.set([0x66, 0x72, 0x65, 0x65], position + 4); // free, same atom size
        output.fill(0, position + header, position + size);
        changed = true;
      } else if (type === 'free' || type === 'skip') {
        if (bytes.subarray(position + header, position + size).some(value => value !== 0)) changed = true;
        output.fill(0, position + header, position + size);
      } else if (MP4_CONTAINERS.has(type) && !walk(position + header, position + size, depth + 1)) return false;
      position += size;
    }
    return position === end;
  }
  return walk(0, bytes.length, 0) && sawMedia ? (changed ? output : bytes) : undefined;
}

const EBML_MASTERS = new Set([0x1a45dfa3, 0x18538067, 0x114d9b74, 0x1549a966, 0x1654ae6b, 0xae, 0xe0, 0xe1, 0x1f43b675, 0xa0, 0x1c53bb6b, 0xbb, 0xb7, 0x1941a469, 0x61a7, 0x1043a770, 0x45b9, 0xb6, 0x80]);
const EBML_METADATA = new Set([0x1254c367, 0x67c8, 0x5741, 0x4d80, 0x4461, 0x7ba9, 0x73a4, 0x7384, 0x3cb923, 0x3eb923, 0x3c83ab, 0x3e83bb, 0x536e]);

function ebmlVint(bytes: Uint8Array, offset: number, end: number, isSize: boolean): { value: number; length: number; unknown: boolean } | undefined {
  if (offset >= end) return undefined;
  const first = bytes[offset];
  let mask = 0x80;
  let length = 1;
  while (length <= (isSize ? 8 : 4) && !(first & mask)) { mask >>= 1; length++; }
  if (length > (isSize ? 8 : 4) || offset + length > end) return undefined;
  let value = isSize ? first & (mask - 1) : first;
  let unknown = isSize && value === mask - 1;
  for (let i = 1; i < length; i++) {
    value = value * 256 + bytes[offset + i];
    unknown = unknown && bytes[offset + i] === 255;
  }
  return { value, length, unknown };
}

function writeVoid(output: Uint8Array, start: number, length: number): boolean {
  for (let sizeLength = 1; sizeLength <= 8; sizeLength++) {
    const payload = length - 1 - sizeLength;
    if (payload < 0 || payload >= 2 ** (7 * sizeLength) - 1) continue;
    output[start] = 0xec;
    for (let i = 0; i < sizeLength; i++) {
      const shift = 8 * (sizeLength - 1 - i);
      output[start + 1 + i] = Math.floor(payload / 2 ** shift) & 255;
    }
    output[start + 1] |= 1 << (8 - sizeLength);
    output.fill(0, start + 1 + sizeLength, start + length);
    return true;
  }
  return false;
}

function stripWebm(bytes: Uint8Array): Uint8Array | undefined {
  if (!matches(bytes, 0, '\x1aE\xdf\xa3')) return undefined;
  const output = bytes.slice();
  let changed = false;
  let sawSegment = false;
  let count = 0;
  const crcElements: Array<{ start: number; length: number }> = [];
  function walk(start: number, end: number, depth: number): boolean {
    if (depth > 16) return false;
    let position = start;
    while (position < end) {
      if (++count > 100000) return false;
      const id = ebmlVint(bytes, position, end, false);
      if (!id) return false;
      const size = ebmlVint(bytes, position + id.length, end, true);
      if (!size) return false;
      const payload = position + id.length + size.length;
      if (size.unknown && id.value !== 0x18538067) return false;
      const next = size.unknown ? end : payload + size.value;
      if (!Number.isSafeInteger(next) || next > end || next < payload) return false;
      if (id.value === 0x18538067) sawSegment = true;
      if (EBML_METADATA.has(id.value)) {
        if (!writeVoid(output, position, next - position)) return false;
        changed = true;
      } else if (id.value === 0xbf) {
        if (size.value !== 4) return false;
        crcElements.push({ start: position, length: next - position });
      } else if (id.value === 0xec) {
        if (bytes.subarray(payload, next).some(value => value !== 0)) changed = true;
        output.fill(0, payload, next);
      } else if (EBML_MASTERS.has(id.value) && !walk(payload, next, depth + 1)) return false;
      position = next;
    }
    return position === end;
  }
  if (!walk(0, bytes.length, 0) || !sawSegment) return undefined;
  if (!changed) return bytes;
  // CRC-32 covers its parent element's bytes. Voiding all parsed CRC elements
  // avoids retaining a checksum that can no longer validate after redaction.
  for (const element of crcElements) if (!writeVoid(output, element.start, element.length)) return undefined;
  return output;
}

interface OggPage { start: number; end: number }
interface OggStream { packetIndex: number; pendingOpen: boolean; pending: number[]; packets: number[][] }

const OGG_CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let crc = i << 24;
    for (let j = 0; j < 8; j++) crc = (crc & 0x80000000) ? ((crc << 1) ^ 0x04c11db7) >>> 0 : (crc << 1) >>> 0;
    table[i] = crc;
  }
  return table;
})();

function pageCrc(bytes: Uint8Array, start: number, end: number): number {
  let crc = 0;
  for (let i = start; i < end; i++) crc = ((crc << 8) ^ OGG_CRC_TABLE[((crc >>> 24) ^ (i >= start + 22 && i < start + 26 ? 0 : bytes[i])) & 255]) >>> 0;
  return crc;
}

function stripOgg(bytes: Uint8Array): Uint8Array | undefined {
  if (!matches(bytes, 0, 'OggS')) return undefined;
  const pages: OggPage[] = [];
  const streams = new Map<number, OggStream>();
  let offset = 0;
  while (offset < bytes.length) {
    if (offset + 27 > bytes.length || !matches(bytes, offset, 'OggS') || bytes[offset + 4] !== 0) return undefined;
    const segmentCount = bytes[offset + 26];
    if (offset + 27 + segmentCount > bytes.length) return undefined;
    let dataLength = 0;
    for (let i = 0; i < segmentCount; i++) dataLength += bytes[offset + 27 + i];
    const dataStart = offset + 27 + segmentCount;
    const end = dataStart + dataLength;
    if (end > bytes.length) return undefined;
    const serial = u32le(bytes, offset + 14);
    const stream = streams.get(serial) ?? { packetIndex: 0, pendingOpen: false, pending: [], packets: [] };
    if (Boolean(bytes[offset + 5] & 1) !== stream.pendingOpen) return undefined;
    let cursor = dataStart;
    for (let i = 0; i < segmentCount; i++) {
      const length = bytes[offset + 27 + i];
      if (stream.packetIndex < 2) for (let j = 0; j < length; j++) stream.pending.push(cursor + j);
      cursor += length;
      stream.pendingOpen = length === 255;
      if (length < 255) {
        if (stream.packetIndex < 2) stream.packets.push(stream.pending);
        stream.pending = [];
        stream.packetIndex++;
      }
    }
    streams.set(serial, stream);
    pages.push({ start: offset, end });
    offset = end;
  }
  const output = bytes.slice();
  let changed = false;
  const patch = (positions: number[], index: number, value: number): void => { output[positions[index]] = value; };
  const read = (positions: number[], index: number): number => bytes[positions[index]];
  const read32 = (positions: number[], index: number): number =>
    (read(positions, index) | (read(positions, index + 1) << 8) | (read(positions, index + 2) << 16) | (read(positions, index + 3) << 24)) >>> 0;
  for (const stream of streams.values()) {
    if (stream.pendingOpen || stream.packets.length < 2) return undefined;
    const [first, second] = stream.packets;
    const signature = (positions: number[], value: string): boolean =>
      positions.length >= value.length && [...value].every((char, index) => read(positions, index) === char.charCodeAt(0));
    const opus = signature(first, 'OpusHead');
    const vorbis = first.length >= 7 && read(first, 0) === 1 && signature(first.slice(1), 'vorbis');
    // A mixed or unknown Ogg stream may carry its own comments. Do not claim
    // complete sanitization unless every logical stream is understood.
    if (!opus && !vorbis) return undefined;
    const prefix = opus ? 8 : 7;
    if (second.length < prefix + 8 || (opus ? !signature(second, 'OpusTags') : read(second, 0) !== 3 || !signature(second.slice(1), 'vorbis'))) return undefined;
    let cursor = prefix;
    const vendorLength = read32(second, cursor);
    cursor += 4;
    if (vendorLength > second.length - cursor - 4) return undefined;
    const vendorStart = cursor;
    cursor += vendorLength;
    const commentCount = read32(second, cursor);
    cursor += 4;
    if (commentCount > (second.length - cursor) / 4) return undefined;
    const comments: Array<{ start: number; length: number }> = [];
    for (let i = 0; i < commentCount; i++) {
      if (cursor + 4 > second.length) return undefined;
      const length = read32(second, cursor);
      cursor += 4;
      if (length > second.length - cursor || (vorbis && length < 2)) return undefined;
      comments.push({ start: cursor, length });
      cursor += length;
    }
    if (vorbis && (cursor >= second.length || (read(second, cursor) & 1) === 0)) return undefined;
    if (opus) {
      // OpusTags permits trailing padding. Clear all text and replace the two
      // length fields with an empty vendor and zero comments.
      for (let i = prefix; i < second.length; i++) patch(second, i, 0);
    } else {
      // Vorbis requires its framing byte at the original location. Keep every
      // length and lacing value, replacing text with valid, anonymous ASCII.
      for (let i = vendorStart; i < vendorStart + vendorLength; i++) patch(second, i, 0x20);
      for (const comment of comments) {
        for (let i = comment.start; i < comment.start + comment.length; i++) patch(second, i, 0x20);
        if (comment.length >= 2) { patch(second, comment.start, 0x58); patch(second, comment.start + 1, 0x3d); }
      }
      for (let i = cursor + 1; i < second.length; i++) patch(second, i, 0);
    }
    changed = true;
  }
  if (!changed) return undefined;
  for (const page of pages) {
    // Recompute all pages; their sequence numbers, granules, lacing and payload
    // lengths remain byte-for-byte fixed.
    put32le(output, page.start + 22, pageCrc(output, page.start, page.end));
  }
  return output;
}

export function stripAudioMetadata(bytes: Uint8Array, mimeType: string): Uint8Array | undefined {
  try {
    const mime = mimeType.toLowerCase().split(';', 1)[0].trim();
    if (mime === 'audio/wav' || mime === 'audio/wave' || mime === 'audio/x-wav') return stripWav(bytes);
    if (mime === 'audio/mpeg' || mime === 'audio/mp3') return stripMp3OrAdts(bytes, false);
    if (mime === 'audio/aac' || mime === 'audio/aacp') return stripMp3OrAdts(bytes, true);
    if (mime === 'audio/mp4' || mime === 'audio/x-m4a' || mime === 'audio/m4a') return stripMp4(bytes);
    if (mime === 'audio/webm' || mime === 'audio/x-matroska') return stripWebm(bytes);
    if (mime === 'audio/ogg' || mime === 'application/ogg' || mime === 'audio/opus') return stripOgg(bytes);
  } catch { /* Caller uploads the original when a parser cannot safely sanitize. */ }
  return undefined;
}
