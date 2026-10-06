import assert from 'node:assert/strict';
import { test } from 'node:test';
import { stripImageMetadata } from './images.js';

const bytes = (...numbers: number[]) => Uint8Array.from(numbers);
const text = (value: string) => new TextEncoder().encode(value);
const joined = (...parts: Uint8Array[]) => {
  const result = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let p = 0;
  for (const part of parts) { result.set(part, p); p += part.length; }
  return result;
};
const includes = (data: Uint8Array, needle: string) => new TextDecoder('latin1').decode(data).includes(needle);
const jpegSegment = (marker: number, data: Uint8Array) => joined(bytes(255, marker, (data.length + 2) >> 8, (data.length + 2) & 255), data);
const le32 = (n: number) => bytes(n & 255, n >> 8 & 255, n >> 16 & 255, n >>> 24);
const webpChunk = (name: string, content: Uint8Array) => joined(text(name), le32(content.length), content, content.length & 1 ? bytes(0) : bytes());

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
test('JPEG removes private APP, XMP, comments, and trailing data while retaining scan data', () => {
  const input = joined(bytes(255, 216), jpegSegment(0xe1, text('XMP private name')),
    jpegSegment(0xef, text('private app')), jpegSegment(0xfe, text('a comment')),
    jpegSegment(0xdb, bytes(0, 1, 2)), jpegSegment(0xda, bytes(1, 1, 0, 0, 63, 0)),
    bytes(1, 2, 255, 0, 3, 255, 208, 4, 255, 217), text('trailing secret'));
  const output = stripImageMetadata(input, 'image/jpeg')!;
  assert.deepEqual(output, joined(bytes(255, 216), jpegSegment(0xdb, bytes(0, 1, 2)),
    jpegSegment(0xda, bytes(1, 1, 0, 0, 63, 0)), bytes(1, 2, 255, 0, 3, 255, 208, 4, 255, 217)));
  const adobe = jpegSegment(0xee, joined(text('Adobe'), bytes(0, 101, 1, 2, 3, 4, 2)));
  const cmyk = joined(bytes(255, 216), adobe, jpegSegment(0xda, bytes(1, 1, 0, 0, 63, 0)), bytes(1, 255, 217));
  const cmykOutput = stripImageMetadata(cmyk, 'image/jpeg')!;
  assert.equal(includes(cmykOutput, 'Adobe'), true);
  assert.equal(cmykOutput[17], 2); // CMYK/YCCK transform survives; old flags/version do not
  assert.equal(cmykOutput[12], 100);
  assert.equal(cmykOutput[13], 0);
});

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
test('JPEG preserves orientation only as a fresh minimal EXIF field', () => {
  const orientation = bytes(69, 120, 105, 102, 0, 0, 73, 73, 42, 0, 8, 0, 0, 0,
    1, 0, 0x12, 1, 3, 0, 1, 0, 0, 0, 6, 0, 0, 0, 0, 0, 0, 0);
  const input = joined(bytes(255, 216), jpegSegment(0xe1, joined(orientation, text('camera owner'))),
    jpegSegment(0xda, bytes(1, 1, 0, 0, 63, 0)), bytes(1, 255, 217));
  const output = stripImageMetadata(input, 'image/jpeg')!;
  assert.equal(includes(output, 'camera owner'), false);
  assert.equal(includes(output, 'Exif'), true);
  assert.equal(output[30], 6);
});

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
test('PNG discards text, EXIF, private chunks and trailer, preserving animation chunks', () => {
  const chunk = (name: string, data: Uint8Array) => joined(bytes(data.length >>> 24, data.length >> 16 & 255, data.length >> 8 & 255, data.length & 255), text(name), data, bytes(0, 0, 0, 0));
  const header = bytes(137, 80, 78, 71, 13, 10, 26, 10);
  const retained = [chunk('IHDR', bytes(0, 0, 0, 1, 0, 0, 0, 1, 8, 6, 0, 0, 0)),
    chunk('acTL', bytes(0, 0, 0, 2, 0, 0, 0, 0)), chunk('IDAT', bytes(1, 2, 3)),
    chunk('fdAT', bytes(0, 0, 0, 1, 4, 5)), chunk('IEND', bytes())];
  const input = joined(header, retained[0]!, chunk('tEXt', text('Author\0Alice')),
    chunk('eXIf', text('secret')), chunk('vpAg', text('private')),
    retained[1]!, retained[2]!, retained[3]!, retained[4]!, text('trailer'));
  assert.deepEqual(stripImageMetadata(input, 'image/png'), joined(header, ...retained));
  const exifOrientation = bytes(73, 73, 42, 0, 8, 0, 0, 0, 1, 0,
    0x12, 1, 3, 0, 1, 0, 0, 0, 8, 0, 0, 0, 0, 0, 0, 0);
  const rotated = joined(header, retained[0]!, chunk('eXIf', joined(exifOrientation, text('camera owner'))), retained[2]!, retained[4]!);
  const rotatedOutput = stripImageMetadata(rotated, 'image/png')!;
  assert.equal(includes(rotatedOutput, 'camera owner'), false);
  assert.equal(includes(rotatedOutput, 'eXIf'), true);
  assert.equal(rotatedOutput[8 + retained[0]!.length + 8 + 18], 8);
});

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
test('WebP removes EXIF, XMP and private chunks, fixes VP8X flags and RIFF size', () => {
  const body = joined(webpChunk('VP8X', bytes(0x2e, 0, 0, 0, 1, 0, 0, 1, 0, 0)),
    webpChunk('ANIM', bytes(0, 0, 0, 0, 0, 0)),
    webpChunk('ANMF', joined(new Uint8Array(16), webpChunk('VP8 ', bytes(1, 2, 3)), webpChunk('EXIF', text('frame secret')))),
    webpChunk('EXIF', text('GPS secret')), webpChunk('XMP ', text('author')),
    webpChunk('zzZZ', text('private')));
  const input = joined(text('RIFF'), le32(body.length + 4), text('WEBP'), body, text('trailer'));
  const output = stripImageMetadata(input, 'image/webp')!;
  assert.equal(output[20], 0x02);
  assert.equal(new DataView(output.buffer).getUint32(4, true), output.length - 8);
  assert.equal(includes(output, 'ANMF'), true);
  for (const word of ['GPS secret', 'author', 'private', 'trailer', 'frame secret']) assert.equal(includes(output, word), false);
});

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
test('GIF retains two frames and loop control, dropping comments and private applications', () => {
  const header = joined(text('GIF89a'), bytes(1, 0, 1, 0, 0, 0, 0));
  const loop = joined(bytes(0x21, 0xff, 11), text('NETSCAPE2.0'), bytes(3, 1, 0, 0, 0));
  const frame = bytes(0x21, 0xf9, 4, 0, 0, 0, 0, 0, 0x2c, 0, 0, 0, 0, 1, 0, 1, 0, 0, 2, 2, 0x4c, 1, 0);
  const privateApp = joined(bytes(0x21, 0xff, 11), text('PRIVATE1234'), bytes(6), text('secret'), bytes(0));
  const comment = joined(bytes(0x21, 0xfe, 6), text('author'), bytes(0));
  const input = joined(header, loop, frame, comment, privateApp, frame, bytes(0x3b), text('trailer'));
  assert.deepEqual(stripImageMetadata(input, 'image/gif'), joined(header, loop, frame, frame, bytes(0x3b)));
});

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
test('BMP V3 rebuild removes gap, reserved fields, resolution and trailer', () => {
  const input = new Uint8Array(64);
  input.set(text('BM'));
  const view = new DataView(input.buffer);
  view.setUint32(2, input.length, true); view.setUint32(10, 58, true); view.setUint32(14, 40, true);
  view.setInt32(18, 1, true); view.setInt32(22, 1, true); view.setUint16(26, 1, true);
  view.setUint16(28, 24, true); input.set(text('XGPS'), 54); input.set(bytes(1, 2, 3, 0), 58);
  const output = stripImageMetadata(input, 'image/bmp')!;
  assert.equal(output.length, 58);
  assert.equal(new DataView(output.buffer).getUint32(10, true), 54);
  assert.deepEqual(output.subarray(54), bytes(1, 2, 3, 0));
  assert.equal(includes(output, 'XGPS'), false);
});

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
test('SVG removes metadata while retaining filenames, paths, accessible content and vector paths', () => {
  const input = text('<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" viewBox="0 0 5 5" sodipodi:docname="source-design.svg" data-source-path="work/designs/source-design.svg" aria-label="Map graphic"><!-- author --><metadata><rdf>GPS XMP camera owner</rdf></metadata><title>Map graphic</title><desc>Route from A to B</desc><inkscape:namedview inkscape:foo="tracking" inkscape:export-filename="exports/map.png"/><path inkscape:label="editor label" d="M0 0L5 5"/></svg>');
  const output = stripImageMetadata(input, 'image/svg+xml')!;
  assert.equal(includes(output, 'M0 0L5 5'), true);
  for (const word of ['source-design.svg', 'work/designs/source-design.svg', 'exports/map.png', 'Map graphic', 'Route from A to B', 'aria-label']) assert.equal(includes(output, word), true);
  for (const word of ['author', 'GPS', 'XMP', 'camera owner', 'tracking', 'editor label']) assert.equal(includes(output, word), false);
  const nestedJpeg = joined(bytes(255, 216), jpegSegment(0xfe, text('camera owner')),
    jpegSegment(0xda, bytes(1, 1, 0, 0, 63, 0)), bytes(1, 255, 217));
  const embedded = text(`<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/jpeg;base64,${btoa(String.fromCharCode(...nestedJpeg))}"/></svg>`);
  const embeddedOutput = stripImageMetadata(embedded, 'image/svg+xml')!;
  assert.equal(includes(embeddedOutput, 'Y2FtZXJhIG93bmVy'), false);
  assert.equal(includes(embeddedOutput, 'data:image/jpeg;base64,'), true);
});

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
test('SVG foreignObject retains visible XHTML text and path references', () => {
  const input = text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 30"><metadata>GPS XMP</metadata><foreignObject x="0" y="0" width="30" height="30"><div xmlns="http://www.w3.org/1999/xhtml" data-file-path="drafts/diagram.svg" aria-label="Diagram note"><p>Visible note</p><a href="folder/source.svg">Open source</a></div></foreignObject><path d="M0 0L30 30"/></svg>');
  const output = stripImageMetadata(input, 'image/svg+xml')!;
  for (const word of ['foreignObject', 'Visible note', 'drafts/diagram.svg', 'folder/source.svg', 'aria-label', 'M0 0L30 30']) assert.equal(includes(output, word), true);
  for (const word of ['GPS', 'XMP']) assert.equal(includes(output, word), false);
});

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
test('unsupported variants return undefined; truncated supported images fail', () => {
  assert.equal(stripImageMetadata(bytes(1, 2), 'image/heic'), undefined);
  assert.equal(stripImageMetadata(bytes(1, 2), 'image/tiff'), undefined);
  const unsupportedBmp = new Uint8Array(54);
  unsupportedBmp.set(text('BM'));
  assert.equal(stripImageMetadata(unsupportedBmp, 'image/bmp'), undefined);
  assert.throws(() => stripImageMetadata(bytes(255, 216, 255), 'image/jpeg'));
});
