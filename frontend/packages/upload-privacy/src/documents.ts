import { DOMParser, XMLSerializer, type Document as XmlDocument, type Element as XmlElement, type Node as XmlNode } from '@xmldom/xmldom';
import JSZip from 'jszip';
import { PDFArray, PDFDict, PDFDocument, PDFHexString, PDFName, PDFRawStream, PDFRef, PDFStream, PDFString } from 'pdf-lib';
import { stripImageMetadata } from './images.js';

const FIXED_ZIP_DATE = new Date('1980-01-01T00:00:00.000Z');
const MAX_ZIP_ENTRIES = 10_000;
const MAX_ZIP_UNCOMPRESSED_BYTES = 256 * 1024 * 1024;
const OFFICE_EXTENSIONS = new Set(['docx', 'xlsx', 'pptx', 'odt', 'ods', 'odp']);
const IMAGE_MIME: Record<string, string> = {
  jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp',
  gif: 'image/gif', tif: 'image/tiff', tiff: 'image/tiff', avif: 'image/avif',
};
const PDF_METADATA_KEYS = ['Metadata', 'PieceInfo', 'LastModified', 'Thumb', 'CreationDate', 'ModDate'];
const IDENTIFYING_ATTRIBUTES = new Set([
  'author', 'creator', 'lastmodifiedby', 'editor', 'initials', 'date', 'created',
  'modified', 'creationdate', 'modificationdate', 'lastmodifiedtime', 'user',
  'username', 'userid', 'personid',
]);
const EPUB_METADATA_ELEMENTS = new Set([
  'creator', 'contributor', 'date', 'publisher', 'rights',
]);
const EPUB_METADATA_PROPERTIES = /(?:author|creator|contributor|editor|file-as|date|modified|timestamp|publisher|generator|identifier|revision)/i;
const PATH_PROPERTY_NAME = /(?:file(?:name|path)?|folder(?:name|path)?|directory|dirpath|source(?:path|file|name)?|hyperlinkbase|template|target(?:path|file|name)?|uri|url|link)/i;
const IDENTIFYING_PROPERTY_NAME = /(?:author|creator|editor|person|user|date|time|modified|revision|version|company|manager|generator|application)/i;

function extension(filename: string): string {
  return filename.split('.').pop()?.toLowerCase() ?? '';
}

function pdfName(name: string): PDFName {
  return PDFName.of(name);
}

function isName(value: unknown, name: string): boolean {
  return value instanceof PDFName && value.asString() === name;
}

/** Reject expansion bombs before JSZip's eager CRC verification inflates entries. */
function zipWithinScrubBudget(bytes: Uint8Array): boolean {
  if (bytes.length < 22) return false;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const u16 = (offset: number) => view.getUint16(offset, true);
  const u32 = (offset: number) => view.getUint32(offset, true);
  const earliest = Math.max(0, bytes.length - 65_557);
  let end = -1;
  for (let offset = bytes.length - 22; offset >= earliest; offset--) {
    if (u32(offset) === 0x06054b50 && offset + 22 + u16(offset + 20) === bytes.length) {
      end = offset;
      break;
    }
  }
  if (end < 0 || u16(end + 4) !== 0 || u16(end + 6) !== 0) return false;
  const count = u16(end + 10);
  const directorySize = u32(end + 12);
  const directoryOffset = u32(end + 16);
  if (count !== u16(end + 8) || count === 0xffff || count > MAX_ZIP_ENTRIES ||
      directorySize === 0xffffffff || directoryOffset === 0xffffffff ||
      directoryOffset + directorySize > end) return false;

  let cursor = directoryOffset;
  let total = 0;
  for (let index = 0; index < count; index++) {
    if (cursor + 46 > end || u32(cursor) !== 0x02014b50) return false;
    if ((u16(cursor + 8) & 1) !== 0) return false; // encrypted entry
    const expandedSize = u32(cursor + 24);
    const compressedSize = u32(cursor + 20);
    const localOffset = u32(cursor + 42);
    if (expandedSize === 0xffffffff || compressedSize === 0xffffffff || localOffset === 0xffffffff) return false;
    total += expandedSize;
    if (total > MAX_ZIP_UNCOMPRESSED_BYTES) return false;
    const nameLength = u16(cursor + 28);
    const extraLength = u16(cursor + 30);
    const commentLength = u16(cursor + 32);
    const next = cursor + 46 + nameLength + extraLength + commentLength;
    if (next > end || localOffset + 30 > directoryOffset) return false;
    // JSZip resolves dot segments and repeated separators while loading. A
    // rewrite would silently rename files or directories, so leave that ZIP raw.
    const nameStart = cursor + 46;
    let segmentStart = 0;
    for (let position = 0; position <= nameLength; position++) {
      if (position !== nameLength && bytes[nameStart + position] !== 0x2f) continue;
      const length = position - segmentStart;
      if ((length === 1 && bytes[nameStart + segmentStart] === 0x2e) ||
          (length === 2 && bytes[nameStart + segmentStart] === 0x2e &&
            bytes[nameStart + segmentStart + 1] === 0x2e) ||
          (length === 0 && position !== 0 && position !== nameLength)) return false;
      segmentStart = position + 1;
    }
    let extra = cursor + 46 + nameLength;
    const extraEnd = extra + extraLength;
    while (extra < extraEnd) {
      if (extra + 4 > extraEnd) return false;
      const field = u16(extra);
      const length = u16(extra + 2);
      if (field === 0x0001 || extra + 4 + length > extraEnd) return false; // ZIP64
      extra += 4 + length;
    }
    cursor = next;
  }
  return cursor <= directoryOffset + directorySize;
}

/**
 * Return undefined when a document format cannot be safely rewritten. Parsing and
 * encryption failures throw so the upload boundary can use the original bytes.
 */
export async function stripDocumentMetadata(
  bytes: Uint8Array,
  mimeType: string,
  filename: string,
): Promise<Uint8Array | undefined> {
  const ext = extension(filename);
  const mime = mimeType.toLowerCase().split(';', 1)[0].trim();
  if (ext === 'pdf' || mime === 'application/pdf') return stripPdfMetadata(bytes);
  if (
    OFFICE_EXTENSIONS.has(ext) || ext === 'epub' || ext === 'zip' ||
    mime === 'application/epub+zip' || mime === 'application/zip' ||
    mime === 'application/x-zip-compressed' ||
    mime.startsWith('application/vnd.openxmlformats-officedocument.') ||
    mime.startsWith('application/vnd.oasis.opendocument.')
  ) return stripZipDocumentMetadata(
    bytes,
    ext === 'epub' || mime === 'application/epub+zip',
    ['odt', 'ods', 'odp'].includes(ext) || mime.startsWith('application/vnd.oasis.opendocument.'),
  );
  return undefined;
}

async function stripPdfMetadata(bytes: Uint8Array): Promise<Uint8Array | undefined> {
  // pdf-lib rejects encrypted PDFs unless explicitly told to ignore encryption.
  const document = await PDFDocument.load(bytes, { updateMetadata: false });
  const context = document.context;
  const objects = context.enumerateIndirectObjects();

  // Rewriting would invalidate a signature. Leave signed documents untouched.
  for (const [, object] of objects) {
    const dict = object instanceof PDFStream ? object.dict : object;
    if (!(dict instanceof PDFDict)) continue;
    if (dict.has(pdfName('ByteRange')) || isName(dict.get(pdfName('FT')), 'Sig') ||
        isName(dict.get(pdfName('Type')), 'Sig')) return undefined;
  }
  if (document.catalog.has(pdfName('Perms'))) return undefined;

  const infoReference = context.trailerInfo.Info;
  const info = context.lookup(infoReference);
  let preservedInfoPath = false;
  if (info instanceof PDFDict) {
    for (const key of info.keys()) {
      const value = info.get(key);
      const decoded = value instanceof PDFString || value instanceof PDFHexString ? value.decodeText() : '';
      if (preservePathValue(key.asString(), decoded)) preservedInfoPath = true;
      else info.delete(key);
    }
  }

  // DCT image streams are ordinary JPEG data. Replacing the stream keeps its
  // PDF resource references, dimensions and color settings intact.
  for (const [ref, object] of objects) {
    if (!(object instanceof PDFRawStream) || !isName(object.dict.get(pdfName('Subtype')), 'Image') ||
        !isName(object.dict.get(pdfName('Filter')), 'DCTDecode')) continue;
    try {
      const cleaned = stripImageMetadata(object.getContents(), 'image/jpeg');
      if (cleaned) context.assign(ref, PDFRawStream.of(object.dict, cleaned));
    } catch {
      // Keep an image stream if it uses JPEG features the image scrubber cannot handle.
    }
  }

  context.trailerInfo.Info = preservedInfoPath ? infoReference : undefined;
  context.trailerInfo.ID = undefined;
  const seen = new Set<object>();
  const reachable = new Set<string>();

  const visit = (object: unknown): void => {
    if (!object || typeof object !== 'object') return;
    if (object instanceof PDFRef) {
      const id = object.toString();
      if (reachable.has(id)) return;
      reachable.add(id);
      visit(context.lookup(object));
      return;
    }
    if (seen.has(object)) return;
    seen.add(object);
    if (object instanceof PDFStream) {
      visit(object.dict);
      return;
    }
    if (object instanceof PDFArray) {
      for (const value of object.asArray()) visit(value);
      return;
    }
    if (!(object instanceof PDFDict)) return;

    for (const key of PDF_METADATA_KEYS) object.delete(pdfName(key));
    // Annotation /NM and /M identify editors; /T is an author on non-widget
    // annotations, but a functional field name on form widgets.
    if (object.has(pdfName('Subtype'))) {
      object.delete(pdfName('NM'));
      object.delete(pdfName('M'));
      if (!isName(object.get(pdfName('Subtype')), 'Widget')) object.delete(pdfName('T'));
    }
    for (const value of object.values()) visit(value);
  };

  visit(context.trailerInfo.Root ?? document.catalog);
  if (preservedInfoPath) visit(infoReference);
  // pdf-lib serializes every registered object, including unreachable old XMP,
  // Info dictionaries and prior incremental revisions. Purge them explicitly.
  for (const [ref] of context.enumerateIndirectObjects()) {
    if (!reachable.has(ref.toString())) context.delete(ref);
  }
  return document.save({ useObjectStreams: false, addDefaultPage: false, updateFieldAppearances: false });
}

function parseXml(xml: string): XmlDocument {
  const parser = new DOMParser({
    onError: (level, message) => {
      if (level !== 'warning') throw new Error(`Invalid document XML: ${message}`);
    },
  });
  const document = parser.parseFromString(xml, 'application/xml');
  if (!document.documentElement) throw new Error('Invalid document XML');
  return document;
}

function children(node: XmlNode): XmlNode[] {
  const result: XmlNode[] = [];
  for (let index = 0; index < node.childNodes.length; index++) {
    const child = node.childNodes.item(index);
    if (child) result.push(child);
  }
  return result;
}

function preservePathValue(label: string, value: string): boolean {
  if (PATH_PROPERTY_NAME.test(label)) return true;
  if (IDENTIFYING_PROPERTY_NAME.test(label)) return false;
  return /(?:[/\\]|^[^@\s]+\.[a-z0-9]{1,10}$)/i.test(value.trim());
}

function preservePathProperty(element: XmlElement): boolean {
  const local = (element.localName ?? element.nodeName.split(':').pop() ?? '').toLowerCase();
  const label = element.getAttribute('name') ?? element.getAttribute('property') ?? local;
  return preservePathValue(label, element.textContent ?? '');
}

function scrubXml(xml: string, path: string, epub: boolean, odf: boolean): string {
  const document = parseXml(xml);
  const lowerPath = path.toLowerCase();
  const propertyPart = (lowerPath.startsWith('docprops/') && lowerPath.endsWith('.xml')) ||
    (odf && lowerPath === 'meta.xml');
  if (propertyPart) {
    // Empty existing property parts instead of removing them: relationship and
    // content-type references continue to resolve correctly.
    const root = document.documentElement!;
    for (const child of children(root)) {
      if (odf && lowerPath === 'meta.xml' && child.nodeType === 1 &&
          (child as XmlElement).localName === 'meta') {
        for (const property of children(child)) {
          if (property.nodeType !== 1 || !preservePathProperty(property as XmlElement)) child.removeChild(property);
        }
      } else if (child.nodeType === 1 && preservePathProperty(child as XmlElement)) {
        continue;
      } else {
        root.removeChild(child);
      }
    }
    return new XMLSerializer().serializeToString(document);
  }

  const officePart = /^(?:word|xl|ppt)\//.test(lowerPath);
  const epubPackage = epub && lowerPath.endsWith('.opf');
  const walk = (node: XmlNode): void => {
    for (const child of children(node)) {
      if (child.nodeType === 8 && (officePart || epubPackage)) {
        node.removeChild(child);
        continue;
      }
      if (child.nodeType !== 1) {
        walk(child);
        continue;
      }
      const element = child as XmlElement;
      const local = (element.localName ?? element.nodeName.split(':').pop() ?? '').toLowerCase();
      if (epubPackage && EPUB_METADATA_ELEMENTS.has(local) &&
          element.parentNode?.nodeName.toLowerCase().endsWith('metadata')) {
        node.removeChild(child);
        continue;
      }
      if (odf && lowerPath === 'content.xml' && (local === 'creator' || local === 'date') &&
          /(?:annotation|change-info)$/.test(element.parentNode?.nodeName.toLowerCase() ?? '')) {
        node.removeChild(child);
        continue;
      }
      if (epubPackage && local === 'meta' &&
          EPUB_METADATA_PROPERTIES.test(element.getAttribute('name') ?? element.getAttribute('property') ?? '')) {
        node.removeChild(child);
        continue;
      }
      if (officePart) {
        for (let index = element.attributes.length - 1; index >= 0; index--) {
          const attribute = element.attributes.item(index);
          if (!attribute) continue;
          const attributeName = (attribute.localName ?? attribute.name.split(':').pop() ?? '').toLowerCase();
          if (IDENTIFYING_ATTRIBUTES.has(attributeName) || attributeName.startsWith('rsid')) {
            element.removeAttributeNode(attribute);
          }
        }
      }
      walk(child);
    }
  };
  walk(document);
  return new XMLSerializer().serializeToString(document);
}

async function stripZipDocumentMetadata(bytes: Uint8Array, epub: boolean, odf: boolean): Promise<Uint8Array | undefined> {
  if (!zipWithinScrubBudget(bytes)) return undefined;
  const zip = await JSZip.loadAsync(bytes, { checkCRC32: true });
  const names = Object.keys(zip.files);
  if (names.some((name) => !zip.files[name].dir &&
      zip.files[name].unsafeOriginalName !== undefined && zip.files[name].unsafeOriginalName !== name)) {
    return undefined;
  }
  if (names.some((name) => /^_xmlsignatures\//i.test(name) || /vbaprojectsignature\.bin$/i.test(name))) {
    return undefined;
  }
  if (epub && names.some((name) => /^meta-inf\/encryption\.xml$/i.test(name))) {
    throw new Error('Encrypted EPUB is unsupported');
  }
  // JSZip's runtime archive comment is not declared in its public TypeScript interface.
  (zip as JSZip & { comment?: string }).comment = '';
  for (const name of names) {
    const file = zip.files[name];
    file.date = FIXED_ZIP_DATE;
    file.comment = '';
    if (file.dir) continue;
    const lowerName = name.toLowerCase();
    if ((epub || odf) && lowerName === 'mimetype') {
      zip.file(name, await file.async('uint8array'), { binary: true, compression: 'STORE', date: FIXED_ZIP_DATE, comment: '' });
      continue;
    }
    if (lowerName.endsWith('.xml') || (epub && lowerName.endsWith('.opf'))) {
      const xml = await file.async('string');
      if (/^docprops\//.test(lowerName) || /^(?:word|xl|ppt)\//.test(lowerName) ||
          (epub && lowerName.endsWith('.opf')) || (odf && (lowerName === 'meta.xml' || lowerName === 'content.xml'))) {
        zip.file(name, scrubXml(xml, name, epub, odf), { date: FIXED_ZIP_DATE, comment: '' });
      }
      continue;
    }
    const imageMime = IMAGE_MIME[extension(name)];
    if (imageMime) {
      const original = await file.async('uint8array');
      try {
        const scrubbed = stripImageMetadata(original, imageMime);
        if (scrubbed) zip.file(name, scrubbed, { binary: true, date: FIXED_ZIP_DATE, comment: '' });
      } catch {
        // An unsupported embedded image cannot prevent the enclosing upload.
      }
    }
  }
  return zip.generateAsync({ type: 'uint8array', compression: 'DEFLATE', compressionOptions: { level: 6 }, comment: '' });
}
